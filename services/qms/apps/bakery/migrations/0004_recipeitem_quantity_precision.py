from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bakery", "0003_finishedgoodsstock_is_demo_productionbatch_is_demo_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="recipeitem",
            name="quantity_for_batch",
            field=models.DecimalField(
                decimal_places=6,
                max_digits=15,
                verbose_name="на партию",
            ),
        ),
    ]
