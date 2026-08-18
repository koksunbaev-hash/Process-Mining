from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bakery", "0005_productionplan"),
    ]

    operations = [
        migrations.AddField(
            model_name="productionorder",
            name="kanban_grouped",
            field=models.BooleanField(
                default=False,
                help_text="Показывать партии этого заказа одним блоком и перемещать их вместе.",
                verbose_name="единый блок на канбане",
            ),
        ),
    ]
