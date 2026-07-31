import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def split_slots(apps, schema_editor):
    slot_model = apps.get_model("planner", "MealPlanSlot")
    for slot in list(slot_model.objects.all().order_by("plan_id", "order")):
        main_id = slot.main_recipe_id
        side_id = slot.side_recipe_id
        slot.slot_type = "main"
        slot.recipe_id = main_id
        slot.save(update_fields=["slot_type", "recipe"])
        slot_model.objects.create(
            plan_id=slot.plan_id,
            slot_type="side",
            order=slot.order,
            start_date=slot.start_date,
            days=slot.days,
            recipe_id=side_id,
            reason=slot.reason,
        )


def merge_slots(apps, schema_editor):
    slot_model = apps.get_model("planner", "MealPlanSlot")
    for main in list(slot_model.objects.filter(slot_type="main")):
        side = slot_model.objects.filter(
            plan_id=main.plan_id, slot_type="side", order=main.order
        ).first()
        main.main_recipe_id = main.recipe_id
        main.side_recipe_id = side.recipe_id if side else None
        main.save(update_fields=["main_recipe", "side_recipe"])
        if side:
            side.delete()


class Migration(migrations.Migration):
    dependencies = [("planner", "0003_mealplanslot_start_date")]

    operations = [
        migrations.RemoveConstraint(
            model_name="mealplanslot", name="unique_plan_slot_order"
        ),
        migrations.AddField(
            model_name="mealplan",
            name="shopping_list",
            field=models.TextField(blank=True, verbose_name="買い物リスト"),
        ),
        migrations.AddField(
            model_name="mealplan",
            name="shopping_list_generated_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="買い物リスト生成日時"
            ),
        ),
        migrations.AddField(
            model_name="mealplanslot",
            name="recipe",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="plan_slots",
                to="recipes.recipe",
                verbose_name="献立",
            ),
        ),
        migrations.AddField(
            model_name="mealplanslot",
            name="slot_type",
            field=models.CharField(
                choices=[("main", "主菜"), ("side", "副菜")],
                max_length=10,
                null=True,
                verbose_name="レーン",
            ),
        ),
        migrations.RunPython(split_slots, merge_slots),
        migrations.RemoveField(model_name="mealplanslot", name="main_recipe"),
        migrations.RemoveField(model_name="mealplanslot", name="side_recipe"),
        migrations.AlterField(
            model_name="mealplanslot",
            name="slot_type",
            field=models.CharField(
                choices=[("main", "主菜"), ("side", "副菜")],
                max_length=10,
                verbose_name="レーン",
            ),
        ),
        migrations.AlterField(
            model_name="mealplanslot",
            name="days",
            field=models.PositiveIntegerField(
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(7),
                ],
                verbose_name="日数",
            ),
        ),
        migrations.AddConstraint(
            model_name="mealplanslot",
            constraint=models.UniqueConstraint(
                fields=("plan", "slot_type", "order"),
                name="unique_plan_lane_slot_order",
            ),
        ),
    ]
