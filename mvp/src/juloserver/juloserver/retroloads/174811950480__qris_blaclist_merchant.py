from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def add_feature_setting_qris_blacklist_merchant(apps, schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.QRIS_MERCHANT_BLACKLIST_NEW,
        parameters={
            "merchant_ids": [],
            "merchant_names": []
        },
        is_active=True,
        description='qris blacklist merchant by id or name',
        category='qris'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            add_feature_setting_qris_blacklist_merchant, migrations.RunPython.noop),
    ]
