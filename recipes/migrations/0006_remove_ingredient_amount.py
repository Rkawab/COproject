"""ingredient テーブルから旧 amount フィールドを削除する。"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("recipes", "0005_migrate_amount_data"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="ingredient",
            name="amount",
        ),
    ]
