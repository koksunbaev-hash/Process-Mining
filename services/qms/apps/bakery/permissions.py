"""Права пекарни на трёх ролях.

Раньше каждый этап держал свой список должностей: замес двигал оператор замеса,
печь - оператор печи. Ролей больше нет, и вместе с ними ушло разделение по
этапам - партию двигает любой вошедший. Смена всё равно записана: `move_batch`
пишет в `BatchStageHistory`, кто и когда перевёл, и эта запись - источник карты
процесса.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission


ADMIN_ROLES = {"admin"}
#: Распоряжаются: заказы, справочники, этапы, демо, чужие голосовые сообщения.
MANAGER_ROLES = {"admin", "manager"}
DISPATCHER_ROLES = MANAGER_ROLES
TECH_ROLES = MANAGER_ROLES
READ_ALL_ROLES = MANAGER_ROLES
ALL_ROLES = {"admin", "manager", "user"}


def role(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return "admin"
    return getattr(getattr(user, "profile", None), "role", None)


def can_manage_catalog(user):
    return role(user) in TECH_ROLES


def can_manage_orders(user):
    return role(user) in DISPATCHER_ROLES


def can_move_batch(user, stage_code=None):
    """Двигать партии может любая из трёх ролей.

    `stage_code` остался в сигнатуре: его передают виды и API, и по нему
    когда-то выбирался список должностей этапа. Сейчас он ни на что не влияет -
    но убрать параметр значит переписать шесть мест вызова ради нуля.
    """
    return role(user) in ALL_ROLES


def can_view_voice(user, voice):
    if role(user) in READ_ALL_ROLES:
        return True
    return voice.created_by_id == user.id or (
        voice.batch_id and voice.batch.assigned_to_id == user.id
    )


class BakeryPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        if view.basename in {"product", "ingredient", "recipe"}:
            return can_manage_catalog(request.user)
        # Раньше здесь отсекался аудитор - единственная роль, которой писать не
        # полагалось. Роли аудитора больше нет, и запрет вместе с ней ушёл.
        return role(request.user) in ALL_ROLES
