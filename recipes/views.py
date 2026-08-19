import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import IngredientFormSet, QuickRecipeForm, RecipeForm, StepFormSet
from .models import (
    COOKING_METHOD_CHOICES,
    FLAVOR_PROFILE_CHOICES,
    MAIN_PROTEIN_CHOICES,
    Ingredient,
    NutritionCache,
    Recipe,
    Step,
)
from .recipe_guesser import guess_ingredients_and_steps
from .recipe_reader import RecipeReadError, extract_recipe_info
from .recipe_url_reader import RecipeURLError, fetch_recipe_from_url

logger = logging.getLogger(__name__)


def _fetch_and_cache_nutrition(recipe, old_name=None):
    """OpenAI API で栄養価を推定しキャッシュに保存する。エラーはログ記録のみ。

    取得に成功してからキャッシュを差し替える。API失敗時に既存の栄養価を
    失わないようにするため、削除は取得成功後にのみ行う。
    """
    ingredients_text = (
        "\n".join([f"- {i.name} {i.display_amount}" for i in recipe.ingredients.all()])
        or "（材料未登録）"
    )

    prompt = f"""以下の料理について、1人分の推定栄養価を教えてください。

料理名: {recipe.name}
人数: {recipe.servings}人前
材料:
{ingredients_text}

以下のJSON形式のみで返答してください（説明文・コードブロック不要）:
{{"calories": 数値, "protein": 数値, "fat": 数値, "carbs": 数値, "salt": 数値,
"fiber": 数値, "vegetables_g": 数値, "main_protein": "分類", "cooking_method": "分類", "flavor_profile": "分類"}}

単位: calories=kcal, protein/fat/carbs/salt/fiber/vegetables_g=g（すべて1人分）
main_protein は {[value for value, _ in MAIN_PROTEIN_CHOICES]} から選択
cooking_method は {[value for value, _ in COOKING_METHOD_CHOICES]} から選択
flavor_profile は {[value for value, _ in FLAVOR_PROFILE_CHOICES]} から選択"""

    raw = ""
    try:
        import openai

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        # ここまで来たら取得成功。名前変更時は古いキャッシュを片付けてから差し替える
        if old_name and old_name != recipe.name:
            NutritionCache.objects.filter(recipe_name=old_name).delete()
        NutritionCache.objects.filter(recipe_name=recipe.name).delete()
        NutritionCache.objects.create(
            recipe_name=recipe.name,
            calories=data.get("calories"),
            protein=data.get("protein"),
            fat=data.get("fat"),
            carbs=data.get("carbs"),
            salt=data.get("salt"),
            fiber=data.get("fiber"),
            vegetables_g=data.get("vegetables_g"),
            raw_response=raw,
        )
        choice_fields = {
            "main_protein": MAIN_PROTEIN_CHOICES,
            "cooking_method": COOKING_METHOD_CHOICES,
            "flavor_profile": FLAVOR_PROFILE_CHOICES,
        }
        for field_name, choices in choice_fields.items():
            value = data.get(field_name, "")
            setattr(
                recipe,
                field_name,
                value if value in {item[0] for item in choices} else "",
            )
        recipe.save(update_fields=list(choice_fields))
        return True
    except json.JSONDecodeError:
        logger.error("栄養価JSONパース失敗: %s", raw)
    except Exception as e:
        logger.error("栄養価取得エラー: %s", e)
    return False


@login_required
def recipe_list(request):
    recipes = Recipe.objects.prefetch_related("ingredients")

    # キーワード検索・ジャンル絞り込み
    query = request.GET.get("q", "").strip()
    genre1 = request.GET.get("genre1", "")
    genre2 = request.GET.get("genre2", "")

    if query:
        recipes = recipes.filter(name__icontains=query)
    if genre1:
        recipes = recipes.filter(genre1=genre1)
    if genre2:
        recipes = recipes.filter(genre2=genre2)

    return render(
        request,
        "recipes/list.html",
        {
            "recipes": recipes,
            "query": query,
            "genre1": genre1,
            "genre2": genre2,
        },
    )


