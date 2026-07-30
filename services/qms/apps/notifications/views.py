from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .querysets import visible_notifications


@login_required
def list_view(request):
    return render(request, "notifications/list.html", {"notifications": visible_notifications(request.user.notifications.all())})


@login_required
def mark_read(request, pk):
    if request.method == "POST":
        visible_notifications(request.user.notifications.filter(pk=pk)).update(is_read=True)
    return redirect("notifications:list")
