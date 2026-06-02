"""YouTube data fetching: metadata + transcripts."""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi


YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
# Example channels — add more as needed
CHANNEL_HANDLES = ["@LigaKubizma"]


@dataclass
class VideoInfo:
    video_id: str
    channel_id: str
    title: str
    published_at: datetime
    transcript: Optional[str] = None


def get_channel_id(youtube, handle: str) -> str:
    """Resolve @handle to channel ID."""
    resp = youtube.search().list(
        part="snippet",
        q=handle,
        type="channel",
        maxResults=1,
    ).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Channel {handle} not found")
    return items[0]["snippet"]["channelId"]


def fetch_recent_videos(youtube, channel_id: str, max_results: int = 10) -> List[VideoInfo]:
    """Fetch recent video metadata from a channel."""
    search_resp = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=max_results,
        order="date",
        type="video",
    ).execute()

    videos: List[VideoInfo] = []
    for item in search_resp.get("items", []):
        snippet = item["snippet"]
        videos.append(VideoInfo(
            video_id=item["id"]["videoId"],
            channel_id=snippet["channelId"],
            title=snippet["title"],
            published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")),
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
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not set")

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY, cache_discovery=False)
    new_videos: List[VideoInfo] = []

    for handle in CHANNEL_HANDLES:
        try:
            channel_id = get_channel_id(youtube, handle)
            videos = fetch_recent_videos(youtube, channel_id, max_per_channel)
            for video in videos:
                if video.video_id in processed_ids:
                    continue
                transcript = fetch_transcript(video.video_id)
                if transcript:
                    video.transcript = transcript
                    new_videos.append(video)
        except Exception as exc:
            print(f"Skipping channel {handle}: {exc}")
            continue

    return new_videos
