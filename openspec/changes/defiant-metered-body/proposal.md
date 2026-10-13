## Why

The Defiant RSS отдаёт только анонс. Страница статьи помечает
`contentAccess=metered` и `content: []`. Полный текст за логином
(`/api/content` → 401). Сейчас этот анонс сохраняется как оригинал, и
сверять факты не с чем.

## What Changes

- Если страница явно прячет тело (`metered`/`pro` и пустой `content`),
  материал не сохраняется.
- Сбой сети по-прежнему оставляет RSS-анонс.

## Out of scope

Логин The Defiant Pro и обход paywall.
