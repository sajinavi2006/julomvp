# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-02-26 09:56
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0361_load_laku6_product'),
    ]

    operations = [
        migrations.AddField(
            model_name='offer',
            name='last_installment_amount',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
