from django.db import migrations


# Ровно то оборудование, что стоит в цеху, и ровно в том количестве. Числа
# здесь - не пример: три миксера, два формовщика, три расстоечных шкафа и пять
# печей. Дальше их правят в админке, а не в коде: купленная шестая печь не
# должна ждать разработчика.
UNITS = {
    "mixing": ("Миксер", 3),
    "forming": ("Формовщик", 2),
    "proofing": ("Шкаф", 3),
    "oven": ("Печь", 5),
}


def seed(apps, schema_editor):
    ProductionStage = apps.get_model("bakery", "ProductionStage")
    ProductionUnit = apps.get_model("bakery", "ProductionUnit")
    for code, (label, count) in UNITS.items():
        stage = ProductionStage.objects.filter(code=code).first()
        if stage is None:
            # Этапы заводит seed_bakery, и на пустой базе миграция идёт раньше
            # него. Тогда устройства создаст сам seed - здесь просто нечего
            # прицепить.
            continue
        for number in range(1, count + 1):
            ProductionUnit.objects.get_or_create(
                stage=stage,
                name=f"{label} {number}",
                defaults={"sequence": number},
            )


def unseed(apps, schema_editor):
    ProductionUnit = apps.get_model("bakery", "ProductionUnit")
    ProductionUnit.objects.filter(stage__code__in=UNITS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("bakery", "0010_production_units"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
