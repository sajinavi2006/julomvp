# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-06 10:02
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='customergraduationfailure',
            name='type',
            field=models.TextField(blank=True, choices=[('graduation', 'graduation'), ('downgrade', 'downgrade')], null=True),
        ),
        migrations.AddField(
            model_name='graduationcustomerhistory2',
            name='customer_graduation_id',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
