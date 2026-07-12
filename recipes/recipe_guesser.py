import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings

logger = logging.getLogger(__name__)

FALLBACK_STEP = "パッケージの記載手順に従って調理する"


class RecipeGuessError(Exception):
    """市販品の材料・手順を推測できなかった場合の例外。"""


def guess_ingredients_and_steps(name: str, servings: int) -> dict:
    prompt = f"""次の料理名から、市販品のパッケージ調理内容を推測してください。

料理名: {name}
人数: {servings}人前

料理名が市販品（ルウ・レトルト・パック等）を特定できる場合は identified=true とし、
パッケージ調理に自分で用意する材料を{servings}人前の分量付きで返してください。
手順は2〜4行の簡潔なものにしてください。
特定できない一般料理名なら identified=false としてください。
quantity は数値または null とし、適量・少々などは quantity=null、amount_text に入れてください。

以下のJSON形式のみで返答してください（説明文・コードブロック不要）:
{{"identified":true,"ingredients":[{{"name":"豚ひき肉","quantity":150,"unit":"g","amount_text":""}}],"steps":["手順1","手順2"]}}"""

    raw = ""
    try:
        import openai

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw.replace("```json", "").replace("```", "").strip())
        return _normalize_guess(data)
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        InvalidOperation,
    ) as exc:
        logger.error("市販品推測JSON解析失敗: %s (%s)", raw, exc)
        raise RecipeGuessError("AIの返答を解析できませんでした。") from exc
    except Exception as exc:
        logger.error("市販品推測APIエラー: %s", exc)
        raise RecipeGuessError("材料・手順の推測に失敗しました。") from exc


def _normalize_guess(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("identified") is not True:
        return {"identified": False, "ingredients": [], "steps": [FALLBACK_STEP]}

    ingredients = []
    for item in data.get("ingredients", []):
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            raise ValueError("材料データが不正です。")
        quantity = item.get("quantity")
        if quantity is not None:
            quantity = Decimal(str(quantity))
            amount_text = ""
        else:
            amount_text = str(item.get("amount_text", "")).strip()[:50]
        ingredients.append(
            {
                "name": str(item["name"]).strip()[:100],
                "quantity": quantity,
                "unit": str(item.get("unit", "")).strip()[:20]
                if quantity is not None
                else "",
                "amount_text": amount_text,
            }
        )

    steps = [str(step).strip() for step in data.get("steps", []) if str(step).strip()]
    if not steps:
        steps = [FALLBACK_STEP]
    return {"identified": True, "ingredients": ingredients, "steps": steps[:4]}
