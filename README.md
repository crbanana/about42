# HYPERISE

Автоматизированный фан-сайт о стримере Пятерка (5opka).

Генерирует статьи, истории и лонгриды на основе транскрипций YouTube-видео нарезчиков.

## Архитектура

- **Pipeline:** GitHub Actions (ежедневный cron) — $0
- **RAG:** Neon Postgres (pgvector) — $0
- **Site:** Astro static site → Render Static Site — $0
- **LLM:** OpenAI `gpt-5-nano` + `text-embedding-3-small`

## Пайплайн

1. **Wiki Updater** — скачивает транскрипции, обновляет структурированную вики
2. **Ideator** — запрашивает RAG, придумывает идеи статей
3. **Writer** — пишет статьи с использованием RAG-контекста

## Запуск локально

```bash
pip install -r requirements.txt
python -m agents.pipeline
```

## Структура

```
.
├── agents/              # Python-агенты
├── wiki/                # Структурированная вики (Markdown)
├── site/                # Astro статичный сайт
├── .github/workflows/   # CI/CD
├── render.yaml          # Render Blueprint
└── ARCHITECTURE.md      # Детальная архитектура
```

## Переменные окружения

См. `.env.example`

## Лицензия

MIT
