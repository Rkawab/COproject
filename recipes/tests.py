import json
import sys
from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from planner.models import MealPlan, MealPlanSlot

from .models import NutritionCache, Recipe
from .views import _fetch_and_cache_nutrition


class QuickRecipeCreateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester",
            email="tester@example.com",
            password="password",
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_initial_servings_is_four(self):
        response = self.client.get(reverse("recipes:quick_create"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].fields["servings"].initial, 4)
        self.assertNotContains(response, "材料名")
        self.assertNotContains(response, "手順を入力")

    @patch("recipes.views._fetch_and_cache_nutrition")
    def test_create_simple_recipe_and_redirect_to_detail(self, fetch_nutrition):
        response = self.client.post(
            reverse("recipes:quick_create"),
            {
                "name": "パックのカレー",
                "genre1": "洋食",
                "genre2": "主菜",
                "genre3": "肉系",
                "servings": 4,
            },
        )

        recipe = Recipe.objects.get(name="パックのカレー")
        self.assertRedirects(response, reverse("recipes:detail", args=[recipe.pk]))
        self.assertTrue(recipe.is_simple)
        self.assertEqual(recipe.servings, 4)
        self.assertFalse(recipe.ingredients.exists())
        self.assertFalse(recipe.steps.exists())
        fetch_nutrition.assert_called_once_with(recipe)

    @patch("recipes.views._fetch_and_cache_nutrition")
    @patch("recipes.views.guess_ingredients_and_steps")
    def test_guess_details_creates_ingredients_and_steps_before_nutrition(
        self, guess_details, fetch_nutrition
    ):
        guess_details.return_value = {
            "identified": True,
            "ingredients": [
                {"name": "豚ひき肉", "quantity": 150, "unit": "g", "amount_text": ""}
            ],
            "steps": ["春雨を戻す", "ひき肉と炒める"],
        }

        def assert_details_exist(recipe):
            self.assertEqual(recipe.ingredients.count(), 1)
            self.assertEqual(recipe.steps.count(), 2)

        fetch_nutrition.side_effect = assert_details_exist
        self.client.post(
            reverse("recipes:quick_create"),
            {
                "name": "永谷園 マーボー春雨",
                "genre1": "中華",
                "genre2": "主菜",
                "genre3": "肉系",
                "servings": 4,
                "guess_details": "on",
            },
        )

        recipe = Recipe.objects.get(name="永谷園 マーボー春雨")
        self.assertEqual(recipe.ingredients.get().name, "豚ひき肉")
        self.assertEqual(list(recipe.steps.values_list("order", flat=True)), [1, 2])
        fetch_nutrition.assert_called_once_with(recipe)

    @patch("recipes.views._fetch_and_cache_nutrition")
    @patch("recipes.views.guess_ingredients_and_steps")
    def test_unidentified_product_creates_fallback_step(
        self, guess_details, _nutrition
    ):
        guess_details.return_value = {
            "identified": False,
            "ingredients": [],
            "steps": ["パッケージの記載手順に従って調理する"],
        }
        self.client.post(
            reverse("recipes:quick_create"),
            {
                "name": "市販のおかず",
                "genre1": "和食",
                "genre2": "主菜",
                "genre3": "肉系",
                "servings": 4,
                "guess_details": "on",
            },
        )

        recipe = Recipe.objects.get(name="市販のおかず")
        self.assertFalse(recipe.ingredients.exists())
        self.assertEqual(
            recipe.steps.get().description, "パッケージの記載手順に従って調理する"
        )

    @patch("recipes.views._fetch_and_cache_nutrition")
    @patch("recipes.views.guess_ingredients_and_steps")
    def test_guess_details_off_does_not_call_guesser(self, guess_details, _nutrition):
        self.client.post(
            reverse("recipes:quick_create"),
            {
                "name": "レトルトカレー",
                "genre1": "洋食",
                "genre2": "主菜",
                "genre3": "肉系",
                "servings": 4,
            },
        )

        recipe = Recipe.objects.get(name="レトルトカレー")
        self.assertFalse(recipe.ingredients.exists())
        self.assertFalse(recipe.steps.exists())
        guess_details.assert_not_called()

    def test_simple_badge_is_shown_on_list_and_detail(self):
        recipe = Recipe.objects.create(
            name="シチュー",
            genre1="洋食",
            genre2="主菜",
            genre3="肉系",
            servings=4,
            is_simple=True,
        )

        list_response = self.client.get(reverse("recipes:list"))
        detail_response = self.client.get(reverse("recipes:detail", args=[recipe.pk]))

        self.assertContains(list_response, "市販品")
        self.assertContains(detail_response, "市販品")


