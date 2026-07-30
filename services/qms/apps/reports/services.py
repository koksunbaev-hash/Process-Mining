from dataclasses import dataclass
from datetime import date

from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone

from apps.equipment.models import MeasuringEquipment
from apps.inspections.models import InspectionCard
from apps.nonconformities.models import CorrectiveAction, Nonconformity

from . import selectors


@dataclass(frozen=True)
class ReportDefinition:
    slug: str
    title: str
    description: str
    icon: str


REPORTS = {
    "inspection-journal": ReportDefinition("inspection-journal", "Журнал контроля", "Карты контроля, задания, объекты, посты и результаты.", "JI"),
    "quality-history": ReportDefinition("quality-history", "История качества объекта", "Хронология контроля, статусов, несоответствий и действий по объекту.", "HQ"),
    "nonconformities": ReportDefinition("nonconformities", "Несоответствия", "Реестр дефектов, причин, решений, сроков и статусов.", "NC"),
    "overdue-nonconformities": ReportDefinition("overdue-nonconformities", "Просроченные несоответствия", "Открытые несоответствия с истёкшим сроком.", "OD"),
    "corrective-actions": ReportDefinition("corrective-actions", "Корректирующие действия", "Планы устранения причин и проверка эффективности.", "CA"),
    "equipment-verification": ReportDefinition("equipment-verification", "Средства измерений и поверка", "Состояние приборов, сроки поверки и доступность.", "ME"),
    "inspector-performance": ReportDefinition("inspector-performance", "Производительность контролёров", "Операционная статистика выполненных проверок.", "IP"),
    "first-pass-yield": ReportDefinition("first-pass-yield", "Прохождение контроля с первого раза", "First Pass Yield по объектам, постам и подразделениям.", "FP"),
}


def clean_filters(form):
    return form.cleaned_data if form.is_valid() else {}


def index_cards(user):
    empty = {}
    return [
        {
            "definition": definition,
            "count": report_count(slug, empty, user),
            "url": reverse("reports:detail", args=[slug]),
        }
        for slug, definition in REPORTS.items()
    ]


def report_count(slug, filters, user):
    if slug == "inspection-journal":
        return selectors.inspection_journal_queryset(filters, user).count()
    if slug == "quality-history":
        return selectors.objects_queryset(filters, user).count()
    if slug == "nonconformities":
        return selectors.nonconformities_queryset(filters, user).count()
    if slug == "overdue-nonconformities":
        return selectors.nonconformities_queryset(filters, user, overdue_only=True).count()
    if slug == "corrective-actions":
        return selectors.corrective_actions_queryset(filters, user).count()
    if slug == "equipment-verification":
        return selectors.equipment_queryset(filters, user).count()
    if slug == "inspector-performance":
        return len(selectors.inspector_performance_rows(filters, user))
    if slug == "first-pass-yield":
        return selectors.first_pass_data(filters, user)["total"]
    return 0


def build_report(slug, filters, user, page_number=1, paginate=True):
    builders = {
        "inspection-journal": build_inspection_journal,
        "quality-history": build_quality_history,
        "nonconformities": build_nonconformities,
        "overdue-nonconformities": build_overdue_nonconformities,
        "corrective-actions": build_corrective_actions,
        "equipment-verification": build_equipment_verification,
        "inspector-performance": build_inspector_performance,
        "first-pass-yield": build_first_pass_yield,
    }
    report = builders[slug](filters, user)
    rows = report["rows"]
    if paginate:
        paginator = Paginator(rows, 25)
        report["page_obj"] = paginator.get_page(page_number)
        report["rows_page"] = report["page_obj"].object_list
    else:
        report["rows_page"] = rows
    report["definition"] = REPORTS[slug]
    report["slug"] = slug
    return report


def build_inspection_journal(filters, user):
    qs = selectors.inspection_journal_queryset(filters, user)
    rows = []
    durations = []
    for card in qs:
        obj = card.quality_object
        if card.started_at and card.completed_at:
            durations.append((card.completed_at - card.started_at).total_seconds() / 60)
        rows.append([
            card.card_number,
            card.task.task_number,
            obj.unique_number,
            obj.get_object_type_display(),
            obj.batch_number,
            obj.serial_number,
            card.control_post.name,
            card.inspector.get_username() if card.inspector else "-",
            card.started_at,
            card.completed_at,
            card.get_overall_result_display(),
            card.get_status_display(),
        ])
    headers = ["Номер карты", "Номер задания", "Объект контроля", "Тип объекта", "Партия", "Серийный номер", "Пост", "Контролёр", "Дата начала", "Дата завершения", "Общий результат", "Статус"]
    summary = [
        ("Всего проверок", qs.count()),
        ("Соответствует", qs.filter(overall_result="conforming").count()),
        ("Не соответствует", qs.filter(overall_result__in=["correction_required", "rejected", "reinspection_required"]).count()),
        ("Незавершённые", qs.exclude(status="completed").count()),
        ("Средняя продолжительность", f"{round(sum(durations) / len(durations), 1) if durations else 0} мин"),
    ]
    return {"headers": headers, "rows": rows, "summary": summary}


