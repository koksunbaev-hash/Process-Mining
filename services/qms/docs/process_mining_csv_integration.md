# Интеграция Process Mining через CSV

KMS хлебозавода отправляет во внешнюю систему только бизнес-события: заказы, производственные партии, переходы этапов, проблемы, повторные проверки и складские операции. Открытие страниц, polling, CSS/JS и технические GET-запросы не экспортируются.

## Endpoint Process Mining

Разработчик Process Mining должен реализовать:

`POST /api/event-logs/import/`

Формат запроса: `multipart/form-data`.

Поля формы:

- `file` - CSV UTF-8.
- `export_id` - UUID пакета.
- `source` - источник, например `kms_bakery`.
- `schema_version` - версия схемы, сейчас `1.0`.
- `checksum` - SHA-256 от CSV в UTF-8.
- `events_count` - количество строк событий без заголовка.

HTTP headers:

- `Authorization: Bearer <token>`
- `Idempotency-Key: <export_id>`

KMS не отправляет API-токен на frontend. Токен хранится только в `.env`.

## CSV

Разделитель: запятая. Кодировка: UTF-8. Русский текст должен приниматься без потерь. Значения с запятыми, кавычками и переносами строк экранируются стандартным CSV.

Колонки в строгом порядке:

```csv
event_id,case_id,case_type,activity,timestamp,user_id,user_name,resource,product_id,product_name,batch_number,order_number,from_stage,to_stage,status,quantity,unit,problem_type,metadata
```

Обязательные поля:

- `event_id`
- `case_id`
- `activity`
- `timestamp`

`timestamp` приходит в ISO 8601 с timezone, например `2026-07-28T14:30:12+05:00`.

`metadata` - компактный JSON в одной CSV-ячейке.

## Идемпотентность

Process Mining должен считать `event_id` уникальным. Повторный импорт одного события не должен создавать дубль.

Process Mining должен также принимать повторную отправку пакета с тем же `Idempotency-Key` и `export_id`. Если пакет уже обработан, нужно вернуть прежний результат или отметить строки как `duplicates`.

## Успешный ответ

```json
{
  "status": "accepted",
  "export_id": "uuid",
  "received": 100,
  "accepted": 98,
  "duplicates": 2,
  "rejected": 0,
  "errors": []
}
```

## Частичная ошибка

```json
{
  "status": "partially_accepted",
  "export_id": "uuid",
  "received": 100,
  "accepted": 95,
  "duplicates": 2,
  "rejected": 3,
  "errors": [
    {
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "code": "INVALID_TIMESTAMP",
      "message": "Invalid timestamp"
    }
  ]
}
```

Правила KMS:

- accepted и duplicates считаются отправленными.
- rejected по конкретной строке переводит это событие в `failed`.
- временная ошибка сервера или timeout оставляет события для повторной отправки.
- после превышения лимита попыток событие уходит в `dead_letter`.

## Что нужно предоставить команде KMS

- Точный URL импорта.
- Тестовый и production Bearer token.
- Максимальный размер CSV.
- Максимальное число строк в пакете.
- Поддерживаемую кодировку и delimiter.
- Формат timestamp.
- Схему ответа.
- Список `error_code`.
- Правила retry и идемпотентности.
- Timeout и rate limits.
- Health endpoint.
- Sandbox/test endpoint.
- Swagger/OpenAPI документацию.

## Ответственность систем

Process Mining отвечает только за приём и анализ event log.

KMS отвечает за бизнес-логику хлебозавода: партии, этапы, заказы, склад, проблемы и права пользователей.
