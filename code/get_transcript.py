"""
Fetch a YouTube transcript and save it as plain text named by air date.

Usage:
    python get_transcript.py <url_or_video_id> [--lang en] [--out-dir ../data/output]
"""

import argparse
import re
import sys
from pathlib import Path

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url_or_id: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url_or_id)
    if match:
        return match.group(1)
    if len(url_or_id) == 11:
        return url_or_id
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def get_video_date(video_id: str) -> str:
    """Return the upload date as YYYY-MM-DD."""
    opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    raw = info.get("upload_date", "")
    if len(raw) != 8:
        raise ValueError(f"Unexpected upload_date format from yt-dlp: {raw!r}")
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def fetch_transcript(video_id: str, lang: str = "en") -> list:
    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id)
    return fetched.snippets


def fmt_ts(seconds: float) -> str:
    """Convert elapsed seconds to [H:MM:SS] or [MM:SS]."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"[{h}:{m:02d}:{s:02d}]"
    return f"[{m}:{s:02d}]"


def save_transcript(snippets, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for snippet in snippets:
            f.write(f"{fmt_ts(snippet.start)} {snippet.text}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="YouTube URL or video ID")
    parser.add_argument("--lang", default="en", help="Language code (default: en)")
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).parent.parent / "data" / "output"),
        help="Output directory (default: data/output relative to project root)",
    )
    args = parser.parse_args()

    video_id = extract_video_id(args.video)
    print(f"Video ID : {video_id}")

    print("Fetching metadata...")
    date_str = get_video_date(video_id)
    print(f"Air date : {date_str}")

    print("Fetching transcript...")
    snippets = fetch_transcript(video_id, args.lang)
    print(f"Entries  : {len(snippets)}")

    out_path = Path(args.out_dir) / f"{date_str}_transcript.txt"
    save_transcript(snippets, out_path)
    print(f"Saved    : {out_path}")


if __name__ == "__main__":
    main()
