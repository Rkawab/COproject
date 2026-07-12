"""ingredient テーブルに quantity, unit, amount_text フィールドを追加する。"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recipes", "0003_alter_recipe_genre2"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingredient",
            name="quantity",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=7,
                null=True,
                verbose_name="数量",
            ),
        ),
        migrations.AddField(
            model_name="ingredient",
            name="unit",
            field=models.CharField(blank=True, max_length=20, verbose_name="単位"),
        ),
        migrations.AddField(
            model_name="ingredient",
            name="amount_text",
            field=models.CharField(
                blank=True, max_length=50, verbose_name="テキスト分量"
            ),
        ),
    ]
