from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        PRODUCTION_DISPATCHER = "production_dispatcher", "Диспетчер производства"
        TECHNOLOGIST = "technologist", "Технолог"
        MIXING_OPERATOR = "mixing_operator", "Оператор замеса"
        FORMING_OPERATOR = "forming_operator", "Оператор формовки"
        PROOFING_OPERATOR = "proofing_operator", "Оператор расстойки"
        OVEN_OPERATOR = "oven_operator", "Оператор печи"
        WAREHOUSE_WORKER = "warehouse_worker", "Складской сотрудник"
        MANAGER = "manager", "Руководитель"
        AUDITOR = "auditor", "Аудитор"
        QUALITY_MANAGER = "quality_manager", "Руководитель службы качества"
        QUALITY_ENGINEER = "quality_engineer", "Инженер по качеству"
        INSPECTOR = "inspector", "Контролёр ОТК"
        MASTER = "master", "Производственный мастер"
        EXECUTOR = "executor", "Ответственный исполнитель"
        DIRECTOR = "director", "Руководитель предприятия"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField("роль", max_length=32, choices=Role.choices, default=Role.MIXING_OPERATOR)
    department = models.ForeignKey(
        "quality.Department", verbose_name="подразделение", on_delete=models.SET_NULL, null=True, blank=True
    )
    phone = models.CharField("телефон", max_length=64, blank=True)

    class Meta:
        verbose_name = "профиль пользователя"
        verbose_name_plural = "профили пользователей"

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

    @property
    def is_read_only(self):
        return self.role in {self.Role.AUDITOR, self.Role.DIRECTOR}

    def can_edit_quality(self):
        return self.role in {
            self.Role.ADMIN,
            self.Role.PRODUCTION_DISPATCHER,
            self.Role.TECHNOLOGIST,
            self.Role.MIXING_OPERATOR,
            self.Role.FORMING_OPERATOR,
            self.Role.PROOFING_OPERATOR,
            self.Role.OVEN_OPERATOR,
            self.Role.WAREHOUSE_WORKER,
            self.Role.QUALITY_MANAGER,
            self.Role.QUALITY_ENGINEER,
            self.Role.INSPECTOR,
            self.Role.MASTER,
        }
