# CLAUDE.md

Контекст для сессий Claude Code в этом репозитории.

Обязательный Git-flow и минимальные проверки — в `AGENTS.md`, он общий для всех агентов (Claude, Cursor, Codex) и подключён сюда целиком:

@AGENTS.md

## Источник правды — GitHub

- Проект развивается на GitHub: [infotheunum/api-scribely](https://github.com/infotheunum/api-scribely), командой через PR (`<type>/<task>` → `dev` → релизный PR `dev → main`).
- Фазы 0–8 из `docs/План_Реализации_MVP.md` — это прототип, с которого стартовал репозиторий (август 2026). Всё, что когда-то делалось только локально и не попало на GitHub, значения не имеет: не переносить, не мержить, не восстанавливать.
- Если локальная ветка разошлась с `origin`, прав GitHub: сохранить нужное в отдельную ветку (если есть что сохранять) и выровнять локальную ветку по `origin`.
- Документы прототипа (ТЗ v0.5, План v0.3, Заметки) — историческая база. Их «зафиксированные решения» во многом устарели (например, «только free-модели OpenRouter», «Publish без вызова CMS», «~2000 символов на материал»). Актуальное поведение определяют код на `origin/dev`, `openspec/` и настройки в Unum Admin — проверять там, а не в документах прототипа.

## Что такое Scribely сейчас

Scribely (`api-scribely`) — бэкенд-фабрика AI-черновиков новостей для theunum.io. Собирает RSS, кластеризует и дедуплицирует инфоповоды (в том числе между EN и RU), делает рерайт EN + RU через платных LLM-провайдеров, прогоняет проверки качества и отдаёт черновики Unum через Export API.

- Редакторы работают в Unum (QA на theunum.io). Cron на VPS `api.theunum.io` сам забирает черновики (`GET /integrations/theunum/v1/drafts`); решение редактора (одобрить / отклонить / удалить) → `POST .../mark-consumed`. Scribely ничего не пушит в Unum.
- Основной пульт управления — Unum Admin (`/admin/news/settings`): темп генерации, промпты, источники. Он ходит в Scribely по M2M-эндпоинтам (`/integrations/theunum/v1/pipeline/*`, Bearer `THEUNUM_INTEGRATION_TOKEN`).
- Собственный UI Scribely — запасной контур для отладки: `/ui` (очередь и ревью черновиков), `/ui/admin` (настройки, источники, промпты, LLM-провайдеры, статистика генерации).
- Дисклеймеры принадлежат Unum (`Article.showDisclaimer`); Scribely отдаёт только `disclaimer_flag` как сигнал.

## Архитектура

Railway, project `api-scribely` (workspace Unum, id `00d2f337-c04d-41f4-8232-b9c72e2662da`): managed Postgres + 3 сервиса на Python 3.12.

| Сервис | Роль | Протокол |
|---|---|---|
| `api` | FastAPI: Export API и M2M для Unum, Admin REST, UI (`/ui`, `/ui/admin`), WebSocket, auth | HTTP |
| `worker` | Scheduler: ingestion, dedup/кластеризация, фильтр тем, dispatch на рерайт, compliance, TTL, синк категорий CMS | HTTP (health) |
| `rewrite` | `scribely-rewrite`: enrichment, рерайт, проверки качества, SEO, теги; LLM-ключи живут только здесь | только gRPC |

- `api`/`worker` → `rewrite` только по gRPC (`proto/`, стабы генерирует `scripts/gen_proto.sh`, не коммитятся). Общий код — только в `libs/` (`db` — модели и `AppSetting`, `common` — инфраструктура и хелперы настроек), без импорта бизнес-логики между сервисами.
- Между Railway и VPS Unum — только HTTPS, gRPC наружу нет.

### Где что лежит

- `services/worker/app/`: `ingestion/` (RSS-поллер, circuit breaker), `dedup/` (эмбеддинги, кластеризация), `filter/` (очередь по темам), `dispatch/` (отбор и темп отправки на рерайт, `regenerate.py`), `compliance/`, `lifecycle/`, `sync/` (категории сайта из CMS theunum.io), `scheduler.py`.
- `services/rewrite/app/`: `rewrite/` — `orchestrator.py`, LLM-ротация (`rotation.py`, `provider_clients.py`), проверки качества (`quality_gate.py`, `fact_diff.py`, `rewrite_review.py`, `review_report.py`, `banned_phrases.py`, `quote_check.py`, `title_lead.py`); `prompt/` — `versions.py`, `style_guide.py`, `seed.py`; `seo/`, `tags/`, `enrich/`; `servicer.py` — gRPC-вход.
- `services/api/app/`: `routers/integration_theunum.py` (Export API + M2M для Unum), `routers/admin.py` (Admin REST), `ui/` (шаблоны Jinja2), `integrations/` (freshness, статус пайплайна), `auth/`, `websocket/`.
- `libs/common/`: `llm_providers.py`, `generation_hours.py` (расписание и дневные лимиты), `rewrite_body_limits.py`, `integration_export_*.py`, `site_categories.py`, `pipeline_telemetry.py`.

## Ключевые механики (смотреть в коде, цифры часто меняются)

- **LLM.** Платные провайдеры OpenAI / Qwen (DashScope) / Anthropic, round-robin на статью среди включённых. Список включённых: AppSetting `llm.enabled_providers` (Admin) → env `LLM_ENABLED_PROVIDERS` → дефолт `openai`. Модели — env `*_MODEL`, дефолты в `provider_clients.py`. OpenRouter для статей не вызывается: ключи `OPENROUTER_KEY_*` и `LlmRotationModel` остались как legacy. Имена `openrouter.*` в AppSetting и `openrouter_*` в `reason_code` Export API тоже исторические: они относятся к ключам всех включённых провайдеров. Это часть контракта с Unum, не переименовывать без согласования.
- **Промпты.** Версии хранятся в БД (`PromptVersion`), активную выбирает админ. Новая версия создаётся от активной (`create_vNN_from_active` в `prompt/versions.py`), правила стиля — `prompt/style_guide.py`. «Без ё» дополнительно обеспечивается детерминированной пост-обработкой.
- **Объём и качество текста.** Пороги длины — `libs/common/rewrite_body_limits.py`, они много раз менялись: верить коду и тестам, не документам. Проверки качества в основном advisory: они прикладывают отчёт к черновику и не отправляют его в dead-letter.
- **Темп генерации.** Часы и дни генерации, лимиты на будни и выходные, ручной burst, темп в час — `libs/common/generation_hours.py` и `services/worker/app/dispatch/pipeline.py`. Значения в runtime — AppSetting `pipeline.*`, `queue.*`, `dispatch.*`, меняются из Unum Admin через M2M или в `/ui/admin`.
- **Runtime-конфигурация** — строки в Postgres (`AppSetting`, `Source`, `Topic`, `PromptVersion`), меняется без редеплоя. В файлы образа такие настройки не класть.
- **Export API** — полный контракт, `meta.reason_code` и псевдокод cron: `docs/Интеграция_theunum_Export_API.md`.

## Процесс разработки

- Git-flow — строго по `AGENTS.md` (см. выше). Сообщения коммитов — Conventional Commits на английском (`feat(rewrite): ...`, `fix(worker): ...`), как в истории репозитория.
- Изменения поведения (промпты, качество, SEO, новые источники данных) команда оформляет через OpenSpec: `openspec/changes/<name>/` (`proposal.md`, `design.md`, `specs/`, `tasks.md`). Артефакты на русском, структурные заголовки и SHALL/MUST — на английском (`openspec/config.yaml`). Скиллы — `.agents/skills/openspec-*`.
- Миграции — Alembic, `migrations/versions/`. Новая миграция ставит `down_revision` на текущую голову `origin/dev`: в истории должна оставаться одна голова.
- Установка, локальный запуск, тесты и деплой — `README.md`. Тестам всех трёх сервисов по умолчанию нужен Postgres на `localhost:55432` (или свой `DATABASE_URL`). Зависимости ставятся без `.venv` в репозитории.

## Документы в `docs/`

- Актуальные, их ведёт команда: `Интеграция_theunum_Export_API.md`, `Правила_Рерайта_и_Стиля_Черновик.md` (стайл-гайд; рабочий промпт — в коде), `Реестр_Источников_Технический_Черновик.md`, `Редакционная_Политика_UNUM_Глобальная_версия.md` (первоисточник требований редполитики).
- Исторические, от прототипа (не обновляются, не опираться как на текущее состояние): `ТЗ_Rewriter_Tool_Черновик.md`, `План_Реализации_MVP.md`, `Заметки_Обогащение_Правки_Промпт.md`.

## Конвенции

- Отвечаем в чате по-русски. Документы — на русском (рабочий язык команды), публикуемые новости — на английском и русском.
- Диаграммы — Mermaid прямо в markdown.
