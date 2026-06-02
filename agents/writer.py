"""Agent 3: writes articles using RAG context."""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agents.ideator import ArticleIdea
from agents.rag import query_rag

LLM_MODEL = "gpt-5-nano"
ARTICLES_DIR = Path("site/src/content/articles")


def _slugify(title: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60]


def write_article(idea: ArticleIdea) -> Optional[str]:
    """Generate an article from an idea + RAG context."""
    # Gather deep context
    rag_queries = [
        idea.title,
        idea.angle,
        idea.synopsis,
    ]
    context_chunks = []
    for q in rag_queries:
        context_chunks.extend(query_rag(q, k=3))

    # Deduplicate by content
    seen = set()
    unique_chunks = []
    for chunk in context_chunks:
        if chunk.page_content not in seen:
            seen.add(chunk.page_content)
            unique_chunks.append(chunk)

    context_text = "\n\n---\n\n".join(
        f"Источник: {c.metadata.get('source', 'wiki')}\n{c.page_content}"
        for c in unique_chunks[:10]
    )

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0.7)
    system = SystemMessage(content=(
        "Ты — автор статей для фан-сайта HYPERISE о стримере Пятерка. "
        "Пиши живо, с юмором, но достоверно. Используй только предоставленный контекст. "
        "Структура: вступление, основная часть с фактами, заключение. "
        "Выходной формат: Markdown с YAML frontmatter (title, date, tags)."
    ))
    human = HumanMessage(content=(
        f"Идея: {idea.title}\n"
        f"Угол: {idea.angle}\n"
        f"Синопсис: {idea.synopsis}\n\n"
        f"Контекст:\n{context_text[:15000]}\n\n"
        "Напиши полноценную статью в Markdown."
    ))

    response = llm.invoke([system, human])
    article_md = str(response.content)

    # Ensure frontmatter
    if not article_md.strip().startswith("---"):
        date_str = datetime.now().strftime("%Y-%m-%d")
        frontmatter = f"""---
title: "{idea.title}"
date: {date_str}
tags: []
draft: false
---

"""
        article_md = frontmatter + article_md

    # Save
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(idea.title)
    filepath = ARTICLES_DIR / f"{slug}.md"
    filepath.write_text(article_md, encoding="utf-8")

    print(f"[Writer] Saved article: {filepath}")
    return str(filepath)
