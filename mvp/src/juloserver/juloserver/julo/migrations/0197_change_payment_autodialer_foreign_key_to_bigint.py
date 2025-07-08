from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0196_auto_20180316_1535'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE payment_autodialer_session_status ALTER COLUMN payment_id TYPE BIGINT;"),
    ]
