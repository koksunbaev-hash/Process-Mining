from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from .exporters.csv_exporter import export_csv
from .exporters.excel_exporter import export_excel
from .exporters.pdf_exporter import export_pdf
from .forms import BaseReportFilterForm
from .selectors import can_view_reports
from .services import REPORTS, build_report, index_cards


def require_reports_access(user):
    if not can_view_reports(user):
        raise PermissionDenied("У вашей роли нет доступа к разделу отчётов.")


@login_required
def index(request):
    require_reports_access(request.user)
    return render(request, "reports/index.html", {"report_cards": index_cards(request.user)})


@login_required
def detail(request, slug):
    require_reports_access(request.user)
    if slug not in REPORTS:
        raise PermissionDenied("Неизвестный отчёт.")
    form = BaseReportFilterForm(request.GET, report_slug=slug)
    filters = form.cleaned_data if form.is_valid() else {}
    if request.GET and not form.is_valid():
        messages.error(request, "Проверьте фильтры отчёта.")
    report = build_report(slug, filters, request.user, page_number=request.GET.get("page", 1), paginate=True)
    return render(request, "reports/report_detail.html", {"form": form, "report": report})


@login_required
def export(request, slug, fmt):
    require_reports_access(request.user)
    if slug not in REPORTS:
        raise PermissionDenied("Неизвестный отчёт.")
    form = BaseReportFilterForm(request.GET, report_slug=slug)
    if not form.is_valid():
        messages.error(request, "Экспорт невозможен: проверьте фильтры отчёта.")
        return redirect("reports:detail", slug=slug)
    report = build_report(slug, form.cleaned_data, request.user, paginate=False)
    if fmt == "csv":
        return export_csv(report)
    if fmt == "xlsx":
        return export_excel(report)
    if fmt == "pdf":
        return export_pdf(report)
    raise PermissionDenied("Неизвестный формат экспорта.")


@login_required
def export_csv_legacy(request, report):
    return export(request, report, "csv")
