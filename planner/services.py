import json
import logging
from datetime import timedelta

from django.conf import settings

from recipes.models import NutritionCache, Recipe

from .models import MealPlan

logger = logging.getLogger(__name__)


class SuggestionError(Exception):
    """週間献立の生成結果を利用できない場合の例外。"""


def _last_used_dates():
    result = {}
    plans = MealPlan.objects.prefetch_related("slots")
    for plan in plans:
        for slot in plan.slots.all():
            used_date = slot.start_date + timedelta(days=slot.days - 1)
            for recipe_id in (slot.main_recipe_id, slot.side_recipe_id):
                if recipe_id and (
                    recipe_id not in result or used_date > result[recipe_id]
                ):
                    result[recipe_id] = used_date
    return result


def build_candidates(genre2):
    last_used = _last_used_dates()
    nutrition_by_name = {
        item.recipe_name: item
        for item in NutritionCache.objects.filter(
            recipe_name__in=Recipe.objects.filter(genre2=genre2).values("name")
        )
    }
    recipes = Recipe.objects.filter(genre2=genre2).prefetch_related("ingredients")
    candidates = []
    for recipe in recipes:
        nutrition = nutrition_by_name.get(recipe.name)
        used = last_used.get(recipe.pk)
        candidates.append(
            {
                "id": recipe.pk,
                "name": recipe.name,
                "genre3": recipe.genre3,
                "main_protein": recipe.main_protein,
                "cooking_method": recipe.cooking_method,
                "flavor_profile": recipe.flavor_profile,
                "main_ingredients": [
                    item.name for item in list(recipe.ingredients.all())[:3]
                ],
                "calories": nutrition.calories if nutrition else None,
                "protein": nutrition.protein if nutrition else None,
                "fat": nutrition.fat if nutrition else None,
                "carbs": nutrition.carbs if nutrition else None,
                "salt": nutrition.salt if nutrition else None,
                "fiber": nutrition.fiber if nutrition else None,
                "vegetables_g": nutrition.vegetables_g if nutrition else None,
                "last_used": used.isoformat() if used else None,
            }
        )
    return candidates


def _dated_slots(slot_config, start_date):
    weekdays = "月火水木金土日"
    result = []
    for slot in slot_config:
        current = slot["start_date"]
        end = current + timedelta(days=slot["days"] - 1)
        result.append(
            {
                "order": slot["order"],
                "days": slot["days"],
                "date_from": f"{current.isoformat()}({weekdays[current.weekday()]})",
                "date_to": f"{end.isoformat()}({weekdays[end.weekday()]})",
            }
        )
    return result


def generate_suggestion(slot_config, start_date, user_request=""):
    target_slots = _dated_slots(slot_config, start_date)

    mains = build_candidates("主菜")
    sides = build_candidates("副菜")
    if not mains or not sides:
        raise SuggestionError("主菜と副菜を1件以上登録してから生成してください。")

    prompt = f"""1週間の献立を選んでください。JSONのみで返答してください。

枠構成:
{json.dumps(target_slots, ensure_ascii=False)}

主菜候補:
{json.dumps(mains, ensure_ascii=False)}

副菜候補:
{json.dumps(sides, ensure_ascii=False)}

ユーザーの要望:
{user_request or "（要望なし）"}

選定条件:
- 要望がある場合は、他の選定条件より優先する
- 「水〜金はカレー」のような日付・曜日指定は、枠の日付範囲を見て該当する枠に反映する
- 肉系と魚系のバランスを取る
- last_used が直近2週間の献立をできるだけ避ける
- 週全体のPFCと塩分のバランスを取る
- 同じ野菜を複数枠で使える組合せを加点する
- 同じ主材料が連続しないようにする
- 主たんぱく源・調理法・味付け系統が連続しないようにし、週内でバランスさせる
- 食物繊維・野菜量も週全体で不足しないようにする
- 人数変動の要望（例: 金曜は1人分）があれば、該当枠の選定理由と週コメントに考慮内容を明記する

出力形式:
{{"slots":[{{"order":1,"main_id":12,"side_id":34,"reason":"選定理由"}}],"week_comment":"週全体のコメント"}}
全ての通常枠を1回ずつ含め、候補に存在するIDだけを使用してください。"""

    raw = ""
    try:
        import openai

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw.replace("```json", "").replace("```", "").strip())
        return validate_suggestion(data, target_slots, mains, sides)
    except SuggestionError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error("献立サジェストJSON解析失敗: %s (%s)", raw, exc)
        raise SuggestionError(
            "AIの返答を解析できませんでした。再生成してください。"
        ) from exc
    except Exception as exc:
        logger.error("献立サジェスト取得エラー: %s", exc)
        raise SuggestionError("献立サジェストの取得に失敗しました。") from exc


def validate_suggestion(data, target_slots, mains, sides):
    if not isinstance(data, dict) or not isinstance(data.get("slots"), list):
        raise SuggestionError("AIの返答形式が正しくありません。")

    expected_orders = {slot["order"] for slot in target_slots}
    main_ids = {item["id"] for item in mains}
    side_ids = {item["id"] for item in sides}
    actual_orders = set()
    cleaned = []
    for slot in data["slots"]:
        try:
            order = int(slot["order"])
            main_id = int(slot["main_id"])
            side_id = int(slot["side_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SuggestionError("AIの枠データが正しくありません。") from exc
        if order in actual_orders or main_id not in main_ids or side_id not in side_ids:
            raise SuggestionError("AIが存在しない献立IDまたは重複した枠を返しました。")
        actual_orders.add(order)
        cleaned.append(
            {
                "order": order,
                "main_id": main_id,
                "side_id": side_id,
                "reason": str(slot.get("reason", ""))[:200],
            }
        )
    if actual_orders != expected_orders:
        raise SuggestionError("AIの返答に不足または余分な枠があります。")
    return {
        "slots": sorted(cleaned, key=lambda item: item["order"]),
        "week_comment": str(data.get("week_comment", "")),
    }


def calculate_nutrition_summary(plan):
    names = set()
    slots = list(plan.slots.select_related("main_recipe", "side_recipe"))
    for slot in slots:
        names.update(
            recipe.name for recipe in (slot.main_recipe, slot.side_recipe) if recipe
        )
    caches = {
        item.recipe_name: item
        for item in NutritionCache.objects.filter(recipe_name__in=names)
    }
    totals = {
        key: 0.0
        for key in (
            "calories",
            "protein",
            "fat",
            "carbs",
            "salt",
            "fiber",
            "vegetables_g",
        )
    }
    included_days = 0
    excluded = []
    for slot in slots:
        has_data = False
        for recipe in (slot.main_recipe, slot.side_recipe):
            cache = caches.get(recipe.name) if recipe else None
            if not cache:
                excluded.append(
                    recipe.name if recipe else f"枠{slot.order}の未設定献立"
                )
                continue
            has_data = True
            for key in totals:
                value = getattr(cache, key)
                if value is not None:
                    totals[key] += value * slot.days
        if has_data:
            included_days += slot.days
    averages = {
        key: round(value / included_days, 1) if included_days else None
        for key, value in totals.items()
    }
    return {"values": averages, "included_days": included_days, "excluded": excluded}
