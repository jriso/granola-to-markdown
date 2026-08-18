#!/usr/bin/env python3
"""Tests for sync.py's error classification, state durability, and log trimming.

No framework, no network, no API key required: `python3 test_sync.py`. Exits
non-zero on failure. These guard behaviours that are easy to re-break:

  1. Which network failures count as transient. The sync runs unattended every
     30 minutes, so a condition the next run would survive must exit 0 quietly
     instead of firing a desktop notification — while a certificate failure or
     a permanent decode error must stay loud.
  2. That a mid-run abort persists state without destroying it, on both the
     default and the --force path.
  3. That --dry-run writes nothing, and that log trimming can't eat a log.
"""

import gzip
import http.client
import os
import socket
import ssl
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}: {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def via_api_request(exc):
    """Call _api_request with urlopen raising `exc`; return what escapes."""
    orig = sync.urllib.request.urlopen

    def boom(*a, **k):
        raise exc

    sync.urllib.request.urlopen = boom
    try:
        sync._api_request("/notes", "test-key")
        return None
    except BaseException as e:  # noqa: BLE001 - we are inspecting the type
        return e
    finally:
        sync.urllib.request.urlopen = orig


def test_transient_classification():
    T = sync.TransientNetworkError
    print("== transient network conditions (must exit quietly) ==")
    # urllib wraps connect-phase failures in URLError; read-phase failures —
    # after the response headers land — propagate bare. Both must classify
    # the same, since a retry can't tell them apart.
    for label, exc in [
        ("TimeoutError (read phase)", TimeoutError("The read operation timed out")),
        ("socket.timeout", socket.timeout("The read operation timed out")),
        ("ssl.SSLEOFError", ssl.SSLEOFError("EOF occurred in violation of protocol")),
        ("ssl.SSLError", ssl.SSLError("decryption failed")),
        ("http.client.IncompleteRead", http.client.IncompleteRead(b"partial")),
        ("http.client.RemoteDisconnected", http.client.RemoteDisconnected("closed")),
        ("ConnectionResetError", ConnectionResetError("reset by peer")),
        ("socket.gaierror", socket.gaierror("no such host")),
        # Seen in the wild in .sync.log; a plain OSError, not a ConnectionError.
        ("URLError(errno 49 EADDRNOTAVAIL)",
         urllib.error.URLError(OSError(49, "Can't assign requested address"))),
        ("URLError(timeout)", urllib.error.URLError(socket.timeout("timed out"))),
        ("HTTP 429", urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)),
    ]:
        e = via_api_request(exc)
        check(f"transient: {label}", isinstance(e, T), f"got {type(e).__name__}: {e}")

    print()
    print("== conditions that must stay loud ==")
    # A rejected certificate is a trust/config problem. In production urllib
    # wraps connect-phase cert failures, so the WRAPPED form is the shape that
    # actually occurs — test both.
    for label, exc in [
        ("bare SSLCertVerificationError", ssl.SSLCertVerificationError("cert verify failed")),
        ("URLError(SSLCertVerificationError)",
         urllib.error.URLError(ssl.SSLCertVerificationError("cert verify failed"))),
        ("gzip.BadGzipFile (corrupt body)", gzip.BadGzipFile("not a gzipped file")),
        ("PermissionError", PermissionError(1, "Operation not permitted")),
        ("ValueError (malformed json)", ValueError("malformed json")),
    ]:
        e = via_api_request(exc)
        check(f"loud: {label}", not isinstance(e, T), f"got {type(e).__name__}: {e}")

    e = via_api_request(urllib.error.HTTPError("u", 401, "Unauthorized", {}, None))
    check("401 -> AuthExpiredError", isinstance(e, sync.AuthExpiredError), f"got {type(e).__name__}")
    e = via_api_request(urllib.error.HTTPError("u", 500, "ISE", {}, None))
    check("500 -> hard RuntimeError", type(e) is RuntimeError, f"got {type(e).__name__}")


def _run_aborting_sync(d, prior, force):
    """Run sync_via_api with a mid-loop abort; return what got saved."""
    saved = {}
    names = ("load_api_key", "save_sync_state", "load_sync_state",
             "fetch_note_list", "fetch_note_detail")
    orig = {n: getattr(sync, n) for n in names}
    on_disk = dict(prior)

    def _save(od, st):
        saved.clear()
        saved.update(st)
        on_disk.clear()
        on_disk.update(st)

    def _boom(k, nid):
        raise sync.TransientNetworkError("network dropped mid-loop")

    sync.load_api_key = lambda: "grn_test"
    sync.save_sync_state = _save
    sync.load_sync_state = lambda od: dict(on_disk)
    sync.fetch_note_list = lambda k, log, **kw: [{"id": "n1", "updated_at": "t1"}]
    sync.fetch_note_detail = _boom
    try:
        sync.sync_via_api(output_dir=d, force=force, dry_run=False, verbose=False)
        aborted = False
    except sync.TransientNetworkError:
        aborted = True
    finally:
        for n, f in orig.items():
            setattr(sync, n, f)
    return aborted, saved


