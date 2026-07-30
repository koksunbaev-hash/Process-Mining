from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class DefectType(models.Model):
    class Criticality(models.TextChoices):
        LOW = "low", "Низкая"
        MEDIUM = "medium", "Средняя"
        HIGH = "high", "Высокая"
        CRITICAL = "critical", "Критическая"

    code = models.CharField("код", max_length=50, unique=True)
    name = models.CharField("название", max_length=220)
    category = models.CharField("категория", max_length=120, blank=True)
    criticality = models.CharField("критичность", max_length=16, choices=Criticality.choices, default=Criticality.MEDIUM)
    description = models.TextField("описание", blank=True)
    repair_allowed = models.BooleanField("ремонт разрешён", default=True)
    process_stop_required = models.BooleanField("остановка процесса", default=False)
    manager_notification_required = models.BooleanField("уведомить руководителя", default=False)
    object_block_required = models.BooleanField("блокировка объекта", default=False)
    recommended_action = models.TextField("рекомендуемое действие", blank=True)
    is_active = models.BooleanField("активно", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "тип дефекта"
        verbose_name_plural = "типы дефектов"

    def __str__(self):
        return self.name


class NonconformityCause(models.Model):
    name = models.CharField("название", max_length=180)
    category = models.CharField("категория", max_length=120)
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("активно", default=True)

    class Meta:
        ordering = ["category", "name"]
        verbose_name = "причина несоответствия"
        verbose_name_plural = "причины несоответствий"

    def __str__(self):
        return self.name


class Nonconformity(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "registered", "Зарегистрировано"
        UNDER_REVIEW = "under_review", "На рассмотрении"
        ASSIGNED = "assigned", "Назначено"
        CAUSE_ANALYSIS = "cause_analysis", "Анализ причины"
        CORRECTION_IN_PROGRESS = "correction_in_progress", "Исправление"
        AWAITING_REINSPECTION = "awaiting_reinspection", "Ожидает повторного контроля"
        RESOLVED = "resolved", "Решено"
        CLOSED = "closed", "Закрыто"
        REJECTED = "rejected", "Отклонено"
        OVERDUE = "overdue", "Просрочено"

    class Decision(models.TextChoices):
        CORRECTION = "correction", "Исправление"
        REWORK = "rework", "Доработка"
        REPAIR = "repair", "Ремонт"
        REINSPECTION = "reinspection", "Повторный контроль"
        SORTING = "sorting", "Сортировка"
        SUPPLIER_RETURN = "supplier_return", "Возврат поставщику"
        WRITE_OFF = "write_off", "Списание"
        FINAL_REJECTION = "final_rejection", "Окончательный брак"
        DEVIATION_USE = "deviation_use", "Использование по отклонению"
        STOP_PRODUCTION = "stop_production", "Остановить производство"
        QUARANTINE = "quarantine", "Карантин"

    number = models.CharField("номер", max_length=40, unique=True, editable=False, db_index=True)
    quality_object = models.ForeignKey("quality.QualityObject", verbose_name="объект", on_delete=models.PROTECT, related_name="nonconformities")
    bakery_order = models.ForeignKey("bakery.ProductionOrder", verbose_name="заказ хлебозавода", on_delete=models.SET_NULL, null=True, blank=True, related_name="nonconformities")
    bakery_batch = models.ForeignKey("bakery.ProductionBatch", verbose_name="производственная партия", on_delete=models.SET_NULL, null=True, blank=True, related_name="nonconformities")
    bakery_product = models.ForeignKey("bakery.Product", verbose_name="продукт", on_delete=models.SET_NULL, null=True, blank=True, related_name="nonconformities")
    bakery_stage = models.ForeignKey("bakery.ProductionStage", verbose_name="этап производства", on_delete=models.SET_NULL, null=True, blank=True, related_name="nonconformities")
    inspection_card = models.ForeignKey("inspections.InspectionCard", verbose_name="карта", on_delete=models.SET_NULL, null=True, blank=True, related_name="nonconformities")
    control_post = models.ForeignKey("quality.ControlPost", verbose_name="пост", on_delete=models.PROTECT)
    detected_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="выявил", on_delete=models.SET_NULL, null=True, blank=True, related_name="detected_nonconformities")
    defect_type = models.ForeignKey(DefectType, verbose_name="тип дефекта", on_delete=models.PROTECT)
    description = models.TextField("описание")
    criticality = models.CharField("критичность", max_length=16, choices=DefectType.Criticality.choices)
    affected_quantity = models.DecimalField("количество", max_digits=12, decimal_places=3, default=1)
    suspected_cause = models.ForeignKey(NonconformityCause, verbose_name="предполагаемая причина", on_delete=models.SET_NULL, null=True, blank=True)
    responsible_department = models.ForeignKey("quality.Department", verbose_name="ответственное подразделение", on_delete=models.SET_NULL, null=True, blank=True)
    responsible_user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="ответственный", on_delete=models.SET_NULL, null=True, blank=True, related_name="nonconformities")
    due_at = models.DateTimeField("срок", null=True, blank=True)
    decision = models.CharField("решение", max_length=32, choices=Decision.choices, blank=True)
    status = models.CharField("статус", max_length=40, choices=Status.choices, default=Status.REGISTERED, db_index=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="закрыл", on_delete=models.SET_NULL, null=True, blank=True, related_name="closed_nonconformities")
    closed_at = models.DateTimeField("закрыто", null=True, blank=True)
    approved_by_quality_manager = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="подтвердил руководитель качества", on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_critical_nonconformities")
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "несоответствие"
        verbose_name_plural = "несоответствия"

    def __str__(self):
        return self.number or "Новое несоответствие"

    def save(self, *args, **kwargs):
        if not self.number:
            last_id = Nonconformity.objects.order_by("-id").values_list("id", flat=True).first() or 0
            self.number = f"QMS-NC-{last_id + 1:06d}"
        if not self.criticality and self.defect_type_id:
            self.criticality = self.defect_type.criticality
        super().save(*args, **kwargs)

    def clean(self):
        if self.status == self.Status.CLOSED and self.criticality == "critical" and not self.approved_by_quality_manager:
            raise ValidationError("Критическое несоответствие нельзя закрыть без подтверждения руководителя качества.")

    def delete(self, *args, **kwargs):
        if self.status in {self.Status.RESOLVED, self.Status.CLOSED}:
            raise ValidationError("Проведённое или закрытое несоответствие нельзя удалить.")
        return super().delete(*args, **kwargs)


