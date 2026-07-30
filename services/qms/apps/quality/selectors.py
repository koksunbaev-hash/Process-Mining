from .models import QualityObject


def quality_objects_list():
    return QualityObject.objects.select_related("department", "route", "current_control_post").prefetch_related("tasks")
