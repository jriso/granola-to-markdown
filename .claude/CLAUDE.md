# granola-to-markdown

Export Granola meeting notes as markdown and access them via Claude Code.

## Data source

The `sync.py` script pulls from Granola's **official public API** (`https://public-api.granola.ai`)
using a personal API key (`grn_…`), read from the `GRANOLA_API_KEY` env var or a `.granola_api_key`
file next to the script. It no longer reads Granola's local cache — recent Granola versions (7.42x+)
encrypt every local artifact behind a macOS Keychain key only the app can read, which killed the old
cache-decryption path (legacy `load_cache`/`_decrypt_granola_file` remain in the file but are dead).

## MCP Server (`granola-mcp`)  — optional, may be broken

After running `install.sh --with-mcp`, Claude Code has access to Granola meetings via MCP tools:

| Tool | What it does |
|------|-------------|
| `get_recent_meetings` | List the N most recent meetings |
| `search_meetings` | Search by text, date range, or participant |
| `get_meeting` | Get full details for a specific meeting |
| `get_transcript` | Get the full transcript with speaker labels |
| `get_meeting_notes` | Get structured notes and AI summary |
| `list_participants` | List all participants with frequency data |
| `get_statistics` | Meeting stats: summary, frequency, duration, participants |
| `export_meeting` | Export a meeting as markdown |
| `analyze_patterns` | Analyze meeting patterns over time |

> ⚠️ GranolaMCP reads Granola's **local cache**, which Granola 7.42x+ encrypts — so these tools may
> return nothing on recent versions. This is independent of the markdown sync, which uses the API.
> For interactive search, prefer Granola's official MCP server at `https://mcp.granola.ai/mcp`.

## Sync Script

Run manually:
```bash
python3 sync.py --verbose
```

Flags: `--output-dir`, `--force`, `--dry-run`, `--verbose` (`--cache-path` is deprecated/ignored)

Default output: `~/granola-notes`

## Exported File Format

Each meeting becomes `YYYY-MM-DD_slugified-title.md` with:

- **YAML frontmatter**: title, date, time, duration_minutes, attendees (name + email), granola_id, updated_at
- **## Notes**: Your notes from the meeting
- **## Summary**: AI-generated summary

Transcripts (when the meeting has one) are saved as `YYYY-MM-DD_title_transcript.md`.

Note: the public API does not expose the user's hand-typed notes, only the AI summary. On refresh,
`read_existing_user_notes()` recovers any existing `## Notes` section from disk so it isn't lost.

## Troubleshooting

- **No API key found**: Set `GRANOLA_API_KEY` or create `.granola_api_key` (a `grn_…` key from
  Granola → Settings → Connectors → API keys; requires a Business/Enterprise plan).
- **API key rejected (401)**: Key invalid or revoked. Regenerate it and update `.granola_api_key`.
- **Sync shows 0 created**: Meetings are already synced. Use `--force` to re-export all.
- **Missing meetings**: The API only returns notes that have a generated AI summary + transcript.
- **MCP tools not working**: See the GranolaMCP caveat above — likely broken on Granola 7.42x+.
