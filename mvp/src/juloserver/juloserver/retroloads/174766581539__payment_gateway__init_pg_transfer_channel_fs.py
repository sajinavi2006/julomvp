# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-05-19 14:43
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.payment_gateway.constants import FeatureNameConst


def execute(apps, schema_editor):

    setting = FeatureSetting.objects.create(
        feature_name=FeatureNameConst.PAYMENT_GATEWAY_TRANSFER_CHANNEL,
        is_active=True,
        parameters={'doku': {}},
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(execute, migrations.RunPython.noop)]
