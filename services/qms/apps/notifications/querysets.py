from django.db.models import Q


def visible_notifications(queryset):
    demo_noise = (
        Q(notification_type="kanban_demo")
        | Q(title__icontains="DEMO-B-")
        | Q(message__icontains="DEMO-B-")
        | Q(title__icontains="Kanban demo")
        | Q(message__icontains="Kanban demo")
    )
    return queryset.exclude(demo_noise)
