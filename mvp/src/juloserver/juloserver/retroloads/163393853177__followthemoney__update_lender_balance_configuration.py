# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-10-11 07:48
from __future__ import unicode_literals

from django.db import migrations
from juloserver.followthemoney.models import LenderCurrent


def update_current_manual_lender(apps, schema_editor):
    jtp = LenderCurrent.objects.get_or_none(lender_name="jtp")
    if jtp:
        jtp.update_safely(
            is_master_lender=True,
            is_xfers_lender_flow=True,
            minimum_balance=5000000000,
            is_low_balance_notification=True,
        )

    gfin = LenderCurrent.objects.get_or_none(lender_name="gfin")
    if gfin:
        gfin.update_safely(
            is_manual_lender_balance=True,
            is_bss_balance_include=True,
            is_low_balance_notification=True,
            minimum_balance=500000000,
        )

    lenders = LenderCurrent.objects.filter(lender_name__in=("jh", "pascal", ))
    for lender in lenders:
        lender.update_safely(
            is_manual_lender_balance=True,
            is_only_escrow_balance=True,
            is_low_balance_notification=True,
            minimum_balance=500000000,
        )

    bss_channeling = LenderCurrent.objects.get_or_none(lender_name="bss_channeling")
    if bss_channeling:
        bss_channeling.update_safely(
            is_manual_lender_balance=True,
            is_xfers_lender_flow=True,
            is_low_balance_notification=True,
            minimum_balance=500000000,
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_current_manual_lender)
    ]
