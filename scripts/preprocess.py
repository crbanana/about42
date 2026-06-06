"""Preprocess raw sources into inbox/ files.

Supports:
- YouTube (subtitles via yt-dlp)
- Twitch clips (audio -> Whisper -> Gemini description)
- TikTok (audio -> Whisper -> Gemini description)
- Telegram (web scraping)
- Plain text (pass-through)
"""

import json
import os
import re
import subprocess
import sys
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


def _fetch_youtube_transcript(video_id: str) -> str | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ru", "en"],
            "subtitlesformat": "json3",
            "outtmpl": str(Path(tmpdir) / "%(id)s"),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            print(f"[Preprocess] yt-dlp failed: {exc}")
            return None

        for ext in ("json3", "srv1", "vtt"):
            for lang in ("ru", "en"):
                path = Path(tmpdir) / f"{video_id}.{lang}.{ext}"
                if path.exists():
                    return _parse_subtitles(path.read_text(encoding="utf-8"), ext)
    return None


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

def _download_audio(url: str) -> Path | None:
    """Download audio from video URL via yt-dlp. Returns path to mp3."""
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
    """Transcribe audio via Whisper through OpenRouter."""
    client = _openrouter_client()
    try:
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(model="openai/whisper-1", file=f)
        return result.text
    except Exception as exc:
        print(f"[Preprocess] Whisper failed: {exc}")
        return None


def _gemini_describe(context: str, source_type: str) -> str | None:
    """Generate description from transcript + metadata via Gemini through OpenRouter."""
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


def _process_video(url: str, source_type: str) -> str:
    """Download, transcribe, describe a video."""
    print(f"[Preprocess] Downloading {source_type} audio...")
    audio = _download_audio(url)
    if not audio:
        return f"URL: {url}\n\n[Не удалось скачать аудио]"

    print(f"[Preprocess] Transcribing with Whisper...")
    transcript = _whisper_transcribe(audio)
    if not transcript:
        return f"URL: {url}\n\n[Не удалось получить транскрипцию]"

    context = f"URL: {url}\n\nТранскрипция:\n{transcript}"
    print(f"[Preprocess] Describing with Gemini...")
    description = _gemini_describe(context, source_type)
    if description:
        return f"URL: {url}\n\nОписание:\n{description}"
    return context


# ── Telegram ─────────────────────────────────────────

def _fetch_telegram_post(url: str) -> str | None:
    """Scrape public Telegram post via embed view."""
    try:
        resp = requests.get(url + "?embed=1", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        # Simple regex extraction — Telegram embed HTML
        text_match = re.search(r'<div class="tgme_widget_message_text[^"]*">(.*?)</div>', resp.text, re.DOTALL)
        if text_match:
            raw = text_match.group(1)
            # Strip HTML tags
            clean = re.sub(r'<[^>]+>', '', raw)
            clean = clean.replace('&nbsp;', ' ').replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>')
            return clean.strip()
    except Exception as exc:
        print(f"[Preprocess] Telegram fetch failed: {exc}")
    return None


# ── Builder ─────────────────────────────────────────────

def _build_inbox_file(issue_id: int, issue_title: str, source_type: str,
                      source_url: str | None, body_text: str,
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
    return f"---\n{fm}\n---\n\n## Описание\n\n{body_text}\n"


def process_issue(issue_id: int, issue_title: str, issue_body: str,
                  labels: list[str], created_at: str) -> str:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    source_type = "text"
    for label in labels:
        if label.startswith("type:"):
            source_type = label.replace("type:", "")
            break

    source_url = _extract_url(issue_body)

    if source_type in ("youtube",) and source_url:
        video_id = _get_youtube_id(source_url)
        if video_id:
            transcript = _fetch_youtube_transcript(video_id)
            body_text = f"URL: {source_url}\n\nТранскрипция:\n{transcript}" if transcript else f"URL: {source_url}\n\n[Не удалось получить транскрипцию]"
        else:
            body_text = f"URL: {source_url}\n\n[Не удалось извлечь video_id]"
    elif source_type in ("twitch", "tiktok") and source_url:
        body_text = _process_video(source_url, source_type)
    elif source_type == "telegram" and source_url:
        post_text = _fetch_telegram_post(source_url)
        body_text = f"URL: {source_url}\n\nТекст поста:\n{post_text}" if post_text else f"URL: {source_url}\n\n[Не удалось получить текст поста]"
    else:
        body_text = issue_body or ""

    filename = _slugify_issue(issue_title, issue_id)
    filepath = INBOX_DIR / filename
    content = _build_inbox_file(issue_id, issue_title, source_type, source_url, body_text, created_at)
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
