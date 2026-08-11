from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.equipment.models import MeasuringEquipment
from apps.inspections.models import InspectionCard, InspectionTask, Reinspection
from apps.nonconformities.models import CorrectiveAction, Nonconformity
from apps.quality.models import Department, QualityObject


FULL_REPORT_ROLES = {
    UserProfile.Role.ADMIN,
    UserProfile.Role.MANAGER,
}


def user_role(user):
    if user.is_superuser:
        return UserProfile.Role.ADMIN
    return getattr(getattr(user, "profile", None), "role", None)


def can_view_reports(user):
    return user.is_authenticated and user_role(user) in {*FULL_REPORT_ROLES, UserProfile.Role.USER}


def restrict_queryset(queryset, user, base):
    """Менеджер видит всё, сотрудник - только своё.

    Раньше сужение было разным у контролёра ОТК (свои карточки), мастера (своё
    подразделение) и исполнителя (свои действия). Этих ролей не осталось, и
    сужение свелось к одному правилу - «то, что назначено мне или заведено
    мной». Подразделение из профиля больше не участвует: мастер, для которого
    это писалось, теперь неотличим от оператора, и фильтр по цеху показывал бы
    оператору чужие карточки вместо своих.
    """
    role = user_role(user)
    if role in FULL_REPORT_ROLES:
        return queryset
    if base == "cards":
        return queryset.filter(Q(inspector=user) | Q(task__assigned_to=user))
    if base == "tasks":
        return queryset.filter(assigned_to=user)
    if base == "nonconformities":
        return queryset.filter(Q(detected_by=user) | Q(inspection_card__inspector=user))
    if base == "actions":
        return queryset.filter(assigned_to=user)
    # Оборудование и объекты качества сужать не по чему: они ни на кого не
    # назначены. Сотруднику отчёт по ним не показывается вовсе.
    return queryset.none()


def apply_date_filter(qs, field_name, filters):
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if date_from:
        qs = qs.filter(**{f"{field_name}__date__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{field_name}__date__lte": date_to})
    return qs


def inspection_journal_queryset(filters, user):
    qs = InspectionCard.objects.select_related(
        "task", "quality_object", "quality_object__department", "control_post", "inspector"
    ).order_by("-created_at")
    qs = restrict_queryset(qs, user, "cards")
    qs = apply_date_filter(qs, "created_at", filters)
    if filters.get("department"):
        qs = qs.filter(quality_object__department=filters["department"])
    if filters.get("control_post"):
        qs = qs.filter(control_post=filters["control_post"])
    if filters.get("inspector"):
        qs = qs.filter(inspector=filters["inspector"])
    if filters.get("quality_object"):
        qs = qs.filter(quality_object=filters["quality_object"])
    if filters.get("batch_number"):
        qs = qs.filter(quality_object__batch_number__icontains=filters["batch_number"])
    if filters.get("result"):
        qs = qs.filter(overall_result=filters["result"])
    if filters.get("status"):
        qs = qs.filter(status=filters["status"])
    return qs


def nonconformities_queryset(filters, user, overdue_only=False):
    qs = Nonconformity.objects.select_related(
        "quality_object", "control_post", "defect_type", "suspected_cause", "responsible_department", "responsible_user"
    ).order_by("-created_at")
    qs = restrict_queryset(qs, user, "nonconformities")
    if overdue_only:
        qs = qs.filter(due_at__lt=timezone.now()).exclude(status__in=["closed", "rejected"])
    else:
        qs = apply_date_filter(qs, "created_at", filters)
    if filters.get("department"):
        qs = qs.filter(responsible_department=filters["department"])
    if filters.get("control_post"):
        qs = qs.filter(control_post=filters["control_post"])
    if filters.get("defect_type"):
        qs = qs.filter(defect_type=filters["defect_type"])
    if filters.get("cause"):
        qs = qs.filter(suspected_cause=filters["cause"])
    if filters.get("criticality"):
        qs = qs.filter(criticality=filters["criticality"])
    if filters.get("responsible"):
        qs = qs.filter(responsible_user=filters["responsible"])
    if filters.get("decision"):
        qs = qs.filter(decision=filters["decision"])
    if filters.get("status"):
        qs = qs.filter(status=filters["status"])
    return qs


def corrective_actions_queryset(filters, user):
    qs = CorrectiveAction.objects.select_related(
        "nonconformity", "nonconformity__quality_object", "nonconformity__responsible_department", "assigned_to"
    ).order_by("-created_at")
    qs = restrict_queryset(qs, user, "actions")
    qs = apply_date_filter(qs, "created_at", filters)
    if filters.get("department"):
        qs = qs.filter(nonconformity__responsible_department=filters["department"])
    if filters.get("responsible"):
        qs = qs.filter(assigned_to=filters["responsible"])
    if filters.get("status"):
        qs = qs.filter(status=filters["status"])
    if filters.get("root_cause_method"):
        qs = qs.filter(root_cause_method=filters["root_cause_method"])
    if filters.get("overdue") is True:
        qs = qs.filter(due_at__lt=timezone.now()).exclude(status__in=["completed", "closed"])
    return qs


