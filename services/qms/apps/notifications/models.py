from django.conf import settings
from django.db import models


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="получатель", on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField("заголовок", max_length=180)
    message = models.TextField("сообщение")
    notification_type = models.CharField("тип", max_length=50)
    related_url = models.CharField("ссылка", max_length=240, blank=True)
    is_read = models.BooleanField("прочитано", default=False, db_index=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления"

    def __str__(self):
        return self.title
