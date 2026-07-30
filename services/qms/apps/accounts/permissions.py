from rest_framework.permissions import SAFE_METHODS, BasePermission


def user_role(user):
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return "admin"
    return getattr(getattr(user, "profile", None), "role", None)


def is_read_only_role(user):
    return user_role(user) in {"auditor", "director"}


class RolePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return not is_read_only_role(request.user)
