# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
from django.db import migrations
from juloserver.followthemoney.constants import LoanAgreementType
from django.template.loader import render_to_string


def summary_lla_default_template(apps, _schema_editor):
    LenderCurrent = apps.get_model("followthemoney", "LenderCurrent")
    LoanAgreementTemplate = apps.get_model("followthemoney", "LoanAgreementTemplate")

    with open('juloserver/followthemoney/templates/summary_lla_default_template.html', "r") as file:
        html = file.read()
        file.close()

    lender_currents = LenderCurrent.objects.all()
    for lender in lender_currents:
        LoanAgreementTemplate.objects.create(
            body=html,
            lender=lender,
            is_active=True,
            agreement_type=LoanAgreementType.SUMMARY
        )

class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0033_add_agreement_type'),
    ]

    operations = [
        migrations.RunPython(summary_lla_default_template, migrations.RunPython.noop)
    ]