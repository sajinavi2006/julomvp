# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-04-08 08:50
from __future__ import unicode_literals

from django.db import migrations

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.constants import DanaFDCResultStatus
from juloserver.julo.models import Partner
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag


def dana_adding_partnership_max_creditor_check(apps, _schema_editor):
    partner = Partner.objects.filter(name=PartnerNameConstant.DANA).last()

    if partner:
        PartnershipFlowFlag.objects.get_or_create(
            partner=partner,
            name=PartnershipFlag.MAX_CREDITOR_CHECK,
            configs={
                'statuses': [
                    DanaFDCResultStatus.APPROVE1,
                    DanaFDCResultStatus.APPROVE2,
                    DanaFDCResultStatus.APPROVE3,
                ],
                'is_active': False,
            },
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(dana_adding_partnership_max_creditor_check, migrations.RunPython.noop),
    ]
