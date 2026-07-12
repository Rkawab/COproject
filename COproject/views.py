from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from planner.models import MealPlan
from recipes.models import Recipe


@login_required
def home(request):
    """今週のプランと最近の献立を表示するダッシュボード。"""
    today = date.today()
    active_plan = None
    for plan in MealPlan.objects.filter(start_date__lte=today).prefetch_related(
        "slots__main_recipe", "slots__side_recipe"
    ):
        if today <= plan.end_date:
            active_plan = plan
            break

    home_slots = []
    is_day_off = False
    if active_plan:
        for slot in active_plan.slots.all():
            home_slots.append(
                {
                    "slot": slot,
                    "is_today": slot.start_date <= today <= slot.end_date,
                }
            )
        is_day_off = not any(item["is_today"] for item in home_slots)

    return render(
        request,
        "home.html",
        {
            "active_plan": active_plan,
            "home_slots": home_slots,
            "is_day_off": is_day_off,
            "recent_recipes": Recipe.objects.all()[:5],
            "today": today,
        },
    )
