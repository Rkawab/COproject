from django.core.management.base import BaseCommand

from recipes.models import NutritionCache, Recipe
from recipes.views import _fetch_and_cache_nutrition


class Command(BaseCommand):
    help = "既存献立の分類属性・食物繊維・野菜量をAIで補完します。"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="処理する最大件数")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="対象件数だけを表示し、APIを呼びません",
        )

    def handle(self, *args, **options):
        targets = []
        caches = {cache.recipe_name: cache for cache in NutritionCache.objects.all()}
        for recipe in Recipe.objects.prefetch_related("ingredients"):
            cache = caches.get(recipe.name)
            attributes_missing = not all(
                (recipe.main_protein, recipe.cooking_method, recipe.flavor_profile)
            )
            nutrition_missing = (
                cache is None or cache.fiber is None or cache.vegetables_g is None
            )
            if attributes_missing or nutrition_missing:
                targets.append(recipe)

        limit = options.get("limit")
        if limit is not None:
            if limit < 1:
                self.stderr.write(
                    self.style.ERROR("--limit は1以上で指定してください。")
                )
                return
            targets = targets[:limit]

        self.stdout.write(f"対象件数: {len(targets)}件")
        if options["dry_run"]:
            self.stdout.write("dry-runのためAPI呼び出し・更新は行いません。")
            return

        succeeded = 0
        failed = 0
        for recipe in targets:
            self.stdout.write(f"処理中: {recipe.name}")
            if _fetch_and_cache_nutrition(recipe):
                succeeded += 1
            else:
                failed += 1
        self.stdout.write(
            self.style.SUCCESS(f"完了: 成功{succeeded}件 / 失敗{failed}件")
        )
