from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE promo_history ALTER COLUMN payment_id TYPE bigint;"
        ),
    ]
