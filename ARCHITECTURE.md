# HYPERISE — Архитектура

Автоматизированный сайт про стримера Пятерка (5opka). Генерация контента из транскрипций YouTube-видео нарезчиков.

## Цели

- 100% бесплатная инфраструктура (serverless)
- Полностью автоматизированный pipeline
- Структурированное накопление знаний (вики)
- RAG для осмысленной генерации контента

## Экономика

| Компонент | Сервис | Цена |
|-----------|--------|------|
| Pipeline (CI/CD + cron) | GitHub Actions (public repo) | **$0** |
| База данных + RAG | Neon Postgres Free (500 MB, pgvector) | **$0** |
| Статичный сайт | Render Static Site (CDN) | **$0** |
| Транскрипции YouTube | `youtube-transcript-api` | **$0** |
| LLM (completion) | OpenAI API (`gpt-5-nano`) | **~$1–3/мес** |
| Embeddings | OpenAI API (`text-embedding-3-small`) | **~$1–2/мес** |

> OpenAI — единственная платная часть. Можно заменить на бесплатные тиры (Gemini, Groq), но качество хуже.

## Пайплайн (3 агента)

```
YouTube Data API  ──┐
youtube-transcript  │
API (субтитры)      ▼
            ┌──────────────────┐
            │  Agent 1: Wiki   │
            │    Updater       │
            └────────┬─────────┘
                     │ обновляет
                     ▼
              wiki/*.md (Git)
                     │
                     │ embed + index
                     ▼
         ┌───────────────────────┐
         │  Neon Postgres +      │
         │  pgvector (RAG store)   │
         └───────────┬───────────┘
                     │ query
                     ▼
            ┌──────────────────┐
            │  Agent 2: Idea   │
            │   Generator      │
            └────────┬─────────┘
                     │ идея
                     ▼
            ┌──────────────────┐
            │  Agent 3: Writer │
            │  (RAG context)     │
            └────────┬─────────┘
                     │
                     ▼
              articles/*.md
                     │
                     ▼
              Git commit + push
                     │
                     ▼
         Render Static Site (Astro)
```

### Agent 1: Wiki Updater
- Получает список новых видео с каналов нарезчиков
- Скачивает транскрипции через `youtube-transcript-api`
- Читает существующую вики, определяет, какие темы обновить
- Дописывает факты, события, цитаты, персонажей в `wiki/`
- Обновляет RAG: делит вики на чанки, генерирует embeddings, пишет в Neon

### Agent 2: Idea Generator
- Запрашивает RAG: "Что интересного произошло за последнее время?"
- Генерирует 3–5 идей для статей (заголовок + аннотация + угол)
- Выбирает лучшую идею (или несколько)

### Agent 3: Writer
- Получает идею + RAG-контекст по теме
- Пишет статью в Markdown с YAML frontmatter
- Сохраняет в `articles/` или `site/src/content/articles/`

## Технический стек

### Pipeline (Python)

```
agents/
├── __init__.py
├── youtube.py          # YouTube Data API + youtube-transcript-api
├── database.py         # Neon Postgres connection, schema
├── rag.py              # LangChain + pgvector (index, query)
├── wiki_updater.py     # Agent 1
├── ideator.py          # Agent 2
├── writer.py           # Agent 3
└── pipeline.py         # Entry point: запускает всех агентов
```

**Зависимости:**
- `youtube-transcript-api` — субтитры без API квоты
- `google-api-python-client` — метаданные каналов
- `langchain`, `langchain-openai`, `langchain-postgres`
- `psycopg2-binary` — драйвер Postgres
- `pydantic` — валидация

### Вики (Git-Markdown)

```
wiki/
├── index.md
├── people/
│   ├── pyaterka.md
│   ├── snusovka.md
│   └── ...
├── events/
│   ├── tournaments.md
│   └── ...
├── games/
│   └── ...
└── quotes/
    └── ...
```

- YAML frontmatter для структурированных метаданных
- Агент 1 дописывает, не перезаписывает (дополняет факты)

### Сайт (Astro 5)

