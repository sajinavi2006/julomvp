# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-10-11 04:09
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='lendercurrent',
            name='is_bss_balance_include',
            field=models.NullBooleanField(default=None),
        ),
        migrations.AddField(
            model_name='lendercurrent',
            name='is_low_balance_notification',
            field=models.NullBooleanField(default=None),
        ),
        migrations.AddField(
            model_name='lendercurrent',
            name='is_manual_lender_balance',
            field=models.NullBooleanField(default=False),
        ),
        migrations.AddField(
            model_name='lendercurrent',
            name='is_master_lender',
            field=models.NullBooleanField(default=False),
        ),
        migrations.AddField(
            model_name='lendercurrent',
            name='is_only_escrow_balance',
            field=models.NullBooleanField(default=None),
        ),
        migrations.AddField(
            model_name='lendercurrent',
            name='is_xfers_lender_flow',
            field=models.NullBooleanField(default=None),
        ),
        migrations.AddField(
            model_name='lendercurrent',
            name='minimum_balance',
            field=models.BigIntegerField(default=0),
        ),
    ]
