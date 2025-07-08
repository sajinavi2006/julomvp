# -*- coding: utf-8 -*-

from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0414_load_one_status_lookup'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE whatsapp_history ALTER COLUMN application_id TYPE bigint ;"),
        migrations.RunSQL(
            "ALTER TABLE whatsapp_history ALTER COLUMN customer_id TYPE bigint;"),
        migrations.RunSQL(
            "ALTER TABLE whatsapp_history ALTER COLUMN payment_id TYPE bigint;"),
    ]