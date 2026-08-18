"""Оборудование цеха по умолчанию.

Ровно то, что стоит в цеху, и ровно в том количестве: три миксера, два
формовщика, три расстоечных шкафа и пять печей. Дальше их правят в админке -
купленная шестая печь не должна ждать разработчика.

Тот же список продублирован в миграции 0011: миграции не ходят в код
приложения, иначе правка этого файла молча меняла бы уже применённую миграцию.
Расхождение двух копий ловит тест - без него свежая база получила бы не то
оборудование, что обновлённая.
"""

DEFAULT_UNITS = {
    "mixing": ("Миксер", 3),
    "forming": ("Формовщик", 2),
    "proofing": ("Шкаф", 3),
    "oven": ("Печь", 5),
}


def ensure_default_units():
    """Завести недостающие устройства. Уже существующие не трогает."""
    from .models import ProductionStage, ProductionUnit

    created = 0
    for code, (label, count) in DEFAULT_UNITS.items():
        stage = ProductionStage.objects.filter(code=code).first()
        if stage is None:
            continue
        for number in range(1, count + 1):
            _, made = ProductionUnit.objects.get_or_create(
                stage=stage,
                name=f"{label} {number}",
                defaults={"sequence": number},
            )
            created += int(made)
    return created