@login_required
def recipe_create(request):
    if request.method == "POST":
        form = RecipeForm(request.POST)
        ingredient_formset = IngredientFormSet(request.POST, prefix="ingredients")
        step_formset = StepFormSet(request.POST, prefix="steps")

        if (
            form.is_valid()
            and ingredient_formset.is_valid()
            and step_formset.is_valid()
        ):
            recipe = form.save()
            ingredient_formset.instance = recipe
            ingredient_formset.save()

            # 手順の order を行番号で自動設定
            steps = step_formset.save(commit=False)
            for i, step in enumerate(steps, 1):
                step.order = i
                step.recipe = recipe
                step.save()
            for step in step_formset.deleted_objects:
                step.delete()

            # 栄養価をAIで自動取得
            _fetch_and_cache_nutrition(recipe)

            messages.success(request, f"「{recipe.name}」を登録しました。")
            return redirect("recipes:detail", pk=recipe.pk)
        else:
            messages.error(
                request, "入力内容にエラーがあります。赤字部分をご確認ください。"
            )
    else:
        form = RecipeForm()
        ingredient_formset = IngredientFormSet(prefix="ingredients")
        step_formset = StepFormSet(prefix="steps")

    return render(
        request,
        "recipes/form.html",
        {
            "form": form,
            "ingredient_formset": ingredient_formset,
            "step_formset": step_formset,
            "title": "献立を登録",
        },
    )


@login_required
def recipe_quick_create(request):
    if request.method == "POST":
        form = QuickRecipeForm(request.POST)
        if form.is_valid():
            recipe = form.save(commit=False)
            recipe.is_simple = True
            recipe.save()

            if form.cleaned_data["guess_details"]:
                try:
                    guessed = guess_ingredients_and_steps(recipe.name, recipe.servings)
                    Ingredient.objects.bulk_create(
                        [
                            Ingredient(
                                recipe=recipe,
                                name=item["name"],
                                quantity=item["quantity"],
                                unit=item["unit"],
                                amount_text=item["amount_text"],
                            )
                            for item in guessed["ingredients"]
                        ]
                    )
                    Step.objects.bulk_create(
                        [
                            Step(recipe=recipe, order=order, description=description)
                            for order, description in enumerate(guessed["steps"], 1)
                        ]
                    )
                except Exception as exc:
                    logger.error("市販品の材料・手順推測エラー: %s", exc)
                    recipe.ingredients.all().delete()
                    recipe.steps.all().delete()
                    Step.objects.create(
                        recipe=recipe,
                        order=1,
                        description="パッケージの記載手順に従って調理する",
                    )

            _fetch_and_cache_nutrition(recipe)

            messages.success(request, f"「{recipe.name}」をクイック登録しました。")
            return redirect("recipes:detail", pk=recipe.pk)
        messages.error(
            request, "入力内容にエラーがあります。赤字部分をご確認ください。"
        )
    else:
        form = QuickRecipeForm()

    return render(request, "recipes/quick_form.html", {"form": form})


@login_required
def recipe_detail(request, pk):
    recipe = get_object_or_404(
        Recipe.objects.prefetch_related("ingredients", "steps"), pk=pk
    )
    nutrition = NutritionCache.objects.filter(recipe_name=recipe.name).first()

    # 材料をグループ別に整理（グループなし→各グループの順）
    ingredients = list(recipe.ingredients.all())
    ungrouped = [i for i in ingredients if not i.group]
    grouped_dict = {}
    for i in ingredients:
        if i.group:
            grouped_dict.setdefault(i.group, []).append(i)
    grouped_ingredients = []
    if ungrouped:
        grouped_ingredients.append(("", ungrouped))
    for group_name, items in grouped_dict.items():
        grouped_ingredients.append((group_name, items))

    return render(
        request,
        "recipes/detail.html",
        {
            "recipe": recipe,
            "nutrition": nutrition,
            "grouped_ingredients": grouped_ingredients,
        },
    )


