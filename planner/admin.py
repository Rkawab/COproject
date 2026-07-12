from django.contrib import admin

from .models import MealPlan, MealPlanSlot


class MealPlanSlotInline(admin.TabularInline):
    model = MealPlanSlot
    extra = 0


@admin.register(MealPlan)
class MealPlanAdmin(admin.ModelAdmin):
    list_display = ("start_date", "created_at", "updated_at")
    inlines = [MealPlanSlotInline]
