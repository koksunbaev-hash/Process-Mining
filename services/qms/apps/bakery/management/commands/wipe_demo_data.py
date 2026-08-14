"""Очистка демонстрационных данных стенда.

Отдельной командой, а не разовым скриптом: удаление на боевом стенде должно
быть повторяемым, читаемым в истории и требовать явного подтверждения.

Порядок удаления — от ссылающихся к тем, на кого ссылаются. Партии идут
последними: `BatchStageHistory.batch` объявлен с `CASCADE`, поэтому вместе с
партией уходит вся её история этапов — а это тот самый след, из которого
строится карта процесса и считается прогноз. Заказы не трогаются: партия
ссылается на строку заказа через `PROTECT`, и заказы переживают удаление
партий сознательно — спрос это не то же самое, что производство.

События `ProcessEvent` тоже остаются: у них `SET_NULL` на партию, и они
представляют собой отдельный журнал для аналитики, а не отображение доски.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.models import AuditLog
from apps.bakery.models import (
    BatchStageHistory,
    FinishedGoodsStock,
    KanbanDemoRun,
    ProductionBatch,
    VoiceCommand,
    VoiceMessage,
)
from apps.nonconformities.models import CorrectiveAction, Nonconformity
from apps.notifications.models import Notification


class Command(BaseCommand):
    help = "Удаляет демонстрационные данные: партии, голосовые, журнал, проблемы, уведомления."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Выполнить удаление. Без флага команда только показывает, что будет удалено.",
        )
        parser.add_argument(
            "--keep-batches",
            action="store_true",
            help="Оставить партии и историю этапов — с ними уходит вся история выпуска.",
        )

    def handle(self, *args, **options):
        plan = [
            ("голосовые команды", VoiceCommand.objects.all()),
            ("голосовые сообщения", VoiceMessage.objects.all()),
            ("корректирующие действия", CorrectiveAction.objects.all()),
            ("проблемы", Nonconformity.objects.all()),
            ("журнал действий", AuditLog.objects.all()),
            ("уведомления", Notification.objects.all()),
            ("демо-запуски канбана", KanbanDemoRun.objects.all()),
        ]
        if not options["keep_batches"]:
            plan += [
                ("готовая продукция", FinishedGoodsStock.objects.all()),
                ("партии", ProductionBatch.objects.all()),
            ]

        history = 0 if options["keep_batches"] else BatchStageHistory.objects.count()

        self.stdout.write("Будет удалено:")
        for label, queryset in plan:
            self.stdout.write(f"  {label:26} {queryset.count()}")
        if history:
            self.stdout.write(self.style.WARNING(f"  {'история этапов (каскадом)':26} {history}"))

        if not options["yes"]:
            self.stdout.write(self.style.WARNING("\nЭто предварительный просмотр. Повторите с --yes."))
            return

        with transaction.atomic():
            for label, queryset in plan:
                count = queryset.count()
                if count:
                    queryset.delete()
                self.stdout.write(f"  {label:26} удалено {count}")

        self.stdout.write(self.style.SUCCESS("Готово."))
