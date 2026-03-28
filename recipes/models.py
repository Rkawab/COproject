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
    # 旧フィールド（移行完了後に削除予定。アプリ側では使用しない）
    amount = models.CharField(max_length=50, verbose_name="分量（旧）", blank=True)
    # 新フィールド: 数値化できる分量
    quantity = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="数量"
    )
    unit = models.CharField(max_length=20, verbose_name="単位", blank=True)
    # 新フィールド: 数値化できない分量（「適量」「少々」等）
    amount_text = models.CharField(max_length=50, verbose_name="テキスト分量", blank=True)
    group = models.CharField(max_length=20, verbose_name="グループ", blank=True)

    class Meta:
        db_table = "ingredient"

    @property
    def display_amount(self):
        """表示用の分量文字列を返す。"""
        if self.quantity is not None:
            # 整数なら小数点以下を省略（2.00 → "2"、1.50 → "1.5"）
            q = self.quantity.normalize()
            return f"{q}{self.unit}"
        if self.amount_text:
            return self.amount_text
        # フォールバック（旧データ）
        return self.amount

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
