# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-09-26 03:53
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RenameField(
            model_name='paymentdeposit',
            old_name='paid_deposit_amount',
            new_name='paid_total_deposit_amount',
        ),
        migrations.RemoveField(
            model_name='paymentdeposit',
            name='paid_admin_fee',
        ),
        migrations.AddField(
            model_name='paymentdeposit',
            name='protection_fee',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='paymentdeposit',
            name='rentee_device',
            field=models.ForeignKey(db_column='rentee_device_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='rentee.RenteeDeviceList'),
        ),
        migrations.AddField(
            model_name='paymentdeposit',
            name='total_deposit_amount',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='paymentdeposit',
            name='deposit_amount',
            field=models.IntegerField(default=0),
        ),
    ]
