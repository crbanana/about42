"""Wiki editor agent powered by Deep Agents.

Reads preprocessed sources from inbox/ and updates wiki/ graph.
"""

import os
from pathlib import Path

from deepagents import create_deep_agent, HarnessProfile, register_harness_profile
from deepagents.backends import FilesystemBackend
from deepagents.profiles.harness import GeneralPurposeSubagentProfile

WIKI_DIR = Path("wiki")
INBOX_DIR = Path("inbox")

SYSTEM_PROMPT = """Ты — редактор вики HYPERISE, фан-сайта о стримере Пятерка (5opka).

ТВОЯ ЗАДАЧА: получать предобработанные источники из папки inbox/ и обновлять вики в папке wiki/.

ПРАВИЛА РАБОТЫ:
1. Вики — это граф знаний, а не иерархия папок. Каждая страница — отдельный Markdown-файл.
2. Названия файлов — транслит без пробелов: Pyaterka.md, Sonya.md, Turnir_2026.md.
3. Страницы связываются Markdown-ссылками: [Соня](Sonya.md).
4. У каждой страницы есть YAML frontmatter: title, tags, sources (список issue_id), last_updated.
5. Ты НЕ создаёшь подпапки в wiki/ — только .md файлы в корне wiki/.

АЛГОРИТМ ДЕЙСТВИЙ:
1. Прочитай все файлы из inbox/ (используй ls и read_file).
2. Для каждого источника:
   a. Пойми суть: люди, события, игры, цитаты.
   b. Посмотри, какие страницы уже есть в wiki/ (ls wiki/). 
   c. Прочитай релевантные страницы (read_file).
   d. Реши: дописать в существующую страницу (edit_file) или создать новую (write_file).
   e. Если создаёшь новую — не забудь про frontmatter.
   f. Обнови связи: добавь Markdown-ссылки на связанные страницы.
3. После обработки всех источников обнови wiki/index.md — оглавление всех страниц.
4. Удали обработанные файлы из inbox/.

ВАЖНО:
- Пиши факты уверенно, как очевидец.
- Не упоминай транскрипции, источники, вики как таковую.
- Сохраняй существующую информацию, дописывай новую.
- Если информация противоречит существующей — допишь оба варианта с пометкой даты.
- Формат дат: DD.MM.YYYY
- Каждый абзац — отдельная мысль. Пустая строка между абзацами.
"""


def create_wiki_editor():
    """Create and return the wiki editor agent."""
    # Register harness profile to disable todos and task subagent
    register_harness_profile(
        "openai:gpt-5-nano",
        HarnessProfile(
            excluded_tools=frozenset({"write_todos", "execute"}),
            excluded_middleware=frozenset({"TodoListMiddleware", "SummarizationMiddleware"}),
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )

    agent = create_deep_agent(
        model="openai:gpt-5-nano",
        system_prompt=SYSTEM_PROMPT,
        backend=FilesystemBackend(root_dir=".", virtual_mode=True),
    )
    return agent


def process_inbox():
    """Run the wiki editor agent on all pending sources."""
    inbox_files = sorted(INBOX_DIR.glob("*.md"))
    if not inbox_files:
        print("[WikiEditor] No sources in inbox/ to process.")
        return

    print(f"[WikiEditor] Found {len(inbox_files)} source(s) in inbox/.")

    # Build a single user message with all sources
    sources_text = []
    for f in inbox_files:
        sources_text.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}\n")

    user_message = (
        "Обработай следующие источники и обнови вики:\n\n"
        + "\n".join(sources_text)
    )

    agent = create_wiki_editor()
    result = agent.invoke({"messages": [{"role": "user", "content": user_message}]})

    print(f"[WikiEditor] Agent finished. Result: {result}")

    # Cleanup: remove processed files
    for f in inbox_files:
        f.unlink()
        print(f"[WikiEditor] Removed processed source: {f.name}")


if __name__ == "__main__":
    process_inbox()
