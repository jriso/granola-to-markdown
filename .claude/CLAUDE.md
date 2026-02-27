# granola-to-markdown

Export Granola meeting notes as markdown and access them via Claude Code.

## MCP Server (`granola-mcp`)

After running `install.sh`, Claude Code has access to Granola meetings via MCP tools:

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

Data source: Local Granola cache at `~/Library/Application Support/Granola/cache-v4.json`. No API key needed.

## Sync Script

Run manually:
```bash
python3 sync.py --verbose
```

Flags: `--cache-path`, `--output-dir`, `--force`, `--dry-run`, `--verbose`

Default output: `~/granola-notes`

## Exported File Format

Each meeting becomes `YYYY-MM-DD_slugified-title.md` with:

- **YAML frontmatter**: title, date, time, duration_minutes, attendees (name + email), granola_id, updated_at
- **## Notes**: Your notes from the meeting
- **## Summary**: AI-generated summary

Transcripts (when available) are saved as `YYYY-MM-DD_title_transcript.md`.

## Troubleshooting

- **MCP tools not working**: Check `~/.mcp.json` has a `granola-mcp` entry. Re-run `./install.sh`.
- **No meetings found**: Open Granola and attend/record a meeting first. The cache file must exist.
- **Sync shows 0 created**: Meetings are already synced. Use `--force` to re-export all.
- **Stale data**: Granola updates its cache after meetings end. Wait a moment and retry.
