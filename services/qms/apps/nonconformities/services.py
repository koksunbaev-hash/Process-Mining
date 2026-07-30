from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import write_audit, write_status_history
from apps.notifications.services import notify
from apps.process_mining.services import safe_record_process_event
from apps.quality.models import QualityObject

from .models import CorrectiveAction, Nonconformity


@transaction.atomic
def register_nonconformity(**data):
    user = data.pop("user", None)
    nc = Nonconformity.objects.create(detected_by=user, **data)
    write_audit("create", nc, user=user)
    safe_record_process_event(
        case_id=nc.bakery_batch.batch_number if nc.bakery_batch_id else nc.number,
        case_type="problem",
        activity="Создание проблемы",
        batch=nc.bakery_batch,
        order=nc.bakery_order,
        user=user,
        product=nc.bakery_product,
        to_stage=nc.bakery_stage.code if nc.bakery_stage_id else "",
        status=nc.status,
        quantity=nc.affected_quantity,
        problem_type=nc.defect_type.name,
        event_data={"nonconformity": nc.number, "criticality": nc.criticality},
    )
    if nc.criticality == "critical" or nc.defect_type.object_block_required:
        nc.quality_object.set_status(QualityObject.Status.BLOCKED, user, "Критическое несоответствие")
        notify(nc.responsible_user, "Критическое несоответствие", nc.number, "critical_nonconformity", f"/nonconformities/{nc.pk}/")
    else:
        nc.quality_object.set_status(QualityObject.Status.CORRECTION_REQUIRED, user, "Зарегистрировано несоответствие")
    return nc


@transaction.atomic
def assign_corrective_action(nonconformity, **data):
    user = data.pop("user", None)
    action = CorrectiveAction.objects.create(nonconformity=nonconformity, created_by=user, **data)
    old = nonconformity.status
    nonconformity.status = Nonconformity.Status.ASSIGNED
    nonconformity.save(update_fields=["status", "updated_at"])
    write_status_history(nonconformity, old, nonconformity.status, user, "Назначено корректирующее действие")
    safe_record_process_event(
        case_id=nonconformity.bakery_batch.batch_number if nonconformity.bakery_batch_id else nonconformity.number,
        case_type="problem",
        activity="Назначение ответственного за проблему",
        batch=nonconformity.bakery_batch,
        order=nonconformity.bakery_order,
        user=user,
        product=nonconformity.bakery_product,
        status=nonconformity.status,
        problem_type=nonconformity.defect_type.name,
        resource=action.assigned_to.username if action.assigned_to_id else "",
        event_data={"action": action.number},
    )
    notify(action.assigned_to, "Назначено корректирующее действие", action.number, "corrective_action", f"/nonconformities/{nonconformity.pk}/")
    return action


@transaction.atomic
def complete_corrective_action(action, user, result=""):
    old_action_status = action.status
    action.status = CorrectiveAction.Status.COMPLETED
    action.completed_at = timezone.now()
    action.effectiveness_result = result
    action.save(update_fields=["status", "completed_at", "effectiveness_result"])
    write_status_history(action, old_action_status, action.status, user, "Действие выполнено")
    nc = action.nonconformity
    old_nc_status = nc.status
    nc.status = Nonconformity.Status.AWAITING_REINSPECTION
    nc.save(update_fields=["status", "updated_at"])
    write_status_history(nc, old_nc_status, nc.status, user, "Ожидает повторного контроля")
    nc.quality_object.set_status(QualityObject.Status.AWAITING_REINSPECTION, user, "Выполнено корректирующее действие")
    return action


@transaction.atomic
def close_nonconformity(nonconformity, user):
    if nonconformity.criticality == "critical":
        role = getattr(getattr(user, "profile", None), "role", "")
        if role not in {"admin", "quality_manager"} and not user.is_superuser:
            raise ValidationError("Критическое несоответствие закрывает только руководитель качества или администратор.")
        nonconformity.approved_by_quality_manager = user
    old = nonconformity.status
    nonconformity.status = Nonconformity.Status.CLOSED
    nonconformity.closed_by = user
    nonconformity.closed_at = timezone.now()
    nonconformity.full_clean()
    nonconformity.save(update_fields=["status", "closed_by", "closed_at", "approved_by_quality_manager", "updated_at"])
    write_status_history(nonconformity, old, nonconformity.status, user, "Несоответствие закрыто")
    safe_record_process_event(
        case_id=nonconformity.bakery_batch.batch_number if nonconformity.bakery_batch_id else nonconformity.number,
        case_type="problem",
        activity="Закрытие проблемы",
        batch=nonconformity.bakery_batch,
        order=nonconformity.bakery_order,
        user=user,
        product=nonconformity.bakery_product,
        status=nonconformity.status,
        problem_type=nonconformity.defect_type.name,
        event_data={"closed_at": nonconformity.closed_at.isoformat() if nonconformity.closed_at else ""},
    )
    return nonconformity
