# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-02-03 07:16
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='creditmatrix',
            name='credit_matrix_type',
            field=models.CharField(choices=[('julo', 'julo'), ('julo_repeat', 'julo_repeat'), ('webapp', 'webapp'), ('julo1', 'julo1'), ('julo1_entry_level', 'julo1_entry_level'), ('julo1_limit_exp', 'julo1_limit_exp'), ('j-starter', 'j-starter'), ('julo1_ios', 'julo1_ios')], max_length=50),
        ),
        migrations.AlterField(
            model_name='highscorefullbypass',
            name='customer_category',
            field=models.CharField(choices=[('julo', 'julo'), ('julo_repeat', 'julo_repeat'), ('webapp', 'webapp'), ('julo1', 'julo1'), ('julo1_entry_level', 'julo1_entry_level'), ('julo1_limit_exp', 'julo1_limit_exp'), ('j-starter', 'j-starter'), ('julo1_ios', 'julo1_ios')], max_length=50),
        ),
        migrations.AlterField(
            model_name='iticonfiguration',
            name='customer_category',
            field=models.CharField(choices=[('julo', 'julo'), ('julo_repeat', 'julo_repeat'), ('webapp', 'webapp'), ('julo1', 'julo1'), ('julo1_entry_level', 'julo1_entry_level'), ('julo1_limit_exp', 'julo1_limit_exp'), ('j-starter', 'j-starter'), ('julo1_ios', 'julo1_ios')], default='julo', max_length=50),
        ),
    ]