def test_state_survives_abort():
    print()
    print("== sync state survives a mid-run abort ==")
    prior = {
        "u1": {"filename": "a.md", "note_id": "n0", "transcript_saved": True},
        "u2": {"filename": "b.md", "note_id": "n9"},
    }
    for force in (False, True):
        with tempfile.TemporaryDirectory() as d:
            aborted, saved = _run_aborting_sync(d, prior, force)
            check(f"abort propagates (force={force})", aborted)
            # Under --force the in-memory state starts empty; saving it
            # wholesale here would strand every prior entry.
            check(f"prior entries kept (force={force})",
                  set(prior) <= set(saved), f"saved={sorted(saved)}")
            check(f"transcript flag kept (force={force})",
                  saved.get("u1", {}).get("transcript_saved") is True, f"saved={saved}")


def test_log_trimming():
    print()
    print("== log trimming ==")
    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, sync.LOG_FILE)

        sync._trim_log(d)
        check("missing log is a no-op", not os.path.exists(log))

        small = b"line\n" * 100
        with open(log, "wb") as f:
            f.write(small)
        sync._trim_log(d)
        with open(log, "rb") as f:
            check("under threshold untouched", f.read() == small)

        lines = [f"line {i:07d}\n".encode() for i in range(120_000)]
        with open(log, "wb") as f:
            f.write(b"".join(lines))
        sync._trim_log(d)
        with open(log, "rb") as f:
            out = f.read()
        # Assert against KEEP, not MAX: a trim that kept 999 KB would satisfy
        # "<= MAX" while doing essentially nothing.
        check("trimmed to about KEEP bytes",
              len(out) <= sync.LOG_KEEP_BYTES + 200, f"{len(out)}")
        check("header written", out.startswith(b"--- log trimmed to last "))
        check("newest line survives", out.endswith(lines[-1]))
        check("oldest line discarded", lines[0] not in out)
        check("no partial first line", out.split(b"\n", 1)[1].startswith(b"line "))

        # launchd holds an O_APPEND descriptor across the trim.
        with open(log, "ab") as f:
            f.write(b"after trim\n")
        with open(log, "rb") as f:
            check("append after trim is clean", f.read().endswith(b"line 0119999\nafter trim\n"))

        with open(log, "rb") as f:
            before = f.read()
        sync._trim_log(d)
        with open(log, "rb") as f:
            check("second trim is a no-op", f.read() == before)

        # A tail with no newline has no partial line to drop; cutting at the
        # first newline anyway would leave nothing but the header.
        for label, payload in [
            ("no-newline tail", b"x" * (sync.LOG_MAX_BYTES + 5000)),
            ("newline outside kept window", b"early\n" + b"y" * (sync.LOG_MAX_BYTES + 5000)),
        ]:
            with open(log, "wb") as f:
                f.write(payload)
            sync._trim_log(d)
            with open(log, "rb") as f:
                check(f"{label} not wiped", len(f.read()) > 100_000)

        # Trimming must never be the reason a sync fails. chmod is a no-op for
        # root and on filesystems without POSIX permissions, so only assert the
        # weak property (no raise) and skip the strong one when not enforced.
        with open(log, "wb") as f:
            f.write(b"z\n" * sync.LOG_MAX_BYTES)
        os.chmod(log, 0o400)
        enforced = not os.access(log, os.W_OK)
        try:
            sync._trim_log(d)
            check("unwritable log does not raise", True)
        except Exception as ex:  # noqa: BLE001
            check("unwritable log does not raise", False, repr(ex))
        finally:
            os.chmod(log, 0o600)
        if enforced:
            with open(log, "rb") as f:
                check("unwritable log left intact", len(f.read()) > sync.LOG_MAX_BYTES)
        else:
            print("SKIP: unwritable log left intact (permissions not enforced here)")


def test_dry_run_does_not_trim():
    print()
    print("== --dry-run does not trim the log ==")
    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, sync.LOG_FILE)
        payload = b"z\n" * sync.LOG_MAX_BYTES
        with open(log, "wb") as f:
            f.write(payload)
        orig_sync, orig_argv = sync.sync_via_api, sys.argv
        sync.sync_via_api = lambda **kw: None
        sys.argv = ["sync.py", "--output-dir", d, "--dry-run"]
        try:
            sync.main()
        except SystemExit:
            pass
        finally:
            sync.sync_via_api, sys.argv = orig_sync, orig_argv
        with open(log, "rb") as f:
            check("--dry-run leaves the log untouched", f.read() == payload)


def test_end_to_end_regression():
    print()
    print("== end to end: the 2026-08-16 failure ==")
    with tempfile.TemporaryDirectory() as d:
        fired = []
        orig = (sync.subprocess.run, sync.urllib.request.urlopen, sys.argv, sync.load_api_key)
        sync.subprocess.run = lambda *a, **k: fired.append(a)
        sync.load_api_key = lambda: "grn_test"

        def boom(*a, **k):
            raise TimeoutError("The read operation timed out")

        sync.urllib.request.urlopen = boom
        sys.argv = ["sync.py", "--output-dir", d, "--verbose"]
        try:
            sync.main()
            code = 0
        except SystemExit as e:
            code = e.code
        finally:
            (sync.subprocess.run, sync.urllib.request.urlopen,
             sys.argv, sync.load_api_key) = orig
        notified = os.path.exists(os.path.join(d, sync.NOTIFY_STATE_FILE)) or bool(fired)
        check("exits 0", code == 0, f"exit {code}")
        check("no desktop notification", not notified)


def main():
    test_transient_classification()
    test_state_survives_abort()
    test_log_trimming()
    test_dry_run_does_not_trim()
    test_end_to_end_regression()
    print()
    print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
