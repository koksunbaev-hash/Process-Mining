# Ручные правки прогноза: хранится не прогноз, а несогласие человека с ним.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("bakery", "0012_production_unit_twin_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="ForecastOverride",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="обновлено")),
                ("date", models.DateField(db_index=True, verbose_name="день")),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=12, verbose_name="количество")),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="forecast_overrides",
                        to="bakery.product",
                        verbose_name="продукт",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="кто исправил",
                    ),
                ),
            ],
            options={
                "verbose_name": "правка прогноза",
                "verbose_name_plural": "правки прогноза",
            },
        ),
        migrations.AddConstraint(
            model_name="forecastoverride",
            constraint=models.UniqueConstraint(fields=("product", "date"), name="unique_forecast_override_per_product_day"),
        ),
    ]
