from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from recipes.models import Recipe


class MealPlan(models.Model):
    start_date = models.DateField(verbose_name="開始日")
    user_request = models.TextField(blank=True, verbose_name="要望")
    ai_comment = models.TextField(blank=True, verbose_name="AIコメント")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "meal_plan"
        ordering = ["-start_date", "-created_at"]

    @property
    def total_days(self):
        return sum(slot.days for slot in self.slots.all())

    @property
    def end_date(self):
        return self.start_date + timedelta(days=6)

    def __str__(self):
        return f"{self.start_date:%Y/%m/%d} の週間プラン"


class MealPlanSlot(models.Model):
    plan = models.ForeignKey(MealPlan, on_delete=models.CASCADE, related_name="slots")
    order = models.PositiveIntegerField(verbose_name="順番")
    start_date = models.DateField(verbose_name="枠の開始日")
    days = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(3)], verbose_name="日数"
    )
    main_recipe = models.ForeignKey(
        Recipe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="main_plan_slots",
        verbose_name="主菜",
    )
    side_recipe = models.ForeignKey(
        Recipe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="side_plan_slots",
        verbose_name="副菜",
    )
    reason = models.CharField(max_length=200, blank=True, verbose_name="選定理由")

    class Meta:
        db_table = "meal_plan_slot"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "order"], name="unique_plan_slot_order"
            )
        ]

    def clean(self):
        if not self.main_recipe_id or not self.side_recipe_id:
            raise ValidationError("枠には主菜と副菜が必要です。")

    @property
    def end_date(self):
        return self.start_date + timedelta(days=self.days - 1)

    @property
    def date_label(self):
        if self.days == 1:
            return self.start_date.strftime("%m/%d")
        return f"{self.start_date:%m/%d}〜{self.end_date:%m/%d}"

    def __str__(self):
        return f"{self.plan} 枠{self.order}"
