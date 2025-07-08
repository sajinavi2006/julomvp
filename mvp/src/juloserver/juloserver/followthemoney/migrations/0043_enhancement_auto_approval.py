# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.constants import FeatureNameConst


def auto_approval_global_setting(apps, _schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    LenderCurrent = apps.get_model("followthemoney", "LenderCurrent")

    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.AUTO_APPROVAL_GLOBAL_SETTING,
        category="followthemoney",
        parameters={"hour": 0, "minute": 15, "second": 0},
        description="Global Setting Lender Auto Approval Time")

    lender = LenderCurrent.objects.filter(lender_name="jtp")
    lender_id = None
    if lender:
        lender_id = lender.last().id

    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
        category="followthemoney",
        parameters={"lender": lender_id},
        description="Default Lender for Matchmaking")

class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0042_add_field_group_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='lenderapproval',
            name='expired_in',
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.RunPython(auto_approval_global_setting, migrations.RunPython.noop)
    ]