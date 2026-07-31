from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from planner.models import MealPlan
from recipes.models import Recipe


@login_required
def home(request):
    """今週のプランと最近の献立を表示するダッシュボード。"""
    today = timezone.localdate()
    active_plan = None
    for plan in MealPlan.objects.filter(start_date__lte=today).prefetch_related(
        "slots__recipe"
    ):
        if today <= plan.end_date:
            active_plan = plan
            break

    home_slots = []
    current_main = None
    current_side = None
    if active_plan:
        for slot in active_plan.slots.all():
            is_today = slot.start_date <= today <= slot.end_date
            home_slots.append(
                {
                    "slot": slot,
                    "is_today": is_today,
                }
            )
            if is_today and slot.slot_type == "main":
                current_main = slot
            if is_today and slot.slot_type == "side":
                current_side = slot

    return render(
        request,
        "home.html",
        {
            "active_plan": active_plan,
            "home_slots": home_slots,
            "current_main": current_main,
            "current_side": current_side,
            "is_day_off": not current_main and not current_side,
            "recent_recipes": Recipe.objects.all()[:5],
            "today": today,
        },
    )
