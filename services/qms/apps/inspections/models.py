from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class InspectionTask(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новое"
        ASSIGNED = "assigned", "Назначено"
        IN_PROGRESS = "in_progress", "В работе"
        OVERDUE = "overdue", "Просрочено"
        AWAITING_REINSPECTION = "awaiting_reinspection", "Ожидает повторного контроля"
        COMPLETED = "completed", "Завершено"
        CANCELLED = "cancelled", "Отменено"

    class Priority(models.TextChoices):
        LOW = "low", "Низкий"
        NORMAL = "normal", "Обычный"
        HIGH = "high", "Высокий"
        URGENT = "urgent", "Срочный"

    task_number = models.CharField("номер задания", max_length=40, unique=True, editable=False, db_index=True)
    quality_object = models.ForeignKey("quality.QualityObject", verbose_name="объект", on_delete=models.CASCADE, related_name="tasks")
    control_post = models.ForeignKey("quality.ControlPost", verbose_name="пост", on_delete=models.PROTECT)
    inspection_template = models.ForeignKey("quality.InspectionTemplate", verbose_name="шаблон", on_delete=models.PROTECT)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="исполнитель", on_delete=models.SET_NULL, null=True, blank=True, related_name="inspection_tasks"
    )
    priority = models.CharField("приоритет", max_length=16, choices=Priority.choices, default=Priority.NORMAL)
    planned_start = models.DateTimeField("плановое начало", null=True, blank=True)
    due_at = models.DateTimeField("срок", null=True, blank=True, db_index=True)
    started_at = models.DateTimeField("начато", null=True, blank=True)
    completed_at = models.DateTimeField("завершено", null=True, blank=True)
    status = models.CharField("статус", max_length=32, choices=Status.choices, default=Status.NEW, db_index=True)
    is_overdue = models.BooleanField("просрочено", default=False)
    created_automatically = models.BooleanField("создано автоматически", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="создал", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_inspection_tasks"
    )
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["quality_object", "control_post", "status"])]
        verbose_name = "задание на контроль"
        verbose_name_plural = "задания на контроль"

    def __str__(self):
        return self.task_number or "Новое задание"

    def save(self, *args, **kwargs):
        if not self.task_number:
            last_id = InspectionTask.objects.order_by("-id").values_list("id", flat=True).first() or 0
            self.task_number = f"QMS-TASK-{last_id + 1:06d}"
        if self.due_at and self.status not in {self.Status.COMPLETED, self.Status.CANCELLED}:
            self.is_overdue = self.due_at < timezone.now()
        super().save(*args, **kwargs)


