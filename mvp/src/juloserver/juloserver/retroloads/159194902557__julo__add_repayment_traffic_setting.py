# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def traffic_management_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.REPAYMENT_TRAFFIC_SETTING,
        category="traffic_managerment",
        parameters={
            "other":
            {
                "title": "Non-BCA Customer",
                "settings":
                {
                    "PERMATA Bank":
                    {
                        "prob": 100,
                        "title": "Permata VA",
                        "selected":"Bank MAYBANK",
                        "backup":
                        {
                            "Bank MAYBANK": "Maybank VA"
                        }
                    },
                    "Bank MAYBANK":
                    {
                        "prob": 0,
                        "title": "Maybank VA",
                        "selected":"PERMATA Bank",
                        "backup":
                        {
                            "PERMATA Bank": "Permata VA"
                        }
                    }
                }
            },
            "bca":
            {
                "title": "BCA Customer",
                "settings":
                {
                    "Bank BCA":
                    {
                        "prob": 100,
                        "title": "BCA VA",
                        "selected":"PERMATA Bank",
                        "backup":
                        {
                            "PERMATA Bank": "Permata VA"
                        }
                    },
                    "PERMATA Bank":
                    {
                        "prob": 0,
                        "title": "Permata VA",
                        "selected":"Bank BCA",
                        "backup":
                        {
                            "Bank BCA": "BCA VA"
                        }
                    }
                }
            }
        },
        description="Config repayment traffic"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(traffic_management_feature_setting, migrations.RunPython.noop)
    ]
