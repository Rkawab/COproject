from django.urls import path

from . import views

app_name = "planner"

urlpatterns = [
    path("", views.plan_list, name="list"),
    path("suggest/", views.plan_suggest, name="suggest"),
    path("<int:pk>/", views.plan_detail, name="detail"),
    path("<int:pk>/slots/<int:slot_pk>/", views.slot_update, name="slot_update"),
    path("<int:pk>/shopping-list/", views.shopping_list_generate, name="shopping_list"),
    path("<int:pk>/delete/", views.plan_delete, name="delete"),
]
