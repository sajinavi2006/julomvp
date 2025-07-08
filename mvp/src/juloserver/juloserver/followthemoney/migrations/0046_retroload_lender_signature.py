# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from django.db.models import Q
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes

def retroload_lender_signature(apps, _schema_editor):
    Loan = apps.get_model("julo", "Loan")
    LenderCurrent = apps.get_model("followthemoney", "LenderCurrent")
    LenderBucket = apps.get_model("followthemoney", "LenderBucket")
    LenderSignature = apps.get_model("followthemoney", "LenderSignature")

    today = timezone.localtime(timezone.now())
    last_month = today - relativedelta(months=6)
    lenders = LenderCurrent.objects.all()

    for lender in lenders:
        loans = Loan.objects.filter(
            Q(lender=lender) &
            Q(application__application_status__status_code__range=(
                ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
                ApplicationStatusCodes.FUND_DISBURSAL_FAILED)) &
            (Q(fund_transfer_ts__gte=last_month) | Q(fund_transfer_ts=None))
            )

        for loan in loans:
            lender_bucket = LenderBucket.objects.filter(
                application_ids__approved__contains=[loan.application.id]).last()

            if not lender_bucket:
                LenderSignature.objects.create(
                    loan=loan,
                    signed_ts=False
                )


class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0045_lender_signature'),
    ]

    operations = [
        migrations.RunSQL("ALTER TABLE lender_signature ALTER COLUMN loan_id TYPE bigint;"),
        migrations.RunPython(retroload_lender_signature, migrations.RunPython.noop)
    ]