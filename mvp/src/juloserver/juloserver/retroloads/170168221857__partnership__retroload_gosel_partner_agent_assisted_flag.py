# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-11-14 10:00
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.partners import PartnerConstant
from juloserver.julo.models import Partner
from juloserver.partnership.constants import PartnershipProductFlow
from juloserver.partnership.models import PartnershipFlowFlag


def partnership_gosel_agent_assisted_flag(apps, _schema_editor):
    partner = Partner.objects.filter(name=PartnerConstant.GOSEL).last()
    if partner:
        PartnershipFlowFlag.objects.get_or_create(
            partner=partner,
            name=PartnershipProductFlow.AGENT_ASSISTED
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(partnership_gosel_agent_assisted_flag, migrations.RunPython.noop),
    ]
