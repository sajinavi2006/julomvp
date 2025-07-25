# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-02-12 10:05
from __future__ import unicode_literals

from django.db import migrations

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Partner
from juloserver.partnership.constants import PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag


def partnership_cermati_mandatory_field_flag(apps, _schema_editor):
    partner = Partner.objects.filter(name=PartnerNameConstant.CERMATI).last()
    if partner:
        partnership_flow_flag, _ = PartnershipFlowFlag.objects.get_or_create(
            partner=partner,
            name=PartnershipFlag.FIELD_CONFIGURATION
        )

        partnership_flow_flag.configs.update({
            "occupied_since": True,
            "dependent": True,
            "monthly_expenses": True,
        })

        partnership_flow_flag.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(partnership_cermati_mandatory_field_flag, migrations.RunPython.noop),
    ]
