"""レシピURLからレシピ情報を抽出するモジュール。

JSON-LD（Schema.org Recipe）を優先的に解析し、
見つからない場合はサイト固有のパーサー（Nadia等）にフォールバックする。
材料テキストの名前・分量・グループへの分割にはOpenAI APIを使用する。
"""

import json
import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)

client = OpenAI(api_key=settings.OPENAI_API_KEY)

# ジャンル推測用のキーワードマッピング
GENRE1_KEYWORDS = {
    "和食": ["和食", "和風", "醤油", "味噌", "出汁", "だし", "煮物", "焼き魚", "japanese"],
    "洋食": ["洋食", "洋風", "パスタ", "グラタン", "シチュー", "ハンバーグ", "western", "italian", "french"],
    "中華": ["中華", "中国", "炒め", "麻婆", "餃子", "チャーハン", "chinese"],
    "スイーツ": ["スイーツ", "デザート", "ケーキ", "クッキー", "プリン", "dessert", "sweet", "sweets"],
}

GENRE2_MAP = {
    "主食": ["主食", "ご飯", "パスタ", "麺", "パン", "うどん", "そば", "丼"],
    "主菜": ["主菜", "メイン", "肉", "魚", "main"],
    "副菜": ["副菜", "サラダ", "サイド", "side", "付け合わせ"],
    "汁物": ["汁物", "スープ", "味噌汁", "soup"],
    "その他": ["デザート", "スイーツ", "ケーキ", "クッキー", "プリン", "お菓子", "ドリンク", "飲み物", "dessert", "sweet"],
}

GENRE3_MAP = {
    "肉系": ["肉", "鶏", "豚", "牛", "ひき肉", "ささみ", "もも肉"],
    "魚系": ["魚", "鮭", "サーモン", "まぐろ", "えび", "いか", "たこ", "seafood"],
}


class RecipeURLError(Exception):
    """レシピURL解析時のエラー"""
    pass


def fetch_recipe_from_url(url):
    """URLからレシピ情報を取得して辞書で返す。

    Returns:
        dict: {
            "name": str,
            "genre1": str,  # 和食/洋食/中華/スイーツ or ""
            "genre2": str,  # 主食/主菜/副菜/汁物 or ""
            "genre3": str,  # 肉系/魚系 or ""
            "servings": int or "",
            "ingredients": [{"name": str, "quantity": float|None, "unit": str, "amount_text": str, "group": str}, ...],
            "steps": [str, ...],
        }
    """
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RecipeURLError(f"URLの取得に失敗しました: {e}")

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # 1) JSON-LD（Schema.org Recipe）を探す
    recipe_data = _extract_jsonld_recipe(soup)
    if recipe_data:
        return _parse_jsonld_recipe(recipe_data)

    # 2) Nadia固有パーサー
    domain = urlparse(url).hostname or ""
    if "nadia" in domain:
        recipe_data = _extract_nadia_recipe(soup)
        if recipe_data:
            return recipe_data

    raise RecipeURLError(
        "このURLからレシピ情報を取得できませんでした。"
        "JSON-LDにRecipeスキーマが含まれていないサイトの可能性があります。"
    )


def _extract_jsonld_recipe(soup):
    """HTML内のJSON-LDからRecipeスキーマを抽出する。"""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        recipe = _find_recipe_in_jsonld(data)
        if recipe:
            return recipe
    return None


def _find_recipe_in_jsonld(data):
    """JSON-LDデータからRecipe型を再帰的に探す。"""
    if isinstance(data, dict):
        schema_type = data.get("@type", "")
        if isinstance(schema_type, list):
            schema_type = " ".join(schema_type)
        if "Recipe" in schema_type:
            return data
        # @graphの中を探す
        if "@graph" in data:
            return _find_recipe_in_jsonld(data["@graph"])
    elif isinstance(data, list):
        for item in data:
            result = _find_recipe_in_jsonld(item)
            if result:
                return result
    return None


