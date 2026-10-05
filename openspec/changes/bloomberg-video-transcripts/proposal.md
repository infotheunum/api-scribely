## Why

Редакция разбирает видео Bloomberg / YouTube как источник фактов, но сейчас
ingestion — только RSS/API текст. Нужен отдельный пайплайн: субтитры → факты →
черновик в админке со связью «статья ← видео».

## What Changes (будущая реализация)

- Этап 1: YouTube Transcript API; для встроенного Bloomberg — WebVTT/TTML из
  сетевых запросов; fallback Whisper (платно).
- Этап 2: чанки 30–60с → краткое изложение + structured facts (кто/что/когда/
  сколько).
- Этап 3: карточка в админке: источник=URL видео, транскрипт с таймкодами,
  факты, черновик рерайта.
- Этап 4: при статье по видео — ссылка на видео-источник; флаг, если факт в
  статье не совпадает с транскриптом.

## Out of scope for this PR

Полный video pipeline не входит в текущий PR parts 3–5 (UI порядок, title≠lead,
disclaimer). Этот change — backlog-proposal.

## Capabilities

### New Capabilities

- `video-transcript-ingestion`: получение и нормализация субтитров.
- `video-fact-extraction`: структурированные факты из транскрипта.
- `video-draft-admin`: карточка видео-источника в Review UI.
- `video-fact-link-check`: сверка фактов статьи с транскриптом.

## Impact

Новые connector/worker jobs, модели БД (VideoSource / TranscriptSegment),
Admin UI, rewrite filters. Зависит от решений по YouTube quota и Whisper budget.
