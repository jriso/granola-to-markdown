# granola-to-markdown

Sync your [Granola](https://granola.ai) meeting notes to clean, permanent markdown — accessible by [Claude](https://claude.ai), [OpenClaw](https://github.com/openclaw/openclaw), or any AI agent.

- Exports every meeting as a markdown file with YAML frontmatter (attendees, date, duration, notes, AI summary)
- Captures the full transcript alongside each meeting
- Pulls from Granola's official public API — full history, no reliance on the local cache
- Optionally syncs automatically every 30 minutes
- Optionally installs the [GranolaMCP](https://github.com/pedramamini/GranolaMCP) server for live meeting search in Claude Code

## Prerequisites

- **macOS** (for the optional launchd auto-sync; the sync script itself is cross-platform)
- A **Granola account on a Business or Enterprise plan** — required to create an API key
- A **Granola Personal API key** (`grn_…`) — see [Get an API key](#get-an-api-key) below
- **Python 3.12+**
- **git**

## Get an API key

The sync pulls from Granola's [public API](https://docs.granola.ai), so it needs a personal API key:

1. In the Granola desktop app, go to **Settings → Connectors → API keys → Create new key**.
2. Copy the generated key (it starts with `grn_`).
3. Make it available to the sync in either way:
   - **Env var:** `export GRANOLA_API_KEY=grn_your_key_here`, or
   - **Key file:** save it to `granola-to-markdown/.granola_api_key` (one line, just the key).
     This file is gitignored so it won't be committed.

> Creating a key requires a Business/Enterprise plan. The older versions of this tool read
> Granola's local cache and needed no key — that path no longer works (see [below](#a-note-on---with-mcp)).

## Quick Start

```bash
git clone https://github.com/jriso/granola-to-markdown.git
cd granola-to-markdown

# Provide your Granola API key (see "Get an API key" above)
echo 'grn_your_key_here' > .granola_api_key   # or: export GRANOLA_API_KEY=grn_...

./install.sh
```

Your meetings are now in `~/granola-notes/` as permanent markdown files.

## What the Installer Does

1. Verifies Python 3.12+, git, and a Granola API key are present
2. Creates `~/granola-notes/` and runs the initial export

With `--with-mcp`, it also:

3. Installs [uv](https://docs.astral.sh/uv/) if not already installed
4. Clones [GranolaMCP](https://github.com/pedramamini/GranolaMCP) to `~/.local/share/granola-mcp/`
5. Adds the `granola-mcp` MCP server to `~/.mcp.json` (preserves your existing config)

The installer is idempotent — safe to run again if you need to update.

## Using with Claude Code

Claude Code can read the exported markdown files in `~/granola-notes/` directly — no extra setup needed. Point it at the directory and ask about your meetings.

### Optional: MCP server for live search

If you want Claude to interactively search and query your meetings (by participant, date range, keyword, etc.) without reading every file, install the MCP server:

```bash
./install.sh --with-mcp
```

This gives Claude tools like `search_meetings`, `get_transcript`, and `get_meeting_notes` — useful if you have hundreds of meetings and want fast, targeted lookups.

### A note on `--with-mcp`

> ⚠️ **This feature may no longer work.** [GranolaMCP](https://github.com/pedramamini/GranolaMCP)
> reads Granola's **local cache**, which recent Granola versions (7.42x+) encrypt behind a macOS
> Keychain key only the Granola app can read. On affected versions the cache is unreadable by
> third-party tools, so GranolaMCP returns nothing. The markdown export in this repo is unaffected —
> it uses the public API. For interactive search, prefer Granola's **official** MCP server at
> `https://mcp.granola.ai/mcp` (browser OAuth), which you can add to Claude Code directly.

## Running Sync Manually

```bash
python3 sync.py --verbose
```

| Flag | Description |
|------|-------------|
| `--output-dir <path>` | Output directory (default: `~/granola-notes`) |
| `--cache-path <path>` | *(Deprecated — ignored. The local cache is no longer used.)* |
| `--force` | Re-export all meetings, not just changed ones |
| `--dry-run` | Preview what would change without writing |
| `--verbose` | Print detailed progress |

## Automatic Sync

To sync every 30 minutes in the background:

```bash
./install.sh --with-launchd
```

This installs a macOS launchd agent that runs the sync script automatically. Logs go to `~/granola-notes/.sync.log`. Once that file passes 1 MB, the next run trims it to its most recent 200 KB — older lines are discarded, so copy anything you need to keep.

The launchd agent reads your API key from the `.granola_api_key` **file** (it doesn't inherit your shell's `GRANOLA_API_KEY` env var), so make sure that file exists for background sync to work.

To stop automatic sync:

```bash
launchctl unload ~/Library/LaunchAgents/com.granola-to-markdown.sync.plist
```

## Exported File Format

Each meeting becomes a markdown file named `YYYY-MM-DD_meeting-title.md`:

```yaml
---
title: Weekly Standup
date: 2025-01-15
time: "09:00"
duration_minutes: 30
attendees:
  - name: Alice Smith
    email: alice@example.com
  - name: Bob Jones
    email: bob@example.com
type: meeting
granola_id: abc123
updated_at: "2025-01-15T09:35:00Z"
---

# Weekly Standup

## Notes

Your notes from the meeting...

## Summary

AI-generated summary of the discussion...
```

Transcripts (when the meeting has one) are saved as separate `*_transcript.md` files.

## Remote AI Access

The exported markdown files work as a universal integration layer. If you run a remote AI agent — on a home server, cloud VM, or anywhere else — you can give it full meeting context.

**Same Mac** — Point the agent at `~/granola-notes/` directly. Nothing else needed.

**LAN (Mac Mini, NAS)** — Use rsync, a shared folder, or Syncthing to mirror the output directory:

```bash
# Example: rsync to a Mac Mini every 30 min (add to crontab)
rsync -a ~/granola-notes/ mini.local:~/meetings/
```

**Cloud VM** — Push to a private git repo and pull from the remote:

```bash
# On your Mac (one-time setup):
cd ~/granola-notes
git init && git remote add origin git@github.com:you/meetings-private.git
git add -A && git commit -m "initial sync" && git push -u origin main

# Add to crontab or run after each sync:
cd ~/granola-notes && git add -A && git commit -m "sync" && git push

# On your remote VM:
git clone git@github.com:you/meetings-private.git ~/meetings
crontab -e  # add: */30 * * * * cd ~/meetings && git pull -q
```

The markdown files contain meeting titles, attendees, notes, AI summaries, and transcripts — everything a remote assistant needs to prep you for meetings, track action items, or search past conversations.

## Uninstalling

```bash
./uninstall.sh
```

This removes the MCP server config (if installed), GranolaMCP, and launchd agent. Your exported meeting notes are **not deleted** — remove them manually if you want.

## Troubleshooting

**"No Granola API key found"** — The sync needs your `grn_` key. Set `GRANOLA_API_KEY` or create a `.granola_api_key` file in the repo. See [Get an API key](#get-an-api-key).

**Sync skipped: "Granola API key rejected (401)"** — Your key is invalid or was revoked. Regenerate it in **Granola → Settings → Connectors → API keys** and update your `.granola_api_key` file (or `GRANOLA_API_KEY`).

**MCP tools not working in Claude Code** — Note that `--with-mcp` may be broken on recent Granola versions (see [A note on `--with-mcp`](#a-note-on---with-mcp)). If you still want to try it: check that `~/.mcp.json` contains a `granola-mcp` entry and re-run `./install.sh --with-mcp`.

**Sync shows "0 created, 0 updated"** — Your meetings are already exported. Use `--force` to re-export everything.

**Missing meetings** — The API only returns notes that have a generated AI summary, so a meeting that was never processed by Granola won't appear. A missing transcript is not a reason for a note to be skipped — those notes sync fine, just without a `_transcript.md` companion. Otherwise the API serves your full history, regardless of age.

**Sync skipped: network error** — The API was temporarily unreachable (or rate-limited). The run exits cleanly with existing notes preserved; the next scheduled run retries automatically.

## License

MIT
