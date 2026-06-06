"""Daily pipeline: process approved inbox sources into wiki."""

import os
from pathlib import Path

from scripts.preprocess import INBOX_DIR
from scripts.wiki_editor import process_inbox


def main():
    # Process only approved sources
    approved_files = []
    for f in sorted(INBOX_DIR.glob("issue-*.md")):
        content = f.read_text(encoding="utf-8")
        if "approved: true" in content:
            approved_files.append(f)

    if not approved_files:
        print("[Pipeline] No approved sources to process.")
        return

    print(f"[Pipeline] Processing {len(approved_files)} approved source(s).")
    process_inbox()
    print("[Pipeline] Done.")


if __name__ == "__main__":
    main()
