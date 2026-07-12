"""ローカルテスト専用設定。

本番と共用の PostgreSQL に接続せず、テスト用の一時 SQLite DB を使う。
"""

from .settings import *  # noqa: F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# テスト中はメールを外部送信せず、メモリ内に保持する。
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
