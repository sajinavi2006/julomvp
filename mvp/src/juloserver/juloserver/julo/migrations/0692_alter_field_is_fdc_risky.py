# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-07-07 01:21
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0691_add_product_partner_to_vendor_history'),
    ]

    operations = [
        migrations.AlterField(
            model_name='earlypaybackoffer',
            name='is_fdc_risky',
            field=models.NullBooleanField(),
        ),
        migrations.AlterField(
            model_name='fdcriskyhistory',
            name='is_fdc_risky',
            field=models.NullBooleanField(),
        ),
    ]
