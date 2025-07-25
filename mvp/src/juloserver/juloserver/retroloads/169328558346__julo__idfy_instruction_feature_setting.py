# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-29 05:06
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting


def add_feature_setting(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name="idfy_instruction_page",
        is_active=True,
        parameters={
            'button_text': 'Mulai Video Call',
            'instruction_image_url': 'info-card/IDFY_INSTRUCTION_PAGE.png',
        },
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_feature_setting, migrations.RunPython.noop),
    ]