class InspectionCard(models.Model):
    class Result(models.TextChoices):
        CONFORMING = "conforming", "Соответствует"
        CONFORMING_WITH_COMMENTS = "conforming_with_comments", "Соответствует с замечаниями"
        REINSPECTION_REQUIRED = "reinspection_required", "Требуется повторный контроль"
        CORRECTION_REQUIRED = "correction_required", "Требуется исправление"
        REJECTED = "rejected", "Забраковано"
        DEVIATION_APPROVED = "deviation_approved", "Отклонение разрешено"
        INCOMPLETE = "incomplete", "Не завершено"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        COMPLETED = "completed", "Завершена"
        APPROVED = "approved", "Утверждена"

    card_number = models.CharField("номер карты", max_length=40, unique=True, editable=False, db_index=True)
    task = models.OneToOneField(InspectionTask, verbose_name="задание", on_delete=models.CASCADE, related_name="card")
    quality_object = models.ForeignKey("quality.QualityObject", verbose_name="объект", on_delete=models.CASCADE, related_name="cards")
    control_post = models.ForeignKey("quality.ControlPost", verbose_name="пост", on_delete=models.PROTECT)
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="контролёр", on_delete=models.SET_NULL, null=True, blank=True)
    started_at = models.DateTimeField("начато", null=True, blank=True)
    completed_at = models.DateTimeField("завершено", null=True, blank=True)
    overall_result = models.CharField("результат", max_length=40, choices=Result.choices, default=Result.INCOMPLETE)
    comments = models.TextField("комментарий", blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="утвердил", on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_cards"
    )
    approved_at = models.DateTimeField("утверждено", null=True, blank=True)
    status = models.CharField("статус", max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "карта контроля"
        verbose_name_plural = "карты контроля"

    def __str__(self):
        return self.card_number or "Новая карта"

    def save(self, *args, **kwargs):
        if not self.card_number:
            last_id = InspectionCard.objects.order_by("-id").values_list("id", flat=True).first() or 0
            self.card_number = f"QMS-CARD-{last_id + 1:06d}"
        super().save(*args, **kwargs)


class InspectionResult(models.Model):
    inspection_card = models.ForeignKey(InspectionCard, verbose_name="карта", on_delete=models.CASCADE, related_name="results")
    template_parameter = models.ForeignKey("quality.InspectionTemplateParameter", verbose_name="параметр шаблона", on_delete=models.PROTECT)
    parameter = models.ForeignKey("quality.ControlParameter", verbose_name="параметр", on_delete=models.PROTECT)
    numeric_value = models.DecimalField("числовое значение", max_digits=12, decimal_places=3, null=True, blank=True)
    text_value = models.TextField("текст", blank=True)
    boolean_value = models.BooleanField("да/нет", null=True, blank=True)
    date_value = models.DateField("дата", null=True, blank=True)
    choice_value = models.CharField("выбор", max_length=160, blank=True)
    conformity_value = models.BooleanField("соответствует", null=True, blank=True)
    measuring_equipment = models.ForeignKey(
        "equipment.MeasuringEquipment", verbose_name="средство измерения", on_delete=models.PROTECT, null=True, blank=True
    )
    comment = models.TextField("комментарий", blank=True)
    is_within_tolerance = models.BooleanField("в допуске", null=True, blank=True, db_index=True)
    is_manual_override = models.BooleanField("ручное изменение", default=False)
    override_reason = models.TextField("причина override", blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    class Meta:
        ordering = ["template_parameter__sequence"]
        unique_together = ("inspection_card", "template_parameter")
        verbose_name = "результат измерения"
        verbose_name_plural = "результаты измерений"

    def __str__(self):
        return f"{self.inspection_card} - {self.parameter}"

    def clean(self):
        if self.measuring_equipment and not self.measuring_equipment.available_for_use:
            raise ValidationError("Нельзя использовать средство измерения с истёкшей поверкой или недоступным статусом.")
        if self.is_manual_override and not self.override_reason:
            raise ValidationError("Ручной override результата требует причины.")
        if self.parameter.value_type == "number" and self.numeric_value is not None:
            low = self.template_parameter.lower_limit
            high = self.template_parameter.upper_limit
            ok = True
            if low is not None and self.numeric_value < low:
                ok = False
            if high is not None and self.numeric_value > high:
                ok = False
            if not ok and not self.comment:
                raise ValidationError("При выходе за допуск требуется комментарий.")

    def save(self, *args, **kwargs):
        if self.parameter.value_type == "number" and self.numeric_value is not None:
            low = self.template_parameter.lower_limit
            high = self.template_parameter.upper_limit
            self.is_within_tolerance = True
            if low is not None and self.numeric_value < low:
                self.is_within_tolerance = False
            if high is not None and self.numeric_value > high:
                self.is_within_tolerance = False
        elif self.parameter.value_type in {"boolean", "conformity"}:
            value = self.conformity_value if self.parameter.value_type == "conformity" else self.boolean_value
            self.is_within_tolerance = bool(value)
        super().save(*args, **kwargs)


class InspectionAttachment(models.Model):
    inspection_card = models.ForeignKey(InspectionCard, verbose_name="карта", on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField("файл", upload_to="inspections/")
    file_type = models.CharField("тип файла", max_length=40)
    title = models.CharField("название", max_length=180, blank=True)
    comment = models.TextField("комментарий", blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="загрузил", on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField("загружено", auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "файл карты"
        verbose_name_plural = "файлы карт"


class Reinspection(models.Model):
    class Result(models.TextChoices):
        PASSED = "passed", "Положительно"
        FAILED = "failed", "Отрицательно"
        PENDING = "pending", "Ожидает"

    number = models.CharField("номер", max_length=40, unique=True, editable=False)
    nonconformity = models.ForeignKey("nonconformities.Nonconformity", verbose_name="несоответствие", on_delete=models.PROTECT, related_name="reinspections")
    quality_object = models.ForeignKey("quality.QualityObject", verbose_name="объект", on_delete=models.PROTECT)
    original_inspection_card = models.ForeignKey(InspectionCard, verbose_name="исходная карта", on_delete=models.PROTECT, related_name="original_reinspections")
    new_inspection_task = models.ForeignKey(InspectionTask, verbose_name="новое задание", on_delete=models.SET_NULL, null=True, blank=True)
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="контролёр", on_delete=models.SET_NULL, null=True, blank=True)
    result = models.CharField("результат", max_length=16, choices=Result.choices, default=Result.PENDING)
    comments = models.TextField("комментарий", blank=True)
    performed_at = models.DateTimeField("выполнено", null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "повторный контроль"
        verbose_name_plural = "повторный контроль"

    def save(self, *args, **kwargs):
        if not self.number:
            last_id = Reinspection.objects.order_by("-id").values_list("id", flat=True).first() or 0
            self.number = f"QMS-RE-{last_id + 1:06d}"
        super().save(*args, **kwargs)