def build_quality_history(filters, user):
    obj = filters.get("quality_object")
    rows = []
    summary = []
    if not obj:
        return {"headers": ["Дата", "Тип", "Документ", "Описание", "Статус"], "rows": rows, "summary": [("Выберите объект", "для построения истории")], "quality_object": None}
    allowed = selectors.objects_queryset({}, user).filter(pk=obj.pk).exists()
    if not allowed:
        return {"headers": ["Дата", "Тип", "Документ", "Описание", "Статус"], "rows": [], "summary": [("Нет доступа", obj.unique_number)], "quality_object": obj}
    rows.append([obj.created_at, "Объект", obj.unique_number, obj.product_name, obj.get_quality_status_display()])
    for task in obj.tasks.select_related("control_post").all():
        rows.append([task.created_at, "Задание", task.task_number, task.control_post.name, task.get_status_display()])
    for card in obj.cards.select_related("control_post").all():
        rows.append([card.created_at, "Карта контроля", card.card_number, card.control_post.name, card.get_overall_result_display()])
        for result in card.results.select_related("parameter").all():
            rows.append([result.created_at, "Результат", card.card_number, result.parameter.name, "OK" if result.is_within_tolerance else "Отклонение"])
    for nc in obj.nonconformities.select_related("defect_type").all():
        rows.append([nc.created_at, "Несоответствие", nc.number, nc.defect_type.name, nc.get_status_display()])
        for action in nc.corrective_actions.all():
            rows.append([action.created_at, "Корректирующее действие", action.number, action.title, action.get_status_display()])
        for reinspection in nc.reinspections.all():
            rows.append([reinspection.performed_at or timezone.now(), "Повторный контроль", reinspection.number, reinspection.comments, reinspection.get_result_display()])
    rows.sort(key=lambda item: item[0] or timezone.now())
    summary = [
        ("Объект", obj.unique_number),
        ("Продукция", obj.product_name),
        ("Партия", obj.batch_number or "-"),
        ("Серийный номер", obj.serial_number or "-"),
        ("Текущий пост", obj.current_control_post.name if obj.current_control_post else "-"),
        ("Статус качества", obj.get_quality_status_display()),
    ]
    return {"headers": ["Дата", "Тип события", "Документ", "Описание", "Статус"], "rows": rows, "summary": summary, "quality_object": obj}


def build_nonconformities(filters, user):
    qs = selectors.nonconformities_queryset(filters, user)
    rows = [nonconformity_row(item) for item in qs]
    headers = ["Номер", "Дата регистрации", "Объект", "Пост обнаружения", "Дефект", "Описание", "Критичность", "Количество", "Причина", "Подразделение", "Ответственный", "Срок", "Решение", "Статус", "Дата закрытия"]
    durations = [(item.closed_at - item.created_at).days for item in qs.exclude(closed_at__isnull=True)]
    summary = [
        ("Всего", qs.count()),
        ("Открытые", qs.exclude(status__in=["closed", "rejected"]).count()),
        ("Критические", qs.filter(criticality="critical").count()),
        ("Просроченные", qs.filter(due_at__lt=timezone.now()).exclude(status__in=["closed", "rejected"]).count()),
        ("Закрытые", qs.filter(status="closed").count()),
        ("Средний срок закрытия", f"{round(sum(durations) / len(durations), 1) if durations else 0} дн."),
    ]
    return {"headers": headers, "rows": rows, "summary": summary}


def build_overdue_nonconformities(filters, user):
    qs = selectors.nonconformities_queryset(filters, user, overdue_only=True)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    data = sorted(qs, key=lambda item: (severity_order.get(item.criticality, 9), -overdue_days(item.due_at)))
    rows = [[item.number, item.quality_object.unique_number, item.get_criticality_display(), item.responsible_user.get_username() if item.responsible_user else "-", item.due_at, overdue_days(item.due_at), item.get_status_display()] for item in data]
    summary = [
        ("Всего просроченных", len(rows)),
        ("Критических", sum(1 for item in data if item.criticality == "critical")),
        ("Больше 7 дней", sum(1 for item in data if overdue_days(item.due_at) > 7)),
        ("Больше 30 дней", sum(1 for item in data if overdue_days(item.due_at) > 30)),
    ]
    return {"headers": ["Номер", "Объект", "Критичность", "Ответственный", "Срок", "Дней просрочки", "Статус"], "rows": rows, "summary": summary}


