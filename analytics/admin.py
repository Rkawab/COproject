from django.contrib import admin
from .models import PageView


@admin.register(PageView)
class PageViewAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "path", "ip_address", "referrer")
    list_filter = ("timestamp",)
    search_fields = ("path", "ip_address", "referrer")
    readonly_fields = ("timestamp", "path", "ip_address", "user_agent", "referrer")
