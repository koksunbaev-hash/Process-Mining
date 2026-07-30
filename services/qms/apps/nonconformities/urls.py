from django.urls import path

from . import views

app_name = "nonconformities"

urlpatterns = [
    path("", views.nonconformity_list, name="list"),
    path("actions/", views.actions_list, name="actions"),
    path("<int:pk>/", views.nonconformity_detail, name="detail"),
    path("from-card/<int:card_id>/", views.create_from_card, name="create_from_card"),
    path("<int:pk>/assign-action/", views.assign_action, name="assign_action"),
    path("<int:pk>/close/", views.close_item, name="close"),
    path("<int:pk>/reinspection/", views.create_reinspection_view, name="create_reinspection"),
]
