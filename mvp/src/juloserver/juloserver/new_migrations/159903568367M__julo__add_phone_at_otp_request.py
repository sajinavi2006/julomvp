# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-03-06 04:43
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE loan_disburse_invoices ALTER COLUMN loan_id TYPE bigint;"),
    ]
