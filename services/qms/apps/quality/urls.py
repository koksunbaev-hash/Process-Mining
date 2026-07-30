from django.urls import path

from . import views

app_name = "quality"

urlpatterns = [
    path("", views.object_list, name="object_list"),
    path("new/", views.object_create, name="object_create"),
    path("<int:pk>/", views.object_detail, name="object_detail"),
    path("routes/", views.routes_list, name="routes"),
]
