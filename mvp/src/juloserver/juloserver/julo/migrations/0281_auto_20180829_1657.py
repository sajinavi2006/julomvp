# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-08-29 09:57
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0280_auto_20180824_0958'),
    ]

    operations = [
        migrations.AddField(
            model_name='dashboardbuckets',
            name='payment_Tminus1',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='dashboardbuckets',
            name='payment_Tminus3',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='dashboardbuckets',
            name='payment_Tminus5',
            field=models.IntegerField(default=0),
        ),
    ]
