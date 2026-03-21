from django.urls import path
from . import views

app_name = "recipes"

urlpatterns = [
    path("", views.recipe_list, name="list"),
    path("new/", views.recipe_create, name="create"),
    path("<int:pk>/", views.recipe_detail, name="detail"),
    path("<int:pk>/edit/", views.recipe_edit, name="edit"),
    path("<int:pk>/delete/", views.recipe_delete, name="delete"),
    path("<int:pk>/nutrition/", views.get_nutrition, name="nutrition"),
    path("read-image/", views.read_recipe_image, name="read_image"),
]
