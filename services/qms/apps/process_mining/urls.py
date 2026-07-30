from django.urls import path

from . import views

app_name = "process_mining"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("last-csv/", views.download_last_csv, name="download_last_csv"),
]
