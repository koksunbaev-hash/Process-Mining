"""Шестнадцать ролей сводятся к трём.

Перевод задан перечислением, а не «всё, кроме админа, - в сотрудники»: молчаливо
понизить руководителя качества до сотрудника хуже, чем не собрать миграцию. То,
чего в списках нет (роль, заведённая руками прямо в базе), уходит в USER -
самый узкий уровень.
"""

from django.db import migrations, models


TO_MANAGER = [
    "production_dispatcher",
    "technologist",
    "manager",
    "director",
    "quality_manager",
    "quality_engineer",
]
TO_USER = [
    "mixing_operator",
    "forming_operator",
    "proofing_operator",
    "oven_operator",
    "warehouse_worker",
    "master",
    "executor",
    "inspector",
    "auditor",
]


def collapse(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    UserProfile.objects.filter(role__in=TO_MANAGER).update(role="manager")
    UserProfile.objects.filter(role__in=TO_USER).update(role="user")
    # Всё незнакомое - тоже в сотрудники: пустая или самодельная роль не должна
    # оставаться значением, которого нет в choices.
    UserProfile.objects.exclude(role__in=["admin", "manager", "user"]).update(role="user")


def uncollapse(apps, schema_editor):
    """Обратно не разворачивается - из «менеджера» не восстановить технолога.

    Откат оставляет три роли как есть: это честнее, чем назначить всем
    правдоподобную должность, которой у них не было.
    """


class Migration(migrations.Migration):

    dependencies = [("accounts", "0002_alter_userprofile_role")]

    operations = [
        migrations.RunPython(collapse, uncollapse),
        migrations.AlterField(
            model_name="userprofile",
            name="role",
            field=models.CharField(
                choices=[("admin", "Администратор"), ("manager", "Менеджер"), ("user", "Сотрудник")],
                default="user",
                max_length=32,
                verbose_name="роль",
            ),
        ),
    ]
