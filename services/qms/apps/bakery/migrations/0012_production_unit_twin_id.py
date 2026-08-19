# Поле twin_id и стартовый маппинг устройств на двойники OpenTwins.
#
# Инвентарь в Ditto и парк в QMS совпали по составу один в один: 3 миксера,
# 2 формовщика, 3 шкафа, 5 печей. Сопоставление по порядковому номеру внутри
# этапа - «Печь 1» получает первую печь из инвентаря. Если в цеху на самом
# деле другая печь стоит первой, это правится в админке, а не в коде: поле
# редактируемое, миграция лишь задаёт стартовое соответствие и не трогает
# устройства, где twin_id уже заполнен.

from django.db import migrations, models

TWIN_BY_STAGE_AND_SEQUENCE = {
    ("mixing", 1): "digitalegiz:ESP32",                        # Миксер ARYSTAN H100 SPIRAL MIXER
    ("mixing", 2): "digitalegiz:ESP32_Dala_Meter_001990",      # Миксер Escher MR 160 PROF 1
    ("mixing", 3): "digitalegiz:ESP32_Dala_Meter_002006",      # Миксер Escher MR 160 PROF 2
    ("forming", 1): "digitalegiz:ESP32_Dala_Meter_002003",     # Формовщик Koenig Mini Rex Multi
    ("forming", 2): "digitalegiz:ESP32_Dala_Meter_002005",     # Формовщик Backtechnik S.I. Fortuna Automat
    ("proofing", 1): "digitalegiz:ESP32_Dala_Meter_002004",    # Шкаф WACHTEL AEROMAT
    ("proofing", 2): "digitalegiz:ESP32_Dala_Meter_002008",    # Шкаф WACHTEL COMPACT
    ("proofing", 3): "digitalegiz:ESP32_Dala_Meter_006411",    # Шкаф Backtechnik S.I. WACHTEL COMPACT
    ("oven", 1): "digitalegiz:Baker1_001989_ESP32_Dala_Meter", # Печь MIWE roll-in 1
    ("oven", 2): "digitalegiz:ESP32_Dala_Meter_001994",        # Печь MIWE roll-in 2
    ("oven", 3): "digitalegiz:ESP32_Dala_Meter_006906",        # Печь WACHTEL COLUMBUS MONO 1
    ("oven", 4): "digitalegiz:ESP32_Dala_Meter_007085",        # Печь WACHTEL COLUMBUS MONO 2
    ("oven", 5): "digitalegiz:ESP32_Dala_Meter_007108",        # Печь Backtechnik S.I. WACHTEL COMPACT
}


def seed_twin_ids(apps, schema_editor):
    ProductionUnit = apps.get_model("bakery", "ProductionUnit")
    for unit in ProductionUnit.objects.select_related("stage").filter(twin_id=""):
        twin_id = TWIN_BY_STAGE_AND_SEQUENCE.get((unit.stage.code, unit.sequence))
        if twin_id:
            unit.twin_id = twin_id
            unit.save(update_fields=["twin_id"])


def clear_twin_ids(apps, schema_editor):
    apps.get_model("bakery", "ProductionUnit").objects.update(twin_id="")


class Migration(migrations.Migration):

    dependencies = [
        ("bakery", "0011_seed_production_units"),
    ]

    operations = [
        migrations.AddField(
            model_name="productionunit",
            name="twin_id",
            field=models.CharField(blank=True, default="", max_length=120, verbose_name="цифровой двойник (thingId)"),
        ),
        migrations.RunPython(seed_twin_ids, clear_twin_ids),
    ]
