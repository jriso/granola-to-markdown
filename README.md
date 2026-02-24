# granola-to-markdown

Sync your [Granola](https://granola.ai) meeting notes to clean, permanent markdown — accessible by [Claude](https://claude.ai), [OpenClaw](https://github.com/openclaw/openclaw), or any AI agent.

- Exports every meeting as a markdown file with YAML frontmatter (attendees, date, duration, notes, AI summary)
- Captures transcripts before Granola's cache evicts them
- Optionally syncs automatically every 30 minutes
- Optionally installs the [GranolaMCP](https://github.com/pedramamini/GranolaMCP) server for live meeting search in Claude Code

## Prerequisites

- **macOS** (Granola is a Mac app)
- **Granola** desktop app installed with at least one meeting recorded
- **Python 3.12+**
- **git**

## Quick Start

```bash
git clone https://github.com/jriso/granola-to-markdown.git
cd granola-to-markdown
./install.sh
```

That's it. Your meetings are now in `~/granola-notes/` as permanent markdown files.

## What the Installer Does

1. Verifies macOS, Python 3.12+, git, and Granola are present
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

This gives Claude tools like `search_meetings`, `get_transcript`, and `get_meeting_notes` — useful if you have hundreds of meetings and want fast, targeted lookups. The markdown export and MCP server read from the same source (Granola's local cache), so the data is identical. The difference is access pattern: bulk files vs. interactive queries.

## Running Sync Manually

```bash
python3 sync.py --verbose
```

| Flag | Description |
|------|-------------|
| `--output-dir <path>` | Output directory (default: `~/granola-notes`) |
| `--cache-path <path>` | Granola cache path (default: auto-detected) |
| `--force` | Re-export all meetings, not just changed ones |
| `--dry-run` | Preview what would change without writing |
| `--verbose` | Print detailed progress |

## Automatic Sync

To sync every 30 minutes in the background:

```bash
./install.sh --with-launchd
```

This installs a macOS launchd agent that runs the sync script automatically. Logs go to `~/granola-notes/.sync.log`.

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

Transcripts (when available in the cache) are saved as separate `*_transcript.md` files.

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

**"Cache file not found"** — Open the Granola app and make sure you've attended at least one meeting. The cache is created after your first meeting.

**MCP tools not working in Claude Code** — Make sure you installed with `--with-mcp`. Check that `~/.mcp.json` contains a `granola-mcp` entry. Re-run `./install.sh --with-mcp` to fix.

**Sync shows "0 created, 0 updated"** — Your meetings are already exported. Use `--force` to re-export everything.

**Missing meetings** — Granola's local cache has a limited retention window. Export regularly (or use `--with-launchd`) to capture meetings before they age out.

## License

MIT
