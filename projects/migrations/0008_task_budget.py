from django.db import migrations, models
from django.db.models import F


def fill_budgets(apps, schema_editor):
    """Tasks written before the budget was kept separately: the best we know is the current price."""
    Task = apps.get_model("projects", "Task")
    Task.objects.filter(budget__isnull=True).update(budget=F("price"))


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0007_application_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="budget",
            field=models.DecimalField(decimal_places=7, max_digits=18, null=True),
        ),
        migrations.RunPython(fill_budgets, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="task",
            name="budget",
            field=models.DecimalField(decimal_places=7, max_digits=18),
        ),
    ]
