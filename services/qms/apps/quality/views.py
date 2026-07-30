from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import is_read_only_role
from apps.audit.models import StatusHistory

from .forms import QualityObjectForm
from .models import ControlRoute, QualityObject
from .selectors import quality_objects_list
from .services import create_quality_object_with_route


@login_required
def object_list(request):
    objects = quality_objects_list()
    if request.GET.get("status"):
        objects = objects.filter(quality_status=request.GET["status"])
    if request.GET.get("object_type"):
        objects = objects.filter(object_type=request.GET["object_type"])
    if request.GET.get("supplier"):
        objects = objects.filter(supplier__icontains=request.GET["supplier"])
    return render(request, "quality/object_list.html", {"objects": objects, "statuses": QualityObject.Status.choices, "types": QualityObject.ObjectType.choices})


@login_required
def object_create(request):
    if is_read_only_role(request.user):
        messages.error(request, "Ваша роль не позволяет создавать объекты контроля.")
        return redirect("quality:object_list")
    form = QualityObjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        data["user"] = request.user
        create_quality_object_with_route(**data)
        messages.success(request, "Объект контроля создан, первое задание сформировано автоматически.")
        return redirect("quality:object_list")
    return render(request, "quality/object_form.html", {"form": form})


@login_required
def object_detail(request, pk):
    obj = get_object_or_404(quality_objects_list(), pk=pk)
    history = StatusHistory.objects.filter(object_id=obj.pk, content_type__model="qualityobject")
    return render(request, "quality/object_detail.html", {"object": obj, "history": history})


@login_required
def routes_list(request):
    return render(request, "quality/routes.html", {"routes": ControlRoute.objects.prefetch_related("steps__control_post")})
