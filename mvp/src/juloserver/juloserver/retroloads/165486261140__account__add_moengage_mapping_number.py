# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-05-25 03:46
from __future__ import unicode_literals

from django.db import migrations
from juloserver.account.models import AccountLookup

def add_moengage_mapping_number(apps, schema_editor):
    AccountLookup.objects.filter(
        name__in=['JULOVER', 'Merchant Financing', 'axiata']).update(moengage_mapping_number=1)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_moengage_mapping_number)
    ]
