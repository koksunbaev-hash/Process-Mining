def unread_notifications(request):
    from .querysets import visible_notifications

    if request.user.is_authenticated:
        return {"unread_notifications_count": visible_notifications(request.user.notifications.filter(is_read=False)).count()}
    return {"unread_notifications_count": 0}
