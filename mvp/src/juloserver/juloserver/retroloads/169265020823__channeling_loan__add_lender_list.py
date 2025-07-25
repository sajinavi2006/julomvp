# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-21 20:36
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.channeling_loan.constants import FeatureNameConst


def ar_switching_lender_list_feature_setting(apps, _schema_editor):
    obj, created = FeatureSetting.objects.update_or_create(
        is_active=True,
        parameters=(
            ('jtp', 'PT Julo Teknologi Perdana'),
            ('jh', 'Julo Holdings Pte. Ltd.'),
            ('pascal', 'Pascal International Pte. Ltd.'),
            ('blue_finc_lender', 'Blue Finc Pte. Ltd'),
        ),
        category='channeling_loan',
        description='AR switching lender list',
        defaults={"feature_name": FeatureNameConst.AR_SWITCHING_LENDER},
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(ar_switching_lender_list_feature_setting, migrations.RunPython.noop)
    ]
