from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import write_audit, write_status_history
from apps.notifications.services import notify
from apps.process_mining.services import safe_record_process_event
from apps.quality.models import QualityObject
from apps.quality.services import create_inspection_task_for_step

from .models import InspectionCard, InspectionResult, InspectionTask, Reinspection


@transaction.atomic
def start_task(task, user):
    if task.status == InspectionTask.Status.COMPLETED:
        raise ValidationError("Нельзя начать уже завершённое задание.")
    old_task_status = task.status
    task.status = InspectionTask.Status.IN_PROGRESS
    task.started_at = task.started_at or timezone.now()
    task.assigned_to = task.assigned_to or user
    task.save(update_fields=["status", "started_at", "assigned_to", "is_overdue"])
    write_status_history(task, old_task_status, task.status, user, "Начало контроля")

    obj = task.quality_object
    obj.set_status(QualityObject.Status.CONTROL_IN_PROGRESS, user, "Начато задание контроля")

    card, created = InspectionCard.objects.get_or_create(
        task=task,
        defaults={
            "quality_object": obj,
            "control_post": task.control_post,
            "inspector": user,
            "started_at": timezone.now(),
        },
    )
    if created:
        for template_parameter in task.inspection_template.parameters.select_related("parameter"):
            InspectionResult.objects.get_or_create(
                inspection_card=card,
                template_parameter=template_parameter,
                defaults={"parameter": template_parameter.parameter},
            )
        write_audit("create", card, user=user)
    return card


def validate_card_completion(card):
    errors = []
    results = card.results.select_related("parameter", "template_parameter", "measuring_equipment")
    result_by_tp = {result.template_parameter_id: result for result in results}
    for tp in card.task.inspection_template.parameters.select_related("parameter"):
        result = result_by_tp.get(tp.id)
        if tp.is_required:
            missing = not result or (
                result.numeric_value is None
                and not result.text_value
                and result.boolean_value is None
                and result.date_value is None
                and not result.choice_value
                and result.conformity_value is None
            )
            if missing:
                errors.append(f"Не заполнен обязательный параметр: {tp.parameter.name}")
        if tp.parameter.requires_photo and not card.attachments.exists():
            errors.append(f"Для параметра {tp.parameter.name} требуется фото.")
        if result:
            result.full_clean()
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def complete_card(card, user):
    if card.task.status == InspectionTask.Status.COMPLETED:
        raise ValidationError("Нельзя завершить задание дважды.")
    if card.quality_object.has_open_critical_nonconformity:
        raise ValidationError("Нельзя перейти дальше при открытом критическом дефекте.")
    validate_card_completion(card)
    bad_results = card.results.filter(is_within_tolerance=False).select_related("parameter")
    critical_bad = bad_results.filter(parameter__criticality="critical").exists()

    old_card_status = card.status
    card.completed_at = timezone.now()
    card.status = InspectionCard.Status.COMPLETED
    card.overall_result = (
        InspectionCard.Result.CORRECTION_REQUIRED if bad_results.exists() else InspectionCard.Result.CONFORMING
    )
    card.save(update_fields=["completed_at", "status", "overall_result", "updated_at"])
    write_status_history(card, old_card_status, card.status, user, "Завершение карты контроля")

    task = card.task
    old_task_status = task.status
    task.status = InspectionTask.Status.COMPLETED
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at", "is_overdue"])
    write_status_history(task, old_task_status, task.status, user, "Карта контроля завершена")

    obj = card.quality_object
    if bad_results.exists():
        obj.set_status(QualityObject.Status.BLOCKED if critical_bad else QualityObject.Status.CORRECTION_REQUIRED, user, "Отклонение по допускам")
        return card

    step = obj.current_route_step
    next_step = None
    if step:
        next_step = obj.route.steps.filter(sequence__gt=step.sequence, is_required=True).first()
    if next_step:
        obj.current_route_step = next_step
        obj.current_control_post = next_step.control_post
        obj.quality_status = QualityObject.Status.AWAITING_CONTROL
        obj.save(update_fields=["current_route_step", "current_control_post", "quality_status", "updated_at"])
        if step.create_next_task_automatically:
            create_inspection_task_for_step(obj, next_step, user=user, automatic=True)
    else:
        obj.set_status(QualityObject.Status.READY_FOR_SHIPMENT, user, "Маршрут контроля завершён")
    return card


@transaction.atomic
def create_reinspection(nonconformity, inspector=None, user=None):
    if not nonconformity:
        raise ValidationError("Нельзя проводить повторный контроль без исходного несоответствия.")
    card = nonconformity.inspection_card
    if not card:
        raise ValidationError("Для повторного контроля нужна исходная карта.")
    task = InspectionTask.objects.create(
        quality_object=nonconformity.quality_object,
        control_post=nonconformity.control_post,
        inspection_template=card.task.inspection_template,
        assigned_to=inspector,
        status=InspectionTask.Status.AWAITING_REINSPECTION,
        created_by=user,
    )
    reinspection = Reinspection.objects.create(
        nonconformity=nonconformity,
        quality_object=nonconformity.quality_object,
        original_inspection_card=card,
        new_inspection_task=task,
        inspector=inspector,
    )
    nonconformity.status = "awaiting_reinspection"
    nonconformity.save(update_fields=["status", "updated_at"])
    nonconformity.quality_object.set_status(QualityObject.Status.AWAITING_REINSPECTION, user, "Назначен повторный контроль")
    notify(inspector, "Требуется повторный контроль", reinspection.number, "reinspection", f"/tasks/{task.pk}/")
    safe_record_process_event(
        case_id=nonconformity.bakery_batch.batch_number if nonconformity.bakery_batch_id else reinspection.number,
        case_type="problem",
        activity="Создание повторной проверки",
        batch=nonconformity.bakery_batch,
        order=nonconformity.bakery_order,
        user=user,
        product=nonconformity.bakery_product,
        status=nonconformity.status,
        problem_type=nonconformity.defect_type.name,
        resource=inspector.username if inspector else "",
        event_data={"reinspection": reinspection.number},
    )
    return reinspection
