"""Правка этапов производства - то, чем распоряжается менеджер.

Этапы задают колонки доски и порядок, по которому партия едет дальше
(`next_stage_for` смотрит на `sequence`), поэтому правки здесь дороже обычных
справочников и обставлены двумя условиями.

Первое: этап нельзя выключить, пока на нём стоят партии. Выключенный этап
пропадает из `kanban_context`, а партии на нём остаются с ссылкой на него -
колонки нет, партии не видно, и найти её можно только в списке.

Второе: `sequence` уникален, поэтому перестановка идёт через свободное
значение. Прямой обмен местами упал бы на ограничении базы уже на первом
UPDATE - оба этапа на миг оказались бы с одним номером.
"""

from django.db import transaction
from django.db.models import Max

from .models import ProductionStage


class StageError(Exception):
    """Правка отклонена по смыслу, а не по форме."""


def rename_stages(posted):
    """Названия из формы. Код и порядок не трогаются: код читают интеграции."""
    changed = 0
    for stage in ProductionStage.objects.all():
        name = (posted.get(f"stage_name_{stage.pk}") or "").strip()
        if name and name != stage.name:
            stage.name = name[:80]
            stage.save(update_fields=["name"])
            changed += 1
    return changed


def set_stage_active(stage, is_active):
    if not is_active:
        held = stage.batches.count()
        if held:
            raise StageError(
                f"Этап «{stage.name}» нельзя выключить: на нём стоят партии ({held}). "
                "Сначала переведите их дальше."
            )
        if ProductionStage.objects.filter(is_active=True).exclude(pk=stage.pk).count() < 2:
            raise StageError("Должно остаться хотя бы два включённых этапа - иначе доске не из чего строить колонки.")
    if stage.is_active == is_active:
        return False
    stage.is_active = is_active
    stage.save(update_fields=["is_active"])
    return True


@transaction.atomic
def move_stage(stage, direction):
    """Поменять этап местами с соседним. direction: -1 вверх, +1 вниз."""
    neighbours = ProductionStage.objects.order_by("sequence")
    if direction < 0:
        neighbour = neighbours.filter(sequence__lt=stage.sequence).last()
    else:
        neighbour = neighbours.filter(sequence__gt=stage.sequence).first()
    if neighbour is None:
        raise StageError(f"Этап «{stage.name}» уже крайний.")

    free = (ProductionStage.objects.aggregate(top=Max("sequence"))["top"] or 0) + 1
    here, there = stage.sequence, neighbour.sequence
    rows = ProductionStage.objects.all()
    rows.filter(pk=stage.pk).update(sequence=free)
    rows.filter(pk=neighbour.pk).update(sequence=here)
    rows.filter(pk=stage.pk).update(sequence=there)
    stage.sequence, neighbour.sequence = there, here
    return neighbour
