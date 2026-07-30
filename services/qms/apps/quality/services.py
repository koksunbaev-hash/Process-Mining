from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import write_audit
from apps.inspections.models import InspectionTask
from apps.notifications.services import notify

from .models import QualityObject


@transaction.atomic
def create_quality_object_with_route(**data):
    user = data.pop("user", None)
    obj = QualityObject.objects.create(created_by=user, **data)
    if obj.route:
        first_step = obj.route.steps.filter(is_required=True).select_related("control_post", "inspection_template").first()
        if first_step:
            obj.current_route_step = first_step
            obj.current_control_post = first_step.control_post
            obj.quality_status = QualityObject.Status.AWAITING_CONTROL
            obj.save(update_fields=["current_route_step", "current_control_post", "quality_status", "updated_at"])
            create_inspection_task_for_step(obj, first_step, user=user, automatic=True)
    else:
        obj.quality_status = QualityObject.Status.CONTROL_NOT_REQUIRED
        obj.save(update_fields=["quality_status", "updated_at"])
    write_audit("create", obj, user=user)
    return obj


@transaction.atomic
def create_inspection_task_for_step(obj, step, user=None, automatic=True):
    active = InspectionTask.objects.filter(
        quality_object=obj,
        control_post=step.control_post,
        status__in=[InspectionTask.Status.NEW, InspectionTask.Status.ASSIGNED, InspectionTask.Status.IN_PROGRESS],
    ).exists()
    if active:
        raise ValidationError("У объекта уже есть активное задание этого поста.")
    task = InspectionTask.objects.create(
        quality_object=obj,
        control_post=step.control_post,
        inspection_template=step.inspection_template,
        assigned_to=step.control_post.responsible_user,
        due_at=timezone.now() + timedelta(minutes=step.normative_duration_minutes),
        status=InspectionTask.Status.ASSIGNED if step.control_post.responsible_user else InspectionTask.Status.NEW,
        created_automatically=automatic,
        created_by=user,
    )
    notify(task.assigned_to, "Назначено новое задание", task.task_number, "task_assigned", f"/tasks/{task.pk}/")
    write_audit("create", task, user=user)
    return task