```
site/
├── src/
│   ├── content/
│   │   ├── articles/       # Сгенерированные статьи (MD)
│   │   └── wiki/           # Синхронизация вики (опционально)
│   ├── layouts/
│   │   └── Article.astro
│   ├── pages/
│   │   ├── index.astro
│   │   ├── articles/
│   │   │   └── [...slug].astro
│   │   └── wiki/
│   │       └── [...slug].astro
│   └── styles/
├── astro.config.mjs
├── package.json
└── tailwind.config.mjs
```

**Почему Astro:**
- Content Collections — типобезопасные Markdown с Zod-схемами
- Полностью статичный экспорт (`output: 'static'`)
- Ноль runtime-зависимостей = работает на Render Static Site (бесплатно)
- Быстрый, SEO-friendly, острова для интерактивности

### База данных (Neon)

```sql
-- Расширение pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Метаданные видео
CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Чанки вики для RAG
CREATE TABLE wiki_chunks (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding VECTOR(1536),  -- text-embedding-3-small
    source TEXT NOT NULL,     -- путь к файлу вики
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Индекс для similarity search
CREATE INDEX ON wiki_chunks USING hnsw (embedding vector_cosine_ops);

-- Статьи (дублируем в БД для удобства, но source of truth — Git)
CREATE TABLE articles (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### GitHub Actions

```yaml
name: Daily Pipeline
on:
  schedule:
    - cron: '0 3 * * *'  # 03:00 UTC (06:00 MSK)
  workflow_dispatch:
jobs:
  pipeline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python -m agents.pipeline
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          NEON_DATABASE_URL: ${{ secrets.NEON_DATABASE_URL }}
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
      - run: |
          git config user.name "hyperise-bot"
          git config user.email "bot@hyperise.dev"
          git add wiki/ site/src/content/articles/
          git diff --cached --quiet || git commit -m "auto: content update $(date -I)"
          git push
```

### Render Blueprint

```yaml
services:
  - type: web
    name: hyperise
    runtime: static
    buildCommand: cd site && npm ci && npm run build
    staticPublishPath: site/dist
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
```

## Почему именно эти решения

| Альтернатива | Почему отказались |
|--------------|-------------------|
| Render Cron Job ($1/мес) | GitHub Actions бесплатно для public repo |
| Chroma / Pinecone / FAISS | Neon pgvector — один сервис, 500 MB хватит на годы |
| Next.js / Nuxt SSR | Нужен Render Web Service ($7/мес). Astro static = $0 |
| Whisper (транскрипция аудио) | youtube-transcript-api берёт готовые субтитры, $0 |
| Deep Agents / LangGraph | Пайплайн линейный — 3 детерминированных шага. Простой LangChain достаточно |

## Масштабирование и ограничения

### Neon Free Tier (500 MB)

- 1 embedding (1536-dim float32) ≈ 6 KB
- 10 000 чанков ≈ 60 MB
- Тексты вики ≈ 5–10 MB
- Метаданные + статьи ≈ 1–2 MB
- **Итого: хватит на годы контента**

### GitHub Actions

- Job timeout: 6 часов
- Pipeline занимает минуты (не часы)
- Public repo = безлимитные минуты

### YouTube

- `youtube-transcript-api` может ломаться при изменениях UI YouTube
- Нужны retry-логика и graceful degradation
- Обработанные видео храним в БД, чтобы не обрабатывать повторно

## Фаза 1: MVP (неделя 1)

1. Скелет репозитория (директории, конфиги)
2. `youtube.py` — скачивание транскрипций
3. `database.py` + схема Neon
4. `rag.py` — базовый RAG с pgvector
5. `wiki_updater.py` — простое добавление в `wiki/raw/`
6. Astro сайт + статья вручную для теста
7. GitHub Actions workflow
8. Render Blueprint + деплой

## Фаза 2: Автоматизация (неделя 2)

1. Agent 2 (ideator) + Agent 3 (writer)
2. Структурированная вики (people, events, games, quotes)
3. Периодические ревизии вики (агент "сжимает" дублирующуюся информацию)
4. Темизация сайта в стиле 5opka
5. RSS / sitemap

## Фаза 3: Расширение (неделя 3+)

1. Несколько каналов-источников
2. Разные форматы контента (лонгриды, новости, заметки)
3. Теги, категории, поиск по сайту (Pagefind или Algolia DocSearch free)
4. Комментарии (Giscus — бесплатно через GitHub Discussions)
