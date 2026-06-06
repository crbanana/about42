# HYPERISE

Автоматизированная вики о стримере Пятерка (5opka).

## Архитектура

GitHub Issue (label: type:*, body: ссылка/текст)
    │
    ▼
inbox/issue-N_*.md  ← предобработанный источник с метаданными
    │
    │ /approve
    ▼
daily-pipeline (wiki_editor агент на Deep Agents)
    │
    ▼
wiki/*.md  ← граф знаний
    │
    ▼
Astro Site  ← сайт с wiki-страницами

## Поддерживаемые источники

| Тип | Обработка |
|-----|-----------|
| `type:youtube` | Субтитры через yt-dlp + title/uploader/date |
| `type:twitch` | Аудио → Whisper → Gemini описание + метаданные |
| `type:tiktok` | Аудио → Whisper → Gemini описание + метаданные |
| `type:telegram` | Web scraping текста поста + channel/date |
| `type:text` | Пропускается как есть |

## Как использовать

1. Создать GitHub Issue с label `type:youtube` (или другой)
2. В body вставить ссылку или текст
3. Бот предобработает → пишет в issue «Добавлено в предложку»
4. Написать `/approve` в комментарий
5. Следующий день 03:00 UTC — агент обновляет wiki

## Переменные окружения

См. `.env.example`

## Лицензия

MIT
