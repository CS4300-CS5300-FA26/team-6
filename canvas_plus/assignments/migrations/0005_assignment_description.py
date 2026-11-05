from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0004_assignment_effort_estimate_source_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="assignment",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]