# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-08-09 04:01
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0274_update_productlookup_mtl'),
    ]

    operations = [
        migrations.AddField(
            model_name='skiptracehistory',
            name='old_application_status',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
