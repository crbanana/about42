"""Preprocess raw sources into inbox/ files.

Handles YouTube transcripts, Telegram text, plain text.
Twitch/TikTok are stubbed for now.
"""

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

INBOX_DIR = Path("inbox")

def _slugify_issue(title: str, issue_id: int) -> str:
    """Generate filename from issue title and id."""
    safe = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:40]
    return f"issue-{issue_id}_{safe}.md"


def _get_youtube_id(url: str) -> str | None:
    """Extract YouTube video ID from URL."""
    parsed = urlparse(url)
    if parsed.hostname in ("www.youtube.com", "youtube.com", "youtu.be"):
        if parsed.path.startswith("/watch"):
            q = parsed.query
            for param in q.split("&"):
                if param.startswith("v="):
                    return param[2:]
        elif parsed.path.startswith("/shorts/"):
            return parsed.path.split("/")[2]
        elif parsed.path.startswith("/live/"):
            return parsed.path.split("/")[2]
        elif parsed.hostname == "youtu.be":
            return parsed.path.lstrip("/")
    return None


def _fetch_youtube_transcript(video_id: str) -> str | None:
    """Fetch auto-captions via yt-dlp."""
    node_path = os.environ.get("NODE_PATH", "/home/crbsnana/.nvm/versions/node/v24.14.1/bin/node")
    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ru", "en"],
            "subtitlesformat": "json3",
            "outtmpl": os.path.join(tmpdir, "%(id)s"),
            "js_runtimes": {"node": {"path": node_path}},
            "remote_components": ("ejs:github",),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            print(f"[Preprocess] yt-dlp failed: {exc}")
            return None

        # Try json3 first, then srv1, then vtt
        for ext in ("json3", "srv1", "vtt"):
            for lang in ("ru", "en"):
                path = Path(tmpdir) / f"{video_id}.{lang}.{ext}"
                if path.exists():
                    content = path.read_text(encoding="utf-8")
                    return _parse_subtitles(content, ext)
    return None


def _parse_subtitles(content: str, fmt: str) -> str:
    """Parse subtitle content to plain text."""
    if fmt == "json3":
        try:
            data = json.loads(content)
            texts = []
            for event in data.get("events", []):
                for seg in event.get("segs", []):
                    if "utf8" in seg:
                        texts.append(seg["utf8"])
            return " ".join(texts)
        except Exception:
            return content
    elif fmt in ("srv1", "vtt"):
        lines = []
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("WEBVTT") and "-->" not in line and not line.isdigit():
                lines.append(line)
        return " ".join(lines)
    return content


def _build_inbox_file(issue_id: int, issue_title: str, source_type: str,
                      source_url: str | None, body_text: str,
                      published_at: str | None = None,
                      approved: bool = False) -> str:
    """Build inbox markdown file content."""
    frontmatter = {
        "issue_id": issue_id,
        "issue_title": issue_title,
        "source_type": source_type,
        "source_url": source_url or "",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "published_at": published_at or "",
        "approved": approved,
    }

    fm_lines = "\n".join(f'{k}: {json.dumps(v)}' for k, v in frontmatter.items())

    return f"""---
{fm_lines}
---

## Описание

{body_text}
"""


def process_issue(issue_id: int, issue_title: str, issue_body: str,
                  labels: list[str], created_at: str) -> str:
    """Process a GitHub issue into an inbox file. Returns filename."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    # Extract source type from labels
    source_type = "text"
    for label in labels:
        if label.startswith("type:"):
            source_type = label.replace("type:", "")
            break

    # Extract URL from body
    urls = re.findall(r"https?://[^\s\)\"\']+", issue_body or "")
    source_url = urls[0] if urls else None

    # Preprocess based on type
    if source_type in ("youtube", "twitch", "tiktok") and source_url:
        if source_type == "youtube":
            video_id = _get_youtube_id(source_url)
            if video_id:
                transcript = _fetch_youtube_transcript(video_id)
                if transcript:
                    body_text = f"URL: {source_url}\n\nТранскрипция:\n{transcript[:10000]}"
                else:
                    body_text = f"URL: {source_url}\n\n[Не удалось получить транскрипцию]"
            else:
                body_text = f"URL: {source_url}\n\n[Не удалось извлечь video_id]"
        else:
            body_text = f"URL: {source_url}\n\n[{source_type}: предобработка пока не реализована]"
    elif source_type == "telegram":
        # Body is already the post text
        body_text = issue_body or ""
    else:
        # Plain text
        body_text = issue_body or ""

    filename = _slugify_issue(issue_title, issue_id)
    filepath = INBOX_DIR / filename
    content = _build_inbox_file(
        issue_id=issue_id,
        issue_title=issue_title,
        source_type=source_type,
        source_url=source_url,
        body_text=body_text,
        published_at=created_at,
        approved=False,
    )
    filepath.write_text(content, encoding="utf-8")
    print(f"[Preprocess] Created {filepath}")
    return str(filepath)


def approve_issue(issue_id: int) -> bool:
    """Mark an inbox file as approved."""
    for f in INBOX_DIR.glob(f"issue-{issue_id}_*.md"):
        content = f.read_text(encoding="utf-8")
        content = content.replace("approved: false", "approved: true")
        f.write_text(content, encoding="utf-8")
        print(f"[Preprocess] Approved {f.name}")
        return True
    print(f"[Preprocess] No inbox file for issue {issue_id}")
    return False


def reject_issue(issue_id: int) -> bool:
    """Remove an inbox file."""
    for f in INBOX_DIR.glob(f"issue-{issue_id}_*.md"):
        f.unlink()
        print(f"[Preprocess] Removed {f.name}")
        return True
    print(f"[Preprocess] No inbox file for issue {issue_id}")
    return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["process", "approve", "reject"])
    parser.add_argument("--issue-id", type=int, required=True)
    parser.add_argument("--issue-title", default="")
    parser.add_argument("--issue-body", default="")
    parser.add_argument("--labels", default="[]")
    parser.add_argument("--created-at", default="")
    args = parser.parse_args()

    labels = json.loads(args.labels)

    if args.command == "process":
        process_issue(
            issue_id=args.issue_id,
            issue_title=args.issue_title,
            issue_body=args.issue_body,
            labels=labels,
            created_at=args.created_at,
        )
    elif args.command == "approve":
        approve_issue(args.issue_id)
    elif args.command == "reject":
        reject_issue(args.issue_id)
