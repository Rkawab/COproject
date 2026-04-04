from decimal import Decimal

from django.db import models

GENRE1_CHOICES = [
    ("和食", "和食"),
    ("洋食", "洋食"),
    ("中華", "中華"),
    ("スイーツ", "スイーツ"),
]

GENRE2_CHOICES = [
    ("主食", "主食"),
    ("主菜", "主菜"),
    ("副菜", "副菜"),
    ("汁物", "汁物"),
    ("その他", "その他"),
]

GENRE3_CHOICES = [
    ("", "---"),
    ("肉系", "肉系"),
    ("魚系", "魚系"),
]


class Recipe(models.Model):
    name = models.CharField(max_length=200, verbose_name="料理名")
    genre1 = models.CharField(max_length=20, choices=GENRE1_CHOICES, verbose_name="ジャンル1")
    genre2 = models.CharField(max_length=20, choices=GENRE2_CHOICES, verbose_name="ジャンル2")
    genre3 = models.CharField(max_length=20, choices=GENRE3_CHOICES, blank=True, verbose_name="ジャンル3")
    servings = models.PositiveIntegerField(verbose_name="人数")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "recipe"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Ingredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    name = models.CharField(max_length=100, verbose_name="材料名")
    quantity = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="数量"
    )
    unit = models.CharField(max_length=20, verbose_name="単位", blank=True)
    # 新フィールド: 数値化できない分量（「適量」「少々」等）
    amount_text = models.CharField(max_length=50, verbose_name="テキスト分量", blank=True)
    group = models.CharField(max_length=20, verbose_name="グループ", blank=True)

    class Meta:
        db_table = "ingredient"

    # Unicode分数パターン（料理で使う一般的な分数）
    _UNICODE_FRACS = [
        (Decimal("0.25"), "\u00BC"),  # ¼
        (Decimal("0.33"), "\u2153"),  # ⅓
        (Decimal("0.34"), "\u2153"),  # ⅓（丸め誤差対応）
        (Decimal("0.50"), "\u00BD"),  # ½
        (Decimal("0.66"), "\u2154"),  # ⅔
        (Decimal("0.67"), "\u2154"),  # ⅔（丸め誤差対応）
        (Decimal("0.75"), "\u00BE"),  # ¾
    ]
    # 分数表示する単位
    _FRAC_UNITS = {"本", "個", "枚", "株", "束", "片", "丁", "玉", "缶", "袋",
                   "パック", "切れ", "切", "大さじ", "小さじ", "カップ", "合", "房"}
    # 整数丸めする単位
    _ROUND_UNITS = {"g", "kg", "ml", "mL", "cc", "L"}

    @staticmethod
    def _format_quantity_plain(q):
        """Decimal を見やすい文字列にする（指数表記を回避）。"""
        normalized = q.normalize()
        if normalized == normalized.to_integral_value():
            return str(int(normalized))
        return str(normalized)

    def _format_quantity_smart(self, q):
        """単位に応じてUnicode分数や整数丸めで表示する。"""
        if self.unit in self._FRAC_UNITS:
            whole = int(q)
            frac = q - whole
            # ほぼ整数
            if frac < Decimal("0.05"):
                return str(whole)
            if frac > Decimal("0.95"):
                return str(whole + 1)
            # Unicode分数パターンに一致するか
            for threshold, char in self._UNICODE_FRACS:
                if abs(frac - threshold) < Decimal("0.05"):
                    return (str(whole) if whole > 0 else "") + char
            # 不一致: 小数1桁に丸めて「約」付き
            return f"約{float(q):.1f}"
        if self.unit in self._ROUND_UNITS:
            return str(round(q))
        # その他: 従来表示
        return self._format_quantity_plain(q)

    @property
    def display_amount(self):
        """表示用の分量文字列を返す。"""
        if self.quantity is not None:
            return f"{self._format_quantity_smart(self.quantity)}{self.unit}"
        if self.amount_text:
            return self.amount_text
        return ""

    @property
    def is_scalable(self):
        """スケーリング可能かどうか。"""
        return self.quantity is not None

    def __str__(self):
        return f"{self.name} {self.display_amount}"


class Step(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField(verbose_name="順番")
    description = models.TextField(verbose_name="手順")

    class Meta:
        db_table = "step"
        ordering = ["order"]

    def __str__(self):
        return f"{self.order}: {self.description[:30]}"


class NutritionCache(models.Model):
    recipe_name = models.CharField(max_length=200, unique=True, verbose_name="料理名")
    calories = models.FloatField(null=True, blank=True, verbose_name="カロリー(kcal/人)")
    protein = models.FloatField(null=True, blank=True, verbose_name="たんぱく質(g/人)")
    fat = models.FloatField(null=True, blank=True, verbose_name="脂質(g/人)")
    carbs = models.FloatField(null=True, blank=True, verbose_name="炭水化物(g/人)")
    salt = models.FloatField(null=True, blank=True, verbose_name="塩分(g/人)")
    raw_response = models.TextField(blank=True, verbose_name="APIレスポンス")
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "nutrition_cache"

    def __str__(self):
        return self.recipe_name
