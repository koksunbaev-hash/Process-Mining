from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class MeasuringEquipment(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Доступно"
        REPAIR = "repair", "Ремонт"
        BLOCKED = "blocked", "Заблокировано"
        WRITTEN_OFF = "written_off", "Списано"

    name = models.CharField("название", max_length=220)
    equipment_type = models.CharField("тип", max_length=120)
    serial_number = models.CharField("серийный номер", max_length=120, unique=True)
    inventory_number = models.CharField("инвентарный номер", max_length=120, blank=True, db_index=True)
    department = models.ForeignKey("quality.Department", verbose_name="подразделение", on_delete=models.PROTECT)
    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="ответственный", on_delete=models.SET_NULL, null=True, blank=True
    )
    measurement_range = models.CharField("диапазон измерений", max_length=180, blank=True)
    accuracy_class = models.CharField("класс точности", max_length=80, blank=True)
    last_verification_date = models.DateField("последняя поверка", null=True, blank=True)
    next_verification_date = models.DateField("следующая поверка", null=True, blank=True, db_index=True)
    status = models.CharField("статус", max_length=24, choices=Status.choices, default=Status.AVAILABLE)
    certificate_file = models.FileField("свидетельство", upload_to="certificates/", blank=True)
    verification_organization = models.CharField("организация поверки", max_length=180, blank=True)
    notes = models.TextField("заметки", blank=True)
    is_active = models.BooleanField("активно", default=True)

    class Meta:
        ordering = ["next_verification_date", "name"]
        verbose_name = "средство измерения"
        verbose_name_plural = "средства измерений"

    def __str__(self):
        return f"{self.name} ({self.serial_number})"

    @property
    def verification_expired(self):
        return bool(self.next_verification_date and self.next_verification_date < timezone.localdate())

    @property
    def verification_expiring_soon(self):
        if not self.next_verification_date:
            return False
        today = timezone.localdate()
        return today <= self.next_verification_date <= today + timedelta(days=30)

    @property
    def available_for_use(self):
        return self.is_active and self.status == self.Status.AVAILABLE and not self.verification_expired
