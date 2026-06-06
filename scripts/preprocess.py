"""Preprocess raw sources into inbox/ files.

Supports:
- YouTube (subtitles via yt-dlp, metadata extraction)
- Twitch clips (audio -> Whisper -> Gemini description, metadata)
- TikTok (audio -> Whisper -> Gemini description, metadata)
- Telegram (web scraping, metadata)
- Plain text (pass-through)
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yt_dlp
from openai import OpenAI

INBOX_DIR = Path("inbox")

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")


def _openrouter_client() -> OpenAI:
    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)


def _slugify_issue(title: str, issue_id: int) -> str:
    safe = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:40]
    return f"issue-{issue_id}_{safe}.md"


def _extract_url(body: str) -> str | None:
    urls = re.findall(r"https?://[^\s\)\"\']+", body or "")
    return urls[0] if urls else None


# ── Metadata helpers ──────────────────────────────────

def _format_date(raw: str | None) -> str:
    """Convert various date formats to YYYY-MM-DD."""
    if not raw:
        return ""
    # yt-dlp returns YYYYMMDD or ISO
    raw = raw.strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return raw[:10]


def _build_meta_block(title: str | None, date: str | None, source_type: str,
                      author: str | None) -> str:
    lines = [f"Тип источника: {source_type}"]
    if title:
        lines.append(f"Название: {title}")
    if date:
        lines.append(f"Дата публикации: {date}")
    if author:
        lines.append(f"Автор: {author}")
    return "\n".join(lines)


# ── YouTube ──────────────────────────────────────────

def _get_youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname in ("www.youtube.com", "youtube.com", "youtu.be"):
        if parsed.path.startswith("/watch"):
            for param in parsed.query.split("&"):
                if param.startswith("v="):
                    return param[2:]
        elif parsed.path.startswith(("/shorts/", "/live/")):
            return parsed.path.split("/")[2]
        elif parsed.hostname == "youtu.be":
            return parsed.path.lstrip("/")
    return None


def _fetch_youtube_info(video_id: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (transcript, title, upload_date, uploader)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    transcript = None
    title = None
    upload_date = None
    uploader = None

    with tempfile.TemporaryDirectory() as tmpdir:
        # First pass: get metadata
        ydl_opts_meta = {"quiet": True, "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title")
                upload_date = info.get("upload_date")
                uploader = info.get("uploader")
        except Exception:
            pass

        # Second pass: get subtitles
        ydl_opts_sub = {
            "quiet": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ru", "en"],
            "subtitlesformat": "json3",
            "outtmpl": str(Path(tmpdir) / "%(id)s"),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts_sub) as ydl:
                ydl.download([url])
        except Exception:
            pass

        for ext in ("json3", "srv1", "vtt"):
            for lang in ("ru", "en"):
                path = Path(tmpdir) / f"{video_id}.{lang}.{ext}"
                if path.exists():
                    transcript = _parse_subtitles(path.read_text(encoding="utf-8"), ext)
                    break
            if transcript:
                break

    return transcript, title, upload_date, uploader


def _parse_subtitles(content: str, fmt: str) -> str:
    if fmt == "json3":
        try:
            data = json.loads(content)
            texts = [seg["utf8"] for ev in data.get("events", []) for seg in ev.get("segs", []) if "utf8" in seg]
            return " ".join(texts)
        except Exception:
            return content
    lines = [ln.strip() for ln in content.split("\n") if ln.strip() and not ln.startswith("WEBVTT") and "-->" not in ln and not ln.strip().isdigit()]
    return " ".join(lines)


# ── Twitch / TikTok (video -> audio -> whisper -> gemini) ──

def _fetch_video_info(url: str) -> tuple[str | None, str | None, str | None]:
    """Return (title, upload_date, uploader)."""
    ydl_opts = {"quiet": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title"), info.get("upload_date"), info.get("uploader")
    except Exception:
        return None, None, None


def _download_audio(url: str) -> Path | None:
    with tempfile.TemporaryDirectory() as tmpdir:
        outtmpl = str(Path(tmpdir) / "%(id)s")
        ydl_opts = {
            "quiet": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                vid_id = info.get("id", "video")
                mp3 = Path(tmpdir) / f"{vid_id}.mp3"
                if mp3.exists():
                    return mp3
        except Exception as exc:
            print(f"[Preprocess] Download failed: {exc}")
    return None


def _whisper_transcribe(audio_path: Path) -> str | None:
    client = _openrouter_client()
    try:
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(model="openai/whisper-1", file=f)
        return result.text
    except Exception as exc:
        print(f"[Preprocess] Whisper failed: {exc}")
        return None


def _gemini_describe(context: str, source_type: str) -> str | None:
    client = _openrouter_client()
    prompt = (
        f"Ты ассистент, который описывает {source_type}-видео стримера Пятерка.\n"
        "На основе транскрипции и метаданных напиши подробное описание:\n"
        "- что происходит,\n"
        "- кто участвует,\n"
        "- ключевые моменты, цитаты,\n"
        "- дата (если указана).\n\n"
        f"Контекст:\n{context[:8000]}"
    )
    try:
        resp = client.chat.completions.create(
            model="google/gemini-3.1-flash-lite",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        return resp.choices[0].message.content
    except Exception as exc:
        print(f"[Preprocess] Gemini failed: {exc}")
        return None


def _process_video(url: str, source_type: str) -> tuple[str, str | None, str | None, str | None]:
    """Download, transcribe, describe. Returns (body_text, title, date, author)."""
    title, upload_date, uploader = _fetch_video_info(url)

    print(f"[Preprocess] Downloading {source_type} audio...")
    audio = _download_audio(url)
    if not audio:
        return f"URL: {url}\n\n[Не удалось скачать аудио]", title, upload_date, uploader

    print(f"[Preprocess] Transcribing with Whisper...")
    transcript = _whisper_transcribe(audio)
    if not transcript:
        return f"URL: {url}\n\n[Не удалось получить транскрипцию]", title, upload_date, uploader

    context = f"URL: {url}\n\nТранскрипция:\n{transcript}"
    print(f"[Preprocess] Describing with Gemini...")
    description = _gemini_describe(context, source_type)

    if description:
        body = f"URL: {url}\n\nОписание:\n{description}"
    else:
        body = context
    return body, title, upload_date, uploader


# ── Telegram ─────────────────────────────────────────

def _fetch_telegram_post(url: str) -> tuple[str | None, str | None, str | None]:
    """Scrape public Telegram post. Returns (text, channel_name, post_date)."""
    try:
        resp = requests.get(url + "?embed=1", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        # Extract channel name from URL
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")
        channel_name = path_parts[0] if path_parts else None

        # Extract date from HTML
        date_match = re.search(r'<time[^>]*datetime="([^"]+)"', resp.text)
        post_date = date_match.group(1) if date_match else None

        # Extract text
        text_match = re.search(r'<div class="tgme_widget_message_text[^"]*">(.*?)</div>', resp.text, re.DOTALL)
        if text_match:
            raw = text_match.group(1)
            clean = re.sub(r'<[^>]+>', '', raw)
            clean = clean.replace('&nbsp;', ' ').replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>')
            return clean.strip(), channel_name, post_date
    except Exception as exc:
        print(f"[Preprocess] Telegram fetch failed: {exc}")
    return None, None, None


# ── Builder ─────────────────────────────────────────────

def _build_inbox_file(issue_id: int, issue_title: str, source_type: str,
                      source_url: str | None, meta_block: str, body_text: str,
                      published_at: str | None = None) -> str:
    frontmatter = {
        "issue_id": issue_id,
        "issue_title": issue_title,
        "source_type": source_type,
        "source_url": source_url or "",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "published_at": published_at or "",
        "approved": False,
    }
    fm = "\n".join(f'{k}: {json.dumps(v)}' for k, v in frontmatter.items())
    return f"---\n{fm}\n---\n\n## Метаданные\n\n{meta_block}\n\n## Описание\n\n{body_text}\n"


def process_issue(issue_id: int, issue_title: str, issue_body: str,
                  labels: list[str], created_at: str) -> str:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    source_type = "text"
    for label in labels:
        if label.startswith("type:"):
            source_type = label.replace("type:", "")
            break

    source_url = _extract_url(issue_body)
    title: str | None = None
    date: str | None = None
    author: str | None = None
    body_text = ""

    if source_type == "youtube" and source_url:
        video_id = _get_youtube_id(source_url)
        if video_id:
            transcript, title, upload_date, uploader = _fetch_youtube_info(video_id)
            date = _format_date(upload_date)
            author = uploader
            if transcript:
                body_text = f"URL: {source_url}\n\nТранскрипция:\n{transcript}"
            else:
                body_text = f"URL: {source_url}\n\n[Не удалось получить транскрипцию]"
        else:
            body_text = f"URL: {source_url}\n\n[Не удалось извлечь video_id]"

    elif source_type in ("twitch", "tiktok") and source_url:
        body_text, title, upload_date, uploader = _process_video(source_url, source_type)
        date = _format_date(upload_date)
        author = uploader

    elif source_type == "telegram" and source_url:
        post_text, channel_name, post_date = _fetch_telegram_post(source_url)
        title = None  # Telegram posts don't have titles
        date = _format_date(post_date)
        author = channel_name
        if post_text:
            body_text = f"URL: {source_url}\n\nТекст поста:\n{post_text}"
        else:
            body_text = f"URL: {source_url}\n\n[Не удалось получить текст поста]"

    else:
        # text or no URL
        body_text = issue_body or ""
        title = issue_title if issue_title else None
        date = _format_date(created_at)

    meta_block = _build_meta_block(title, date, source_type, author)

    filename = _slugify_issue(issue_title, issue_id)
    filepath = INBOX_DIR / filename
    content = _build_inbox_file(issue_id, issue_title, source_type, source_url, meta_block, body_text, created_at)
    filepath.write_text(content, encoding="utf-8")
    print(f"[Preprocess] Created {filepath}")
    return str(filepath)


def approve_issue(issue_id: int) -> bool:
    for f in INBOX_DIR.glob(f"issue-{issue_id}_*.md"):
        content = f.read_text(encoding="utf-8")
        content = content.replace("approved: false", "approved: true")
        f.write_text(content, encoding="utf-8")
        print(f"[Preprocess] Approved {f.name}")
        return True
    print(f"[Preprocess] No inbox file for issue {issue_id}")
    return False


def reject_issue(issue_id: int) -> bool:
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
        process_issue(args.issue_id, args.issue_title, args.issue_body, labels, args.created_at)
    elif args.command == "approve":
        approve_issue(args.issue_id)
    elif args.command == "reject":
        reject_issue(args.issue_id)
