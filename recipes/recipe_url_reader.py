"""レシピURLからレシピ情報を抽出するモジュール。

JSON-LD（Schema.org Recipe）を優先的に解析し、
見つからない場合はサイト固有のパーサー（Nadia等）にフォールバックする。
"""

import json
import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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
            "ingredients": [{"name": str, "amount": str, "group": str}, ...],
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

    # 材料
    ingredients = []
    for item in data.get("recipeIngredient", []):
        parsed = _parse_ingredient_text(str(item))
        ingredients.append(parsed)

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

    # 材料
    ingredients = []
    for item in recipe.get("ingredients", []):
        ingredients.append({
            "name": item.get("name", ""),
            "amount": item.get("amount", "") + item.get("memo", ""),
            "group": item.get("kubun", "") or "",
        })

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


def _parse_ingredient_text(text):
    """「鶏もも肉 300g」のようなテキストを名前と分量に分割する。"""
    text = text.strip()
    # よくあるパターン: 「材料名 分量」または「材料名：分量」
    match = re.match(r"^(.+?)\s+([\d０-９].*)$", text)
    if match:
        return {"name": match.group(1).strip(), "amount": match.group(2).strip(), "group": ""}

    # 区切り文字で分割
    for sep in ["：", ":", "…", "−", "–"]:
        if sep in text:
            parts = text.split(sep, 1)
            return {"name": parts[0].strip(), "amount": parts[1].strip(), "group": ""}

    return {"name": text, "amount": "", "group": ""}


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