def _parse_jsonld_recipe(data):
    """JSON-LD Recipeスキーマを共通フォーマットに変換する。"""
    name = data.get("name", "")

    # 材料（AIで分割）
    raw_ingredients = [str(item) for item in data.get("recipeIngredient", [])]
    ingredients = _parse_ingredients_with_ai(raw_ingredients)

    # 手順
    steps = []
    instructions = data.get("recipeInstructions", [])
    if isinstance(instructions, str):
        # テキストの場合は改行で分割
        steps = [s.strip() for s in instructions.split("\n") if s.strip()]
    elif isinstance(instructions, list):
        for inst in instructions:
            if isinstance(inst, str):
                steps.append(inst.strip())
            elif isinstance(inst, dict):
                # HowToStep / HowToSection
                if inst.get("@type") == "HowToSection":
                    for sub in inst.get("itemListElement", []):
                        text = sub.get("text", "") if isinstance(sub, dict) else str(sub)
                        if text.strip():
                            steps.append(text.strip())
                else:
                    text = inst.get("text", "")
                    if text.strip():
                        steps.append(text.strip())

    # 人数
    servings = _parse_servings(data.get("recipeYield", ""))

    # ジャンル推測
    category = data.get("recipeCategory", "")
    cuisine = data.get("recipeCuisine", "")
    hint_text = f"{name} {category} {cuisine}"
    genre1, genre2, genre3 = _guess_genres(hint_text, ingredients)

    return {
        "name": name,
        "genre1": genre1,
        "genre2": genre2,
        "genre3": genre3,
        "servings": servings,
        "ingredients": ingredients,
        "steps": steps,
    }


