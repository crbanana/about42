"""Agent 2: queries RAG and generates article ideas."""

from dataclasses import dataclass
from typing import List

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from agents.rag import query_rag

LLM_MODEL = "gpt-5-nano"


@dataclass
class ArticleIdea:
    title: str
    angle: str
    synopsis: str


def generate_ideas(count: int = 3) -> List[ArticleIdea]:
    """Query recent wiki additions and propose article ideas."""
    # Retrieve recent context
    recent_context = query_rag("Что нового и интересного произошло недавно?", k=8)
    context_text = "\n\n".join(doc.page_content for doc in recent_context)

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0.8)
    system = SystemMessage(content=(
        "Ты — редактор контента для фан-сайта стримера Пятерка. "
        "Придумывай увлекательные идеи для статей на основе свежих событий. "
        "НЕ упоминай вики, транскрипции, источники или базу знаний. "
        "Каждая идея должна иметь: заголовок, угол (чем интересна), короткое описание. "
        "Формат ответа: JSON-массив объектов с полями title, angle, synopsis."
    ))
    human = HumanMessage(content=(
        f"Свежие события и факты:\n\n{context_text[:12000]}\n\n"
        f"Придумай {count} идею для статьи."
    ))

    response = llm.invoke([system, human])
    content = str(response.content)

    # Parse JSON array — sometimes LLM wraps in markdown code blocks
    import json, re
    json_match = re.search(r'\[.*\]', content, re.DOTALL)
    if json_match:
        content = json_match.group(0)

    try:
        data = json.loads(content)
        ideas = [ArticleIdea(**item) for item in data[:count]]
    except Exception:
        # Fallback: split by titles manually
        ideas = [ArticleIdea(title=content[:80], angle="general", synopsis=content[:200])]

    print(f"[Ideator] Generated {len(ideas)} ideas")
    for idea in ideas:
        print(f"  - {idea.title}")
    return ideas
