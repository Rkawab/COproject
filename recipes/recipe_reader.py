import base64
import json
from mimetypes import guess_type
from typing import BinaryIO

from django.conf import settings
from openai import OpenAI


class RecipeReadError(Exception):
    """レシピ画像の読み取りに失敗したときに投げる例外."""
    pass


client = OpenAI(api_key=settings.OPENAI_API_KEY)


def _file_to_data_url(image_file: BinaryIO) -> str:
    """Django の UploadedFile を data URL に変換。"""
    data = image_file.read()

    mime_type = getattr(image_file, "content_type", None)
    if not mime_type:
        mime_type, _ = guess_type(getattr(image_file, "name", ""))
    if not mime_type:
        mime_type = "image/jpeg"

    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


def extract_recipe_info(image_file: BinaryIO) -> dict:
    """
    手書きレシピノートの画像から献立情報を抽出して返す。

    戻り値の dict 例:
    {
        "name": "肉じゃが",
        "genre1": "和食",
        "genre2": "主菜",
        "genre3": "肉系",
        "servings": 2,
        "ingredients": [
            {"name": "じゃがいも", "quantity": 3, "unit": "個", "amount_text": "", "group": ""},
            {"name": "醤油", "quantity": 2, "unit": "大さじ", "amount_text": "", "group": "A"},
            {"name": "塩", "quantity": None, "unit": "", "amount_text": "少々", "group": ""},
        ],
        "steps": [
            "じゃがいもの皮をむいて一口大に切る。",
            "鍋に油を熱し、肉を炒める。",
            "(A) を加えて煮込む。",
        ]
    }
    """
    data_url = _file_to_data_url(image_file)

    user_prompt = """
これは手書きの料理レシピノートの画像です。内容を読み取って、以下の情報を JSON で返してください。

- name: 料理名（文字列）
- genre1: ジャンル1。必ず次のどれか一つ: 「和食」「洋食」「中華」「スイーツ」
- genre2: ジャンル2。必ず次のどれか一つ: 「主食」「主菜」「副菜」「汁物」
- genre3: ジャンル3（genre2 が「主菜」の場合のみ）。次のどれか: 「肉系」「魚系」「」。主菜でなければ空文字。
- servings: 何人分か（整数）
- ingredients: 材料の配列。各要素は以下の形式:
  {"name": "材料名", "quantity": 数値またはnull, "unit": "単位", "amount_text": "テキスト分量", "group": "グループ"}
  * quantity: 数値化できる分量の数値部分（例: 2, 200, 0.5）。数値化できない場合は null。
  * unit: 単位（例: "大さじ", "g", "個", "本"）。数値化できない場合は空文字 ""。
  * amount_text: 数値化できない分量（例: "適量", "少々", "ひとつまみ"）。数値がある場合は空文字 ""。
  * quantity と amount_text は排他的: どちらか一方のみ値を入れる。
  * group について: レシピで (A) や (B) のようにまとめられた調味料グループがある場合、そのグループ名を入れる（例: "A", "B"）。グループに属さない材料は空文字 "" にする。
- steps: 手順の配列（文字列の配列）。番号は不要、手順の内容だけを入れる。

読み取りのルール:
- 手書き文字が多少読みにくくても、文脈から推測して埋めてください。
- 分量は数値と単位に分けてください。例: 「大さじ1」→ quantity=1, unit="大さじ"、「200g」→ quantity=200, unit="g"
- 分数は小数に変換してください。例: 「1/2」→ 0.5、「小さじ1/2」→ quantity=0.5, unit="小さじ"
- 「適量」「少々」「ひとつまみ」など数値化できない分量は amount_text に入れ、quantity は null にしてください。
- 略語表記（例: 大1 = 大さじ1）も可能な限り展開してください。
- 分量は手順に書いてある場合もあります。手順からも分量を読み取って ingredients に反映してください。
- 調味料グループ（A, B など）がある場合は、必ず ingredients の group フィールドに反映してください。
  * 「(A)」「【A】」「☆」「★」「◎」「〇」「●」などの記号がグループを示す場合がある。
  * 記号がグループの場合、name からその記号を除去すること。
- 手順中の「(A) を加える」のような表記はそのまま残してください。
- 文章は省略して書かれているものも多いため、適宜文章構成を変更しても構いませんが、意味が変わらないようにしてください。

必ず JSON のみを返してください（説明文不要）:

{
  "name": "料理名",
  "genre1": "和食",
  "genre2": "主菜",
  "genre3": "肉系",
  "servings": 2,
  "ingredients": [
    {"name": "材料名", "quantity": 2, "unit": "大さじ", "amount_text": "", "group": ""},
    {"name": "塩", "quantity": null, "unit": "", "amount_text": "少々", "group": ""}
  ],
  "steps": ["手順1", "手順2"]
}
    """.strip()

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an assistant that reads handwritten Japanese recipe notes "
                        "and extracts structured data. Respond ONLY in JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=2000,
        )
    except Exception as e:
        raise RecipeReadError(f"AI呼び出しでエラーが発生しました: {e}")

    content = response.choices[0].message.content

    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        raise RecipeReadError("AIの応答をJSONとして解釈できませんでした。")

    # 必須キーのチェック
    for key in ("name", "genre1", "genre2", "servings", "ingredients", "steps"):
        if key not in obj:
            raise RecipeReadError(f"AIの応答に '{key}' が含まれていません。")

    # genre3 のデフォルト
    if "genre3" not in obj:
        obj["genre3"] = ""

    # servings を整数に
    try:
        obj["servings"] = int(obj["servings"])
    except (TypeError, ValueError):
        raise RecipeReadError(f"人数を整数に変換できません: {obj['servings']}")

    # ingredients の正規化
    ingredients = []
    for item in obj["ingredients"]:
        qty = item.get("quantity")
        # 数値変換（文字列で返ってきた場合の対応）
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
    obj["ingredients"] = ingredients

    # steps の正規化
    obj["steps"] = [str(s) for s in obj["steps"]]

    return obj