def _extract_nadia_recipe(soup):
    """Nadia（oceans-nadia.com）の__NEXT_DATA__からレシピを抽出する。"""
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        return None

    try:
        next_data = json.loads(script.string)
        recipe = next_data["props"]["pageProps"]["data"]["publishedRecipe"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    name = recipe.get("title", "")

    # 材料（Nadiaは amount が文字列なので AI パースで分割する）
    raw_ingredients = []
    nadia_groups = {}  # index -> group名
    for idx, item in enumerate(recipe.get("ingredients", [])):
        amount_str = (item.get("amount", "") + " " + item.get("memo", "")).strip()
        name = item.get("name", "")
        raw_ingredients.append(f"{name} {amount_str}".strip())
        kubun = item.get("kubun", "") or ""
        if kubun:
            nadia_groups[idx] = kubun
    ingredients = _parse_ingredients_with_ai(raw_ingredients)
    # Nadiaのグループ情報を復元
    for idx, ing in enumerate(ingredients):
        if idx in nadia_groups and not ing.get("group"):
            ing["group"] = nadia_groups[idx]

    # 手順
    steps = []
    for inst in sorted(recipe.get("instructions", []), key=lambda x: x.get("sortOrder", 0)):
        comment = inst.get("comment", "")
        # HTMLタグを除去
        comment = re.sub(r"<[^>]+>", "", comment).strip()
        if comment:
            steps.append(comment)

    # 人数
    servings = _parse_servings(recipe.get("numberOfServings", ""))

    # ジャンル推測
    recipe_type = recipe.get("recipeType", {})
    type_name = recipe_type.get("name", "") if isinstance(recipe_type, dict) else ""
    hint_text = f"{name} {type_name}"
    genre1, genre2, genre3 = _guess_genres(hint_text, ingredients)

    # Nadiaの recipeType.name は「副菜」「主菜」等が直接入っている場合がある
    if not genre2 and type_name in ("主食", "主菜", "副菜", "汁物", "その他"):
        genre2 = type_name

    return {
        "name": name,
        "genre1": genre1,
        "genre2": genre2,
        "genre3": genre3,
        "servings": servings,
        "ingredients": ingredients,
        "steps": steps,
    }


def _parse_ingredients_with_ai(raw_ingredients):
    """材料テキストのリストをOpenAI APIで名前・数量・単位・テキスト分量・グループに分割する。

    Args:
        raw_ingredients: ["鶏もも肉 300g", "醤油 大さじ1", ...] のような文字列リスト

    Returns:
        [{"name": "鶏もも肉", "quantity": 300, "unit": "g", "amount_text": "", "group": ""}, ...]
    """
    if not raw_ingredients:
        return []

    ingredient_lines = "\n".join(f"- {item}" for item in raw_ingredients)

    user_prompt = f"""
以下はレシピサイトから取得した材料テキストの一覧です。
各行を「材料名」「数量」「単位」「テキスト分量」「グループ」に分割して JSON 配列で返してください。

ルール:
- name: 材料名のみ。分量や単位は含めない。
- quantity: 数値化できる分量の数値部分（例: 2, 200, 0.5）。数値化できない場合は null。
  * 分数は小数に変換すること（1/2 → 0.5）。
- unit: 単位（例: "大さじ", "g", "個", "本"）。数値化できない場合は空文字 ""。
- amount_text: 数値化できない分量テキスト（例: "適量", "少々", "ひとつまみ"）。数値がある場合は空文字 ""。
  * quantity と amount_text は排他的: どちらか一方のみ値を入れること。
- group: 調味料グループ（A, B, タレ等）がある場合はそのグループ名。なければ空文字。
  * 「(A)」「【A】」「☆」「★」「◎」などの記号がグループを示す場合がある。
  * 記号がグループの場合、name からその記号を除去すること。
- 元のテキストに書かれている情報だけを使い、推測で材料を追加しないこと。

材料一覧:
{ingredient_lines}

必ず JSON 配列のみを返してください（説明文不要）:
[{{"name": "材料名", "quantity": 2, "unit": "大さじ", "amount_text": "", "group": ""}}]
    """.strip()

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an assistant that parses Japanese recipe ingredient text "
                        "into structured data. Respond ONLY in JSON."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=2000,
        )
    except Exception as e:
        logger.warning("材料のAI解析に失敗、フォールバック処理を使用: %s", e)
        return [{"name": item.strip(), "quantity": None, "unit": "", "amount_text": "", "group": ""} for item in raw_ingredients]

    content = response.choices[0].message.content

    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("AIの応答をJSONとして解釈できません、フォールバック処理を使用")
        return [{"name": item.strip(), "quantity": None, "unit": "", "amount_text": "", "group": ""} for item in raw_ingredients]

    # レスポンスが {"ingredients": [...]} の形式の場合にも対応
    if isinstance(obj, dict):
        for key in ("ingredients", "items", "data"):
            if key in obj and isinstance(obj[key], list):
                obj = obj[key]
                break
        else:
            # dictだがリストを含まない場合はフォールバック
            logger.warning("AIの応答が期待した形式ではありません")
            return [{"name": item.strip(), "quantity": None, "unit": "", "amount_text": "", "group": ""} for item in raw_ingredients]

    # 各要素を正規化
    ingredients = []
    for item in obj:
        qty = item.get("quantity")
        if qty is not None:
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                qty = None
        ingredients.append({
            "name": str(item.get("name", "")),
            "quantity": qty,
            "unit": str(item.get("unit", "")),
            "amount_text": str(item.get("amount_text", "")),
            "group": str(item.get("group", "")),
        })

    return ingredients


def _parse_servings(value):
    """人数をintに変換する。変換できなければ空文字を返す。"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"(\d+)", value)
        if match:
            return int(match.group(1))
    return ""


def _guess_genres(hint_text, ingredients):
    """料理名・カテゴリ・材料からジャンルを推測する。"""
    hint_text = hint_text.lower()
    ingredient_names = " ".join(i.get("name", "") for i in ingredients).lower()
    full_text = f"{hint_text} {ingredient_names}"

    # genre1: 和食/洋食/中華/スイーツ
    genre1 = ""
    for genre, keywords in GENRE1_KEYWORDS.items():
        if any(kw in full_text for kw in keywords):
            genre1 = genre
            break

    # genre2: 主食/主菜/副菜/汁物
    genre2 = ""
    for genre, keywords in GENRE2_MAP.items():
        if any(kw in full_text for kw in keywords):
            genre2 = genre
            break

    # genre3: 肉系/魚系（主菜のときだけ意味がある）
    genre3 = ""
    if genre2 == "主菜":
        for genre, keywords in GENRE3_MAP.items():
            if any(kw in full_text for kw in keywords):
                genre3 = genre
                break

    return genre1, genre2, genre3
