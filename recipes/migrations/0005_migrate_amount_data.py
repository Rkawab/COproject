"""既存の amount フィールドをパースして quantity/unit/amount_text に振り分けるデータマイグレーション。"""

import re
from decimal import Decimal, InvalidOperation

from django.db import migrations


# 数値化できない分量キーワード
NON_NUMERIC = {"適量", "少々", "ひとつまみ", "お好みで", "適宜"}

# 日本語計量単位（前置型: 「大さじ2」のように単位が数値の前に来る）
PREFIX_UNITS = ["大さじ", "小さじ"]

# 後置型単位（数値の後に来る）
SUFFIX_UNITS = [
    "g",
    "ｇ",
    "ml",
    "mL",
    "ｍｌ",
    "cc",
    "ℓ",
    "L",
    "個",
    "本",
    "枚",
    "切",
    "切れ",
    "片",
    "丁",
    "房",
    "缶",
    "束",
    "袋",
    "合",
    "杯",
    "カット",
    "cm",
    "ｃｍ",
]

# 全角→半角変換テーブル（数字 + アルファベット単位文字）
ZEN_TO_HAN = str.maketrans(
    "０１２３４５６７８９．ｇｍｌＬｃ",
    "0123456789.gmlLc",
)


def parse_fraction(s):
    """分数文字列（例: "1/2"）をDecimalに変換。失敗したらNone。"""
    s = s.strip()
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2:
            try:
                return Decimal(parts[0].strip()) / Decimal(parts[1].strip())
            except (InvalidOperation, ZeroDivisionError):
                return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_amount(amount_str):
    """
    分量文字列をパースして (quantity, unit, amount_text) を返す。

    Returns:
        (Decimal or None, str, str)
    """
    if not amount_str or not amount_str.strip():
        return None, "", ""

    text = amount_str.strip()
    # 全角数字を半角に変換
    text_normalized = text.translate(ZEN_TO_HAN)

    # 完全一致で非数値キーワードチェック
    if text in NON_NUMERIC:
        return None, "", text

    # 前置型単位: 「大さじ1」「小さじ1/2」
    for unit in PREFIX_UNITS:
        pattern = rf"^{re.escape(unit)}\s*(\d+[\./]?\d*(?:/\d+)?)"
        m = re.match(pattern, text_normalized)
        if m:
            qty = parse_fraction(m.group(1))
            if qty is not None:
                return qty, unit, ""

    # 後置型: 「200g」「3個」「1/2丁」
    # パターン: (数値 or 分数)(単位)
    suffix_pattern = (
        r"^(\d+[\./]?\d*(?:/\d+)?)\s*("
        + "|".join(re.escape(u) for u in SUFFIX_UNITS)
        + r")$"
    )
    m = re.match(suffix_pattern, text_normalized)
    if m:
        qty = parse_fraction(m.group(1))
        unit = m.group(2)
        if qty is not None:
            # 全角単位を正規化
            unit_map = {"ｇ": "g", "ｍｌ": "ml", "ｃｍ": "cm"}
            unit = unit_map.get(unit, unit)
            return qty, unit, ""

    # 後置型（単位なし、数値+日本語カウンタ）: 「2切れ」「1片」等は上で処理済み

    # 修飾語付き: 「中1個」「大きめ3個」→ 数値+単位部分だけ抽出
    m = re.search(
        r"(\d+[\./]?\d*(?:/\d+)?)\s*("
        + "|".join(re.escape(u) for u in SUFFIX_UNITS)
        + r")",
        text_normalized,
    )
    if m:
        qty = parse_fraction(m.group(1))
        unit = m.group(2)
        if qty is not None:
            unit_map = {"ｇ": "g", "ｍｌ": "ml", "ｃｍ": "cm"}
            unit = unit_map.get(unit, unit)
            return qty, unit, ""

    # 前置型の部分一致（修飾語付き）
    for unit in PREFIX_UNITS:
        m = re.search(rf"{re.escape(unit)}\s*(\d+[\./]?\d*(?:/\d+)?)", text_normalized)
        if m:
            qty = parse_fraction(m.group(1))
            if qty is not None:
                return qty, unit, ""

    # パースできない → amount_text にフォールバック
    return None, "", text


def migrate_forward(apps, schema_editor):
    """既存の amount を新フィールドに変換する。"""
    Ingredient = apps.get_model("recipes", "Ingredient")
    for ing in Ingredient.objects.all():
        if not ing.amount:
            continue
        qty, unit, amount_text = parse_amount(ing.amount)
        ing.quantity = qty
        ing.unit = unit
        ing.amount_text = amount_text
        ing.save(update_fields=["quantity", "unit", "amount_text"])


def migrate_backward(apps, schema_editor):
    """ロールバック: 新フィールドをクリアするだけ（amount は残っている）。"""
    Ingredient = apps.get_model("recipes", "Ingredient")
    Ingredient.objects.all().update(quantity=None, unit="", amount_text="")


class Migration(migrations.Migration):
    dependencies = [
        ("recipes", "0004_ingredient_quantity_unit_amount_text"),
    ]

    operations = [
        migrations.RunPython(migrate_forward, migrate_backward),
    ]
