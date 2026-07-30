from django.urls import path

from . import views

app_name = "inspections"

urlpatterns = [
    path("", views.task_list, name="task_list"),
    path("<int:pk>/", views.task_detail, name="task_detail"),
    path("<int:pk>/start/", views.task_start, name="task_start"),
    path("cards/", views.card_list, name="card_list"),
    path("cards/<int:pk>/", views.card_detail, name="card_detail"),
    path("cards/<int:pk>/save/", views.card_save, name="card_save"),
    path("cards/<int:pk>/complete/", views.card_complete, name="card_complete"),
]
