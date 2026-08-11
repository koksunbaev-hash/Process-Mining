from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """План производства: сколько цех собирается испечь в этот день.

    Отдельно от заказов покупателей - заказ это то, что попросили, план это то,
    что решили печь, и правка одного не должна менять другое.
    """

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        # Ветка вторая по счёту: 0004 занят миграцией точности в рецептурах,
        # и две миграции с одним номером - это два листа графа, на которых
        # Django останавливается.
        ("bakery", "0004_recipeitem_quantity_precision"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductionPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="создано")),
                ("date", models.DateField(db_index=True, verbose_name="дата")),
                ("quantity", models.DecimalField(decimal_places=3, default=0, max_digits=12, verbose_name="количество")),
                ("note", models.CharField(blank=True, max_length=200, verbose_name="примечание")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="обновлено")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plans", to="bakery.product", verbose_name="продукт")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="production_plans", to=settings.AUTH_USER_MODEL, verbose_name="изменил")),
            ],
            options={
                "verbose_name": "план производства",
                "verbose_name_plural": "планы производства",
                "ordering": ["date", "product__name"],
            },
        ),
        migrations.AddConstraint(
            model_name="productionplan",
            constraint=models.UniqueConstraint(fields=("date", "product"), name="unique_plan_per_product_per_day"),
        ),
    ]
