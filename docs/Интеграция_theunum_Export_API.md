# Интеграция api-scribely → api.theunum.io

Cron на VPS **забирает AI-черновики** из scribely (Railway) для QA и дальнейшей работы на theunum.io.

## Ключи и env

Сгенерировать **один** секрет:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### api-scribely (Railway, сервис `api`)

| Переменная | Обязательно | Описание |
|---|---|---|
| `THEUNUM_INTEGRATION_TOKEN` | **Да** | Тот же секрет, что на VPS. Без него `/integrations/theunum/v1/*` → 503 |
| `CORS_ALLOWED_ORIGINS` | Нет | Только если браузер admin.theunum.io ходит в scribely напрямую. Cron **не нуждается** в CORS |

Остальное без изменений: `DATABASE_URL`, `JWT_SECRET`, `INTERNAL_SERVICE_TOKEN`, `REWRITE_GRPC_ADDRESS`.

OpenRouter-ключи (`OPENROUTER_KEY_1..3`) — **только** на сервисе `rewrite`, не на `api`.

### api.theunum.io (VPS)

| Переменная | Обязательно | Описание |
|---|---|---|
| `SCRIBELY_BASE_URL` | **Да** | Prod: `https://api-scribely-production.up.railway.app` |
| `SCRIBELY_INTEGRATION_TOKEN` | **Да** | **Тот же** секрет, что `THEUNUM_INTEGRATION_TOKEN` на scribely |

## HTTP API (scribely)

Prefix: `/integrations/theunum/v1`  
Auth: `Authorization: Bearer <token>` или `X-Theunum-Service-Token: <token>`

| Method | Path | Назначение |
|---|---|---|
| GET | `/drafts` | Список unconsumed черновиков (EN+RU в каждом item) |
| GET | `/drafts/{id}` | Полный черновик |
| POST | `/drafts/mark-consumed` | Batch: пометить «уже забрали» |
| POST | `/drafts/{id}/mark-consumed` | Один черновик |
| GET | `/status` | Пайплайн, OpenRouter errors, очередь |

### Cron на VPS (псевдокод)

```typescript
const resp = await fetch(`${SCRIBELY_BASE_URL}/integrations/theunum/v1/drafts?limit=50`, {
  headers: { Authorization: `Bearer ${SCRIBELY_INTEGRATION_TOKEN}` },
});
const { items, meta } = await resp.json();

if (!items.length) {
  if (meta.reason_code !== "queue_empty") {
    await alertOps({ code: meta.reason_code, message: meta.reason_message });
  }
  return;
}

const toMark = [];
for (const draft of items) {
  const localId = await upsertQaDraft(draft); // dedupe по draft.id
  toMark.push({ draft_id: draft.id, theunum_reference_id: localId });
}

await fetch(`${SCRIBELY_BASE_URL}/integrations/theunum/v1/drafts/mark-consumed`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${SCRIBELY_INTEGRATION_TOKEN}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ items: toMark }),
});
```

## meta.reason_code (диагностика)

| Код | Значение |
|---|---|
| `queue_empty` | Норма — нечего забирать |
| `openrouter_payment_required` | Credits OpenRouter закончились |
| `openrouter_rate_limited` | Rate limit |
| `openrouter_keys_exhausted` | Все ключи отвалились |
| `dispatch_disabled` | AI dispatch выключен в Admin Settings |
| `rewrite_unavailable` | rewrite-сервис недоступен |

## Миграция

```bash
alembic upgrade head   # таблица draft_export_log
```
