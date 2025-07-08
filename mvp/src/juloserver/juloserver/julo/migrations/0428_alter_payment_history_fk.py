from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0427_create_payment_history_table'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE payment_history ALTER COLUMN payment_id TYPE bigint;"),
        migrations.RunSQL(
            "ALTER TABLE payment_history ALTER COLUMN loan_id TYPE bigint;"),
        migrations.RunSQL(
            "ALTER TABLE payment_history ALTER COLUMN application_id TYPE bigint;"),
    ]