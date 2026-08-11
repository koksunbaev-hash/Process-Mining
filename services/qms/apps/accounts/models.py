from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    class Role(models.TextChoices):
        """Три роли вместо шестнадцати.

        Прежний список описывал должности хлебозавода - оператор замеса,
        оператор печи, контролёр ОТК, - и каждая новая проверка прав требовала
        перечислить, кто из шестнадцати её проходит. Списки разъезжались:
        технолог значился в READ_ALL_ROLES, но не в MANAGER_ROLES, а мастер не
        значился нигде, кроме отчётов.

        Три уровня отвечают на единственный вопрос, который на самом деле
        задавался: настраивает, распоряжается или работает. Кто именно стоит у
        печи, записано в имени пользователя и подразделении, а не в правах.
        """

        ADMIN = "admin", "Администратор"
        MANAGER = "manager", "Менеджер"
        USER = "user", "Сотрудник"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField("роль", max_length=32, choices=Role.choices, default=Role.USER)
    department = models.ForeignKey(
        "quality.Department", verbose_name="подразделение", on_delete=models.SET_NULL, null=True, blank=True
    )
    phone = models.CharField("телефон", max_length=64, blank=True)

    class Meta:
        verbose_name = "профиль пользователя"
        verbose_name_plural = "профили пользователей"

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"
