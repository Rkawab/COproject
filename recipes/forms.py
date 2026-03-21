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


# 材料フォームセット（親: Recipe）
IngredientFormSet = inlineformset_factory(
    Recipe,
    Ingredient,
    fields=["name", "amount", "group"],
    extra=3,
    can_delete=True,
    widgets={
        "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "材料名"}),
        "amount": forms.TextInput(attrs={"class": "form-control", "placeholder": "例: 大さじ1 / 100g / 適量"}),
        "group": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "A / タレ…"}),
    },
    labels={
        "name": "材料名",
        "amount": "分量",
        "group": "グループ",
    },
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
