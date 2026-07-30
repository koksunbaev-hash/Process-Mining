from .models import Notification


def notify(recipient, title, message, notification_type="info", related_url=""):
    if not recipient:
        return None
    return Notification.objects.create(
        recipient=recipient,
        title=title,
        message=message,
        notification_type=notification_type,
        related_url=related_url,
    )
