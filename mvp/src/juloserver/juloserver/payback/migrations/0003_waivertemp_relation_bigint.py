# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('payback', '0002_waivertemp'),
    ]

    operations = [
        migrations.RunSQL("ALTER TABLE waiver_temp ALTER COLUMN loan_id TYPE bigint;"),
        migrations.RunSQL("ALTER TABLE waiver_temp ALTER COLUMN payment_id TYPE bigint;"),
    ]