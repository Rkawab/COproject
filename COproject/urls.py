from django.contrib import admin
from django.urls import path, include
from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("recipes/", include("recipes.urls")),
    path("analytics/", include("analytics.urls")),
    path("", views.home, name="home"),
]
