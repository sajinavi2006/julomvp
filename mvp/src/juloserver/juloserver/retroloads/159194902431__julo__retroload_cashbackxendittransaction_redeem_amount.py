# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from juloserver.julo.services2.xendit import XenditConst


from juloserver.julo.models import CashbackXenditTransaction



def retroload_redeem_amount(apps, schema_editor):
    
    cashback_request_list = CashbackXenditTransaction.objects.filter(
        transfer_status=XenditConst.STATUS_REQUESTED)
    cashback_pending_list = CashbackXenditTransaction.objects.filter(
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
    ]

    operations = [
        migrations.RunPython(retroload_redeem_amount, migrations.RunPython.noop)
    ]