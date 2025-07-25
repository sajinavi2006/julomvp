# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-03-12 04:29
from __future__ import unicode_literals

import cuser.fields
from django.conf import settings
from django.db import migrations
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0190_customer_appsflyer_device_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='repaymenttransaction',
            name='added_by',
            field=cuser.fields.CurrentUserField(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='repayment_transactions', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterModelTable(
            name='repaymenttransaction',
            table='repayment_transaction',
        ),
    ]
