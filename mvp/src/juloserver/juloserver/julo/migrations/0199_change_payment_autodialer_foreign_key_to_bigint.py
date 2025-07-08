from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0198_auto_20180319_1218'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE payment_autodialer_session ALTER COLUMN payment_id TYPE BIGINT;"),
    ]
