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
    # Transliterate Cyrillic to Latin for URL slugs
    cyr_to_lat = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z',
        'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
        'с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'shch',
        'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',' ':'-',
    }
    title = title.lower()
    result = []
    for ch in title:
        if ch in cyr_to_lat:
            result.append(cyr_to_lat[ch])
        elif ch.isalnum():
            result.append(ch)
        else:
            result.append('-')
    slug = ''.join(result)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:60]


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

    # Hide sources from LLM to prevent it from saying "according to wiki"
    context_text = "\n\n".join(c.page_content for c in unique_chunks[:10])

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0.7)
    system = SystemMessage(content=(
        "Ты — автор статей для фан-сайта HYPERISE о стримере Пятерка. "
        "Пиши от первого лица наблюдателя и фана — живо, с юмором, но достоверно. "
        "НИКОГДА не упоминай вики, базу знаний, транскрипции, источники или то, что ты "
        "что-то "прочитал" или "узнал откуда-то". Пиши как человек, который сам всё видел. "
        "Не используй фразы типа: согласно вики, как написано, данные показывают, "
        "транскрипция свидетельствует. Просто рассказывай факты уверенно и естественно. "
        "Структура: вступление, основная часть с фактами, заключение. "
        "Выходной формат: Markdown с YAML frontmatter (title, date, tags)."
    ))
    human = HumanMessage(content=(
        f"Идея: {idea.title}\n"
        f"Угол: {idea.angle}\n"
        f"Синопсис: {idea.synopsis}\n\n"
        f"Факты и события для статьи:\n{context_text[:15000]}\n\n"
        "Напиши полноценную статью в Markdown."
    ))

    response = llm.invoke([system, human])
    article_md = str(response.content)

    # Ensure frontmatter
    if not article_md.strip().startswith("---"):
        date_str = datetime.now().strftime("%Y-%m-%d")
        frontmatter = f"""---
title: "{idea.title}"
date: "{date_str}"
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
