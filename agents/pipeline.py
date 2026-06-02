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
    print("[Pipeline] Step 1: Fetching new videos...")
    processed_ids = get_processed_video_ids()
    new_videos = get_new_videos(processed_ids, max_per_channel=5)
    print(f"[Pipeline] Found {len(new_videos)} new videos")

    for video in new_videos:
        try:
            run_wiki_updater(video)
        except Exception as exc:
            print(f"[Pipeline] Wiki updater failed for {video.video_id}: {exc}")

    # --- Step 2: Generate article ideas ---
    print("[Pipeline] Step 2: Generating article ideas...")
    try:
        ideas = generate_ideas(count=3)
    except Exception as exc:
        print(f"[Pipeline] Ideator failed: {exc}")
        ideas = []

    # --- Step 3: Write articles ---
    print("[Pipeline] Step 3: Writing articles...")
    for idea in ideas:
        try:
            write_article(idea)
        except Exception as exc:
            print(f"[Pipeline] Writer failed for '{idea.title}': {exc}")

    print("[Pipeline] Done.")


if __name__ == "__main__":
    main()
