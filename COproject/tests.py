from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from planner.models import MealPlan, MealPlanSlot
from recipes.models import Recipe


class HomeTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="home-tester",
            email="home@example.com",
            password="password",
            is_active=True,
        )
        self.client.force_login(user)

    def test_home_shows_active_plan_and_recent_recipes(self):
        main = Recipe.objects.create(
            name="今日の主菜", genre1="和食", genre2="主菜", servings=4
        )
        side = Recipe.objects.create(
            name="今日の副菜", genre1="和食", genre2="副菜", servings=4
        )
        plan = MealPlan.objects.create(start_date=date.today())
        MealPlanSlot.objects.create(
            plan=plan,
            order=1,
            start_date=date.today(),
            days=1,
            main_recipe=main,
            side_recipe=side,
        )

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "今日の主菜")
        self.assertContains(response, "今日の副菜")
        self.assertContains(response, "今日")

    def test_home_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("home"))

        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={reverse('home')}"
        )
