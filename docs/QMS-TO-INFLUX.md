# Как QMS передаёт данные в общий InfluxDB

Внешняя Grafana (`dt.digitalegiz.kz`) читает из общей базы
`influx.digitalegiz.kz`. Телеметрия счётчиков — ток, напряжение,
киловатт-часы — доходит туда своим путём: от устройств через MQTT и
Telegraf. Производственная часть раньше туда не попадала вовсе: движения
партий уходили только в Ditto, на 3D-сцену локальной Grafana стенда.

Теперь QMS пишет в общую базу второй поток — движения партий. Это другой
канал, чем Ditto, и они не заменяют друг друга:

| куда | что | зачем |
|---|---|---|
| Ditto (`твин машины`) | что на машине **сейчас** | табло 3D-сцены |
| InfluxDB (`bucket qms`) | **история**: каждый перевод партии | графики и панели внешней Grafana |

## Что именно уходит

Каждый перевод партии на этап — одна точка `qms_batch_event`:

```
qms_batch_event,stage=oven,from=proofing,product=MON-20260803-011,unit=Печь\ 3
    batch="11 от 05.08.2026",case_id="REAL-20260805-011",
    stage_name="Печь",product_name="Бородинский хлеб 300гр в упаковке",
    order="REAL-20260805",quantity=106 1785909000000000000
```

Теги (по ним группируют и фильтруют): `stage` и `from` — коды этапов,
`product` — код продукта, `unit` — машина. Номера партий и заказов —
поля, не теги: серия на каждую партию раздула бы базу.

Демо-партии не отправляются: общая витрина показывает завод, а не
репетицию.

## Дисциплина доставки

Та же, что у Ditto, и это осознанно: Influx — витрина, а не источник
истины. Точка уходит после коммита, в фоновом потоке, с таймаутом
5 секунд. Сеть моргнула — в лог упадёт предупреждение, партия переедет
как ни в чём не бывало, а витрина отстанет на точку.

Дыры лечит переливка:

```bash
cd ~/Process-Mining && docker compose exec -T qms python manage.py sync_influx
```

Точки идемпотентны по (тегам, времени) — переливать можно сколько
угодно, ничего не задваивается. Посмотреть, не отправляя:

```bash
docker compose exec -T qms python manage.py sync_influx --dry-run --days 7
```

## Включение

Выключено по умолчанию. В `~/Process-Mining/.env`:

```
INFLUX_ENABLED=True
INFLUX_URL=https://influx.digitalegiz.kz
INFLUX_ORG=opentwins
INFLUX_BUCKET=qms
INFLUX_TOKEN=<токен с правом записи в bucket qms>
INFLUX_TIMEOUT_SECONDS=5
```

Токен лежит там же, где его берёт openegiz. После правки — перезапустить:

```bash
cd ~/Process-Mining && docker compose up -d qms
```

## Как читать из Grafana

Источник данных InfluxDB у внешней Grafana уже настроен на организацию
`opentwins` — bucket `qms` виден ему без доработок. Примеры Flux:

Партии, дошедшие до «Готово», по дням:

```flux
from(bucket: "qms")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "qms_batch_event"
                   and r.stage == "done"
                   and r._field == "quantity")
  |> aggregateWindow(every: 1d, fn: count)
```

Загрузка машин — сколько партий прошло через каждую:

```flux
from(bucket: "qms")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "qms_batch_event"
                   and r._field == "batch"
                   and exists r.unit)
  |> group(columns: ["unit"])
  |> count()
```

Выпуск по продуктам за неделю:

```flux
from(bucket: "qms")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "qms_batch_event"
                   and r.stage == "done"
                   and r._field == "quantity")
  |> group(columns: ["product"])
  |> sum()
```

## Проверка

Сколько точек в базе:

```bash
TOKEN=$(grep "^INFLUX_TOKEN=" ~/Process-Mining/.env | cut -d= -f2-)
printf '%s' 'from(bucket: "qms") |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "qms_batch_event" and r._field == "batch")
  |> group() |> count()' > /tmp/q.flux
curl -s -X POST "https://influx.digitalegiz.kz/api/v2/query?org=opentwins" \
  -H "Authorization: Token $TOKEN" -H "Content-Type: application/vnd.flux" \
  -H "Accept: application/csv" --data-binary @/tmp/q.flux
```

`cut -d= -f2-` с дефисом обязателен: токен кончается на `==`, и без
дефиса от него остаётся первый кусок.

Логи отправки:

```bash
docker compose logs --tail=50 qms | grep -i influx
```

## Что где лежит в коде

| файл | назначение |
|---|---|
| `services/qms/apps/bakery/influx.py` | точки, транспорт, сигнал |
| `services/qms/apps/bakery/management/commands/sync_influx.py` | переливка истории |
| `services/qms/apps/bakery/tests/test_influx.py` | тесты (в сеть не ходят) |
| `services/qms/config/settings.py` | настройки `INFLUX_*` |
