from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from recipes.models import Recipe


class MealPlan(models.Model):
    start_date = models.DateField(verbose_name="開始日")
    user_request = models.TextField(blank=True, verbose_name="要望")
    ai_comment = models.TextField(blank=True, verbose_name="AIコメント")
    shopping_list = models.TextField(blank=True, verbose_name="買い物リスト")
    shopping_list_generated_at = models.DateTimeField(
        null=True, blank=True, verbose_name="買い物リスト生成日時"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "meal_plan"
        ordering = ["-start_date", "-created_at"]

    @property
    def total_days(self):
        covered = set()
        for slot in self.slots.all():
            covered.update(
                slot.start_date + timedelta(days=offset) for offset in range(slot.days)
            )
        return len(covered)

    @property
    def end_date(self):
        return self.start_date + timedelta(days=6)

    def __str__(self):
        return f"{self.start_date:%Y/%m/%d} の週間プラン"


class MealPlanSlot(models.Model):
    SLOT_TYPE_CHOICES = [("main", "主菜"), ("side", "副菜")]

    plan = models.ForeignKey(MealPlan, on_delete=models.CASCADE, related_name="slots")
    slot_type = models.CharField(
        max_length=10, choices=SLOT_TYPE_CHOICES, verbose_name="レーン"
    )
    order = models.PositiveIntegerField(verbose_name="順番")
    start_date = models.DateField(verbose_name="枠の開始日")
    days = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(7)], verbose_name="日数"
    )
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plan_slots",
        verbose_name="献立",
    )
    reason = models.CharField(max_length=200, blank=True, verbose_name="選定理由")

    class Meta:
        db_table = "meal_plan_slot"
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "slot_type", "order"],
                name="unique_plan_lane_slot_order",
            )
        ]

    def clean(self):
        max_days = 3 if self.slot_type == "main" else 7
        if not 1 <= self.days <= max_days:
            raise ValidationError(
                {"days": f"{self.get_slot_type_display()}は1〜{max_days}日です。"}
            )
        if not self.recipe_id:
            raise ValidationError("枠には献立が必要です。")

    @property
    def end_date(self):
        return self.start_date + timedelta(days=self.days - 1)

    @property
    def date_label(self):
        weekdays = "月火水木金土日"
        start = f"{self.start_date.month}/{self.start_date.day}({weekdays[self.start_date.weekday()]})"
        if self.days == 1:
            return start
        end = f"{self.end_date.month}/{self.end_date.day}({weekdays[self.end_date.weekday()]})"
        return f"{start}〜{end}"

    def __str__(self):
        return f"{self.plan} 枠{self.order}"
