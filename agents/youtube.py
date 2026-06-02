"""YouTube data fetching via yt-dlp (no API key needed)."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

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


def fetch_recent_videos(channel_url: str, max_results: int = 10) -> List[VideoInfo]:
    """Fetch recent video metadata from a channel via yt-dlp."""
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": max_results,
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
        videos.append(VideoInfo(
            video_id=video_id,
            channel_id=entry.get("channel_id", ""),
            title=entry.get("title", ""),
            published_at=datetime.fromtimestamp(entry.get("timestamp", 0)),
        ))
    return videos


def fetch_transcript(video_id: str, languages: Optional[List[str]] = None) -> Optional[str]:
    """Fetch transcript text for a video ID."""
    if languages is None:
        languages = ["ru", "en"]
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        return " ".join(segment["text"] for segment in transcript_list)
    except Exception:
        return None


def get_new_videos(
    processed_ids: List[str],
    max_per_channel: int = 10,
) -> List[VideoInfo]:
    """Get new videos with transcripts that haven't been processed yet."""
    new_videos: List[VideoInfo] = []

    for channel_url in CHANNEL_URLS:
        try:
            videos = fetch_recent_videos(channel_url, max_per_channel)
            for video in videos:
                if video.video_id in processed_ids:
                    continue
                transcript = fetch_transcript(video.video_id)
                if transcript:
                    video.transcript = transcript
                    new_videos.append(video)
        except Exception as exc:
            print(f"Skipping channel {channel_url}: {exc}")
            continue

    return new_videos
