# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-10-26 10:04
from __future__ import unicode_literals

from django.db import migrations

from juloserver.streamlined_communication.constant import (
    CardProperty,
    TemplateCode,
)
from juloserver.streamlined_communication.models import StreamlinedCommunication


def create_or_update_serbucuankita_campaign(apps, schema_editor):
    streamlined_communication = StreamlinedCommunication.objects.get_or_none(
        template_code=TemplateCode.CARD_REFERRAL_SERBUCUANKITA,
    )

    streamlined_communication.update_safely(
        extra_conditions=CardProperty.J1_ACTIVE_REFERRAL_CODE_EXIST
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_or_update_serbucuankita_campaign, migrations.RunPython.noop),
    ]
