from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import MobileFeatureSetting



def create_boost_feature_settings(apps, schema_editor):
    
    setting = MobileFeatureSetting(
        feature_name="boost",
        parameters={'bpjs': {'is_active': True},
                    'bank': {'is_active': False, 'bca': {'is_active': True},
                             'mandiri': {'is_active': True}, 'bri': {'is_active': True},
                             'bni': {'is_active': True}}})
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_boost_feature_settings),
    ]
