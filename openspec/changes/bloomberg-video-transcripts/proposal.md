## Why

Редакция разбирает видео Bloomberg / YouTube как источник фактов, но сейчас
ingestion — только RSS/API текст. Нужен отдельный пайплайн: субтитры → факты →
черновик со связью «статья ← видео».

## Ownership (жёстко)

| Слой | Где |
|------|-----|
| Получение субтитров / Whisper / чанки | worker/connector (может жить рядом со Scribely ingestion **или** Unum API job) |
| Structured facts + связь с Article | **api.theunum.io** + **admin.theunum.io** |
| Карточка редактора: URL видео, транскрипт, факты, черновик | **admin.theunum.io** (Article / отдельная entity) — **не** Scribely `draft_detail.html` |
| Флаг «факт статьи ≠ транскрипт» | Unum admin QA + site publish gate |
| Scribely | только если видео идёт как источник rewrite-пайплайна (export `disclaimer_flag`-style quality signals) |

## What Changes (будущая реализация)

- Этап 1: YouTube Transcript API; Bloomberg WebVTT/TTML; fallback Whisper.
- Этап 2: чанки 30–60с → summary + structured facts.
- Этап 3: Unum admin fields (источник=URL, транскрипт+таймкоды, факты, draft).
- Этап 4: article ↔ video link; mismatch flag.

## Out of scope / wrong place

Не строить CMS-поля транскрипта/дисклеймер-текстов во втором admin (Scribely UI).
Текст дисклеймера на сайте — i18n / `Article.showDisclaimer` в Unum.

## Capabilities

### New Capabilities

- `video-transcript-ingestion`
- `video-fact-extraction`
- `video-draft-admin` (Unum admin)
- `video-fact-link-check`

## Impact

Unum Prisma models, admin.theunum.io entity detail, optionally Scribely connector.
