# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-27 06:28
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='julovers',
            name='customer_xid',
            field=models.CharField(blank=True, max_length=50, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='julovers',
            name='email_tokenized',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='julovers',
            name='fullname_tokenized',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='julovers',
            name='mobile_phone_number_tokenized',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='julovers',
            name='real_nik_tokenized',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
