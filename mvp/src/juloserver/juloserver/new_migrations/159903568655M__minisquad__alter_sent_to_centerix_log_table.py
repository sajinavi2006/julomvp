from __future__ import unicode_literals
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE sent_to_centerix_log ALTER COLUMN payment_id TYPE bigint;"
        ),
        migrations.RunSQL(
            "ALTER TABLE sent_to_centerix_log ALTER COLUMN application_id TYPE bigint;"
        )
    ]
