from __future__ import unicode_literals

from django.db import migrations


def create_boost_feature_settings(apps, schema_editor):
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting")
    setting = MobileFeatureSetting(
        feature_name="boost",
        parameters={'bpjs': {'is_active': True},
                    'bank': {'is_active': False, 'bca': {'is_active': True},
                             'mandiri': {'is_active': True}, 'bri': {'is_active': True},
                             'bni': {'is_active': True}}})
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0676_application_update_contact'),
    ]

    operations = [
        migrations.RunPython(create_boost_feature_settings),
    ]
