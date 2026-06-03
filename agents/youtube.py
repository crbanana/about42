"""YouTube data fetching via yt-dlp (no API key needed)."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import yt_dlp

# Example channels — add more as needed
CHANNEL_URLS = [
    "https://www.youtube.com/@LigaKubizma/videos",
]


@dataclass
class VideoInfo:
    video_id: str
    channel_id: str
    title: str
    published_at: datetime
    transcript: Optional[str] = None


def fetch_recent_videos(channel_url: str, batch_size: int = 10, offset: int = 0) -> List[VideoInfo]:
    """Fetch a batch of video metadata from a channel via yt-dlp."""
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playliststart": offset + 1,
        "playlistend": offset + batch_size,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    videos: List[VideoInfo] = []
    for entry in info.get("entries", []):
        if not entry:
            continue
        video_id = entry.get("id", "")
        if not video_id:
            continue
        ts = entry.get("timestamp")
        published_at = datetime.fromtimestamp(ts) if ts else datetime.utcnow()
        videos.append(VideoInfo(
            video_id=video_id,
            channel_id=entry.get("channel_id", ""),
            title=entry.get("title", ""),
            published_at=published_at,
        ))
    return videos


def _parse_vtt(content: str) -> str:
    """Parse VTT subtitle content to plain text."""
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line or line.isdigit():
            continue
        lines.append(line)
    return " ".join(lines)


def _parse_json3(content: str) -> str:
    """Parse YouTube JSON3 subtitle content."""
    import json
    try:
        data = json.loads(content)
        texts = []
        for event in data.get("events", []):
            if "segs" in event:
                for seg in event["segs"]:
                    if "utf8" in seg:
                        texts.append(seg["utf8"])
        return " ".join(texts)
    except Exception:
        return ""


def fetch_transcript(video_id: str, languages: Optional[List[str]] = None) -> Optional[str]:
    """Fetch transcript via yt-dlp (bypasses transcript API IP blocks)."""
    if languages is None:
        languages = ["ru", "en"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    import time
    time.sleep(5.0)  # rate limit: avoid 429

    # Get video info including subtitles
    node_path = "/home/crbsnana/.nvm/versions/node/v24.14.1/bin/node"
    ydl_opts = {"quiet": True, "skip_download": True, "js_runtimes": {"node": {"path": node_path}}}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None

    # Try automatic captions first, then manual subtitles
    captions = info.get("automatic_captions", {}) or info.get("subtitles", {})

    for lang in languages:
        if lang not in captions:
            continue
        sub_formats = captions[lang]
        if not sub_formats:
            continue

        # Prefer vtt/srv1/json3 formats
        for fmt in sub_formats:
            sub_url = fmt.get("url")
            if not sub_url:
                continue
            try:
                import urllib.request
                req = urllib.request.Request(sub_url)
                req.add_header("User-Agent", "Mozilla/5.0")
                with urllib.request.urlopen(req, timeout=10) as response:
                    content = response.read().decode("utf-8")

                if "json3" in sub_url:
                    text = _parse_json3(content)
                elif "vtt" in sub_url or "srv" in sub_url:
                    text = _parse_vtt(content)
                else:
                    text = " ".join(
                        line.strip() for line in content.split("\n")
                        if line.strip() and "-->" not in line and not line.strip().isdigit()
                    )
                if text:
                    return text
            except Exception:
                continue

    return None


def get_new_videos(
    processed_ids: List[str],
    target_count: int = 10,
) -> List[VideoInfo]:
    """Get target_count new videos with transcripts, backfilling older ones if needed."""
    new_videos: List[VideoInfo] = []

    for channel_url in CHANNEL_URLS:
        try:
            offset = 0
            batch_size = 10
            while len(new_videos) < target_count:
                videos = fetch_recent_videos(channel_url, batch_size=batch_size, offset=offset)
                if not videos:
                    break

                for video in videos:
                    if video.video_id in processed_ids:
                        continue
                    transcript = fetch_transcript(video.video_id)
                    if transcript:
                        video.transcript = transcript
                        new_videos.append(video)
                        if len(new_videos) >= target_count:
                            break

                offset += len(videos)
                if len(videos) < batch_size:
                    break  # no more videos on this channel
        except Exception as exc:
            print(f"Skipping channel {channel_url}: {exc}")
            continue

    return new_videos
