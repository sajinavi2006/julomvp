# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-11-22 03:25
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunSQL('ALTER SEQUENCE ops.lender_repayment_transaction_transaction_id_seq RESTART WITH 10000000'),
    ]
