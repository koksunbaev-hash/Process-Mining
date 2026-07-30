from django import forms
from django.contrib.auth import get_user_model

from apps.equipment.models import MeasuringEquipment
from apps.inspections.models import InspectionCard
from apps.nonconformities.models import CorrectiveAction, DefectType, Nonconformity, NonconformityCause
from apps.quality.models import ControlPost, Department, QualityObject


class BaseReportFilterForm(forms.Form):
    date_from = forms.DateField(label="Дата от", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label="Дата до", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    department = forms.ModelChoiceField(label="Подразделение", required=False, queryset=Department.objects.none())
    control_post = forms.ModelChoiceField(label="Пост контроля", required=False, queryset=ControlPost.objects.none())
    quality_object = forms.ModelChoiceField(label="Объект контроля", required=False, queryset=QualityObject.objects.none())
    inspector = forms.ModelChoiceField(label="Контролёр", required=False, queryset=get_user_model().objects.none())
    responsible = forms.ModelChoiceField(label="Ответственный", required=False, queryset=get_user_model().objects.none())
    status = forms.ChoiceField(label="Статус", required=False, choices=())
    result = forms.ChoiceField(label="Результат", required=False, choices=())
    criticality = forms.ChoiceField(label="Критичность", required=False, choices=())
    defect_type = forms.ModelChoiceField(label="Вид дефекта", required=False, queryset=DefectType.objects.none())
    cause = forms.ModelChoiceField(label="Причина", required=False, queryset=NonconformityCause.objects.none())
    decision = forms.ChoiceField(label="Решение", required=False, choices=())
    root_cause_method = forms.ChoiceField(label="Метод анализа", required=False, choices=())
    object_type = forms.ChoiceField(label="Тип объекта", required=False, choices=())
    batch_number = forms.CharField(label="Партия", required=False)
    serial_number = forms.CharField(label="Серийный номер", required=False)
    supplier = forms.CharField(label="Поставщик", required=False)
    product_name = forms.CharField(label="Наименование продукции", required=False)
    overdue = forms.NullBooleanField(label="Только просроченные", required=False)

    def __init__(self, *args, report_slug=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.report_slug = report_slug
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["control_post"].queryset = ControlPost.objects.filter(is_active=True)
        self.fields["quality_object"].queryset = QualityObject.objects.all()
        self.fields["inspector"].queryset = User.objects.filter(inspection_tasks__isnull=False).distinct()
        self.fields["responsible"].queryset = User.objects.all()
        self.fields["defect_type"].queryset = DefectType.objects.filter(is_active=True)
        self.fields["cause"].queryset = NonconformityCause.objects.filter(is_active=True)
        self.fields["status"].choices = [("", "Все")] + self._status_choices(report_slug)
        self.fields["result"].choices = [("", "Все")] + list(InspectionCard.Result.choices)
        self.fields["criticality"].choices = [("", "Все")] + list(DefectType.Criticality.choices)
        self.fields["decision"].choices = [("", "Все")] + list(Nonconformity.Decision.choices)
        self.fields["root_cause_method"].choices = [("", "Все")] + list(CorrectiveAction.RootCauseMethod.choices)
        self.fields["object_type"].choices = [("", "Все")] + list(QualityObject.ObjectType.choices)
        self._limit_fields(report_slug)

    def _status_choices(self, slug):
        if slug in {"inspection-journal", "first-pass-yield"}:
            return list(InspectionCard.Status.choices)
        if slug in {"nonconformities", "overdue-nonconformities"}:
            return list(Nonconformity.Status.choices)
        if slug == "corrective-actions":
            return list(CorrectiveAction.Status.choices)
        if slug == "equipment-verification":
            return list(MeasuringEquipment.Status.choices)
        return list(QualityObject.Status.choices)

    def _limit_fields(self, slug):
        fields_by_report = {
            "inspection-journal": {"date_from", "date_to", "department", "control_post", "inspector", "quality_object", "batch_number", "result", "status"},
            "quality-history": {"quality_object"},
            "nonconformities": {"date_from", "date_to", "department", "control_post", "defect_type", "cause", "criticality", "responsible", "decision", "status"},
            "overdue-nonconformities": {"department", "control_post", "criticality", "responsible"},
            "corrective-actions": {"date_from", "date_to", "department", "responsible", "status", "root_cause_method", "overdue"},
            "equipment-verification": {"department", "responsible", "status", "overdue"},
            "inspector-performance": {"date_from", "date_to", "department", "control_post", "inspector"},
            "first-pass-yield": {"date_from", "date_to", "department", "control_post", "object_type", "product_name", "batch_number", "supplier"},
        }
        allowed = fields_by_report.get(slug, set(self.fields))
        for name in list(self.fields):
            if name not in allowed:
                self.fields.pop(name)

    def clean(self):
        cleaned = super().clean()
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError("Дата начала не может быть позже даты окончания.")
        return cleaned