def equipment_queryset(filters, user):
    qs = MeasuringEquipment.objects.select_related("department", "responsible_user").order_by("next_verification_date", "name")
    qs = restrict_queryset(qs, user, "equipment")
    if filters.get("department"):
        qs = qs.filter(department=filters["department"])
    if filters.get("responsible"):
        qs = qs.filter(responsible_user=filters["responsible"])
    if filters.get("status"):
        qs = qs.filter(status=filters["status"])
    if filters.get("overdue") is True:
        qs = qs.filter(next_verification_date__lt=timezone.localdate())
    return qs


def objects_queryset(filters, user):
    qs = QualityObject.objects.select_related("department", "route", "current_control_post").order_by("-created_at")
    qs = restrict_queryset(qs, user, "objects")
    if filters.get("department"):
        qs = qs.filter(department=filters["department"])
    if filters.get("control_post"):
        qs = qs.filter(current_control_post=filters["control_post"])
    if filters.get("object_type"):
        qs = qs.filter(object_type=filters["object_type"])
    if filters.get("product_name"):
        qs = qs.filter(product_name__icontains=filters["product_name"])
    if filters.get("batch_number"):
        qs = qs.filter(batch_number__icontains=filters["batch_number"])
    if filters.get("supplier"):
        qs = qs.filter(supplier__icontains=filters["supplier"])
    return apply_date_filter(qs, "created_at", filters)


def inspector_performance_rows(filters, user):
    User = get_user_model()
    users = User.objects.filter(inspectioncard__isnull=False).select_related("profile__department").distinct()
    if filters.get("inspector"):
        users = users.filter(pk=filters["inspector"].pk)
    if filters.get("department"):
        users = users.filter(profile__department=filters["department"])
    # Отчёт о работе контролёров: менеджер смотрит на всех, сотрудник - только
    # на себя. Сравнивать себя с соседями по цеху ему не полагалось и раньше.
    if user_role(user) not in FULL_REPORT_ROLES:
        users = users.filter(pk=user.pk)
    rows = []
    for inspector in users:
        cards = InspectionCard.objects.filter(inspector=inspector, status="completed")
        cards = apply_date_filter(cards, "completed_at", filters)
        if filters.get("control_post"):
            cards = cards.filter(control_post=filters["control_post"])
        completed = cards.count()
        conforming = cards.filter(overall_result="conforming").count()
        nc_count = Nonconformity.objects.filter(detected_by=inspector).count()
        overdue_tasks = InspectionTask.objects.filter(assigned_to=inspector, is_overdue=True).count()
        in_time = InspectionTask.objects.filter(assigned_to=inspector, status="completed", completed_at__lte=models_f("due_at")).count() if False else 0
        rows.append({
            "inspector": inspector,
            "department": getattr(getattr(inspector, "profile", None), "department", None),
            "completed": completed,
            "conforming": conforming,
            "nonconformities": nc_count,
            "avg_time": average_card_minutes(cards),
            "overdue_tasks": overdue_tasks,
            "on_time_rate": round(((completed - overdue_tasks) / completed) * 100, 1) if completed else 0,
        })
    return rows


def average_card_minutes(cards):
    total = 0
    count = 0
    for card in cards.exclude(started_at__isnull=True).exclude(completed_at__isnull=True):
        total += (card.completed_at - card.started_at).total_seconds() / 60
        count += 1
    return round(total / count, 1) if count else 0


def first_pass_data(filters, user):
    objects = objects_queryset(filters, user)
    completed = objects.filter(quality_status__in=["conforming", "ready_for_shipment", "conforming_with_comments", "deviation_approved"])
    total = completed.count()
    reinspection_object_ids = Reinspection.objects.values_list("quality_object_id", flat=True)
    nc_object_ids = Nonconformity.objects.values_list("quality_object_id", flat=True)
    failed_ids = set(reinspection_object_ids).union(set(nc_object_ids))
    first_pass = completed.exclude(id__in=failed_ids).count()
    need_reinspection = completed.filter(id__in=reinspection_object_ids).count()
    by_post = InspectionCard.objects.filter(quality_object__in=completed).values("control_post__name").annotate(total=Count("id"), bad=Count("nonconformities")).order_by("control_post__sequence")
    by_department = completed.values("department__name").annotate(total=Count("id")).order_by("department__name")
    return {
        "objects": completed,
        "total": total,
        "first_pass": first_pass,
        "need_reinspection": need_reinspection,
        "percent": round(first_pass / total * 100, 1) if total else 0,
        "by_post": list(by_post),
        "by_department": list(by_department),
    }
