"""Replace demo production history with the real 04-08 August 2026 sheets.

Quantities and production dates are transcribed from the five paper sheets.
The sheets contain no transition timestamps, so stage times are reconstructed
deterministically across the three factory shifts and labelled as estimates in
Process Mining metadata.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.bakery.models import (
    BatchStageHistory,
    Customer,
    FinishedGoodsStock,
    OrderEvent,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionPlan,
    ProductionStage,
    Product,
    Unit,
)
from apps.process_mining.models import ProcessEvent, ProcessEventExport


COMMON = [
    "Багет Луковый 300гр в упаковке",
    "Багет Новый 300гр в упаковке",
    "Багет Отрубной 300гр в упаковке",
    "Багет Премиум 350гр в упаковке",
    "Батон Верный 400гр в упаковке",
    "Батон Нарезной 400гр",
    "Батон Нарезной 400гр в упаковке",
    "Береке хлеб 420гр",
    "Береке хлеб 420гр в упаковке",
    "Бородинский хлеб 300гр",
    "Бородинский хлеб 300гр в упаковке",
    "Булочка для гамбургера штучно",
    "Булочка для гамбургера штучно большой с кунжутом",
    "Булочка для хотдога штучно",
    "Булочки в упаковке",
]

DAY_04_NAMES = COMMON + [
    "Детский хлеб 500гр в упаковке",
    "Деревенский хлеб 500гр в упаковке",
    "Деревенский хлеб 500гр нарезной в упаковке",
    "Диетический хлеб 200гр",
    "Диетический хлеб 200гр в упаковке",
    "Жайлы хлеб 600гр",
    "Жайлы хлеб 600гр в упаковке",
    "Здоровье хлеб 400гр",
    "Здоровье хлеб 400гр в упаковке",
    "Зерновое солодовый хлеб 350гр в упаковке осн",
    "Кукурузный хлеб 350гр в упаковке",
    "Любимый хлеб 500гр",
    "Любимый хлеб 500гр в упаковке",
    "Любимый хлеб 500гр нарезной в упаковке",
    "Немецкий хлеб 250гр в упаковке",
    "Отрубной хлеб 450гр",
    "Отрубной хлеб 450гр в упаковке",
    "Плетенка с кунжутной посыпкой 400гр",
    "Плетенка с маковой посыпкой 400гр",
    "Ржаной хлеб 450гр",
    "Ржаной хлеб 450гр в упаковке",
    "Семейный хлеб 600гр",
    "Семейный хлеб 600гр в упаковке",
    "Славянский хлеб 600гр в упаковке",
    "Спорт Актив хлеб 350гр в упаковке",
    "Столичный хлеб 450гр в упаковке",
    "Сэндвич Chicken Hit 250 гр",
    "Сэндвич Mega cheese 250 гр",
    "Сэндвич классика 280 гр",
    "Сэндвич с охотничьей колбаской 280 гр",
    "Сэндвич шт Панини",
    "Сэндвич шт Панини (черные)",
    "Сэндвичи в упаковке (3шт)",
    "Тартин бездрожжевой 430 гр в упаковке",
    "Тостовый хлеб 250гр в упаковке",
    "Формовой мини хлеб 300гр",
    "Формовой мини хлеб 300гр в упаковке",
    "Формовой хлеб 600гр",
    "Формовой хлеб 600гр в упаковке",
    "Хлеб Зерновой 430гр",
    "Хлеб Зерновой 430гр в упаковке",
    "Хлеб Чиабатта шт",
    "Хот-дог",
]

DAY_05_NAMES = COMMON + [
    "Гречишный хлеб 350гр в упаковке",
    "Детский хлеб 500гр в упаковке",
    "Деревенский хлеб 500гр в упаковке",
    "Диетический хлеб 200гр",
    "Диетический хлеб 200гр в упаковке",
    "Домашний хлеб 500гр в упаковке",
    "Жайлы хлеб 600гр",
    "Жайлы хлеб 600гр в упаковке",
    "Здоровье хлеб 400гр",
    "Здоровье хлеб 400гр в упаковке",
    "Кукурузный хлеб 350гр в упаковке",
    "Любимый хлеб 500гр",
    "Любимый хлеб 500гр в упаковке",
    "Немецкий хлеб 250гр в упаковке",
    "Отрубной хлеб 450гр",
    "Отрубной хлеб 450гр в упаковке",
    "Плетенка с кунжутной посыпкой 400гр",
    "Плетенка с маковой посыпкой 400гр",
    "Ржаной хлеб 450гр",
    "Ржаной хлеб 450гр в упаковке",
    "Семейный хлеб 600гр",
    "Семейный хлеб 600гр в упаковке",
    "Славянский хлеб 600гр в упаковке",
    "Спорт Актив хлеб 350гр в упаковке",
    "Столичный хлеб 450гр в упаковке",
    "Сэндвич Chicken Hit 250 гр",
    "Сэндвич Mega cheese 250 гр",
    "Сэндвич классика 280 гр",
    "Сэндвич с охотничьей колбаской 280 гр",
    "Сэндвич шт Панини",
    "Сэндвич шт Панини (черные)",
    "Сэндвичи в упаковке (3шт)",
    "Тартин бездрожжевой 430 гр в упаковке",
    "Тостовый хлеб 250гр в упаковке",
    "Формовой мини хлеб 300гр",
    "Формовой мини хлеб 300гр в упаковке",
    "Формовой хлеб 600гр",
    "Формовой хлеб 600гр в упаковке",
    "Хлеб Зерновой 430гр",
    "Хлеб Зерновой 430гр в упаковке",
    "Хлеб с семечками 350гр в упаковке осн",
    "Хлеб Чиабатта шт",
    "Хот-дог",
]

DAY_06_NAMES = ["Баварский хлеб 450гр в упаковке"] + COMMON + [
    "Гречишный хлеб 350гр в упаковке",
    "Детский хлеб 500гр в упаковке",
    "Деревенский хлеб 500гр в упаковке",
    "Деревенский хлеб 500гр нарезной в упаковке",
    "Диетический хлеб 200гр",
    "Диетический хлеб 200гр в упаковке",
    "Жайлы хлеб 600гр",
    "Жайлы хлеб 600гр в упаковке",
    "Здоровье хлеб 400гр",
    "Здоровье хлеб 400гр в упаковке",
    "Зерновое солодовый хлеб 350гр в упаковке осн",
    "Кукурузный хлеб 350гр в упаковке",
    "Любимый хлеб 500гр",
    "Любимый хлеб 500гр в упаковке",
    "Любимый хлеб 500гр нарезной в упаковке",
    "Немецкий хлеб 250гр в упаковке",
    "Отрубной хлеб 450гр",
    "Отрубной хлеб 450гр в упаковке",
    "Плетенка с кунжутной посыпкой 400гр",
    "Плетенка с кунжутной посыпкой 400гр в упаковке",
    "Плетенка с маковой посыпкой 400гр",
    "Плетенка с маковой посыпкой 400гр в упаковке",
    "Ржаной хлеб 450гр",
    "Ржаной хлеб 450гр в упаковке",
    "Семейный хлеб 600гр",
    "Семейный хлеб 600гр в упаковке",
    "Славянский хлеб 600гр в упаковке",
    "Спорт Актив хлеб 350гр в упаковке",
    "Столичный хлеб 450гр в упаковке",
    "Сэндвич Chicken Hit 250 гр",
    "Сэндвич Mega cheese 250 гр",
    "Сэндвич классика 280 гр",
    "Сэндвич с кунжутом шт",
    "Сэндвич с охотничьей колбаской 280 гр",
    "Сэндвич шт Панини",
    "Сэндвич шт Панини (черные)",
    "Сэндвичи в упаковке (3шт)",
    "Тартин бездрожжевой 430 гр в упаковке",
    "Тостовый хлеб 250гр в упаковке",
    "Формовой мини хлеб 300гр",
    "Формовой мини хлеб 300гр в упаковке",
    "Формовой хлеб 600гр",
    "Формовой хлеб 600гр в упаковке",
    "Хлеб Зерновой 430гр",
    "Хлеб Зерновой 430гр в упаковке",
    "Хлеб с семечками 350гр в упаковке осн",
    "Хлеб Чиабатта шт",
    "Хот-дог",
]

DAY_08_NAMES = COMMON + [
    "Гречишный хлеб 350гр в упаковке",
    "Детский хлеб 500гр в упаковке",
    "Деревенский хлеб 500гр в упаковке",
    "Диетический хлеб 200гр",
    "Диетический хлеб 200гр в упаковке",
    "Домашний хлеб 500гр в упаковке",
    "Жайлы хлеб 600гр",
    "Жайлы хлеб 600гр в упаковке",
    "Здоровье хлеб 400гр",
    "Здоровье хлеб 400гр в упаковке",
    "Кукурузный хлеб 350гр в упаковке",
    "Любимый хлеб 500гр",
    "Любимый хлеб 500гр в упаковке",
    "Немецкий хлеб 250гр в упаковке",
    "Отрубной хлеб 450гр",
    "Отрубной хлеб 450гр в упаковке",
    "Плетенка с кунжутной посыпкой 400гр",
    "Плетенка с маковой посыпкой 400гр",
    "Ржаной хлеб 450гр",
    "Ржаной хлеб 450гр в упаковке",
    "Семейный хлеб 600гр",
    "Семейный хлеб 600гр в упаковке",
    "Славянский хлеб 600гр в упаковке",
    "Спорт Актив хлеб 350гр в упаковке",
    "Столичный хлеб 450гр в упаковке",
    "Сэндвич Chicken Hit 250 гр",
    "Сэндвич Mega cheese 250 гр",
    "Сэндвич классика 280 гр",
    "Сэндвич с кунжутом шт",
    "Сэндвич с охотничьей колбаской 280 гр",
    "Сэндвич шт Панини",
    "Сэндвич шт Панини (черные)",
    "Сэндвичи в упаковке (3шт)",
    "Тартин бездрожжевой 430 гр в упаковке",
    "Тостовый хлеб 250гр в упаковке",
    "Формовой мини хлеб 300гр",
    "Формовой мини хлеб 300гр в упаковке",
    "Формовой хлеб 600гр",
    "Формовой хлеб 600гр в упаковке",
    "Хлеб Зерновой 430гр",
    "Хлеб Зерновой 430гр в упаковке",
    "Хлеб Чиабатта шт",
    "Хот-дог",
]

SHEETS = {
    date(2026, 8, 4): (DAY_04_NAMES, [46,142,50,6,88,123,18,37,13,312,194,290,790,645,3,5,5,18,86,68,38,24,3,1,19,3,415,6,42,12,74,32,37,11,35,24,68,65,9,8,2,89,56,79,64,5495,170,7,1,8,155,60,1372,156,305,21,63,32], 12000),
    date(2026, 8, 5): (DAY_05_NAMES, [22,138,25,13,24,128,14,41,29,315,106,260,485,575,2,6,9,11,100,50,6,28,32,3,1,5,405,18,7,86,49,28,7,40,21,60,48,2,7,3,64,28,72,30,2085,110,5,3,5,180,47,1307,92,265,23,1,18,30], 7574),
    date(2026, 8, 6): (DAY_06_NAMES, [1,41,141,51,13,52,96,28,38,8,225,167,470,785,815,2,5,11,3,27,109,38,41,30,3,1,24,5,306,6,39,6,64,42,16,5,7,5,19,23,61,49,2,9,2,44,20,41,250,20,3500,70,4,1,1,130,31,1214,114,252,36,1,60,26], 9706),
    date(2026, 8, 7): (DAY_05_NAMES, [27,190,36,10,31,168,12,60,5,347,156,220,500,512,7,4,23,11,104,81,10,39,24,3,1,3,455,26,7,109,40,33,10,50,20,58,48,2,4,5,50,18,42,20,1380,80,3,1,8,190,61,1600,106,355,31,2,12,24], 7434),
    date(2026, 8, 8): (DAY_08_NAMES, [34,223,54,23,37,178,52,71,36,300,189,220,830,492,8,4,14,14,133,78,8,57,44,3,6,3,490,31,9,106,69,45,7,61,43,88,87,11,9,7,90,46,85,300,39,4495,150,10,2,19,199,72,1582,192,355,30,27,42], 11909),
}

ALIASES = {
    "Баварский хлеб 450гр в упаковке": "Хлеб «Баварский»",
    "Зерновое солодовый хлеб 350гр в упаковке осн": "Хлеб «Солодовый» с семечками нарезанный",
}

STAGE_RESOURCES = {
    "queue": "Диспетчер производства",
    "mixing": "Оператор замеса",
    "forming": "Оператор формовки",
    "proofing": "Оператор расстойки",
    "oven": "Оператор печи",
    "warehouse": "Склад готовой продукции",
    "done": "Диспетчер производства",
}

STAGE_ACTIVITIES = {
    "queue": "Партия поступила в очередь",
    "mixing": "Начало замеса",
    "forming": "Передача на формовку",
    "proofing": "Передача на расстойку",
    "oven": "Передача в печь",
    "warehouse": "Приём продукции на склад",
    "done": "Завершение партии",
}


class Command(BaseCommand):
    help = "Импортирует реальные производственные листы 04-08.08.2026 с расчётным временем этапов."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Очистить старые данные и выполнить импорт.")

    def handle(self, *args, **options):
        self._validate_sheets()
        self.stdout.write("Подготовлено: 5 заказов, 296 позиций, 48 623 шт.")
        self.stdout.write(
            "Будет удалено: "
            f"заказов {ProductionOrder.objects.count()}, "
            f"партий {ProductionBatch.objects.count()}, "
            f"планов {ProductionPlan.objects.count()}, "
            f"PM-событий {ProcessEvent.objects.count()}, "
            f"PM-отправок {ProcessEventExport.objects.count()}."
        )
        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Предварительный просмотр. Для выполнения добавьте --apply."))
            return

        with transaction.atomic():
            self._clear_old_data()
            stats = self._create_history()

        self.stdout.write(
            self.style.SUCCESS(
                f"Создано: заказов {stats['orders']}, позиций/партий {stats['batches']}, "
                f"историй этапов {stats['history']}, PM-событий {stats['events']}."
            )
        )

    def _validate_sheets(self):
        total_items = 0
        total_quantity = 0
        for production_date, (names, quantities, expected) in SHEETS.items():
            if len(names) != len(quantities):
                raise CommandError(f"{production_date}: названий {len(names)}, количеств {len(quantities)}")
            actual = sum(quantities)
            if actual != expected:
                raise CommandError(f"{production_date}: итог {actual}, на листе {expected}")
            total_items += len(names)
            total_quantity += actual
        if total_items != 296 or total_quantity != 48623:
            raise CommandError(f"Общий итог не сошёлся: {total_items} позиций, {total_quantity} шт.")

    def _clear_old_data(self):
        # Stock protects a batch; events are independent and must be removed
        # first so no old queue/sent state survives the replacement.
        ProcessEvent.objects.all().delete()
        ProcessEventExport.objects.all().delete()
        FinishedGoodsStock.objects.all().delete()
        ProductionBatch.objects.all().delete()
        ProductionOrder.objects.all().delete()
        ProductionPlan.objects.all().delete()

    def _create_history(self):
        stages = {stage.code: stage for stage in ProductionStage.objects.all()}
        required = {"queue", "mixing", "forming", "proofing", "oven", "warehouse", "done"}
        missing = required - stages.keys()
        if missing:
            raise CommandError("Не найдены этапы: " + ", ".join(sorted(missing)))

        User = get_user_model()
        actor = User.objects.filter(is_superuser=True).order_by("id").first() or User.objects.order_by("id").first()
        customer, _ = Customer.objects.get_or_create(
            name="Производственный план — реальные данные",
            defaults={"notes": "Производственные листы 04–08 августа 2026 года."},
        )

        histories = []
        history_times = []
        events = []
        order_events = []
        order_event_times = []
        batch_count = 0

        for production_date, (names, quantities, _) in sorted(SHEETS.items()):
            order_created = self._aware(production_date - timedelta(days=1), time(14, 0))
            required_date = self._aware(production_date, time(23, 59))
            order = ProductionOrder.objects.create(
                order_number=f"REAL-{production_date:%Y%m%d}",
                customer=customer,
                order_date=order_created,
                required_date=required_date,
                priority=ProductionOrder.Priority.NORMAL,
                status=ProductionOrder.Status.READY,
                notes="Реальные количества с производственного листа. Время этапов восстановлено приблизительно.",
                created_by=actor,
                is_demo=False,
                # Видимая нумерация начинается заново каждый производственный
                # день, и на день приходится ровно один лист - значит номера
                # карточек совпадают с порядком строк листа, а заказ забирает
                # первый. Без этого импорт вернул бы в интерфейс технические
                # REAL-20260804-001 рядом с двузначными номерами доски.
                daily_batch_number=1,
                batch_number_date=production_date,
            )
            ProductionOrder.objects.filter(pk=order.pk).update(created_at=order_created, updated_at=required_date)

            order_timeline = [
                (order_created, "created", "Заказ создан"),
                (order_created + timedelta(minutes=20), "confirmed", "Заказ подтверждён"),
                (required_date - timedelta(hours=1), "ready", "Заказ готов"),
            ]
            for moment, event_type, message in order_timeline:
                order_events.append(OrderEvent(order=order, event_type=event_type, message=message, created_by=actor))
                order_event_times.append(moment)
                events.append(
                    ProcessEvent(
                        case_id=order.order_number,
                        case_type=ProcessEvent.CaseType.ORDER,
                        activity=message,
                        occurred_at=moment,
                        order=order,
                        user=actor,
                        status=ProductionOrder.Status.READY if event_type == "ready" else event_type,
                        resource="Диспетчер производства",
                        event_data=self._metadata(production_date),
                    )
                )

            for index, (source_name, raw_quantity) in enumerate(zip(names, quantities), start=1):
                product = self._product_for(source_name)
                quantity = Decimal(raw_quantity)
                recipe = product.recipes.filter(is_active=True).first()
                item = ProductionOrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    unit=product.unit,
                    recipe=recipe,
                    notes="Количество с бумажного производственного листа.",
                    is_demo=False,
                )

                moments = self._stage_moments(production_date, index)
                batch = ProductionBatch.objects.create(
                    batch_number=f"REAL-{production_date:%Y%m%d}-{index:03d}",
                    daily_card_number=index,
                    card_number_date=production_date,
                    order_item=item,
                    product=product,
                    recipe=recipe,
                    planned_quantity=quantity,
                    actual_quantity=quantity,
                    unit=product.unit,
                    current_stage=stages["done"],
                    status=ProductionBatch.Status.COMPLETED,
                    assigned_to=actor,
                    planned_start=moments["mixing"],
                    actual_start=moments["mixing"],
                    planned_finish=moments["done"],
                    actual_finish=moments["done"],
                    notes="Реальный выпуск; время этапов рассчитано приблизительно.",
                    is_demo=False,
                )
                ProductionBatch.objects.filter(pk=batch.pk).update(
                    created_at=moments["queue"], updated_at=moments["done"]
                )
                ProductionPlan.objects.create(
                    date=production_date,
                    product=product,
                    quantity=quantity,
                    note="Реальный производственный лист",
                    updated_by=actor,
                )

                codes = ["queue", "mixing", "forming", "proofing", "oven", "warehouse", "done"]
                for position, code in enumerate(codes):
                    previous = codes[position - 1] if position else None
                    histories.append(
                        BatchStageHistory(
                            batch=batch,
                            from_stage=stages[previous] if previous else None,
                            to_stage=stages[code],
                            started_at=moments[previous] if previous else moments[code] - timedelta(minutes=10),
                            finished_at=moments[code],
                            changed_by=actor,
                            comment="Расчётное историческое время; количество подтверждено производственным листом.",
                        )
                    )
                    history_times.append(moments[code])
                    events.append(
                        ProcessEvent(
                            case_id=batch.batch_number,
                            case_type=ProcessEvent.CaseType.BATCH,
                            activity=STAGE_ACTIVITIES[code],
                            occurred_at=moments[code],
                            batch=batch,
                            order=order,
                            user=actor,
                            product=product,
                            from_stage=previous or "",
                            to_stage=code,
                            status=ProductionBatch.Status.COMPLETED if code == "done" else (
                                ProductionBatch.Status.QUEUED if code == "queue" else ProductionBatch.Status.IN_PROGRESS
                            ),
                            quantity=quantity,
                            unit=product.unit,
                            resource=STAGE_RESOURCES[code],
                            event_data=self._metadata(production_date),
                        )
                    )
                batch_count += 1

        OrderEvent.objects.bulk_create(order_events, batch_size=500)
        for record, moment in zip(order_events, order_event_times):
            record.created_at = moment
        OrderEvent.objects.bulk_update(order_events, ["created_at"], batch_size=500)

        BatchStageHistory.objects.bulk_create(histories, batch_size=500)
        for record, moment in zip(histories, history_times):
            record.created_at = moment
        BatchStageHistory.objects.bulk_update(histories, ["created_at"], batch_size=500)

        ProcessEvent.objects.bulk_create(events, batch_size=500)
        return {
            "orders": len(SHEETS),
            "batches": batch_count,
            "history": len(histories),
            "events": len(events),
        }

    def _product_for(self, source_name):
        name = ALIASES.get(source_name, source_name)
        product = Product.objects.filter(name=name).order_by("id").first()
        if product:
            return product

        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10].upper()
        category = Product.Category.SANDWICH if "Сэндвич" in name else (
            Product.Category.BUN if any(word in name for word in ("Булоч", "Чиабат", "Хот-дог")) else Product.Category.BREAD
        )
        return Product.objects.create(
            code=f"REAL-{digest}",
            name=name,
            description="Добавлено из реального производственного листа 04–08.08.2026.",
            category=category,
            unit=Unit.PCS,
            is_active=True,
        )

    @staticmethod
    def _aware(day, at):
        return timezone.make_aware(datetime.combine(day, at), timezone.get_current_timezone())

    def _stage_moments(self, production_date, index):
        # Consecutive paper sheets share their night boundary: the evening
        # shift of one sheet is also the previous-evening shift of the next.
        # Putting reconstructed completions there would count the same output
        # on two dates. The source sheets do not say which shift made a row,
        # so estimates stay inside the non-overlapping 08:00-20:00 interval.
        # Lines operate in parallel; a nine-minute start cadence keeps even the
        # 64-row day inside that shift while retaining realistic durations.
        mixing = self._aware(production_date, time(8, 0)) + timedelta(minutes=(index - 1) * 9)
        forming = mixing + timedelta(minutes=18 + index % 10)
        proofing = forming + timedelta(minutes=12 + index % 8)
        oven = proofing + timedelta(minutes=35 + index % 20)
        warehouse = oven + timedelta(minutes=18 + index % 12)
        done = warehouse + timedelta(minutes=8 + index % 8)
        return {
            "queue": mixing - timedelta(minutes=15 + index % 10),
            "mixing": mixing,
            "forming": forming,
            "proofing": proofing,
            "oven": oven,
            "warehouse": warehouse,
            "done": done,
        }

    @staticmethod
    def _metadata(production_date):
        return {
            "source": "real_production_sheets_2026_08_04_08",
            "quantities_are_real": True,
            "timestamps_are_estimated": True,
            "production_date": production_date.isoformat(),
            "is_demo": False,
        }
