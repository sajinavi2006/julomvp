from __future__ import unicode_literals

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('payment_status', '0003_auto_20171218_1108'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE payment_locked_master ALTER COLUMN payment_id TYPE bigint;"),
        migrations.RunSQL(
            "ALTER TABLE payment_locked ALTER COLUMN payment_id TYPE bigint;"),
    ]
