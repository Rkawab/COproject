import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import forms
from django.forms import inlineformset_factory
from .models import Recipe, Ingredient, Step, GENRE1_CHOICES, GENRE2_CHOICES, GENRE3_CHOICES


class RecipeForm(forms.ModelForm):
    class Meta:
        model = Recipe
        fields = ["name", "genre1", "genre2", "genre3", "servings"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "例: 肉じゃが"}),
            "genre1": forms.Select(attrs={"class": "form-select"}),
            "genre2": forms.Select(attrs={"class": "form-select", "id": "id_genre2"}),
            "genre3": forms.Select(attrs={"class": "form-select", "id": "id_genre3"}),
            "servings": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 99}),
        }
        labels = {
            "name": "料理名",
            "genre1": "ジャンル1",
            "genre2": "ジャンル2",
            "genre3": "ジャンル3（主菜のときだけ）",
            "servings": "人数",
        }


class IngredientForm(forms.ModelForm):
    """材料フォーム。quantity+unit と amount_text の排他入力をバリデーション。"""

    # quantity を CharField にして分数テキスト入力（例: 1/2, 1 1/8）を受け付ける
    quantity = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "数量",
        }),
        label="数量",
    )

    class Meta:
        model = Ingredient
        fields = ["name", "quantity", "unit", "amount_text", "group"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "材料名",
            }),
            "unit": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "単位",
            }),
            "amount_text": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "適量 / 少々",
            }),
            "group": forms.TextInput(attrs={
                "class": "form-control form-control-sm group-input", "placeholder": "A / タレ…",
            }),
        }

    # Decimal → 分数文字列への変換マップ（フォーム表示用）
    _FRACTION_MAP = [
        (Decimal("0.125"), "1/8"),
        (Decimal("0.25"),  "1/4"),
        (Decimal("0.333"), "1/3"),
        (Decimal("0.375"), "3/8"),
        (Decimal("0.5"),   "1/2"),
        (Decimal("0.625"), "5/8"),
        (Decimal("0.667"), "2/3"),
        (Decimal("0.75"),  "3/4"),
        (Decimal("0.875"), "7/8"),
    ]

    @classmethod
    def _decimal_to_fraction_str(cls, q):
        """Decimal を分数文字列に変換（フォーム表示用）。例: 0.5 → "1/2"、1.5 → "1 1/2"。"""
        if q == q.to_integral_value():
            return str(int(q))
        whole = int(q)
        frac = q - whole
        for dec, frac_str in cls._FRACTION_MAP:
            if abs(frac - dec) < Decimal("0.005"):
                return f"{whole} {frac_str}" if whole > 0 else frac_str
        # マッチしない場合は不要な末尾ゼロを除いた小数で返す
        return Ingredient._format_quantity_plain(q)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 数値を分数文字列で表示（例: 0.5 → "1/2"、0.125 → "1/8"）
        if self.instance and self.instance.quantity is not None:
            self.initial["quantity"] = self._decimal_to_fraction_str(self.instance.quantity)

    def clean_quantity(self):
        """分数文字列（例: 1/2、1 1/8）または小数・整数を Decimal に変換する。"""
        value = self.cleaned_data.get("quantity", "")
        if not value or not value.strip():
            return None
        value = value.strip()

        # 帯分数: "1 1/2"、"2 3/4" など
        mixed = re.fullmatch(r'(\d+)\s+(\d+)/(\d+)', value)
        # 真分数: "1/2"、"3/8" など
        simple = re.fullmatch(r'(\d+)/(\d+)', value)

        if mixed:
            whole, num, den = int(mixed.group(1)), int(mixed.group(2)), int(mixed.group(3))
            if den == 0:
                raise forms.ValidationError("分母に0は使えません。")
            result = Decimal(whole) + Decimal(num) / Decimal(den)
        elif simple:
            num, den = int(simple.group(1)), int(simple.group(2))
            if den == 0:
                raise forms.ValidationError("分母に0は使えません。")
            result = Decimal(num) / Decimal(den)
        else:
            try:
                result = Decimal(value)
            except InvalidOperation:
                raise forms.ValidationError("数値または分数（例: 1/2、1 1/2）で入力してください。")

        return result.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    def clean(self):
        cleaned = super().clean()
        qty = cleaned.get("quantity")
        amount_text = cleaned.get("amount_text", "").strip()

        # 排他チェック: 両方入っている場合はエラー
        if qty is not None and amount_text:
            raise forms.ValidationError("「数量+単位」と「テキスト分量」は同時に入力できません。どちらか一方を入力してください。")

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        # 排他フィールドの整合性を保つ
        if instance.quantity is not None:
            instance.amount_text = ""
        elif instance.amount_text:
            instance.quantity = None
            instance.unit = ""
        if commit:
            instance.save()
        return instance


# 材料フォームセット（親: Recipe）
IngredientFormSet = inlineformset_factory(
    Recipe,
    Ingredient,
    form=IngredientForm,
    extra=3,
    can_delete=True,
)

# 手順フォームセット（親: Recipe）
StepFormSet = inlineformset_factory(
    Recipe,
    Step,
    fields=["order", "description"],
    extra=3,
    can_delete=True,
    widgets={
        "order": forms.HiddenInput(),
        "description": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "手順を入力"}),
    },
    labels={
        "description": "手順",
    },
)
