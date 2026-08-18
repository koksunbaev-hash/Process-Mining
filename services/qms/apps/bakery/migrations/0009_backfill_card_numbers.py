from django.db import migrations
from django.utils import timezone


def production_day(batch):
    """День, за который считается видимый номер партии.

    Тот же выбор, что и в services.assign_batch_card_numbers: плановый срок
    заказа, а не дата создания записи. Заказ на завтра оформляют сегодня, и
    номер должен лечь в завтрашний ряд.
    """
    order = batch.order_item.order
    if order.required_date:
        return timezone.localtime(order.required_date).date()
    return timezone.localtime(batch.created_at).date()


def backfill(apps, schema_editor):
    """Раздать видимые номера всем партиям, которым их ещё не дали.

    Миграции 0007 и 0008 пронумеровали только активные партии - остальные
    продолжали показывать технический номер (B-1000 -> «1000»), и в списках
    рядом с двузначными номерами доски стояли четырёхзначные из другой жизни.

    История нумеруется задним числом по своему производственному дню, так что
    сквозной последовательности через все дни не возникает: 01, 02, 03 внутри
    каждого дня, как на доске.
    """
    ProductionBatch = apps.get_model("bakery", "ProductionBatch")
    ProductionOrder = apps.get_model("bakery", "ProductionOrder")

    pending = list(
        ProductionBatch.objects
        .select_related("order_item__order")
        .filter(daily_card_number__isnull=True, is_demo=False)
        .order_by("id")
    )
    if not pending:
        return

    # Счётчик каждого дня стартует выше всего, что этот день уже занял - и по
    # партиям, и по заказам. Номер заказа берётся из того же ряда, что и номера
    # карточек, а на паре (дата, номер) заказа висит уникальный индекс: начни
    # ряд с нуля, и первая же историческая партия столкнулась бы с активной.
    counters = {}
    for row in ProductionBatch.objects.filter(daily_card_number__isnull=False).values_list(
        "card_number_date", "daily_card_number"
    ):
        day, number = row
        if day is not None:
            counters[day] = max(counters.get(day, 0), number)
    for row in ProductionOrder.objects.filter(daily_batch_number__isnull=False).values_list(
        "batch_number_date", "daily_batch_number"
    ):
        day, number = row
        if day is not None:
            counters[day] = max(counters.get(day, 0), number)

    grouped_numbers = {}
    first_per_order = {}
    for batch in pending:
        order = batch.order_item.order
        day = production_day(batch)
        if order.kanban_grouped:
            # Единый производственный блок остаётся одной партией для человека:
            # один номер на все товарные строки, как и на доске.
            number = grouped_numbers.get((order.pk, day))
            if number is None:
                counters[day] = number = counters.get(day, 0) + 1
                grouped_numbers[(order.pk, day)] = number
        else:
            counters[day] = number = counters.get(day, 0) + 1
        ProductionBatch.objects.filter(pk=batch.pk).update(
            daily_card_number=number,
            card_number_date=day,
        )
        first_per_order.setdefault(order.pk, (number, day))

    for order_id, (number, day) in first_per_order.items():
        ProductionOrder.objects.filter(
            pk=order_id,
            daily_batch_number__isnull=True,
        ).update(daily_batch_number=number, batch_number_date=day)


class Migration(migrations.Migration):
    dependencies = [
        ("bakery", "0008_batch_card_numbers"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
