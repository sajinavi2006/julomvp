# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_feature_settings_emergency_contact_blacklist(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.EMERGENCY_CONTACT_BLACKLIST,
        is_active=False,
        category='fraud',
        description="Feature Setting to turn on/off Emergency Contact Blacklist",
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            create_feature_settings_emergency_contact_blacklist, migrations.RunPython.noop
        )
    ]
