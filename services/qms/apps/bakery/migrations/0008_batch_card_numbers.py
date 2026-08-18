from django.db import migrations, models
from django.utils import timezone


def number_active_cards(apps, schema_editor):
    ProductionBatch = apps.get_model("bakery", "ProductionBatch")
    ProductionOrder = apps.get_model("bakery", "ProductionOrder")
    today = timezone.localdate()
    batches = list(
        ProductionBatch.objects
        .select_related("order_item__order")
        .exclude(status__in=["completed", "cancelled"])
        .exclude(current_stage__code="done")
        .order_by("id")
    )
    active_order_ids = {batch.order_item.order_id for batch in batches}
    # 0007 already assigned one number per order. The new card-level sequence
    # can swap those values, and PostgreSQL checks the unique constraint after
    # every UPDATE. Free only the active orders first so the renumbering cannot
    # collide midway; completed history is deliberately untouched.
    ProductionOrder.objects.filter(pk__in=active_order_ids).update(
        daily_batch_number=None,
        batch_number_date=None,
    )
    grouped_numbers = {}
    first_per_order = {}
    number = 0
    for batch in batches:
        order = batch.order_item.order
        if order.kanban_grouped:
            value = grouped_numbers.get(order.pk)
            if value is None:
                number += 1
                value = grouped_numbers[order.pk] = number
        else:
            number += 1
            value = number
        ProductionBatch.objects.filter(pk=batch.pk).update(
            daily_card_number=value,
            card_number_date=today,
        )
        first_per_order.setdefault(order.pk, value)

    for order_id, value in first_per_order.items():
        ProductionOrder.objects.filter(pk=order_id).update(
            daily_batch_number=value,
            batch_number_date=today,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("bakery", "0007_daily_batch_numbers"),
    ]

    operations = [
        migrations.AddField(
            model_name="productionbatch",
            name="daily_card_number",
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True, verbose_name="номер блока за день"),
        ),
        migrations.AddField(
            model_name="productionbatch",
            name="card_number_date",
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name="дата номера блока"),
        ),
        migrations.RunPython(number_active_cards, migrations.RunPython.noop),
    ]
