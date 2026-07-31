import json
import logging
from datetime import timedelta

from django.conf import settings

from recipes.models import NutritionCache, Recipe

from .models import MealPlan

logger = logging.getLogger(__name__)
SHOPPING_CATEGORIES = ("野菜・果物", "肉・魚", "卵・乳・豆腐", "調味料", "その他")


class SuggestionError(Exception):
    """AI生成結果を利用できない場合の例外。"""


class ShoppingListError(SuggestionError):
    """買い物リストを生成できない場合の例外。"""


def _last_used_dates():
    result = {}
    for plan in MealPlan.objects.prefetch_related("slots"):
        for slot in plan.slots.all():
            used_date = slot.start_date + timedelta(days=slot.days - 1)
            if slot.recipe_id and (
                slot.recipe_id not in result or used_date > result[slot.recipe_id]
            ):
                result[slot.recipe_id] = used_date
    return result


def build_candidates(genre2):
    last_used = _last_used_dates()
    recipes = Recipe.objects.filter(genre2=genre2).prefetch_related("ingredients")
    nutrition_by_name = {
        item.recipe_name: item
        for item in NutritionCache.objects.filter(
            recipe_name__in=recipes.values("name")
        )
    }
    result = []
    for recipe in recipes:
        nutrition = nutrition_by_name.get(recipe.name)
        result.append(
            {
                "id": recipe.pk,
                "name": recipe.name,
                "genre3": recipe.genre3,
                "main_protein": recipe.main_protein,
                "cooking_method": recipe.cooking_method,
                "flavor_profile": recipe.flavor_profile,
                "main_ingredients": [
                    item.name for item in recipe.ingredients.all()[:3]
                ],
                **{
                    key: getattr(nutrition, key) if nutrition else None
                    for key in (
                        "calories",
                        "protein",
                        "fat",
                        "carbs",
                        "salt",
                        "fiber",
                        "vegetables_g",
                    )
                },
                "last_used": last_used.get(recipe.pk).isoformat()
                if last_used.get(recipe.pk)
                else None,
            }
        )
    return result


def _dated_slots(config):
    weekdays = "月火水木金土日"
    return [
        {
            "order": slot["order"],
            "days": slot["days"],
            "date_from": f"{slot['start_date'].isoformat()}({weekdays[slot['start_date'].weekday()]})",
            "date_to": f"{slot['end_date'].isoformat()}({weekdays[slot['end_date'].weekday()]})",
        }
        for slot in config
    ]


def generate_suggestion(main_config, side_config, start_date, user_request=""):
    main_targets = _dated_slots(main_config)
    side_targets = _dated_slots(side_config)
    mains = build_candidates("主菜")
    sides = build_candidates("副菜")
    if not mains or not sides:
        raise SuggestionError("主菜と副菜を1件以上登録してから生成してください。")

    prompt = f"""1週間の献立を選び、JSONのみで返答してください。

主菜枠構成:
{json.dumps(main_targets, ensure_ascii=False)}
副菜枠構成:
{json.dumps(side_targets, ensure_ascii=False)}
主菜候補:
{json.dumps(mains, ensure_ascii=False)}
副菜候補:
{json.dumps(sides, ensure_ascii=False)}
ユーザーの要望:
{user_request or "（要望なし）"}

選定条件:
- 要望を他の条件より優先し、日付・曜日・人数変動は理由と週コメントに明記する
- 肉/魚、PFC、塩分、食物繊維、野菜量を週全体でバランスさせる
- 直近2週間の献立、同じ主材料・主たんぱく源・調理法・味付けの連続を避ける
- 材料の使い回しも考慮する
- 副菜は作り置きして複数日食べる。長い副菜枠には日持ちする献立を優先する

出力形式:
{{"main_slots":[{{"order":1,"recipe_id":12,"reason":"理由"}}],"side_slots":[{{"order":1,"recipe_id":34,"reason":"理由"}}],"week_comment":"コメント"}}"""
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
        return validate_suggestion(data, main_targets, side_targets, mains, sides)
    except SuggestionError:
        raise
    except Exception as exc:
        logger.error("献立サジェスト解析・取得エラー: %s / raw=%s", exc, raw)
        raise SuggestionError("献立サジェストの取得または解析に失敗しました。") from exc


