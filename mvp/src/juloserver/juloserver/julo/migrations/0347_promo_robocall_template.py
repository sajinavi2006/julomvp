# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-01-28 09:48
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0347_auto_20190204_1631'),
    ]

    operations = [
        migrations.AddField(
            model_name='robocalltemplate',
            name='promo_end_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='robocalltemplate',
            name='promo_start_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='robocalltemplate',
            name='template_category',
            field=models.CharField(choices=[('PTP', 'PTP'), ('DEFAULT', 'Default'), ('PROMO', 'Promos')], default='DEFAULT', max_length=7),
        ),
    ]
