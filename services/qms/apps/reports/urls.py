from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<slug:slug>/export/<slug:fmt>/", views.export, name="export"),
    path("export/<slug:report>/", views.export_csv_legacy, name="export_csv"),
]
