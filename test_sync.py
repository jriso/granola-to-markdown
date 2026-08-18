#!/usr/bin/env python3
"""Tests for sync.py's error classification, state durability, and log trimming.

No framework and no network: run with `python3 test_sync.py`. Exits non-zero on
failure. These guard behaviours that are easy to re-break by accident:

  1. Which network failures count as transient. The sync runs unattended every
     30 minutes, so a condition the next run would survive must exit 0 quietly
     instead of firing a desktop notification — while a certificate failure or
     a malformed response must stay loud.
  2. That a mid-run abort still persists sync state.
  3. That --dry-run writes nothing, and that log trimming can't eat a log.
"""

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


T = sync.TransientNetworkError

print("== transient network conditions (must exit quietly) ==")
# urllib wraps connect-phase failures in URLError; read-phase failures — after
# the response headers land — propagate bare. Both must classify the same.
for label, exc in [
    ("TimeoutError (read phase)", TimeoutError("The read operation timed out")),
    ("socket.timeout", socket.timeout("The read operation timed out")),
    ("ssl.SSLEOFError", ssl.SSLEOFError("EOF occurred in violation of protocol")),
    ("ssl.SSLError", ssl.SSLError("decryption failed")),
    ("http.client.IncompleteRead", http.client.IncompleteRead(b"partial")),
    ("http.client.RemoteDisconnected", http.client.RemoteDisconnected("closed")),
    ("ConnectionResetError", ConnectionResetError("reset by peer")),
    ("socket.gaierror", socket.gaierror("no such host")),
    ("bare OSError", OSError("connection machinery failed")),
    ("URLError(timeout)", urllib.error.URLError(socket.timeout("timed out"))),
    ("URLError(errno 49)", urllib.error.URLError(OSError(49, "Can't assign requested address"))),
    ("HTTP 429", urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)),
]:
    e = via_api_request(exc)
    check(f"transient: {label}", isinstance(e, T), f"got {type(e).__name__}: {e}")

print()
print("== conditions that must stay loud ==")
# A rejected certificate is a trust/config problem. Retrying it every 30
# minutes would bury it, so it must NOT be laundered into a quiet skip.
e = via_api_request(ssl.SSLCertVerificationError("certificate verify failed"))
check("certificate failure is not transient", not isinstance(e, T), f"got {type(e).__name__}")
e = via_api_request(ValueError("malformed json"))
check("ValueError propagates", isinstance(e, ValueError), f"got {type(e).__name__}")
e = via_api_request(urllib.error.HTTPError("u", 401, "Unauthorized", {}, None))
check("401 -> AuthExpiredError", isinstance(e, sync.AuthExpiredError), f"got {type(e).__name__}")
e = via_api_request(urllib.error.HTTPError("u", 500, "ISE", {}, None))
check("500 -> hard RuntimeError", type(e) is RuntimeError, f"got {type(e).__name__}")

print()
print("== sync state survives a mid-run abort ==")
with tempfile.TemporaryDirectory() as d:
    saved = {}
    orig = (sync.save_sync_state, sync.load_sync_state,
            sync.fetch_note_list, sync.fetch_note_detail)
    sync.save_sync_state = lambda od, st: saved.update(st)
    sync.load_sync_state = lambda od: {"old-uuid": {"filename": "old.md", "note_id": "n0"}}
    sync.fetch_note_list = lambda k, log, **kw: [{"id": "n1", "updated_at": "t1"}]

    def _boom(k, nid):
        raise T("network dropped mid-loop")

    sync.fetch_note_detail = _boom
    try:
        sync.sync_via_api(output_dir=d, force=False, dry_run=False, verbose=False)
        aborted = False
    except T:
        aborted = True
    finally:
        (sync.save_sync_state, sync.load_sync_state,
         sync.fetch_note_list, sync.fetch_note_detail) = orig
    check("abort still propagates to main()", aborted)
    check("prior state is not discarded",
          saved.get("old-uuid", {}).get("filename") == "old.md", f"saved={saved}")

print()
print("== log trimming ==")
with tempfile.TemporaryDirectory() as d:
    log = os.path.join(d, sync.LOG_FILE)

    sync._trim_log(d)
    check("missing log is a no-op", not os.path.exists(log))

    small = b"line\n" * 100
    open(log, "wb").write(small)
    sync._trim_log(d)
    check("under threshold untouched", open(log, "rb").read() == small)

    lines = [f"line {i:07d}\n".encode() for i in range(120_000)]
    open(log, "wb").write(b"".join(lines))
    sync._trim_log(d)
    out = open(log, "rb").read()
    check("trimmed below max", len(out) <= sync.LOG_MAX_BYTES, f"{len(out)}")
    check("header written", out.startswith(b"--- log trimmed to last "))
    check("newest line survives", out.endswith(lines[-1]))
    check("oldest line discarded", lines[0] not in out)
    check("no partial first line", out.split(b"\n", 1)[1].startswith(b"line "))

    # launchd holds an O_APPEND descriptor across the trim.
    with open(log, "ab") as f:
        f.write(b"after trim\n")
    check("append after trim is clean", open(log, "rb").read().endswith(b"line 0119999\nafter trim\n"))

    before = open(log, "rb").read()
    sync._trim_log(d)
    check("second trim is a no-op", open(log, "rb").read() == before)

    # A tail containing no newline has no partial line to drop; cutting at the
    # first newline anyway would leave nothing but the header.
    open(log, "wb").write(b"x" * (sync.LOG_MAX_BYTES + 5000))
    sync._trim_log(d)
    check("no-newline tail not wiped", len(open(log, "rb").read()) > 100_000)
    open(log, "wb").write(b"early\n" + b"y" * (sync.LOG_MAX_BYTES + 5000))
    sync._trim_log(d)
    check("newline outside kept window not wiped", len(open(log, "rb").read()) > 100_000)

    # Trimming must never be the reason a sync fails.
    open(log, "wb").write(b"z\n" * sync.LOG_MAX_BYTES)
    os.chmod(log, 0o400)
    try:
        sync._trim_log(d)
        check("unwritable log does not raise", True)
    except Exception as ex:  # noqa: BLE001
        check("unwritable log does not raise", False, repr(ex))
    finally:
        os.chmod(log, 0o600)

print()
print("== --dry-run writes nothing ==")
with tempfile.TemporaryDirectory() as d:
    log = os.path.join(d, sync.LOG_FILE)
    payload = b"z\n" * sync.LOG_MAX_BYTES
    open(log, "wb").write(payload)
    orig_sync, orig_argv = sync.sync_via_api, sys.argv
    sync.sync_via_api = lambda **kw: None
    sys.argv = ["sync.py", "--output-dir", d, "--dry-run"]
    try:
        sync.main()
    except SystemExit:
        pass
    finally:
        sync.sync_via_api, sys.argv = orig_sync, orig_argv
    check("--dry-run leaves the log untouched", open(log, "rb").read() == payload)

print()
print("== end to end: the 2026-08-16 failure ==")
with tempfile.TemporaryDirectory() as d:
    fired = []
    orig_run, orig_urlopen, orig_argv = sync.subprocess.run, sync.urllib.request.urlopen, sys.argv
    sync.subprocess.run = lambda *a, **k: fired.append(a)

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
        sync.subprocess.run, sync.urllib.request.urlopen, sys.argv = orig_run, orig_urlopen, orig_argv
    notified = os.path.exists(os.path.join(d, sync.NOTIFY_STATE_FILE)) or bool(fired)
    check("exits 0", code == 0, f"exit {code}")
    check("no desktop notification", not notified)

print()
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
