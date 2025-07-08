# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def update_traffic_management_feature_setting(apps, _schema_editor):
    
    featureSettings = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REPAYMENT_TRAFFIC_SETTING
    ).first()
    if featureSettings:
        parameters = {
            "other":
            {
                "title": "Other Bank Customer",
                "settings":
                {
                    "PERMATA Bank":
                    {
                        "prob": 100,
                        "title": "Permata VA",
                        "selected": ["Bank MAYBANK"],
                        "backup":
                        {
                            "Bank MAYBANK": "Maybank VA",
                            "Bank BCA": "BCA VA",
                            "Bank BRI": "BRI VA"
                        }
                    },
                    "Bank MAYBANK":
                    {
                        "prob": 0,
                        "title": "Maybank VA",
                        "selected": ["PERMATA Bank"],
                        "backup":
                        {
                            "PERMATA Bank": "Permata VA",
                            "Bank BCA": "BCA VA",
                            "Bank BRI": "BRI VA"

                        }
                    }
                }
            },
            "bri":
            {
                "title": "BRI Customer",
                "settings":
                {
                    "Bank BRI":
                    {
                        "prob": 100,
                        "title": "BRI VA",
                        "selected": ["PERMATA Bank"],
                        "backup":
                        {
                            "PERMATA Bank": "Permata VA",
                            "Bank BCA": "BCA VA",
                            "Bank MAYBANK": "Maybank VA"
                        }
                    },
                    "PERMATA Bank":
                    {
                        "prob": 0,
                        "title": "Permata VA",
                        "selected": ["Bank BRI"],
                        "backup":
                        {
                            "Bank BRI": "BRI VA",
                            "Bank BCA": "BCA VA",
                            "Bank MAYBANK": "Maybank VA",
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
                            "selected": ["PERMATA Bank"],
                            "backup":
                                {
                                    "PERMATA Bank": "Permata VA",
                                    "Bank BRI": "BRI VA",
                                    "Bank MAYBANK": "Maybank VA",
                                }
                        },
                    "PERMATA Bank":
                        {
                            "prob": 0,
                            "title": "Permata VA",
                            "selected": ["Bank BCA"],
                            "backup":
                                {
                                    "Bank BCA": "BCA VA",
                                    "Bank BRI": "BRI VA",
                                    "Bank MAYBANK": "Maybank VA"
                                }
                        }
                }
            }
        }
        featureSettings.parameters = parameters
        featureSettings.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_traffic_management_feature_setting, migrations.RunPython.noop)
    ]
