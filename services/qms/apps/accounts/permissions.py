from rest_framework.permissions import SAFE_METHODS, BasePermission


def user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return "admin"
    return getattr(getattr(user, "profile", None), "role", None)


def is_read_only_role(user):
    """Роль, которой можно только смотреть. Сейчас такой нет.

    До сведения к трём ролям это были аудитор и директор. Ни один из трёх
    уровней - администратор, менеджер, сотрудник - смотреть-но-не-трогать не
    означает, поэтому функция всегда отвечает «нет».

    Она оставлена, а вызовы в inspections, nonconformities и quality не тронуты,
    потому что здесь единственное место, куда возвращать проверку, если
    read-only роль понадобится снова. Убрать её - значит разнести это решение
    по семи видам в четырёх приложениях.
    """
    return False


class RolePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return not is_read_only_role(request.user)
