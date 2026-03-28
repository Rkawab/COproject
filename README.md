# 献立記録アプリ（Django）

このアプリケーションは、**家族で献立を記録・管理するための Django 製 Web アプリ**です。  
日々の料理をジャンル・材料・手順とともに記録し、キーワードやジャンルで検索できます。

また、登録した献立に対して **OpenAI API による栄養価の自動推定機能** を備えており、  
カロリー・たんぱく質・脂質・炭水化物・塩分（1人分）をワンクリックで取得できます。

---

## 📦 主な機能

### 🍽️ 献立管理
- **献立登録** - 料理名・ジャンル・人数・材料・手順を記録
- **献立一覧** - 登録順に一覧表示
- **献立詳細** - 材料（グループ別表示対応）・手順・栄養価をまとめて確認
- **献立編集・削除** - 登録内容の修正・削除
- **キーワード検索** - 料理名で絞り込み
- **ジャンル絞り込み** - 和食/洋食/中華/スイーツ、主食/主菜/副菜/汁物/その他で検索
- **材料グループ** - 材料を「A」「タレ」等のグループにまとめて管理（登録・詳細画面で視覚的に区別）

### 📷 手書きレシピ画像読み取り
- **AIによるレシピ画像OCR（OpenAI `gpt-4o-mini`）**
  - 手書きノートやレシピの写真をアップロードすると、AIが内容を読み取りフォームに自動入力
  - PC: ファイル選択ダイアログ / スマホ: カメラ撮影・写真ライブラリから選択

### 🔗 レシピURL読み取り
- **レシピサイトのURLから料理名・材料・手順を自動入力**
  - JSON-LD（Schema.org Recipe）を優先的に解析
  - Nadia（oceans-nadia.com）固有パーサーにも対応
  - ジャンル・人数の自動推測

### 🥗 栄養価推定
- **AIによる栄養価自動推定（OpenAI `gpt-4o-mini`）**
  - 料理名・人数・材料を元に1人分の栄養価を推定
  - 取得項目: カロリー（kcal）・たんぱく質・脂質・炭水化物・塩分（g）
  - 詳細画面の「栄養価を取得」ボタンで非同期取得
  - 同じ料理名は再取得しない（DBキャッシュ）

### 🔐 認証・セキュリティ
- ユーザー登録・認証（メール有効化付き）
- セキュアなカスタムユーザーモデル（`accounts.User`）
- BCrypt による安全なパスワードハッシュ
- `@login_required` によるアクセス制限
- CSRF 対策など Django 標準の安全機構

### 🎨 UI・UX
- Bootstrap 5 によるレスポンシブデザイン
- スマートフォン優先のUI
- 日本語完全対応

---

## 🗂️ ディレクトリ構成

```
COproject/
├── COproject/               # Django プロジェクト設定
│   ├── settings.py          # DB・認証・静的ファイル設定
│   ├── urls.py              # URL ルーティング
│   └── ...
│
├── accounts/                # ユーザー認証・管理アプリ
│   ├── models.py            # カスタムユーザーモデル
│   ├── forms.py             # 登録・ログイン・編集フォーム
│   ├── views.py             # 認証/登録/メール確認などの処理
│   └── ...
│
├── recipes/                 # 献立管理アプリ
│   ├── models.py            # Recipe・Ingredient・Step・NutritionCache モデル
│   ├── views.py             # 一覧・登録・詳細・編集・削除・栄養価取得・画像/URL読み取り
│   ├── forms.py             # RecipeForm・IngredientFormSet・StepFormSet
│   ├── recipe_reader.py     # 手書きレシピ画像のAI読み取り処理
│   ├── recipe_url_reader.py # レシピURL解析（JSON-LD / Nadia対応）
│   └── ...
│
├── templates/               # HTML テンプレート
│   ├── base.html            # 共通レイアウト
│   ├── includes/            # 共通パーツ（Bootstrap フォーム等）
│   ├── accounts/            # 認証関連テンプレート
│   └── recipes/             # 献立画面（一覧・詳細・フォーム・削除確認）
│
├── static/                  # CSS / JS など静的ファイル
│   └── css/custom.css
│
├── requirements.txt         # 依存パッケージ
├── manage.py
└── .gitignore
```

