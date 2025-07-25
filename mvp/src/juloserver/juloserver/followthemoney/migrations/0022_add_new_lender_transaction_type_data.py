# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-10-24 07:02
from __future__ import unicode_literals

from django.db import migrations
from juloserver.followthemoney.constants import LenderTransactionTypeConst
from juloserver.followthemoney.models import LenderTransactionType


def add_lender_transaction_type_data(apps, schema_editor):
    LenderTransactionType.objects.create(transaction_type=LenderTransactionTypeConst.RECONCILE)

class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0021_lla_lender_relationship_update'),
    ]

    operations = [
        migrations.RunPython(add_lender_transaction_type_data)
    ]
