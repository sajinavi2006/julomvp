# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-04-02 08:47
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cootek', '0003_initial_cootek_config_data'),
    ]

    operations = [
        migrations.RenameField(
            model_name='cootekconfiguration',
            old_name='task_name',
            new_name='strategy_name',
        ),
    ]
