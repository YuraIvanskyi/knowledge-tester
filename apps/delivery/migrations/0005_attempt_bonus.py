from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("delivery", "0004_attempt_away"),
    ]

    operations = [
        migrations.AddField(
            model_name="attempt",
            name="bonus_points",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=8),
        ),
        migrations.AddField(
            model_name="attempt",
            name="bonus_note",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
