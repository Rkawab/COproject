import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from recipes.models import Recipe

from .models import MealPlan, MealPlanSlot
from .services import (
    ShoppingListError,
    SuggestionError,
    build_shopping_list,
    calculate_nutrition_summary,
    generate_suggestion,
)

MAIN_DEFAULT = ("new", "continue", "new", "continue", "new", "continue", "new")
SIDE_DEFAULT = (
    "new",
    "continue",
    "continue",
    "continue",
    "new",
    "continue",
    "continue",
)
DAY_STATUS_CHOICES = (("new", "作る"), ("continue", "前日の続き"), ("skip", "作らない"))
WEEKDAYS = "月火水木金土日"


def _default_start_date():
    return timezone.localdate()


def build_day_rows(start_date, main_statuses=MAIN_DEFAULT, side_statuses=SIDE_DEFAULT):
    return [
        {
            "index": index,
            "date": start_date + timedelta(days=index),
            "weekday": WEEKDAYS[(start_date + timedelta(days=index)).weekday()],
            "main_status": main_statuses[index],
            "side_status": side_statuses[index],
        }
        for index in range(7)
    ]


def parse_day_schedule(statuses, start_date, max_days, lane_name):
    allowed = {choice[0] for choice in DAY_STATUS_CHOICES}
    if len(statuses) != 7 or any(status not in allowed for status in statuses):
        raise ValueError(f"{lane_name}: 7日分の選択を確認してください。")
    slots = []
    current_slot = None
    previous_status = None
    for index, status in enumerate(statuses):
        current_date = start_date + timedelta(days=index)
        if status == "new":
            current_slot = {
                "order": len(slots) + 1,
                "start_date": current_date,
                "end_date": current_date,
                "days": 1,
            }
            slots.append(current_slot)
        elif status == "continue":
            if previous_status not in ("new", "continue") or current_slot is None:
                raise ValueError(f"{lane_name}: 続きは直前が作る日の場合のみ選べます。")
            if current_slot["days"] >= max_days:
                raise ValueError(f"{lane_name}: 同じ献立は最大{max_days}日です。")
            current_slot["days"] += 1
            current_slot["end_date"] = current_date
        else:
            current_slot = None
        previous_status = status
    if not slots:
        raise ValueError(f"{lane_name}: 作る日を1日以上選んでください。")
    return slots


def _date_label(slot):
    def label(value):
        return f"{value.month}/{value.day}({WEEKDAYS[value.weekday()]})"

    return (
        label(slot["start_date"])
        if slot["days"] == 1
        else f"{label(slot['start_date'])}〜{label(slot['end_date'])}"
    )


def _editable_lane(config, generated, lane, request=None):
    suggestions = {item["order"]: item for item in generated or []}
    result = []
    for slot in config:
        item = dict(slot)
        item["date_label"] = _date_label(slot)
        suggestion = suggestions.get(slot["order"], {})
        item["recipe_id"] = suggestion.get("recipe_id")
        item["reason"] = suggestion.get("reason", "")
        if request and request.POST.get("action") == "save":
            item["recipe_id"] = (
                request.POST.get(f"{lane}_recipe_{slot['order']}") or None
            )
            item["reason"] = request.POST.get(f"{lane}_reason_{slot['order']}", "")
        result.append(item)
    return result


@login_required
def plan_list(request):
    return render(
        request,
        "planner/list.html",
        {"plans": MealPlan.objects.prefetch_related("slots")},
    )


