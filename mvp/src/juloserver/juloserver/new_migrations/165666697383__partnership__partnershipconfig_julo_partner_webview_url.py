# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-07-01 09:16
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='partnershipconfig',
            name='julo_partner_webview_url',
            field=models.URLField(blank=True, null=True),
        ),
    ]
