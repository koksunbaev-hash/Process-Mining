import uuid

from django.conf import settings
from django.db import models


class ProcessEvent(models.Model):
    class CaseType(models.TextChoices):
        BATCH = "batch", "партия"
        ORDER = "order", "заказ"
        PROBLEM = "problem", "проблема"
        SHIPMENT = "shipment", "отгрузка"

    class ExportStatus(models.TextChoices):
        PENDING = "pending", "ожидает"
        PROCESSING = "processing", "обработка"
        SENT = "sent", "отправлено"
        FAILED = "failed", "ошибка"
        DEAD_LETTER = "dead_letter", "dead letter"

    event_id = models.UUIDField("event_id", default=uuid.uuid4, unique=True, editable=False, db_index=True)
    case_id = models.CharField("case_id", max_length=120, db_index=True)
    case_type = models.CharField("тип процесса", max_length=40, choices=CaseType.choices, db_index=True)
    activity = models.CharField("действие", max_length=180)
    occurred_at = models.DateTimeField("произошло", db_index=True)
    batch = models.ForeignKey("bakery.ProductionBatch", verbose_name="партия", on_delete=models.SET_NULL, null=True, blank=True, related_name="process_events")
    order = models.ForeignKey("bakery.ProductionOrder", verbose_name="заказ", on_delete=models.SET_NULL, null=True, blank=True, related_name="process_events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", on_delete=models.SET_NULL, null=True, blank=True, related_name="process_events")
    product = models.ForeignKey("bakery.Product", verbose_name="продукт", on_delete=models.SET_NULL, null=True, blank=True, related_name="process_events")
    from_stage = models.CharField("от этапа", max_length=80, blank=True)
    to_stage = models.CharField("к этапу", max_length=80, blank=True)
    status = models.CharField("статус бизнес-объекта", max_length=80, blank=True)
    quantity = models.DecimalField("количество", max_digits=14, decimal_places=3, null=True, blank=True)
    unit = models.CharField("единица", max_length=20, blank=True)
    problem_type = models.CharField("тип проблемы", max_length=180, blank=True)
    resource = models.CharField("ресурс", max_length=180, blank=True)
    event_data = models.JSONField("metadata", default=dict, blank=True)
    export_status = models.CharField("статус экспорта", max_length=24, choices=ExportStatus.choices, default=ExportStatus.PENDING, db_index=True)
    export_attempts = models.PositiveIntegerField("попытки", default=0)
    export = models.ForeignKey("ProcessEventExport", verbose_name="экспорт", on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    exported_at = models.DateTimeField("отправлено", null=True, blank=True)
    last_attempt_at = models.DateTimeField("последняя попытка", null=True, blank=True)
    last_error = models.TextField("последняя ошибка", blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["occurred_at", "id"]
        indexes = [
            models.Index(fields=["case_id", "occurred_at"]),
            models.Index(fields=["export_status", "created_at"]),
        ]
        verbose_name = "событие Process Mining"
        verbose_name_plural = "события Process Mining"

    def __str__(self):
        return f"{self.case_id}: {self.activity}"


class ProcessEventExport(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "создан"
        SENDING = "sending", "отправляется"
        ACCEPTED = "accepted", "принят"
        PARTIALLY_ACCEPTED = "partially_accepted", "частично принят"
        FAILED = "failed", "ошибка"

    export_id = models.UUIDField("export_id", default=uuid.uuid4, unique=True, editable=False, db_index=True)
    status = models.CharField("статус", max_length=32, choices=Status.choices, default=Status.CREATED, db_index=True)
    events_count = models.PositiveIntegerField("событий", default=0)
    file_name = models.CharField("имя файла", max_length=180, blank=True)
    checksum = models.CharField("SHA-256", max_length=64, blank=True)
    attempts = models.PositiveIntegerField("попытки", default=0)
    response_status_code = models.PositiveIntegerField("HTTP статус", null=True, blank=True)
    response_body = models.TextField("ответ", blank=True)
    csv_content = models.TextField("последний CSV", blank=True)
    started_at = models.DateTimeField("начато", null=True, blank=True)
    finished_at = models.DateTimeField("завершено", null=True, blank=True)
    last_error = models.TextField("последняя ошибка", blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "экспорт Process Mining"
        verbose_name_plural = "экспорты Process Mining"

    def __str__(self):
        return str(self.export_id)
