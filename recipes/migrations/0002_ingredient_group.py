from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recipes", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingredient",
            name="group",
            field=models.CharField(blank=True, max_length=20, verbose_name="グループ"),
        ),
    ]
