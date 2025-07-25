# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-06 09:06
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
    ]

    state_operations = [
        migrations.RemoveField(
            model_name='graduationcustomerhistory',
            name='account',
        ),
        migrations.RemoveField(
            model_name='graduationcustomerhistory',
            name='available_limit_history',
        ),
        migrations.RemoveField(
            model_name='graduationcustomerhistory',
            name='max_limit_history',
        ),
        migrations.RemoveField(
            model_name='graduationcustomerhistory',
            name='set_limit_history',
        ),
        migrations.DeleteModel(
            name='GraduationCustomerHistory',
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[], state_operations=state_operations
        )
    ]
