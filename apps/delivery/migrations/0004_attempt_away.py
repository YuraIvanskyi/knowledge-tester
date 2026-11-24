from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("delivery", "0003_attempt_variant"),
    ]

    operations = [
        migrations.AddField(
            model_name="attempt",
            name="away_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="attempt",
            name="away_seconds",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