class BackfillRecipeAttributesTests(TestCase):
    def setUp(self):
        Recipe.objects.create(
            name="未補完レシピ", genre1="和食", genre2="主菜", servings=4
        )

    @patch(
        "recipes.management.commands.backfill_recipe_attributes._fetch_and_cache_nutrition"
    )
    def test_dry_run_does_not_call_ai(self, fetch_nutrition):
        output = StringIO()

        call_command("backfill_recipe_attributes", dry_run=True, stdout=output)

        self.assertIn("対象件数: 1件", output.getvalue())
        fetch_nutrition.assert_not_called()

    @patch(
        "recipes.management.commands.backfill_recipe_attributes._fetch_and_cache_nutrition",
        return_value=True,
    )
    def test_limit_restricts_processed_count(self, fetch_nutrition):
        Recipe.objects.create(
            name="未補完レシピ2", genre1="洋食", genre2="副菜", servings=4
        )
        output = StringIO()

        call_command("backfill_recipe_attributes", limit=1, stdout=output)

        self.assertEqual(fetch_nutrition.call_count, 1)
        self.assertIn("成功1件", output.getvalue())


class RecipeDeleteTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="delete-tester",
            email="delete@example.com",
            password="password",
            is_active=True,
        )
        self.client.force_login(self.user)

    def _create_recipe(self, name="肉じゃが"):
        recipe = Recipe.objects.create(
            name=name, genre1="和食", genre2="主菜", servings=4
        )
        NutritionCache.objects.create(recipe_name=name, calories=400)
        return recipe

    def test_delete_recipe_used_by_plan_clears_slot_reference(self):
        recipe = self._create_recipe()
        plan = MealPlan.objects.create(start_date=date(2026, 7, 12))
        slot = MealPlanSlot.objects.create(
            plan=plan,
            slot_type="main",
            order=1,
            start_date=date(2026, 7, 12),
            days=1,
            recipe=recipe,
        )

        response = self.client.post(reverse("recipes:delete", args=[recipe.pk]))

        self.assertRedirects(response, reverse("recipes:list"))
        slot.refresh_from_db()
        self.assertIsNone(slot.recipe)

    def test_delete_removes_orphan_nutrition_cache(self):
        recipe = self._create_recipe()

        self.client.post(reverse("recipes:delete", args=[recipe.pk]))

        self.assertFalse(NutritionCache.objects.filter(recipe_name="肉じゃが").exists())

    def test_cache_is_kept_when_same_name_recipe_remains(self):
        recipe = self._create_recipe()
        Recipe.objects.create(name="肉じゃが", genre1="和食", genre2="主菜", servings=2)

        self.client.post(reverse("recipes:delete", args=[recipe.pk]))

        self.assertTrue(NutritionCache.objects.filter(recipe_name="肉じゃが").exists())


class RecipeFormValidationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="form-tester",
            email="form@example.com",
            password="password",
            is_active=True,
        )
        self.client.force_login(self.user)

    @patch("recipes.views._fetch_and_cache_nutrition")
    def test_zero_servings_is_rejected(self, _nutrition):
        response = self.client.post(
            reverse("recipes:quick_create"),
            {"name": "0人前", "genre1": "和食", "genre2": "主菜", "servings": 0},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Recipe.objects.filter(name="0人前").exists())


class ExtendedNutritionTests(TestCase):
    def test_single_ai_response_updates_nutrition_and_recipe_attributes(self):
        recipe = Recipe.objects.create(
            name="野菜炒め", genre1="中華", genre2="主菜", servings=4
        )
        data = {
            "calories": 350,
            "protein": 18,
            "fat": 12,
            "carbs": 30,
            "salt": 2.1,
            "fiber": 5.2,
            "vegetables_g": 180,
            "main_protein": "豚肉",
            "cooking_method": "炒める",
            "flavor_profile": "リスト外",
        }
        client = Mock()
        client.chat.completions.create.return_value.choices = [
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))
        ]
        fake_openai = SimpleNamespace(OpenAI=Mock(return_value=client))

        with patch.dict(sys.modules, {"openai": fake_openai}):
            succeeded = _fetch_and_cache_nutrition(recipe)

        recipe.refresh_from_db()
        nutrition = NutritionCache.objects.get(recipe_name=recipe.name)
        self.assertTrue(succeeded)
        self.assertEqual(nutrition.fiber, 5.2)
        self.assertEqual(nutrition.vegetables_g, 180)
        self.assertEqual(recipe.main_protein, "豚肉")
        self.assertEqual(recipe.cooking_method, "炒める")
        self.assertEqual(recipe.flavor_profile, "")

    def test_api_failure_keeps_existing_cache(self):
        recipe = Recipe.objects.create(
            name="肉じゃが", genre1="和食", genre2="主菜", servings=4
        )
        NutritionCache.objects.create(recipe_name="肉じゃが", calories=380)
        client = Mock()
        client.chat.completions.create.side_effect = RuntimeError("APIエラー")
        fake_openai = SimpleNamespace(OpenAI=Mock(return_value=client))

        with patch.dict(sys.modules, {"openai": fake_openai}):
            succeeded = _fetch_and_cache_nutrition(recipe)

        self.assertFalse(succeeded)
        self.assertEqual(
            NutritionCache.objects.get(recipe_name="肉じゃが").calories, 380
        )