class NonconformityAttachment(models.Model):
    nonconformity = models.ForeignKey(Nonconformity, verbose_name="несоответствие", on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField("файл", upload_to="defects/")
    attachment_type = models.CharField("тип", max_length=40)
    comment = models.TextField("комментарий", blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="загрузил", on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField("загружено", auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "файл несоответствия"
        verbose_name_plural = "файлы несоответствий"


class CorrectiveAction(models.Model):
    class RootCauseMethod(models.TextChoices):
        FIVE_WHYS = "five_whys", "5 Why"
        CAUSE_DIAGRAM = "cause_diagram", "Диаграмма причин"
        EXPERT_OPINION = "expert_opinion", "Экспертная оценка"

    class Status(models.TextChoices):
        PLANNED = "planned", "Запланировано"
        ASSIGNED = "assigned", "Назначено"
        IN_PROGRESS = "in_progress", "В работе"
        COMPLETED = "completed", "Выполнено"
        EFFECTIVENESS_CHECK = "effectiveness_check", "Проверка эффективности"
        CLOSED = "closed", "Закрыто"
        OVERDUE = "overdue", "Просрочено"

    number = models.CharField("номер", max_length=40, unique=True, editable=False)
    nonconformity = models.ForeignKey(Nonconformity, verbose_name="несоответствие", on_delete=models.CASCADE, related_name="corrective_actions")
    title = models.CharField("название", max_length=220)
    temporary_action = models.TextField("временное действие", blank=True)
    root_cause = models.TextField("коренная причина", blank=True)
    root_cause_method = models.CharField("метод анализа", max_length=32, choices=RootCauseMethod.choices, default=RootCauseMethod.FIVE_WHYS)
    action_plan = models.TextField("план действий")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="исполнитель", on_delete=models.SET_NULL, null=True, blank=True)
    due_at = models.DateTimeField("срок", null=True, blank=True)
    completed_at = models.DateTimeField("выполнено", null=True, blank=True)
    effectiveness_result = models.TextField("результат эффективности", blank=True)
    status = models.CharField("статус", max_length=32, choices=Status.choices, default=Status.PLANNED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_corrective_actions")
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "корректирующее действие"
        verbose_name_plural = "корректирующие действия"

    def __str__(self):
        return self.number or self.title

    def save(self, *args, **kwargs):
        if not self.number:
            last_id = CorrectiveAction.objects.order_by("-id").values_list("id", flat=True).first() or 0
            self.number = f"QMS-CA-{last_id + 1:06d}"
        super().save(*args, **kwargs)
