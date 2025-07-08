# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from ..services2.xendit import XenditConst


def retroload_redeem_amount(apps, schema_editor):
    CashbackXenditTrans = apps.get_model("julo", "CashbackXenditTransaction")
    cashback_request_list = CashbackXenditTrans.objects.filter(
        transfer_status=XenditConst.STATUS_REQUESTED)
    cashback_pending_list = CashbackXenditTrans.objects.filter(
        transfer_status=XenditConst.STATUS_PENDING)

    for cashback_request in cashback_request_list:
        redeem_amount = cashback_request.transfer_amount
        transfer_amount = redeem_amount - XenditConst.ADMIN_FEE
        cashback_request.redeem_amount = redeem_amount
        cashback_request.transfer_amount = transfer_amount
        cashback_request.save()

    for cashback_pending in cashback_pending_list:
        redeem_amount = cashback_pending.transfer_amount
        cashback_pending.redeem_amount = redeem_amount
        cashback_pending.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0264_cashbackxendittransaction_redeem_amount'),
    ]

    operations = [
        migrations.RunPython(retroload_redeem_amount, migrations.RunPython.noop)
    ]