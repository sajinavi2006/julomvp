# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-09 01:20
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='partnershipcustomerdata',
            name='certificate_date',
            field=models.DateField(blank=True, null=True, verbose_name='Tanggal akta'),
        ),
        migrations.AddField(
            model_name='partnershipcustomerdata',
            name='certificate_number',
            field=models.CharField(
                blank=True, max_length=100, null=True, verbose_name='Nomor akta'
            ),
        ),
        migrations.AddField(
            model_name='partnershipcustomerdata',
            name='user_type',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
