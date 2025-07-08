# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('julo_privyid', '0002_privy_feature_setting'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE privy_document_data RENAME application TO application_id"),
    ]
