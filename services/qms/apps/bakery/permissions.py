from rest_framework.permissions import SAFE_METHODS, BasePermission


ADMIN_ROLES = {"admin"}
DISPATCHER_ROLES = {"admin", "production_dispatcher"}
TECH_ROLES = {"admin", "technologist"}
MANAGER_ROLES = {"admin", "production_dispatcher", "manager", "director", "quality_manager"}
READ_ALL_ROLES = MANAGER_ROLES | {"auditor", "technologist"}
STAGE_ROLES = {
    "mixing": {"admin", "production_dispatcher", "mixing_operator"},
    "forming": {"admin", "production_dispatcher", "forming_operator"},
    "proofing": {"admin", "production_dispatcher", "proofing_operator"},
    "oven": {"admin", "production_dispatcher", "oven_operator"},
    "warehouse": {"admin", "production_dispatcher", "warehouse_worker"},
    "queue": {"admin", "production_dispatcher"},
    "done": {"admin", "production_dispatcher", "warehouse_worker"},
}


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
    user_role = role(user)
    if user_role in MANAGER_ROLES:
        return True
    if stage_code:
        return user_role in STAGE_ROLES.get(stage_code, set())
    return user_role in set().union(*STAGE_ROLES.values())


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
        return role(request.user) not in {"auditor"}
