# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-03-28 10:53
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0399_add_birth_place_feature'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='teaser_loan_amount',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='teaser_loan_amount',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
