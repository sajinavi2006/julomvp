# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-03-04 06:48
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='partnershipapplicationdata',
            name='email_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='partnershipapplicationdata',
            name='fullname_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='partnershipapplicationdata',
            name='mobile_phone_1_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='partnershipcustomerdata',
            name='email_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='partnershipcustomerdata',
            name='nik_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='partnershipcustomerdata',
            name='phone_number_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
    ]
