# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-03-27 10:45
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunSQL('ALTER TABLE payback_transaction ALTER COLUMN payment_id TYPE bigint;'),
        migrations.RunSQL('ALTER TABLE payback_transaction ALTER COLUMN loan_id TYPE bigint;'),
        migrations.RunSQL('ALTER TABLE payback_transaction ALTER COLUMN customer_id TYPE bigint;'),
    ]
