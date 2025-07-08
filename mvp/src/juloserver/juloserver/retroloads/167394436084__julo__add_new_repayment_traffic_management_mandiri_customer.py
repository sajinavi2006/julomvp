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
        featureSettings.parameters.update(
            {
                "mandiri":
                {
                    "title": "Mandiri Customer",
                    "settings":
                    {
                        "Bank MANDIRI":
                        {
                            "prob": 100,
                            "title": "Mandiri VA",
                            "selected": ["PERMATA Bank", "Bank BCA", "Bank BRI", "Bank MAYBANK"],
                            "backup":
                            {
                                "PERMATA Bank": "Permata VA",
                                "Bank BCA": "BCA VA",
                                "Bank BRI": "BRI VA",
                                "Bank MAYBANK": "Maybank VA",
                            }
                        },
                        "PERMATA Bank":
                        {
                            "prob": 0,
                            "title": "Permata VA",
                            "selected": ["Bank MANDIRI", "Bank BCA", "Bank BRI", "Bank MAYBANK"],
                            "backup":
                            {
                                "Bank MANDIRI": "Mandiri VA",
                                "Bank BCA": "BCA VA",
                                "Bank BRI": "BRI VA",
                                "Bank MAYBANK": "Maybank VA",
                            }
                        }
                    }
                }
            })
        
        for key,value in featureSettings.parameters.items():
            if key == 'mandiri':
                continue
            elif key == 'bca':
                featureSettings.parameters[key]['settings']['Bank BCA']['backup']["Bank MANDIRI"]="Mandiri VA"
                featureSettings.parameters[key]['settings']['Bank BCA']['selected'].append("Bank MANDIRI")
            elif key == 'bri':
                featureSettings.parameters[key]['settings']['Bank BRI']['backup']["Bank MANDIRI"]="Mandiri VA"
                featureSettings.parameters[key]['settings']['Bank BRI']['selected'].append("Bank MANDIRI")
            elif key == 'other':
                featureSettings.parameters[key]['settings']['Bank MAYBANK']['backup']["Bank MANDIRI"]="Mandiri VA"
                featureSettings.parameters[key]['settings']['Bank MAYBANK']['selected'].append("Bank MANDIRI")
            
            featureSettings.parameters[key]['settings']['PERMATA Bank']['backup']["Bank MANDIRI"]="Mandiri VA"
            featureSettings.parameters[key]['settings']['PERMATA Bank']['selected'].append("Bank MANDIRI")

        featureSettings.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_traffic_management_feature_setting, migrations.RunPython.noop)
    ]
