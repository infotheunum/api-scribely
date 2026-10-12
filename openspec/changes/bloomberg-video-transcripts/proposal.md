## Why

С Bloomberg в ленту попадают страницы `/news/videos/`: в RSS только короткий
анонс, полного текста нет, сверять факты не с чем. Видео редакции не нужно —
в оригинал должен попадать только текст статьи.

Решение: видео-URL не сохранять. У статей забирать абзацы из
`__NEXT_DATA__.story.body` (видимый HTML часто обрывается на AI-takeaway).

## Ownership

Ingestion в Scribely worker: пропуск видео-URL и текст статьи в `RawItem.body`.
Админка уже показывает этот `body` как оригинал.

## What Changes

- Poll пропускает URL с `/videos/` и YouTube.
- `fetch_full_text` для статей Bloomberg берёт абзацы `story.body`, не плеер и не анонс.
- Транскрипт, Whisper и плеер в админке не делаем.

## Out of scope

Плеер, скачивание видео, субтитры, Whisper, отдельные поля транскрипта в админке.

## Impact

`libs/common/fulltext.py`, `services/worker` poller. Уже сохранённые видео-черновики не удаляются.
