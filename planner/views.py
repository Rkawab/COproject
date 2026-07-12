from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from recipes.models import Recipe

from .models import MealPlan, MealPlanSlot
from .services import SuggestionError, calculate_nutrition_summary, generate_suggestion

DEFAULT_SCHEDULE = ("new", "continue", "new", "continue", "new", "continue", "new")
DAY_STATUS_CHOICES = (
    ("new", "作る"),
    ("continue", "前日の続き"),
    ("skip", "作らない"),
)
WEEKDAYS = "月火水木金土日"


def _default_start_date():
    today = date.today()
    return today - timedelta(days=today.weekday())


def build_day_rows(start_date, statuses=DEFAULT_SCHEDULE):
    return [
        {
            "index": index,
            "date": start_date + timedelta(days=index),
            "weekday": WEEKDAYS[(start_date + timedelta(days=index)).weekday()],
            "status": status,
        }
        for index, status in enumerate(statuses)
    ]


def parse_day_schedule(statuses, start_date):
    if len(statuses) != 7 or any(
        status not in {choice[0] for choice in DAY_STATUS_CHOICES}
        for status in statuses
    ):
        raise ValueError("7日分の選択を確認してください。")

    slots = []
    current_slot = None
    previous_status = None
    for index, status in enumerate(statuses):
        current_date = start_date + timedelta(days=index)
        if status == "new":
            current_slot = {
                "order": len(slots) + 1,
                "start_date": current_date,
                "days": 1,
            }
            slots.append(current_slot)
        elif status == "continue":
            if previous_status not in ("new", "continue") or current_slot is None:
                raise ValueError("「前日の続き」は、直前が作る日の場合のみ選べます。")
            if current_slot["days"] >= 3:
                raise ValueError("同じ献立を続ける期間は最大3日です。")
            current_slot["days"] += 1
        else:
            current_slot = None
        previous_status = status
    if not slots:
        raise ValueError("「作る」日を1日以上選んでください。")
    return slots


def _editable_slots(config, suggestion=None, request=None):
    suggested = {item["order"]: item for item in (suggestion or {}).get("slots", [])}
    result = []
    for slot in config:
        item = dict(slot)
        end_date = slot["start_date"] + timedelta(days=slot["days"] - 1)
        item["date_label"] = (
            slot["start_date"].strftime("%m/%d")
            if slot["start_date"] == end_date
            else f"{slot['start_date']:%m/%d}〜{end_date:%m/%d}"
        )
        ai_slot = suggested.get(slot["order"], {})
        item["main_id"] = ai_slot.get("main_id")
        item["side_id"] = ai_slot.get("side_id")
        item["reason"] = ai_slot.get("reason", "")
        if request and request.POST.get("action") == "save":
            item["main_id"] = request.POST.get(f"main_{slot['order']}") or None
            item["side_id"] = request.POST.get(f"side_{slot['order']}") or None
            item["reason"] = request.POST.get(f"reason_{slot['order']}", "")
        result.append(item)
    return result


@login_required
def plan_list(request):
    plans = MealPlan.objects.prefetch_related("slots")
    return render(request, "planner/list.html", {"plans": plans})


