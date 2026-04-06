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

    class Meta:
        model = Ingredient
        fields = ["name", "quantity", "unit", "amount_text", "group"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "材料名",
            }),
            "quantity": forms.NumberInput(attrs={
                "class": "form-control", "placeholder": "数量",
                "step": "any", "min": "0",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 入力欄の初期値から不要な小数桁を除去（200.00 → 200、1.50 → 1.5）
        if self.instance and self.instance.quantity is not None:
            self.initial["quantity"] = Ingredient._format_quantity_plain(self.instance.quantity)

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