@login_required
def plan_suggest(request):
    mains = Recipe.objects.filter(genre2="主菜")
    sides = Recipe.objects.filter(genre2="副菜")
    start_date = _default_start_date()
    main_statuses = list(MAIN_DEFAULT)
    side_statuses = list(SIDE_DEFAULT)
    context = {
        "start_date": start_date.isoformat(),
        "day_rows": build_day_rows(start_date),
        "day_status_choices": DAY_STATUS_CHOICES,
        "user_request": "",
        "mains": mains,
        "sides": sides,
        "main_slots": None,
        "side_slots": None,
        "week_comment": "",
    }
    if request.method != "POST":
        return render(request, "planner/suggest.html", context)
    try:
        start_date = date.fromisoformat(request.POST.get("start_date", ""))
    except (TypeError, ValueError):
        messages.error(request, "開始日を確認してください。")
        return render(request, "planner/suggest.html", context)
    main_statuses = [request.POST.get(f"main_day_{i}", "") for i in range(7)]
    side_statuses = [request.POST.get(f"side_day_{i}", "") for i in range(7)]
    context.update(
        {
            "start_date": start_date.isoformat(),
            "day_rows": build_day_rows(start_date, main_statuses, side_statuses),
            "user_request": request.POST.get("user_request", "").strip(),
        }
    )
    try:
        main_config = parse_day_schedule(main_statuses, start_date, 3, "主菜")
        side_config = parse_day_schedule(side_statuses, start_date, 7, "副菜")
    except ValueError as exc:
        messages.error(request, str(exc))
        return render(request, "planner/suggest.html", context)
    action = request.POST.get("action")
    if action in ("generate", "regenerate"):
        try:
            suggestion = generate_suggestion(
                main_config, side_config, start_date, context["user_request"]
            )
        except SuggestionError as exc:
            messages.error(request, str(exc))
            suggestion = {"main_slots": [], "side_slots": [], "week_comment": ""}
        context["main_slots"] = _editable_lane(
            main_config, suggestion["main_slots"], "main"
        )
        context["side_slots"] = _editable_lane(
            side_config, suggestion["side_slots"], "side"
        )
        context["week_comment"] = suggestion["week_comment"]
        return render(request, "planner/suggest.html", context)
    if action == "save":
        main_slots = _editable_lane(main_config, [], "main", request)
        side_slots = _editable_lane(side_config, [], "side", request)
        context.update(
            {
                "main_slots": main_slots,
                "side_slots": side_slots,
                "week_comment": request.POST.get("week_comment", ""),
            }
        )
        try:
            with transaction.atomic():
                plan = MealPlan.objects.create(
                    start_date=start_date,
                    user_request=context["user_request"],
                    ai_comment=context["week_comment"],
                )
                for lane, slots, genre in (
                    ("main", main_slots, "主菜"),
                    ("side", side_slots, "副菜"),
                ):
                    for item in slots:
                        recipe = Recipe.objects.get(pk=item["recipe_id"], genre2=genre)
                        slot = MealPlanSlot(
                            plan=plan,
                            slot_type=lane,
                            order=item["order"],
                            start_date=item["start_date"],
                            days=item["days"],
                            recipe=recipe,
                            reason=item["reason"][:200],
                        )
                        slot.full_clean()
                        slot.save()
        except (Recipe.DoesNotExist, TypeError, ValueError, ValidationError) as exc:
            messages.error(request, f"枠の献立を確認してください。{exc}")
            return render(request, "planner/suggest.html", context)
        messages.success(request, "週間プランを保存しました。")
        return redirect("planner:detail", pk=plan.pk)
    messages.error(request, "操作を確認できませんでした。")
    return render(request, "planner/suggest.html", context)


@login_required
def plan_detail(request, pk):
    plan = get_object_or_404(MealPlan.objects.prefetch_related("slots__recipe"), pk=pk)
    shopping = None
    if plan.shopping_list:
        try:
            shopping = json.loads(plan.shopping_list)
        except json.JSONDecodeError:
            shopping = None
    return render(
        request,
        "planner/detail.html",
        {
            "plan": plan,
            "main_slots": plan.slots.filter(slot_type="main"),
            "side_slots": plan.slots.filter(slot_type="side"),
            "nutrition": calculate_nutrition_summary(plan),
            "mains": Recipe.objects.filter(genre2="主菜"),
            "sides": Recipe.objects.filter(genre2="副菜"),
            "shopping": shopping,
        },
    )


@login_required
def slot_update(request, pk, slot_pk):
    plan = get_object_or_404(MealPlan, pk=pk)
    slot = get_object_or_404(MealPlanSlot, pk=slot_pk, plan=plan)
    if request.method == "POST":
        genre = "主菜" if slot.slot_type == "main" else "副菜"
        slot.recipe = get_object_or_404(
            Recipe, pk=request.POST.get("recipe"), genre2=genre
        )
        try:
            slot.full_clean()
            slot.save()
        except ValidationError as exc:
            messages.error(request, f"枠を更新できませんでした。{exc}")
        else:
            messages.success(
                request, f"{slot.get_slot_type_display()}枠{slot.order}を更新しました。"
            )
    return redirect("planner:detail", pk=plan.pk)


@login_required
def shopping_list_generate(request, pk):
    plan = get_object_or_404(MealPlan, pk=pk)
    if request.method == "POST":
        try:
            shopping = build_shopping_list(plan)
        except ShoppingListError as exc:
            messages.error(request, str(exc))
        else:
            plan.shopping_list = json.dumps(shopping, ensure_ascii=False)
            plan.shopping_list_generated_at = timezone.now()
            plan.save(update_fields=["shopping_list", "shopping_list_generated_at"])
            messages.success(request, "買い物リストを作成しました。")
    return redirect("planner:detail", pk=plan.pk)


@login_required
def plan_delete(request, pk):
    plan = get_object_or_404(MealPlan, pk=pk)
    if request.method == "POST":
        plan.delete()
        messages.success(request, "週間プランを削除しました。")
        return redirect("planner:list")
    return render(request, "planner/confirm_delete.html", {"plan": plan})