---

## 🖥️ 使用技術

- **バックエンド**: Python 3.12 / Django 5.2
- **データベース**: PostgreSQL（Supabase）
- **フロントエンド**: HTML5 / Bootstrap 5
- **スタイリング**: CSS3 + django-widget-tweaks
- **静的ファイル**: WhiteNoise
- **WSGIサーバ**: Gunicorn
- **環境管理**: python-dotenv
- **AI（栄養価推定）**: OpenAI API `gpt-4o-mini`

---

## 🔧 セットアップ方法

### 1. リポジトリをクローン

```bash
git clone https://github.com/Rkawab/COproject.git
cd COproject
```

### 2. 仮想環境を作成

```bash
python -m venv venv
source venv/bin/activate  # Windowsは venv\Scripts\activate
```

### 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 4. .env ファイルを作成

プロジェクトルートに `.env` を作成し、以下を記載：

```ini
SECRET_KEY=your-secret-key
DEBUG=True

user=your-db-user
password=your-db-password
host=your-db-host
port=5432
dbname=your-db-name

EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-email-app-password

SITE_URL=http://localhost:8000
OPENAI_API_KEY=your-openai-api-key
```

### 5. マイグレーションと管理ユーザー作成

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. ローカルサーバーで起動

```bash
python manage.py runserver
```

ブラウザで http://localhost:8000 にアクセス。

---

## 🚀 デプロイ

### 本番構成（Raspberry Pi）

```
[スマホ / PC]
     ↓ HTTPS
Cloudflare Tunnel（household-app-bacon.net）
     ↓ http://localhost:80
Nginx（/cooking/ → Gunicorn）
     ↓
Gunicorn（COproject）
     ↓
Supabase（PostgreSQL）
```

**注**: DS-Lite(transix)環境のためポートフォワード不可。Cloudflare Tunnelで公開。  
CHAproject（家計簿アプリ）と同一ドメイン・同一Tunnelで `/cooking/` パスに同居。

#### デプロイ手順（初回）


```bash
# 1. アプリ配置
sudo mkdir -p /opt/COproject && sudo chown isogo:isogo /opt/COproject
cd /opt/COproject && git clone https://github.com/Rkawab/COproject .

# 2. venv・パッケージ
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && pip install gunicorn

# 3. .env を作成（FORCE_SCRIPT_NAME=/cooking を必ず含める）

# 4. DB・静的ファイル
python manage.py migrate
python manage.py collectstatic --noinput

# 5. systemd サービス登録 → Nginx に /cooking/ ブロック追加
```

#### コード更新時

```bash
cd /opt/COproject && source venv/bin/activate
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart coproject
```

#### Pi上のサービス管理

```bash
sudo systemctl status coproject       # Gunicorn
sudo systemctl status nginx           # Nginx
sudo systemctl status cloudflared     # Cloudflare Tunnel

sudo journalctl -u coproject -n 50 --no-pager
```

#### Pi上の主要ファイルパス

| パス | 内容 |
|------|------|
| `/opt/COproject/` | アプリ本体 |
| `/opt/COproject/.env` | 環境変数 |
| `/etc/nginx/sites-available/chaproject` | Nginx設定（CHAprojectと共用） |
| `/etc/systemd/system/coproject.service` | Gunicorn systemd設定 |

---

## 📌 注意事項

- `DEBUG=False` にすること（本番環境）
- `.env` は Git に含めない（`.gitignore` に記載済み）
- 本番の `.env` に `FORCE_SCRIPT_NAME=/cooking` を必ず設定すること（ないとURL生成が壊れる）
- Supabase 無料プランは一定期間アクセスがないと DB が一時停止する場合あり

---

## 📝 ライセンス

MIT License

---

## 🙌 作者

- 名前：Rkawab
- GitHub: @Rkawab
