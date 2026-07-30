from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class StatusHistory(models.Model):
    content_type = models.ForeignKey(ContentType, verbose_name="тип объекта", on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField("ID объекта")
    content_object = GenericForeignKey("content_type", "object_id")
    previous_status = models.CharField("предыдущий статус", max_length=80, blank=True)
    new_status = models.CharField("новый статус", max_length=80)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="изменил", on_delete=models.SET_NULL, null=True, blank=True)
    changed_at = models.DateTimeField("изменено", auto_now_add=True)
    reason = models.TextField("причина", blank=True)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name = "история статуса"
        verbose_name_plural = "история статусов"


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField("действие", max_length=80)
    model_name = models.CharField("модель", max_length=120)
    object_id = models.CharField("ID объекта", max_length=80, blank=True)
    object_repr = models.CharField("объект", max_length=240, blank=True)
    changes = models.JSONField("изменения", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "запись аудита"
        verbose_name_plural = "журнал аудита"
