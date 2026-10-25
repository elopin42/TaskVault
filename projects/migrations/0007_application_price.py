from django.db import migrations, models


def fill_prices(apps, schema_editor):
    """Applications written before freelances proposed a price bid the task's budget."""
    Application = apps.get_model("projects", "Application")
    for app in Application.objects.select_related("task").only("pk", "task__price"):
        Application.objects.filter(pk=app.pk).update(price=app.task.price)


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0006_project_published_cancelled"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="price",
            field=models.DecimalField(decimal_places=7, max_digits=18, null=True),
        ),
        migrations.RunPython(fill_prices, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="application",
            name="price",
            field=models.DecimalField(decimal_places=7, max_digits=18),
        ),
    ]