@login_required
def recipe_edit(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk)

    if request.method == "POST":
        old_name = recipe.name  # 名前変更検出のため保存前に記録
        form = RecipeForm(request.POST, instance=recipe)
        ingredient_formset = IngredientFormSet(
            request.POST, instance=recipe, prefix="ingredients"
        )
        step_formset = StepFormSet(request.POST, instance=recipe, prefix="steps")

        if (
            form.is_valid()
            and ingredient_formset.is_valid()
            and step_formset.is_valid()
        ):
            form.save()
            ingredient_formset.save()

            # 手順の保存（削除チェック分も含めてformsetに任せる）
            step_formset.save()
            # 残った手順の order を振り直す
            for i, step in enumerate(recipe.steps.all(), 1):
                if step.order != i:
                    step.order = i
                    step.save()

            # 栄養価をAIで自動取得（内容変更があるためキャッシュを更新）
            _fetch_and_cache_nutrition(recipe, old_name=old_name)

            messages.success(request, f"「{recipe.name}」を更新しました。")
            return redirect("recipes:detail", pk=recipe.pk)
        else:
            messages.error(
                request, "入力内容にエラーがあります。赤字部分をご確認ください。"
            )
    else:
        form = RecipeForm(instance=recipe)
        ingredient_formset = IngredientFormSet(instance=recipe, prefix="ingredients")
        step_formset = StepFormSet(instance=recipe, prefix="steps")

    return render(
        request,
        "recipes/form.html",
        {
            "form": form,
            "ingredient_formset": ingredient_formset,
            "step_formset": step_formset,
            "title": "献立を編集",
            "recipe": recipe,
        },
    )


@login_required
def recipe_delete(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk)
    if request.method == "POST":
        name = recipe.name
        recipe.delete()
        # 同名の献立が他に残っていなければ栄養価キャッシュも片付ける
        if not Recipe.objects.filter(name=name).exists():
            NutritionCache.objects.filter(recipe_name=name).delete()
        messages.success(request, f"「{name}」を削除しました。")
        return redirect("recipes:list")
    return render(request, "recipes/confirm_delete.html", {"recipe": recipe})


@login_required
def get_nutrition(request, pk):
    """栄養価キャッシュをJSONで返す。無ければ推定して保存してから返す。

    推定処理は登録・編集時と同じ `_fetch_and_cache_nutrition` に一本化している
    （以前はここだけ5項目のプロンプトを持っており、fiber・vegetables_g が欠けた
    不完全なキャッシュを作ってしまう状態だった）。
    """
    recipe = get_object_or_404(Recipe, pk=pk)

    cached = NutritionCache.objects.filter(recipe_name=recipe.name).first()
    was_cached = cached is not None
    if not was_cached:
        if not _fetch_and_cache_nutrition(recipe):
            return JsonResponse({"error": "栄養価の取得に失敗しました。"}, status=500)
        cached = NutritionCache.objects.filter(recipe_name=recipe.name).first()

    return JsonResponse(
        {
            "cached": was_cached,
            "calories": cached.calories,
            "protein": cached.protein,
            "fat": cached.fat,
            "carbs": cached.carbs,
            "salt": cached.salt,
            "fiber": cached.fiber,
            "vegetables_g": cached.vegetables_g,
        }
    )


@login_required
def read_recipe_image(request):
    """手書きレシピ画像をAIで読み取り、JSONで返す。"""
    if request.method != "POST":
        return JsonResponse({"error": "POSTのみ対応しています。"}, status=405)

    image_file = request.FILES.get("image")
    if not image_file:
        return JsonResponse({"error": "画像ファイルが送信されていません。"}, status=400)

    try:
        data = extract_recipe_info(image_file)
        return JsonResponse(data)
    except RecipeReadError as e:
        logger.error("レシピ読み取りエラー: %s", e)
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.error("レシピ読み取り予期せぬエラー: %s", e)
        return JsonResponse({"error": "レシピの読み取りに失敗しました。"}, status=500)


@login_required
def read_recipe_url(request):
    """レシピURLからJSON-LD等を解析し、レシピ情報をJSONで返す。"""
    if request.method != "POST":
        return JsonResponse({"error": "POSTのみ対応しています。"}, status=405)

    url = request.POST.get("url", "").strip()
    if not url:
        return JsonResponse({"error": "URLが入力されていません。"}, status=400)

    try:
        data = fetch_recipe_from_url(url)
        return JsonResponse(data)
    except RecipeURLError as e:
        logger.error("レシピURL解析エラー: %s", e)
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        logger.error("レシピURL解析 予期せぬエラー: %s", e)
        return JsonResponse({"error": "レシピURLの解析に失敗しました。"}, status=500)
