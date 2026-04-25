from __future__ import annotations

from .rss import fetch as _rss_fetch
from .types import RawItem


def fetch(source_id: str, channel_id: str | None = None, channel_url: str | None = None) -> list[RawItem]:
    """Fetch YouTube channel videos via RSS (no API key needed)."""
    if channel_id:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    elif channel_url:
        url = channel_url
    else:
        return []
    items = _rss_fetch(source_id, url)
    # Attempt to fetch transcripts for each video
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        for item in items:
            if item.url and "watch?v=" in item.url:
                vid_id = item.url.split("watch?v=")[-1].split("&")[0]
                try:
                    transcript = YouTubeTranscriptApi.get_transcript(vid_id)
                    item.body_text = " ".join(t["text"] for t in transcript)[:4000]
                except Exception:
                    pass
    except ImportError:
        pass
    return items
