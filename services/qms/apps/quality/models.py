from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    class Meta:
        abstract = True


class Department(models.Model):
    name = models.CharField("название", max_length=180)
    code = models.CharField("код", max_length=40, unique=True)
    is_active = models.BooleanField("активно", default=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "подразделение"
        verbose_name_plural = "подразделения"

    def __str__(self):
        return self.name


class ControlType(models.Model):
    name = models.CharField("название", max_length=160)
    code = models.CharField("код", max_length=40, unique=True)
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("активно", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "вид контроля"
        verbose_name_plural = "виды контроля"

    def __str__(self):
        return self.name


class ControlPost(models.Model):
    code = models.CharField("код", max_length=40, unique=True)
    name = models.CharField("название", max_length=220)
    department = models.ForeignKey(Department, verbose_name="подразделение", on_delete=models.PROTECT)
    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="ответственный", on_delete=models.SET_NULL, null=True, blank=True
    )
    control_type = models.ForeignKey(ControlType, verbose_name="вид контроля", on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField("последовательность", default=1, db_index=True)
    is_required = models.BooleanField("обязательный", default=True)
    is_active = models.BooleanField("активно", default=True)
    normative_duration_minutes = models.PositiveIntegerField("норматив, мин", default=60)
    escalation_minutes = models.PositiveIntegerField("эскалация, мин", default=120)
    description = models.TextField("описание", blank=True)

    class Meta:
        ordering = ["sequence", "name"]
        verbose_name = "пост контроля"
        verbose_name_plural = "посты контроля"

    def __str__(self):
        return self.name


class ControlParameter(models.Model):
    class ValueType(models.TextChoices):
        NUMBER = "number", "Число"
        TEXT = "text", "Текст"
        DATE = "date", "Дата"
        BOOLEAN = "boolean", "Да/нет"
        CHOICE = "choice", "Выбор"
        CONFORMITY = "conformity", "Соответствие"
        FILE = "file", "Файл"
        PHOTO = "photo", "Фото"
        CONCLUSION = "conclusion", "Заключение"

    class Criticality(models.TextChoices):
        LOW = "low", "Низкая"
        MEDIUM = "medium", "Средняя"
        HIGH = "high", "Высокая"
        CRITICAL = "critical", "Критическая"

    code = models.CharField("код", max_length=50, unique=True)
    name = models.CharField("название", max_length=220)
    unit = models.CharField("единица", max_length=40, blank=True)
    value_type = models.CharField("тип значения", max_length=24, choices=ValueType.choices)
    nominal_value = models.DecimalField("номинал", max_digits=12, decimal_places=3, null=True, blank=True)
    lower_limit = models.DecimalField("нижний допуск", max_digits=12, decimal_places=3, null=True, blank=True)
    upper_limit = models.DecimalField("верхний допуск", max_digits=12, decimal_places=3, null=True, blank=True)
    decimal_places = models.PositiveSmallIntegerField("знаков после запятой", default=2)
    is_required = models.BooleanField("обязательный", default=True)
    method = models.CharField("метод", max_length=220, blank=True)
    criticality = models.CharField("критичность", max_length=16, choices=Criticality.choices, default=Criticality.MEDIUM)
    instruction = models.TextField("инструкция", blank=True)
    requires_photo = models.BooleanField("требует фото", default=False)
    requires_double_check = models.BooleanField("двойная проверка", default=False)
    is_active = models.BooleanField("активно", default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "параметр контроля"
        verbose_name_plural = "параметры контроля"

    def __str__(self):
        return self.name

    def clean(self):
        if self.lower_limit is not None and self.upper_limit is not None and self.lower_limit > self.upper_limit:
            raise ValidationError("Нижний допуск не может быть больше верхнего.")


class NormativeDocument(TimestampedModel):
    title = models.CharField("название", max_length=220)
    number = models.CharField("номер", max_length=80)
    revision = models.CharField("ревизия", max_length=40, blank=True)
    effective_date = models.DateField("действует с", null=True, blank=True)
    expiration_date = models.DateField("действует до", null=True, blank=True)
    file = models.FileField("файл", upload_to="protocols/", blank=True)
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("активно", default=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "нормативный документ"
        verbose_name_plural = "нормативные документы"

    def __str__(self):
        return f"{self.number} {self.title}"


class InspectionTemplate(TimestampedModel):
    name = models.CharField("название", max_length=220)
    code = models.CharField("код", max_length=50, unique=True)
    control_post = models.ForeignKey(ControlPost, verbose_name="пост", on_delete=models.PROTECT)
    control_type = models.ForeignKey(ControlType, verbose_name="вид контроля", on_delete=models.PROTECT)
    product_type = models.CharField("тип продукции", max_length=120, blank=True)
    version = models.CharField("версия", max_length=30, default="1.0")
    is_active = models.BooleanField("активно", default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="утвердил", on_delete=models.SET_NULL, null=True, blank=True
    )
    approved_at = models.DateTimeField("утверждено", null=True, blank=True)

    class Meta:
        ordering = ["control_post__sequence", "name"]
        verbose_name = "шаблон карты контроля"
        verbose_name_plural = "шаблоны карт контроля"

    def __str__(self):
        return self.name


class InspectionTemplateParameter(models.Model):
    template = models.ForeignKey(InspectionTemplate, verbose_name="шаблон", on_delete=models.CASCADE, related_name="parameters")
    parameter = models.ForeignKey(ControlParameter, verbose_name="параметр", on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField("порядок", default=1)
    lower_limit_override = models.DecimalField("нижний допуск", max_digits=12, decimal_places=3, null=True, blank=True)
    upper_limit_override = models.DecimalField("верхний допуск", max_digits=12, decimal_places=3, null=True, blank=True)
    nominal_value_override = models.DecimalField("номинал", max_digits=12, decimal_places=3, null=True, blank=True)
    is_required_override = models.BooleanField("обязательный", null=True, blank=True)

    class Meta:
        ordering = ["sequence"]
        unique_together = ("template", "parameter")
        verbose_name = "параметр шаблона"
        verbose_name_plural = "параметры шаблона"

    def __str__(self):
        return f"{self.template}: {self.parameter}"

    @property
    def lower_limit(self):
        return self.lower_limit_override if self.lower_limit_override is not None else self.parameter.lower_limit

    @property
    def upper_limit(self):
        return self.upper_limit_override if self.upper_limit_override is not None else self.parameter.upper_limit

    @property
    def nominal_value(self):
        return self.nominal_value_override if self.nominal_value_override is not None else self.parameter.nominal_value

    @property
    def is_required(self):
        return self.is_required_override if self.is_required_override is not None else self.parameter.is_required


class ControlRoute(TimestampedModel):
    name = models.CharField("название", max_length=220)
    code = models.CharField("код", max_length=50, unique=True)
    product_type = models.CharField("тип продукции", max_length=120, blank=True)
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("активно", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "маршрут контроля"
        verbose_name_plural = "маршруты контроля"

    def __str__(self):
        return self.name


class ControlRouteStep(models.Model):
    route = models.ForeignKey(ControlRoute, verbose_name="маршрут", on_delete=models.CASCADE, related_name="steps")
    control_post = models.ForeignKey(ControlPost, verbose_name="пост", on_delete=models.PROTECT)
    inspection_template = models.ForeignKey(InspectionTemplate, verbose_name="шаблон", on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField("порядок", default=1)
    is_required = models.BooleanField("обязательный", default=True)
    normative_duration_minutes = models.PositiveIntegerField("норматив, мин", default=60)
    create_next_task_automatically = models.BooleanField("создавать следующее задание", default=True)

    class Meta:
        ordering = ["sequence"]
        unique_together = ("route", "sequence")
        verbose_name = "этап маршрута"
        verbose_name_plural = "этапы маршрута"

    def __str__(self):
        return f"{self.route} - {self.sequence}. {self.control_post}"


class QualityObject(TimestampedModel):
    class ObjectType(models.TextChoices):
        MATERIAL_BATCH = "material_batch", "Партия материалов"
        COMPONENT = "component", "Комплектующее"
        PART = "part", "Деталь"
        ASSEMBLY = "assembly", "Сборочная единица"
        SEMIFINISHED = "semifinished", "Полуфабрикат"
        MODULE = "module", "Модуль"
        FINISHED_PRODUCT = "finished_product", "Готовое изделие"
        PACKAGE = "package", "Упаковочная единица"

    class Status(models.TextChoices):
        CONTROL_NOT_REQUIRED = "control_not_required", "Контроль не требуется"
        AWAITING_CONTROL = "awaiting_control", "Ожидает контроля"
        CONTROL_IN_PROGRESS = "control_in_progress", "Контроль в работе"
        CONFORMING = "conforming", "Соответствует"
        CONFORMING_WITH_COMMENTS = "conforming_with_comments", "Соответствует с замечаниями"
        QUARANTINE = "quarantine", "Карантин"
        BLOCKED = "blocked", "Заблокирован"
        CORRECTION_REQUIRED = "correction_required", "Требуется исправление"
        AWAITING_REINSPECTION = "awaiting_reinspection", "Ожидает повторного контроля"
        REJECTED = "rejected", "Забракован"
        DEVIATION_APPROVED = "deviation_approved", "Разрешено отклонение"
        READY_FOR_SHIPMENT = "ready_for_shipment", "Готов к отгрузке"

    unique_number = models.CharField("уникальный номер", max_length=80, unique=True, db_index=True)
    object_type = models.CharField("тип объекта", max_length=32, choices=ObjectType.choices)
    product_name = models.CharField("наименование", max_length=220)
    product_code = models.CharField("код продукции", max_length=80, blank=True)
    characteristic = models.CharField("характеристика", max_length=220, blank=True)
    batch_number = models.CharField("партия", max_length=80, blank=True, db_index=True)
    serial_number = models.CharField("серийный номер", max_length=80, blank=True, db_index=True)
    quantity = models.DecimalField("количество", max_digits=12, decimal_places=3, default=1)
    unit = models.CharField("единица", max_length=30, default="шт")
    supplier = models.CharField("поставщик", max_length=180, blank=True)
    manufacturer = models.CharField("изготовитель", max_length=180, blank=True)
    production_date = models.DateField("дата производства", null=True, blank=True)
    receipt_date = models.DateField("дата поступления", null=True, blank=True)
    department = models.ForeignKey(Department, verbose_name="подразделение", on_delete=models.PROTECT)
    warehouse = models.CharField("склад", max_length=120, blank=True)
    related_document_number = models.CharField("документ", max_length=120, blank=True)
    route = models.ForeignKey(ControlRoute, verbose_name="маршрут", on_delete=models.SET_NULL, null=True, blank=True)
    current_route_step = models.ForeignKey(
        ControlRouteStep, verbose_name="текущий этап", on_delete=models.SET_NULL, null=True, blank=True
    )
    current_control_post = models.ForeignKey(
        ControlPost, verbose_name="текущий пост", on_delete=models.SET_NULL, null=True, blank=True
    )
    quality_status = models.CharField("статус качества", max_length=40, choices=Status.choices, default=Status.AWAITING_CONTROL, db_index=True)
    barcode = models.CharField("штрихкод", max_length=120, blank=True)
    qr_code = models.CharField("QR-код", max_length=120, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "объект контроля"
        verbose_name_plural = "объекты контроля"

    def __str__(self):
        return f"{self.unique_number} - {self.product_name}"

    def set_status(self, new_status, user=None, reason=""):
        old = self.quality_status
        self.quality_status = new_status
        self.save(update_fields=["quality_status", "updated_at"])
        if old != new_status:
            from apps.audit.services import write_status_history

            write_status_history(self, old, new_status, user, reason)

    @property
    def has_open_critical_nonconformity(self):
        return self.nonconformities.filter(criticality="critical").exclude(status__in=["closed", "rejected"]).exists()
