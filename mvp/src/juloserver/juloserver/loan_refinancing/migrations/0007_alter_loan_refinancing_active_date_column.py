# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-02-26 08:03
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loan_refinancing', '0006_alter_loan_id_in_loan_refinancing_table'),
    ]

    operations = [
        migrations.AlterField(
            model_name='loanrefinancing',
            name='refinancing_active_date',
            field=models.DateField(blank=True, null=True),
        )
    ]
