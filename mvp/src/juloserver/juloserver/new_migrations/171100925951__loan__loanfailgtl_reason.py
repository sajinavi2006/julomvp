# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-03-25 07:07
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='loanfailgtl',
            name='reason',
            field=models.CharField(choices=[('inside', 'inside'), ('outside', 'outside')], default='inside', max_length=10),
            preserve_default=False,
        ),
    ]
