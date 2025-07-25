# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-03 04:59
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='email_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='merchant',
            name='nik_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='merchant',
            name='npwp_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='merchant',
            name='owner_name_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='merchant',
            name='phone_number_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
    ]
