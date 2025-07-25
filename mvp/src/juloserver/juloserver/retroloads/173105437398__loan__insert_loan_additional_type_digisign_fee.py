# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-08 08:26
from __future__ import unicode_literals

from django.db import migrations

from juloserver.loan.constants import LoanDigisignFeeConst
from juloserver.loan.models import LoanAdditionalFeeType


def insert_digisign_fee_type_loan_additional_type(apps, _schema_editor):
    LoanAdditionalFeeType.objects.create(
        name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE,
        notes=("Digisign fee for loan. This fee will ignore daily max fee rule")
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(insert_digisign_fee_type_loan_additional_type, migrations.RunPython.noop),
    ]
