# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-09-14 07:38
from __future__ import unicode_literals

from django.db import migrations
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE merchant_historical_transaction ALTER COLUMN merchant_historical_transaction_id TYPE bigint;"),
    ]
