from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import MeasuringEquipment


@login_required
def equipment_list(request):
    equipment = MeasuringEquipment.objects.select_related("department", "responsible_user")
    status = request.GET.get("status")
    if status == "expired":
        equipment = [item for item in equipment if item.verification_expired]
    elif status == "soon":
        equipment = [item for item in equipment if item.verification_expiring_soon]
    elif status:
        equipment = equipment.filter(status=status)
    return render(request, "equipment/list.html", {"equipment": equipment})
