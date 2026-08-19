from django.apps import AppConfig


class BakeryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bakery"
    verbose_name = "Хлебозавод"

    def ready(self):
        # Сигналы, которые держат цифровые двойники оборудования в курсе
        # происходящего на доске. Модуль подключает их при импорте.
        from . import twins  # noqa: F401
