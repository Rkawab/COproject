import json
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from recipes.models import NutritionCache, Recipe

from .models import MealPlan, MealPlanSlot
from .services import calculate_nutrition_summary, generate_suggestion
from .views import parse_day_schedule


class DayScheduleTests(TestCase):
    def test_builds_slots_and_skips_days(self):
        slots = parse_day_schedule(
            ["new", "continue", "skip", "new", "continue", "continue", "skip"],
            date(2026, 7, 13),
        )
        self.assertEqual(
            slots,
            [
                {"order": 1, "start_date": date(2026, 7, 13), "days": 2},
                {"order": 2, "start_date": date(2026, 7, 16), "days": 3},
            ],
        )

    def test_continue_after_skip_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "直前が作る日"):
            parse_day_schedule(
                ["new", "skip", "continue", "skip", "skip", "skip", "skip"],
                date(2026, 7, 13),
            )

    def test_more_than_three_days_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "最大3日"):
            parse_day_schedule(
                ["new", "continue", "continue", "continue", "skip", "skip", "skip"],
                date(2026, 7, 13),
            )

    def test_no_cooking_day_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "1日以上"):
            parse_day_schedule(["skip"] * 7, date(2026, 7, 13))


class NutritionSummaryTests(TestCase):
    def test_average_uses_only_slot_days(self):
        main = Recipe.objects.create(
            name="主菜", genre1="和食", genre2="主菜", servings=4
        )
        side = Recipe.objects.create(
            name="副菜", genre1="和食", genre2="副菜", servings=4
        )
        NutritionCache.objects.create(
            recipe_name="主菜",
            calories=400,
            protein=20,
            fat=10,
            carbs=30,
            salt=2,
            fiber=4,
            vegetables_g=80,
        )
        NutritionCache.objects.create(
            recipe_name="副菜",
            calories=100,
            protein=5,
            fat=2,
            carbs=15,
            salt=1,
            fiber=3,
            vegetables_g=120,
        )
        plan = MealPlan.objects.create(start_date=date(2026, 7, 13))
        MealPlanSlot.objects.create(
            plan=plan,
            order=1,
            start_date=date(2026, 7, 13),
            days=2,
            main_recipe=main,
            side_recipe=side,
        )
        MealPlanSlot.objects.create(
            plan=plan,
            order=2,
            start_date=date(2026, 7, 17),
            days=1,
            main_recipe=main,
            side_recipe=side,
        )

        summary = calculate_nutrition_summary(plan)

        self.assertEqual(summary["included_days"], 3)
        self.assertEqual(summary["values"]["calories"], 500.0)
        self.assertEqual(summary["values"]["fiber"], 7.0)
        self.assertEqual(summary["values"]["vegetables_g"], 200.0)


class SuggestionPromptTests(TestCase):
    @patch("planner.services.build_candidates")
    def test_prompt_uses_actual_slot_dates_and_extended_constraints(self, candidates):
        candidates.side_effect = [[{"id": 1}], [{"id": 2}]]
        response_data = {
            "slots": [{"order": 1, "main_id": 1, "side_id": 2}],
            "week_comment": "考慮済み",
        }
        client = Mock()
        client.chat.completions.create.return_value.choices = [
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(response_data)))
        ]
        fake_openai = SimpleNamespace(OpenAI=Mock(return_value=client))
        config = [{"order": 1, "start_date": date(2026, 7, 17), "days": 1}]

        with patch.dict(sys.modules, {"openai": fake_openai}):
            generate_suggestion(config, date(2026, 7, 13), "金曜は1人分")

        prompt = client.chat.completions.create.call_args.kwargs["messages"][0][
            "content"
        ]
        self.assertIn("2026-07-17(金)", prompt)
        self.assertIn("金曜は1人分", prompt)
        self.assertIn("主たんぱく源・調理法・味付け系統", prompt)
        self.assertIn("食物繊維・野菜量", prompt)
