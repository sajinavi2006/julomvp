# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-05-08 08:53
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0425_payment_is_whatsapp_blasted_flag'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payment',
            name='is_whatsapp_blasted',
            field=models.NullBooleanField(),
        ),
    ]
