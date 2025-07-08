# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def warning_letter_contacts_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.WARNING_LETTER_CONTACTS,
        category="collection",
        parameters={
            'collection_wa_number': '0813 1778 2070',
            'collection_email_address': 'collections@julo.co.id',
            'collection_phone_number_1': '021 5071 8800',
            'collection_phone_number_2': '021 5071 8822',
        },
        description="configuration for contacts on warning letter email"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(warning_letter_contacts_feature_setting, migrations.RunPython.noop)
    ]
