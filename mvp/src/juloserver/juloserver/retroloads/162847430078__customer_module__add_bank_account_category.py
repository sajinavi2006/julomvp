# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-09 01:58
from __future__ import unicode_literals

from django.db import migrations

from juloserver.customer_module.models import BankAccountCategory


def add_bank_account_category(apps, _schema_editor):
    BankAccountCategory.objects.get_or_create(
        id=6,
        category='partner',
        display_label='partner',
        parent_category_id=6
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_bank_account_category, migrations.RunPython.noop),
    ]
