# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-12-13 06:43
from __future__ import unicode_literals

from django.db import migrations

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Partner
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag


def qoala_add_clik_config(apps, schema_editor):
    partner = Partner.objects.get_or_none(name=PartnerNameConstant.QOALA)

    if partner:
        partnership_flow_flag, _ = PartnershipFlowFlag.objects.get_or_create(
            partner=partner,
            name=PartnershipFlag.CLIK_INTEGRATION,
            configs={
                "swap_ins": {
                    "delay": 5,
                    "pgood": 0.75,
                    "is_active": False,
                    "score_raw": 500,
                    "total_overdue": 1000000,
                },
                "swap_outs": {
                    "delay": 5,
                    "is_active": True,
                    "score_raw": 200,
                    "total_overdue": 1000000,
                    "reporting_providers": 10,
                },
                "shadow_score": {"is_active": True},
            }
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(qoala_add_clik_config, migrations.RunPython.noop)]
