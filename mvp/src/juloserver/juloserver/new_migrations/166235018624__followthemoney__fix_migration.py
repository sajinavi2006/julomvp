# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-09-05 03:56
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='loanagreementtemplate',
            name='body',
            field=models.TextField(help_text='For custom parameter text use double bracket         and split using dot(.) for table and field.        i.e: {{lender.lender_name}}'),
        ),
    ]
