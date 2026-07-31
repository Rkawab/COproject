import json
import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from recipes.models import Ingredient, NutritionCache, Recipe

from .models import MealPlan, MealPlanSlot
from .services import (
    ShoppingListError,
    _shopping_ingredients,
    calculate_nutrition_summary,
    generate_suggestion,
    validate_shopping_list,
    validate_suggestion,
)
from .views import parse_day_schedule


class LaneScheduleTests(TestCase):
    def test_main_and_side_have_different_max_days(self):
        statuses = [
            "new",
            "continue",
            "continue",
            "continue",
            "continue",
            "skip",
            "skip",
        ]
        with self.assertRaisesMessage(ValueError, "主菜: 同じ献立は最大3日"):
            parse_day_schedule(statuses, date(2026, 7, 13), 3, "主菜")
        side = parse_day_schedule(statuses, date(2026, 7, 13), 7, "副菜")
        self.assertEqual(side[0]["days"], 5)

    def test_continue_after_skip_and_empty_lane_are_rejected(self):
        with self.assertRaisesMessage(ValueError, "副菜: 続き"):
            parse_day_schedule(
                ["new", "skip", "continue", "skip", "skip", "skip", "skip"],
                date(2026, 7, 13),
                7,
                "副菜",
            )
        with self.assertRaisesMessage(ValueError, "主菜: 作る日"):
            parse_day_schedule(["skip"] * 7, date(2026, 7, 13), 3, "主菜")


class LaneModelTests(TestCase):
    def test_date_label_has_japanese_weekday(self):
        plan = MealPlan.objects.create(start_date=date(2026, 7, 12))
        recipe = Recipe.objects.create(
            name="主菜", genre1="和食", genre2="主菜", servings=4
        )
        slot = MealPlanSlot.objects.create(
            plan=plan,
            slot_type="main",
            order=1,
            start_date=date(2026, 7, 12),
            days=2,
            recipe=recipe,
        )
        self.assertEqual(slot.date_label, "7/12(日)〜7/13(月)")


class SuggestionValidationTests(TestCase):
    def test_validates_each_lane_independently(self):
        data = {
            "main_slots": [{"order": 1, "recipe_id": 1}],
            "side_slots": [{"order": 1, "recipe_id": 2}],
        }
        result = validate_suggestion(
            data, [{"order": 1}], [{"order": 1}], [{"id": 1}], [{"id": 2}]
        )
        self.assertEqual(result["main_slots"][0]["recipe_id"], 1)
        with self.assertRaisesMessage(Exception, "副菜"):
            validate_suggestion(
                {**data, "side_slots": []},
                [{"order": 1}],
                [{"order": 1}],
                [{"id": 1}],
                [{"id": 2}],
            )

    @patch("planner.services.build_candidates")
    def test_prompt_contains_separate_lanes(self, candidates):
        candidates.side_effect = [[{"id": 1}], [{"id": 2}]]
        payload = {
            "main_slots": [{"order": 1, "recipe_id": 1}],
            "side_slots": [{"order": 1, "recipe_id": 2}],
            "week_comment": "ok",
        }
        client = Mock()
        client.chat.completions.create.return_value.choices = [
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
        ]
        config = [
            {
                "order": 1,
                "start_date": date(2026, 7, 12),
                "end_date": date(2026, 7, 13),
                "days": 2,
            }
        ]
        with patch.dict(
            sys.modules, {"openai": SimpleNamespace(OpenAI=Mock(return_value=client))}
        ):
            generate_suggestion(config, config, date(2026, 7, 12))
        prompt = client.chat.completions.create.call_args.kwargs["messages"][0][
            "content"
        ]
        self.assertIn("主菜枠構成", prompt)
        self.assertIn("副菜枠構成", prompt)
        self.assertIn("日持ちする", prompt)


class DailyNutritionTests(TestCase):
    def test_combines_lanes_per_day_and_skips_empty_days(self):
        main = Recipe.objects.create(
            name="主菜", genre1="和食", genre2="主菜", servings=4
        )
        side = Recipe.objects.create(
            name="副菜", genre1="和食", genre2="副菜", servings=4
        )
        NutritionCache.objects.create(recipe_name="主菜", calories=400)
        NutritionCache.objects.create(recipe_name="副菜", calories=100)
        plan = MealPlan.objects.create(start_date=date(2026, 7, 12))
        MealPlanSlot.objects.create(
            plan=plan,
            slot_type="main",
            order=1,
            start_date=date(2026, 7, 12),
            days=2,
            recipe=main,
        )
        MealPlanSlot.objects.create(
            plan=plan,
            slot_type="side",
            order=1,
            start_date=date(2026, 7, 13),
            days=2,
            recipe=side,
        )
        summary = calculate_nutrition_summary(plan)
        self.assertEqual(summary["included_days"], 3)
        self.assertEqual(summary["values"]["calories"], 333.3)


class ShoppingListTests(TestCase):
    def test_scales_each_slot_to_four_servings(self):
        recipe = Recipe.objects.create(
            name="料理", genre1="和食", genre2="主菜", servings=2
        )
        Ingredient.objects.create(
            recipe=recipe, name="玉ねぎ", quantity=Decimal("0.5"), unit="個"
        )
        plan = MealPlan.objects.create(start_date=date(2026, 7, 12))
        MealPlanSlot.objects.create(
            plan=plan,
            slot_type="main",
            order=1,
            start_date=date(2026, 7, 12),
            days=2,
            recipe=recipe,
        )
        items = _shopping_ingredients(plan)
        self.assertEqual(items[0]["quantity"], 1.0)

    def test_validates_category_names(self):
        with self.assertRaises(ShoppingListError):
            validate_shopping_list({"categories": [{"name": "不正", "items": []}]})
