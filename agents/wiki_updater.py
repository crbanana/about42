"""Agent 1: reads transcripts and updates the structured wiki."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agents.database import insert_video
from agents.rag import chunk_wiki_document, index_wiki_chunks
from agents.youtube import VideoInfo

WIKI_DIR = Path("wiki")
RAW_DIR = WIKI_DIR / "raw"
LLM_MODEL = "gpt-5-nano"


def _ensure_dirs():
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def _load_existing_wiki() -> str:
    """Load all existing wiki markdown for context."""
    parts = []
    for md_file in sorted(WIKI_DIR.rglob("*.md")):
        if md_file.name == "index.md":
            continue
        rel = md_file.relative_to(WIKI_DIR)
        parts.append(f"--- File: {rel} ---\n{md_file.read_text(encoding='utf-8')}\n")
    return "\n".join(parts)


def _extract_facts(transcript: str, video: VideoInfo, existing_wiki: str) -> str:
    """Use LLM to extract structured facts from a transcript."""
    llm = ChatOpenAI(model=LLM_MODEL, temperature=0.2)
    system = SystemMessage(content=(
        "Ты — ассистент, который извлекает факты из транскрипций стримов Пятерка. "
        "Пиши кратко, по делу, структурированно.\n\n"
        "ОБЯЗАТЕЛЬНАЯ СТРУКТУРА выходного Markdown:\n"
        "## События\n"
        "- Краткое описание события 1\n"
        "- Краткое описание события 2\n\n"
        "## Персонажи\n"
        "- Упоминания людей, их действия\n\n"
        "## Игры\n"
        "- Названия игр, моменты из игр\n\n"
        "## Цитаты\n"
        "- \"> Прямая цитата Пятерки\"\n\n"
        "Если информация дублирует существующую вики — укажи ТОЛЬКО новые факты."
    ))
    human = HumanMessage(content=(
        f"Видео: {video.title}\n"
        f"Дата: {video.published_at.isoformat()}\n\n"
        f"Существующая вики:\n{existing_wiki[:8000] or '(пусто)'}\n\n"
        f"Транскрипция (первые 8000 символов):\n{transcript[:8000]}\n\n"
        "Извлеки новые факты в структурированном Markdown."
    ))
    response = llm.invoke([system, human])
    return str(response.content)


def _update_wiki_files(video: VideoInfo, facts_md: str) -> List[str]:
    """Write raw facts and return list of updated file paths."""
    _ensure_dirs()
    date_str = video.published_at.strftime("%Y-%m-%d")
    safe_title = re.sub(r'[^\w\s-]', '', video.title).strip().replace(' ', '_')[:50]
    filename = f"{date_str}_{safe_title}.md"
    filepath = RAW_DIR / filename

    frontmatter = f"""---
video_id: {video.video_id}
channel_id: {video.channel_id}
published_at: {video.published_at.isoformat()}
title: {json.dumps(video.title)}
source: youtube
---

"""
    filepath.write_text(frontmatter + facts_md, encoding="utf-8")
    return [str(filepath)]


def run(video: VideoInfo) -> List[str]:
    """Process a single video: extract facts, update wiki, index in RAG."""
    if not video.transcript:
        return []

    existing_wiki = _load_existing_wiki()
    facts_md = _extract_facts(video.transcript, video, existing_wiki)
    updated_files = _update_wiki_files(video, facts_md)

    # Index new content into RAG
    for filepath in updated_files:
        text = Path(filepath).read_text(encoding="utf-8")
        docs = chunk_wiki_document(filepath, text)
        index_wiki_chunks(docs)

    # Mark as processed
    insert_video(
        video.video_id,
        video.channel_id,
        video.title,
        video.published_at.isoformat(),
    )

    print(f"[WikiUpdater] Processed {video.title} → {updated_files}")
    return updated_files
