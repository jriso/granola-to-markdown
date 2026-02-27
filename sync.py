#!/usr/bin/env python3
"""Sync Granola meeting notes to markdown files.

Reads Granola's local cache and exports each meeting as a clean markdown
file with YAML frontmatter. Supports incremental updates via .sync-state.json.

Stdlib only — no external dependencies.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

DEFAULT_CACHE_PATH = os.path.expanduser(
    "~/Library/Application Support/Granola/cache-v4.json"
)
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/granola-notes")
STATE_FILE = ".sync-state.json"


# ---------------------------------------------------------------------------
# Tiptap JSON -> Markdown converter
# ---------------------------------------------------------------------------

def tiptap_to_markdown(node, indent=0, ordered_num=None):
    """Recursively convert a Tiptap JSON node to markdown."""
    if node is None:
        return ""

    ntype = node.get("type", "")
    content = node.get("content", [])
    attrs = node.get("attrs", {})

    if ntype == "doc":
        return "\n".join(tiptap_to_markdown(c) for c in content).strip()

    if ntype == "heading":
        level = attrs.get("level", 1)
        text = "".join(tiptap_to_markdown(c) for c in content)
        return f"\n{'#' * level} {text}\n"

    if ntype == "paragraph":
        text = "".join(tiptap_to_markdown(c) for c in content)
        if indent > 0:
            return text
        return f"\n{text}\n"

    if ntype == "bulletList":
        lines = []
        for item in content:
            lines.append(tiptap_to_markdown(item, indent))
        return "\n".join(lines)

    if ntype == "orderedList":
        lines = []
        for i, item in enumerate(content, 1):
            lines.append(tiptap_to_markdown(item, indent, ordered_num=i))
        return "\n".join(lines)

    if ntype == "listItem":
        parts = []
        sub_lists = []
        for c in content:
            if c.get("type") in ("bulletList", "orderedList"):
                sub_lists.append(c)
            else:
                parts.append(c)

        prefix = "  " * indent
        marker = f"{ordered_num}." if ordered_num else "-"
        text = "".join(tiptap_to_markdown(c, indent) for c in parts).strip()
        result = f"{prefix}{marker} {text}"

        for sl in sub_lists:
            result += "\n" + tiptap_to_markdown(sl, indent + 1)

        return result

    if ntype == "text":
        text = node.get("text", "")
        marks = node.get("marks", [])
        for mark in marks:
            mtype = mark.get("type", "")
            if mtype == "bold":
                text = f"**{text}**"
            elif mtype == "italic":
                text = f"*{text}*"
            elif mtype == "link":
                href = mark.get("attrs", {}).get("href", "")
                text = f"[{text}]({href})"
            elif mtype == "code":
                text = f"`{text}`"
        return text

    if ntype == "horizontalRule":
        return "\n---\n"

    if ntype == "hardBreak":
        return "\n"

    if ntype == "codeBlock":
        text = "".join(tiptap_to_markdown(c) for c in content)
        lang = attrs.get("language", "")
        return f"\n```{lang}\n{text}\n```\n"

    if ntype == "blockquote":
        text = "".join(tiptap_to_markdown(c) for c in content)
        return "\n" + "\n".join(f"> {line}" for line in text.strip().split("\n")) + "\n"

    # Unknown node type — render children
    return "".join(tiptap_to_markdown(c, indent) for c in content)


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------

def slugify(text):
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def parse_datetime(dt_string):
    """Parse ISO 8601 datetime string, handling timezone offsets."""
    if not dt_string:
        return None
    # Remove colon in timezone offset for Python 3.x < 3.7 compat
    # "2026-01-05T11:45:00-05:00" -> works directly with fromisoformat in 3.7+
    try:
        return datetime.fromisoformat(dt_string)
    except (ValueError, TypeError):
        return None


def get_attendee_name(attendee):
    """Extract the best available name from an attendee dict."""
    if attendee.get("name"):
        return attendee["name"]
    details = attendee.get("details", {})
    person = details.get("person", {})
    name_obj = person.get("name", {})
    if name_obj.get("fullName"):
        return name_obj["fullName"]
    return attendee.get("email", "Unknown")


def extract_meeting_data(doc, panels, folders=None):
    """Extract structured meeting data from a Granola document."""
    doc_id = doc["id"]
    title = doc.get("title", "Untitled Meeting")

    # Date and time from calendar event or created_at
    cal_event = doc.get("google_calendar_event")
    duration_minutes = None
    if cal_event and cal_event.get("start", {}).get("dateTime"):
        start_dt = parse_datetime(cal_event["start"]["dateTime"])
        end_dt = parse_datetime(cal_event.get("end", {}).get("dateTime"))
        if start_dt and end_dt:
            duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
    else:
        start_dt = parse_datetime(doc.get("created_at"))

    if not start_dt:
        start_dt = datetime.now()

    date_str = start_dt.strftime("%Y-%m-%d")
    time_str = start_dt.strftime("%H:%M")

    # Attendees
    attendees = []
    people = doc.get("people") or {}
    creator = people.get("creator")
    if creator:
        attendees.append({
            "name": get_attendee_name(creator),
            "email": creator.get("email", ""),
        })
    for att in people.get("attendees", []):
        attendees.append({
            "name": get_attendee_name(att),
            "email": att.get("email", ""),
        })

    # User notes — prefer notes_markdown, fall back to Tiptap conversion
    notes_md = doc.get("notes_markdown", "")
    if not notes_md and doc.get("notes"):
        notes_md = tiptap_to_markdown(doc["notes"])
    notes_md = (notes_md or "").strip()

    # AI summary from documentPanels
    summary_md = ""
    doc_panels = panels.get(doc_id, {})
    for panel_id, panel in doc_panels.items():
        panel_content = panel.get("content")
        if panel_content and isinstance(panel_content, dict):
            summary_md = tiptap_to_markdown(panel_content).strip()
            break
        # Fallback: use original_content (HTML) if no Tiptap
        html = panel.get("original_content", "")
        if html and not summary_md:
            summary_md = html_to_basic_markdown(html)

    return {
        "id": doc_id,
        "title": title,
        "date": date_str,
        "time": time_str,
        "duration_minutes": duration_minutes,
        "attendees": attendees,
        "folders": folders or [],
        "notes": notes_md,
        "summary": summary_md,
        "updated_at": doc.get("updated_at", ""),
    }


def html_to_basic_markdown(html):
    """Minimal HTML to markdown for fallback (handles h3, ul/li, p)."""
    text = html
    text = re.sub(r"<h[1-6][^>]*>", "\n### ", text)
    text = re.sub(r"</h[1-6]>", "\n", text)
    text = re.sub(r"<li[^>]*>", "- ", text)
    text = re.sub(r"</li>", "\n", text)
    text = re.sub(r"<p[^>]*>", "\n", text)
    text = re.sub(r"</p>", "\n", text)
    text = re.sub(r"<strong>", "**", text)
    text = re.sub(r"</strong>", "**", text)
    text = re.sub(r"<em>", "*", text)
    text = re.sub(r"</em>", "*", text)
    text = re.sub(r"<[^>]+>", "", text)  # Strip remaining tags
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def yaml_escape(value):
    """Escape a string value for YAML output."""
    if not isinstance(value, str):
        return str(value)
    # Quote strings that contain special YAML characters
    if any(c in value for c in ":#{}[]|>&*!%@`'\"\\,\n"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if not value:
        return '""'
    return value


def format_transcript(utterances):
    """Format transcript utterances as readable markdown."""
    lines = []
    current_speaker = None
    for utt in utterances:
        speaker = "You" if utt.get("source") == "microphone" else "Other"
        text = utt.get("text", "").strip()
        if not text:
            continue
        ts = utt.get("start_timestamp", "")
        time_str = ""
        if ts:
            dt = parse_datetime(ts)
            if dt:
                time_str = f"[{dt.strftime('%H:%M:%S')}] "
        if speaker != current_speaker:
            lines.append(f"\n**{speaker}:** {time_str}{text}")
            current_speaker = speaker
        else:
            lines.append(f"{time_str}{text}")
    return "\n".join(lines).strip()


def build_markdown(data):
    """Build the final markdown file content with YAML frontmatter."""
    lines = ["---"]
    lines.append(f"title: {yaml_escape(data['title'])}")
    lines.append(f"date: {data['date']}")
    lines.append(f'time: "{data["time"]}"')
    if data["duration_minutes"] is not None:
        lines.append(f"duration_minutes: {data['duration_minutes']}")
    if data["attendees"]:
        lines.append("attendees:")
        for att in data["attendees"]:
            lines.append(f"  - name: {yaml_escape(att['name'])}")
            lines.append(f"    email: {att['email']}")
    if data["folders"]:
        lines.append("folders:")
        for folder in data["folders"]:
            lines.append(f"  - {yaml_escape(folder)}")
    lines.append("type: meeting")
    lines.append(f"granola_id: {data['id']}")
    lines.append(f'updated_at: "{data["updated_at"]}"')
    lines.append("---")
    lines.append("")
    lines.append(f"# {data['title']}")
    lines.append("")

    if data["notes"]:
        lines.append("## Notes")
        lines.append("")
        lines.append(data["notes"])
        lines.append("")

    if data["summary"]:
        lines.append("## Summary")
        lines.append("")
        lines.append(data["summary"])
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def load_cache(cache_path):
    """Load and parse the Granola cache file."""
    with open(cache_path, "r") as f:
        raw = json.load(f)

    cache_data = raw["cache"]
    if isinstance(cache_data, str):
        cache_data = json.loads(cache_data)
    return cache_data["state"]


def load_sync_state(output_dir):
    """Load the sync state tracking file."""
    state_path = os.path.join(output_dir, STATE_FILE)
    if os.path.exists(state_path):
        with open(state_path, "r") as f:
            return json.load(f)
    return {}


def save_sync_state(output_dir, state):
    """Save the sync state tracking file."""
    state_path = os.path.join(output_dir, STATE_FILE)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def sync(cache_path, output_dir, force=False, dry_run=False, verbose=False):
    """Main sync function."""
    log = lambda msg: print(msg) if verbose else None

    log(f"Loading cache from {cache_path}")
    state = load_cache(cache_path)

    documents = state.get("documents", {})
    panels = state.get("documentPanels", {})
    transcripts = state.get("transcripts", {})

    # Build reverse lookup: document_id -> [folder_name, ...]
    doc_lists_meta = state.get("documentListsMetadata", {})
    doc_lists = state.get("documentLists", {})
    doc_folders = {}
    for list_id, doc_ids in doc_lists.items():
        name = doc_lists_meta.get(list_id, {}).get("title")
        if name:
            for did in doc_ids:
                doc_folders.setdefault(did, []).append(name)
    for did in doc_folders:
        doc_folders[did].sort()

    log(f"Found {len(documents)} documents, {len(transcripts)} transcripts")

    os.makedirs(output_dir, exist_ok=True)
    sync_state = load_sync_state(output_dir) if not force else {}

    # First pass: determine all filenames to detect collisions
    all_data = {}
    filenames_used = set()
    for doc_id, doc in documents.items():
        if doc.get("deleted_at") or doc.get("was_trashed"):
            log(f"  Skipping deleted: {doc.get('title', doc_id)}")
            continue
        data = extract_meeting_data(doc, panels, folders=doc_folders.get(doc_id))
        all_data[doc_id] = data

    # Assign filenames (detect collisions)
    filenames = {}
    filename_counts = {}
    for doc_id, data in all_data.items():
        slug = slugify(data["title"]) or "untitled"
        base = f"{data['date']}_{slug}"
        filename = f"{base}.md"
        if filename in filename_counts:
            filename_counts[filename] += 1
            filename = f"{base}_{doc_id[:8]}.md"
        else:
            filename_counts[filename] = 1
        filenames[doc_id] = filename

    # Handle collisions for the first occurrence too
    for doc_id, data in all_data.items():
        slug = slugify(data["title"]) or "untitled"
        base = f"{data['date']}_{slug}"
        orig_filename = f"{base}.md"
        if filename_counts.get(orig_filename, 0) > 1 and filenames[doc_id] == orig_filename:
            filenames[doc_id] = f"{base}_{doc_id[:8]}.md"

    # Sync each document
    created = 0
    updated = 0
    skipped = 0
    new_sync_state = {}

    for doc_id, data in all_data.items():
        filename = filenames[doc_id]
        prev = sync_state.get(doc_id, {})

        # Check if update needed
        if not force and prev.get("updated_at") == data["updated_at"]:
            new_sync_state[doc_id] = prev
            skipped += 1
            continue

        # Clean up old file if title/date changed (rename detection)
        old_filename = prev.get("filename")
        if old_filename and old_filename != filename:
            old_path = os.path.join(output_dir, old_filename)
            if os.path.exists(old_path):
                if dry_run:
                    log(f"  Would remove old file: {old_filename}")
                else:
                    os.remove(old_path)
                    log(f"  Removed old file: {old_filename}")

        # Write the file
        filepath = os.path.join(output_dir, filename)
        content = build_markdown(data)

        if dry_run:
            action = "create" if not prev else "update"
            log(f"  Would {action}: {filename}")
        else:
            with open(filepath, "w") as f:
                f.write(content)
            if prev:
                updated += 1
                log(f"  Updated: {filename}")
            else:
                created += 1
                log(f"  Created: {filename}")

        new_sync_state[doc_id] = {
            "updated_at": data["updated_at"],
            "filename": filename,
        }

    # Export transcripts (ephemeral in cache — save before Granola evicts them)
    transcripts_saved = 0
    for doc_id, utterances in transcripts.items():
        if not utterances or doc_id not in all_data:
            continue
        prev = new_sync_state.get(doc_id, sync_state.get(doc_id, {}))
        if prev.get("transcript_saved"):
            continue  # Already captured this transcript

        data = all_data[doc_id]
        slug = slugify(data["title"]) or "untitled"
        transcript_filename = f"{data['date']}_{slug}_transcript.md"
        transcript_path = os.path.join(output_dir, transcript_filename)
        transcript_md = format_transcript(utterances)

        if dry_run:
            log(f"  Would save transcript: {transcript_filename} ({len(utterances)} utterances)")
        else:
            with open(transcript_path, "w") as f:
                f.write(f"---\ntitle: \"{data['title']} — Transcript\"\n")
                f.write(f"date: {data['date']}\n")
                f.write(f"granola_id: {doc_id}\n")
                f.write(f"type: transcript\n---\n\n")
                f.write(f"# {data['title']} — Transcript\n\n")
                f.write(transcript_md)
                f.write("\n")
            log(f"  Saved transcript: {transcript_filename} ({len(utterances)} utterances)")

        transcripts_saved += 1
        if doc_id in new_sync_state:
            new_sync_state[doc_id]["transcript_saved"] = True
            new_sync_state[doc_id]["transcript_filename"] = transcript_filename
        else:
            new_sync_state[doc_id] = {
                "updated_at": data["updated_at"],
                "filename": filenames.get(doc_id, ""),
                "transcript_saved": True,
                "transcript_filename": transcript_filename,
            }

    # Clean up files for documents no longer in cache
    # Note: transcript files are preserved even if the document leaves the cache
    removed = 0
    for doc_id, prev in sync_state.items():
        if doc_id not in all_data:
            old_path = os.path.join(output_dir, prev.get("filename", ""))
            if os.path.exists(old_path):
                if dry_run:
                    log(f"  Would remove orphan: {prev['filename']}")
                else:
                    os.remove(old_path)
                    log(f"  Removed orphan: {prev['filename']}")
                removed += 1
            # Preserve transcript state so the file isn't orphaned
            if prev.get("transcript_saved"):
                new_sync_state[doc_id] = {
                    "transcript_saved": True,
                    "transcript_filename": prev["transcript_filename"],
                }

    if not dry_run:
        save_sync_state(output_dir, new_sync_state)

    prefix = "[DRY RUN] " if dry_run else ""
    parts = [
        f"{created} created, {updated} updated",
        f"{skipped} unchanged, {removed} removed",
    ]
    if transcripts_saved:
        parts.append(f"{transcripts_saved} transcripts saved")
    print(f"{prefix}Sync complete: {', '.join(parts)}")


def main():
    parser = argparse.ArgumentParser(
        description="Sync Granola meeting notes to markdown files"
    )
    parser.add_argument(
        "--cache-path",
        default=DEFAULT_CACHE_PATH,
        help=f"Path to Granola cache file (default: {DEFAULT_CACHE_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for markdown files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-export of all documents",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed progress",
    )
    args = parser.parse_args()

    if not os.path.exists(args.cache_path):
        print(f"Error: Cache file not found: {args.cache_path}", file=sys.stderr)
        sys.exit(1)

    sync(
        cache_path=args.cache_path,
        output_dir=args.output_dir,
        force=args.force,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
