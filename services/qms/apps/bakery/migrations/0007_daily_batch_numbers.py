from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def number_active_orders(apps, schema_editor):
    ProductionBatch = apps.get_model("bakery", "ProductionBatch")
    ProductionOrder = apps.get_model("bakery", "ProductionOrder")
    today = timezone.localdate()
    order_ids = (
        ProductionBatch.objects
        .exclude(status__in=["completed", "cancelled"])
        .exclude(current_stage__code="done")
        .order_by("id")
        .values_list("order_item__order_id", flat=True)
    )
    seen = set()
    number = 0
    for order_id in order_ids:
        if order_id in seen:
            continue
        seen.add(order_id)
        number += 1
        ProductionOrder.objects.filter(pk=order_id).update(
            daily_batch_number=number,
            batch_number_date=today,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("bakery", "0006_productionorder_kanban_grouped"),
    ]

    operations = [
        migrations.AddField(
            model_name="productionorder",
            name="daily_batch_number",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="номер партии за день"),
        ),
        migrations.AddField(
            model_name="productionorder",
            name="batch_number_date",
            field=models.DateField(blank=True, db_index=True, null=True, verbose_name="дата номера партии"),
        ),
        migrations.RunPython(number_active_orders, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="productionorder",
            constraint=models.UniqueConstraint(
                condition=Q(batch_number_date__isnull=False, daily_batch_number__isnull=False),
                fields=("batch_number_date", "daily_batch_number"),
                name="unique_daily_production_batch_number",
            ),
        ),
    ]
