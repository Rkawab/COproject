from django.contrib import admin
from .models import Recipe, Ingredient, Step, NutritionCache


class IngredientInline(admin.TabularInline):
    model = Ingredient
    extra = 1
    fields = ("name", "quantity", "unit", "amount_text", "group")


class StepInline(admin.TabularInline):
    model = Step
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("name", "genre1", "genre2", "genre3", "servings", "created_at")
    list_filter = ("genre1", "genre2")
    search_fields = ("name",)
    inlines = [IngredientInline, StepInline]


@admin.register(NutritionCache)
class NutritionCacheAdmin(admin.ModelAdmin):
    list_display = ("recipe_name", "calories", "protein", "fat", "carbs", "salt", "fetched_at")
