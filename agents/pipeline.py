"""Entry point: runs the full HYPERISE content pipeline."""

import os

from agents.database import init_db
from agents.ideator import generate_ideas
from agents.wiki_updater import run as run_wiki_updater
from agents.writer import write_article
from agents.database import get_processed_video_ids
from agents.youtube import get_new_videos


def main():
    # Ensure DB schema exists
    init_db()

    # --- Step 1: Fetch new videos and update wiki ---
    print("[Pipeline] Step 1: Fetching new videos (target=10)...")
    processed_ids = get_processed_video_ids()
    new_videos = get_new_videos(processed_ids, target_count=10)
    print(f"[Pipeline] Found {len(new_videos)} new videos with transcripts")

    for idx, video in enumerate(new_videos, 1):
        print(f"[Pipeline] [{idx}/{len(new_videos)}] Processing: {video.title[:60]}...")
        try:
            run_wiki_updater(video)
        except Exception as exc:
            print(f"[Pipeline] Wiki updater failed for {video.video_id}: {exc}")

    # --- Step 2: Generate 1 article idea based on fresh content ---
    print("[Pipeline] Step 2: Generating article idea...")
    try:
        ideas = generate_ideas(count=1)
    except Exception as exc:
        print(f"[Pipeline] Ideator failed: {exc}")
        ideas = []

    # --- Step 3: Write 1 article ---
    print("[Pipeline] Step 3: Writing article...")
    if ideas:
        try:
            write_article(ideas[0])
        except Exception as exc:
            print(f"[Pipeline] Writer failed for '{ideas[0].title}': {exc}")
    else:
        print("[Pipeline] No ideas generated, skipping article.")

    print("[Pipeline] Done.")


if __name__ == "__main__":
    main()