def build_corrective_actions(filters, user):
    qs = selectors.corrective_actions_queryset(filters, user)
    rows = []
    for action in qs:
        nc = action.nonconformity
        rows.append([action.number, nc.number, nc.quality_object.unique_number, action.title, action.root_cause, action.get_root_cause_method_display(), action.assigned_to.get_username() if action.assigned_to else "-", action.created_at, action.due_at, action.completed_at, action.get_status_display(), action.effectiveness_result])
    summary = [
        ("Всего", qs.count()),
        ("Запланировано", qs.filter(status="planned").count()),
        ("В работе", qs.filter(status="in_progress").count()),
        ("Просрочено", qs.filter(due_at__lt=timezone.now()).exclude(status__in=["completed", "closed"]).count()),
        ("Проверка эффективности", qs.filter(status="effectiveness_check").count()),
        ("Закрыто", qs.filter(status="closed").count()),
    ]
    return {"headers": ["Номер", "Несоответствие", "Объект", "Действие", "Коренная причина", "Метод", "Ответственный", "Создано", "Срок", "Выполнено", "Статус", "Эффективность"], "rows": rows, "summary": summary}


def build_equipment_verification(filters, user):
    qs = selectors.equipment_queryset(filters, user)
    rows = []
    today = date.today()
    for item in qs:
        days = (item.next_verification_date - today).days if item.next_verification_date else None
        category = "Неактивен" if not item.is_active else "Просрочена" if item.verification_expired else "Скоро истекает" if item.verification_expiring_soon else "Действующая"
        rows.append([item.name, item.equipment_type, item.serial_number, item.inventory_number, item.department.name, item.responsible_user.get_username() if item.responsible_user else "-", item.last_verification_date, item.next_verification_date, days if days is not None else "-", item.get_status_display(), "Да" if item.available_for_use else "Нет", category])
    summary = [
        ("Всего приборов", qs.count()),
        ("Доступно", sum(1 for item in qs if item.available_for_use)),
        ("Скоро истекает", sum(1 for item in qs if item.verification_expiring_soon)),
        ("Просрочено", sum(1 for item in qs if item.verification_expired)),
        ("Неактивно", qs.filter(is_active=False).count()),
    ]
    return {"headers": ["Название", "Тип", "Заводской номер", "Инвентарный номер", "Подразделение", "Ответственный", "Последняя поверка", "Следующая поверка", "Дней до поверки", "Статус", "Можно использовать", "Категория"], "rows": rows, "summary": summary}


def build_inspector_performance(filters, user):
    data = selectors.inspector_performance_rows(filters, user)
    rows = [[item["inspector"].get_full_name() or item["inspector"].get_username(), item["department"].name if item["department"] else "-", item["completed"], item["conforming"], item["nonconformities"], item["avg_time"], item["overdue_tasks"], item["on_time_rate"]] for item in data]
    summary = [("Контролёров", len(rows)), ("Проверок", sum(item["completed"] for item in data)), ("Несоответствий", sum(item["nonconformities"] for item in data)), ("Среднее время", f"{round(sum(item['avg_time'] for item in data) / len(data), 1) if data else 0} мин")]
    return {"headers": ["Контролёр", "Подразделение", "Завершено", "Соответствует", "Выявлено НС", "Среднее время, мин", "Просрочено заданий", "Завершено в срок, %"], "rows": rows, "summary": summary, "note": "Показатели являются статистикой операций и не являются оценкой качества работы сотрудника без контекста."}


def build_first_pass_yield(filters, user):
    data = selectors.first_pass_data(filters, user)
    rows = [[obj.unique_number, obj.product_name, obj.get_object_type_display(), obj.department.name, obj.get_quality_status_display()] for obj in data["objects"]]
    summary = [("First Pass Yield", f"{data['percent']}%"), ("С первого раза", data["first_pass"]), ("Всего завершивших", data["total"]), ("Повторный контроль", data["need_reinspection"])]
    chart = {
        "labels": [item["control_post__name"] or "-" for item in data["by_post"]],
        "values": [max(item["total"] - item["bad"], 0) for item in data["by_post"]],
    }
    return {"headers": ["Объект", "Продукция", "Тип", "Подразделение", "Статус"], "rows": rows, "summary": summary, "chart": chart}


def nonconformity_row(item):
    return [
        item.number,
        item.created_at,
        item.quality_object.unique_number,
        item.control_post.name,
        item.defect_type.name,
        item.description,
        item.get_criticality_display(),
        item.affected_quantity,
        item.suspected_cause.name if item.suspected_cause else "-",
        item.responsible_department.name if item.responsible_department else "-",
        item.responsible_user.get_username() if item.responsible_user else "-",
        item.due_at,
        item.get_decision_display() if item.decision else "-",
        item.get_status_display(),
        item.closed_at,
    ]


def overdue_days(due_at):
    if not due_at:
        return 0
    delta = timezone.now() - due_at
    return max(delta.days, 0)
