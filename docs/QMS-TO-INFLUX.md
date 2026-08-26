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
| InfluxDB, `qms_batch_event` | **история**: каждый перевод партии | графики выработки и загрузки |
| InfluxDB, `qms_unit_state` | что на машине **сейчас** | панели рядом с телеметрией счётчика |

## Что именно уходит

Каждый перевод партии на этап — одна точка `qms_batch_event`:

```
qms_batch_event,stage=oven,from=proofing,product=MON-20260803-011,unit=Печь\ 3,
    thingId=digitalegiz:ESP32_Dala_Meter_001994
    batch="11 от 05.08.2026",case_id="REAL-20260805-011",
    stage_name="Печь",product_name="Бородинский хлеб 300гр в упаковке",
    order="REAL-20260805",quantity=106 1785909000000000000
```

Теги (по ним группируют и фильтруют): `stage` и `from` — коды этапов,
`product` — код продукта, `unit` — машина, `thingId` — её двойник. Номера
партий и заказов — поля, не теги: серия на каждую партию раздула бы базу.

`thingId` — тот же тег, которым Telegraf помечает телеметрию счётчиков, и
написан он так же, camelCase: `join` в Flux сводит таблицы по имени колонки,
и `thing_id` пришлось бы переименовывать в каждой панели. Тег появляется
только у машин с заполненным `twin_id` (админка → Производственные
устройства). Пустое поле — тега нет вовсе: тег без значения Influx отвергает
вместе со всей точкой.

## Что на машине сейчас — измерение `qms_unit_state`

`qms_batch_event` — это история: точка пишется в момент перевода партии.
Вопрос «что на печи прямо сейчас» она отвечает кружным путём, и с двумя
ловушками: нужно окно пошире, группировка по машине и `last()` в каждой
группе, а освободившаяся печь всё равно продолжает показывать последнюю
партию — события «партия ушла» в истории переводов просто нет.

Поэтому рядом идёт второе измерение, `qms_unit_state`: одна точка на машину,
переписывается при каждом движении доски.

```
qms_unit_state,unit=Печь\ 3,stage=oven,thingId=digitalegiz:ESP32_Dala_Meter_001994
    product="Бородинский хлеб",quantity=106,quantity_unit="шт",
    card="11",order="№REAL-20260805",customer="Кафе",
    status="в работе",stage_name="Печь",started_at="2026-08-05T16:10:00+06:00"
```

Свободная машина пишет тот же набор полей с `status="свободно"`, пустыми
строками и `quantity=0` — форма точки не меняется от того, занята печь или
нет. Поле единицы измерения названо `quantity_unit`, а не `unit`: тег и поле
с одним именем Influx не различает.

Запрос к нему — `filter` да `last()`, без окон и группировок:

```flux
from(bucket: "qms")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "qms_unit_state")
  |> last()
  |> group()
  |> keep(columns: ["thingId", "unit", "stage", "_field", "_value"])
  |> pivot(rowKey: ["thingId", "unit", "stage"], columnKey: ["_field"], valueColumn: "_value")
```

Для одного объекта 3D-сцены — добавить фильтр по его двойнику:

```flux
  |> filter(fn: (r) => r.thingId == "digitalegiz:ESP32_Dala_Meter_001994")
```

Готовый дашборд с обеими панелями лежит в
`docs/grafana/unit-state-dashboard.json` — импортируется в Grafana как есть,
при импорте спросит, какой источник данных использовать.

## Продукт машины рядом с её киловаттами

Два потока — телеметрия счётчика и движения партий — сходятся ровно по
`thingId`, и только по нему: имя машины телеметрии неизвестно. Панель, где на
каждой машине видно и ток, и что она сейчас печёт:

```flux
meter = from(bucket: "default")
  |> range(start: -5m)
  |> filter(fn: (r) => exists r.thingId)
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group(columns: ["thingId"])
  |> keep(columns: ["thingId", "value_current_a", "value_voltage_v",
                    "value_live_active_power_w", "value_status"])

qms = from(bucket: "qms")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "qms_batch_event")
  |> filter(fn: (r) => r._field == "order" or r._field == "product_name")
  |> filter(fn: (r) => exists r.thingId)
  |> group(columns: ["thingId", "_field"])
  |> last()
  |> pivot(rowKey: ["thingId"], columnKey: ["_field"], valueColumn: "_value")
  |> keep(columns: ["thingId", "order", "product_name"])

join(tables: {m: meter, q: qms}, on: ["thingId"])
```

Ключевое здесь — `group(columns: ["thingId"])` перед `last()`: без
группировки `last()` берёт одну последнюю точку на весь цех, и к счётчикам
всех машин приезжает партия какой-то одной. Соединение по выдуманному
постоянному ключу (`map(fn: (r) => ({r with join_key: 1}))`) даёт ровно ту
же ошибку — на экране она выглядит правдоподобно, пока в цеху работает одна
машина.

Партия на машине последние 7 дней — это «что было на ней в последний раз», а
не «что стоит сейчас»: событие пишется в момент перевода. Текущее состояние
знает двойник (фича `product`, см. `docs/QMS-TO-GRAFANA.md`).

Тег добавлен к новым точкам. У истории, записанной до него, тега нет, и
`sync_influx` её не исправит: точка с новым набором тегов — это новая серия
рядом со старой, а не замена. Панели за прошлые недели поэтому лучше строить
по `unit`.

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