def _validate_lane(items, targets, candidates, lane_name):
    if not isinstance(items, list):
        raise SuggestionError(f"{lane_name}の返答形式が正しくありません。")
    expected = {item["order"] for item in targets}
    candidate_ids = {item["id"] for item in candidates}
    actual = set()
    cleaned = []
    for item in items:
        try:
            order = int(item["order"])
            recipe_id = int(item["recipe_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SuggestionError(f"{lane_name}の枠データが正しくありません。") from exc
        if order in actual or recipe_id not in candidate_ids:
            raise SuggestionError(
                f"{lane_name}に存在しない献立IDまたは重複枠があります。"
            )
        actual.add(order)
        cleaned.append(
            {
                "order": order,
                "recipe_id": recipe_id,
                "reason": str(item.get("reason", ""))[:200],
            }
        )
    if actual != expected:
        raise SuggestionError(f"{lane_name}の返答に不足または余分な枠があります。")
    return sorted(cleaned, key=lambda item: item["order"])


def validate_suggestion(data, main_targets, side_targets, mains, sides):
    if not isinstance(data, dict):
        raise SuggestionError("AIの返答形式が正しくありません。")
    return {
        "main_slots": _validate_lane(
            data.get("main_slots"), main_targets, mains, "主菜"
        ),
        "side_slots": _validate_lane(
            data.get("side_slots"), side_targets, sides, "副菜"
        ),
        "week_comment": str(data.get("week_comment", "")),
    }


def calculate_nutrition_summary(plan):
    slots = list(plan.slots.select_related("recipe"))
    caches = {
        item.recipe_name: item
        for item in NutritionCache.objects.filter(
            recipe_name__in=[slot.recipe.name for slot in slots if slot.recipe]
        )
    }
    keys = ("calories", "protein", "fat", "carbs", "salt", "fiber", "vegetables_g")
    totals = {key: 0.0 for key in keys}
    excluded = []
    included_days = 0
    for offset in range(7):
        current = plan.start_date + timedelta(days=offset)
        day_slots = [
            slot for slot in slots if slot.start_date <= current <= slot.end_date
        ]
        if not day_slots:
            continue
        included_days += 1
        for slot in day_slots:
            cache = caches.get(slot.recipe.name) if slot.recipe else None
            if not cache:
                label = (
                    slot.recipe.name
                    if slot.recipe
                    else f"{slot.get_slot_type_display()}枠{slot.order}"
                )
                if label not in excluded:
                    excluded.append(label)
                continue
            for key in keys:
                value = getattr(cache, key)
                if value is not None:
                    totals[key] += value
    values = {
        key: round(value / included_days, 1) if included_days else None
        for key, value in totals.items()
    }
    return {"values": values, "included_days": included_days, "excluded": excluded}


def _shopping_ingredients(plan):
    result = []
    for slot in plan.slots.select_related("recipe").prefetch_related(
        "recipe__ingredients"
    ):
        if not slot.recipe:
            continue
        scale = 4 / slot.recipe.servings
        for ingredient in slot.recipe.ingredients.all():
            result.append(
                {
                    "name": ingredient.name,
                    "quantity": float(ingredient.quantity) * scale
                    if ingredient.quantity is not None
                    else None,
                    "unit": ingredient.unit,
                    "amount_text": ingredient.amount_text,
                    "recipe": slot.recipe.name,
                }
            )
    return result


def build_shopping_list(plan):
    ingredients = _shopping_ingredients(plan)
    prompt = f"""材料一覧を買い物リストに整理し、JSONのみで返してください。
材料:
{json.dumps(ingredients, ensure_ascii=False)}

表記揺れを名寄せし、g/kg・ml/cc・大さじ/小さじ等の換算可能な単位は合算してください。
換算できない組合せは「2個 ＋ 100g」のように併記し、適量・少々はamountを「適量」「少々」としてください。
カテゴリは必ず {list(SHOPPING_CATEGORIES)} の5つを、この順ですべて返してください。
形式: {{"categories":[{{"name":"野菜・果物","items":[{{"name":"玉ねぎ","amount":"2個","note":""}}]}}]}}"""
    raw = ""
    try:
        import openai

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw.replace("```json", "").replace("```", "").strip())
        return validate_shopping_list(data)
    except ShoppingListError:
        raise
    except Exception as exc:
        logger.error("買い物リスト解析・取得エラー: %s / raw=%s", exc, raw)
        raise ShoppingListError("買い物リストの生成に失敗しました。") from exc


def validate_shopping_list(data):
    categories = data.get("categories") if isinstance(data, dict) else None
    if not isinstance(categories, list) or [
        item.get("name") for item in categories
    ] != list(SHOPPING_CATEGORIES):
        raise ShoppingListError("買い物リストのカテゴリ形式が正しくありません。")
    for category in categories:
        if not isinstance(category.get("items"), list):
            raise ShoppingListError("買い物リストの品目形式が正しくありません。")
        category["items"] = [
            {
                "name": str(item.get("name", ""))[:100],
                "amount": str(item.get("amount", ""))[:100],
                "note": str(item.get("note", ""))[:100],
            }
            for item in category["items"]
            if isinstance(item, dict) and item.get("name")
        ]
    return {"categories": categories}