@login_required
def plan_suggest(request):
    mains = Recipe.objects.filter(genre2="主菜")
    sides = Recipe.objects.filter(genre2="副菜")
    start_date = _default_start_date()
    statuses = list(DEFAULT_SCHEDULE)
    context = {
        "start_date": start_date.isoformat(),
        "day_rows": build_day_rows(start_date, statuses),
        "day_status_choices": DAY_STATUS_CHOICES,
        "user_request": "",
        "mains": mains,
        "sides": sides,
        "slots": None,
        "week_comment": "",
    }
    if request.method != "POST":
        return render(request, "planner/suggest.html", context)

    try:
        start_date = date.fromisoformat(request.POST.get("start_date", ""))
    except (TypeError, ValueError):
        messages.error(request, "開始日を確認してください。")
        return render(request, "planner/suggest.html", context)

    statuses = [request.POST.get(f"day_{index}", "") for index in range(7)]
    context.update(
        {
            "start_date": start_date.isoformat(),
            "day_rows": build_day_rows(start_date, statuses),
            "user_request": request.POST.get("user_request", "").strip(),
        }
    )
    try:
        config = parse_day_schedule(statuses, start_date)
    except ValueError as exc:
        messages.error(request, str(exc))
        return render(request, "planner/suggest.html", context)

    action = request.POST.get("action")
    if action in ("generate", "regenerate"):
        try:
            suggestion = generate_suggestion(
                config, start_date=start_date, user_request=context["user_request"]
            )
        except SuggestionError as exc:
            messages.error(request, str(exc))
            context["slots"] = _editable_slots(config)
        else:
            context["slots"] = _editable_slots(config, suggestion)
            context["week_comment"] = suggestion["week_comment"]
        return render(request, "planner/suggest.html", context)

    if action == "save":
        slots = _editable_slots(config, request=request)
        context["slots"] = slots
        context["week_comment"] = request.POST.get("week_comment", "")
        try:
            with transaction.atomic():
                plan = MealPlan.objects.create(
                    start_date=start_date,
                    user_request=context["user_request"],
                    ai_comment=context["week_comment"],
                )
                for slot in slots:
                    main = Recipe.objects.get(pk=slot["main_id"], genre2="主菜")
                    side = Recipe.objects.get(pk=slot["side_id"], genre2="副菜")
                    plan_slot = MealPlanSlot(
                        plan=plan,
                        order=slot["order"],
                        start_date=slot["start_date"],
                        days=slot["days"],
                        main_recipe=main,
                        side_recipe=side,
                        reason=slot["reason"][:200],
                    )
                    plan_slot.full_clean()
                    plan_slot.save()
        except (Recipe.DoesNotExist, TypeError, ValueError, ValidationError) as exc:
            messages.error(request, f"枠の献立を確認してください。{exc}")
            return render(request, "planner/suggest.html", context)
        messages.success(request, "週間プランを保存しました。")
        return redirect("planner:detail", pk=plan.pk)

    messages.error(request, "操作を確認できませんでした。")
    return render(request, "planner/suggest.html", context)


@login_required
def plan_detail(request, pk):
    plan = get_object_or_404(
        MealPlan.objects.prefetch_related("slots__main_recipe", "slots__side_recipe"),
        pk=pk,
    )
    return render(
        request,
        "planner/detail.html",
        {
            "plan": plan,
            "nutrition": calculate_nutrition_summary(plan),
            "mains": Recipe.objects.filter(genre2="主菜"),
            "sides": Recipe.objects.filter(genre2="副菜"),
        },
    )


@login_required
def slot_update(request, pk, slot_pk):
    plan = get_object_or_404(MealPlan, pk=pk)
    slot = get_object_or_404(MealPlanSlot, pk=slot_pk, plan=plan)
    if request.method == "POST":
        slot.main_recipe = get_object_or_404(
            Recipe, pk=request.POST.get("main_recipe"), genre2="主菜"
        )
        slot.side_recipe = get_object_or_404(
            Recipe, pk=request.POST.get("side_recipe"), genre2="副菜"
        )
        try:
            slot.full_clean()
            slot.save()
        except ValidationError as exc:
            messages.error(request, f"枠を更新できませんでした。{exc}")
        else:
            messages.success(request, f"枠{slot.order}を更新しました。")
    return redirect("planner:detail", pk=plan.pk)


@login_required
def plan_delete(request, pk):
    plan = get_object_or_404(MealPlan, pk=pk)
    if request.method == "POST":
        plan.delete()
        messages.success(request, "週間プランを削除しました。")
        return redirect("planner:list")
    return render(request, "planner/confirm_delete.html", {"plan": plan})
