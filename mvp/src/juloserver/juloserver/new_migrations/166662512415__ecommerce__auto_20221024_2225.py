# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-10-24 15:25
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
    ]

    state_operations = [
        migrations.RemoveField(
            model_name='juloshopstatushistory',
            name='changed_by',
        ),
        migrations.RemoveField(
            model_name='juloshoptransaction',
            name='order_status',
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=state_operations
        )
    ]
