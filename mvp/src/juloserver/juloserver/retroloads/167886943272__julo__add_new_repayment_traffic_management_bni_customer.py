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
                "bni":
                {
                    "title": "BNI Customer",
                    "settings":
                    {
                        "Bank BNI":
                        {
                            "prob": 100,
                            "title": "BNI VA",
                            "selected": ["PERMATA Bank", "Bank BCA", "Bank BRI", "Bank MAYBANK", "Bank MANDIRI"],
                            "backup":
                            {
                                "PERMATA Bank": "Permata VA",
                                "Bank BCA": "BCA VA",
                                "Bank BRI": "BRI VA",
                                "Bank MAYBANK": "Maybank VA",
                                "Bank MANDIRI": "Mandiri VA"
                            }
                        },
                        "PERMATA Bank":
                        {
                            "prob": 0,
                            "title": "Permata VA",
                            "selected": ["Bank BNI", "Bank MANDIRI", "Bank BCA", "Bank BRI", "Bank MAYBANK"],
                            "backup":
                            {
                                "Bank BNI": "BNI VA",    
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
            if key == 'bni':
                continue
            elif key == 'bca':
                featureSettings.parameters[key]['settings']['Bank BCA']['backup']["Bank BNI"]="BNI VA"
            elif key == 'bri':
                featureSettings.parameters[key]['settings']['Bank BRI']['backup']["Bank BNI"]="BNI VA"
            elif key == 'mandiri':
                featureSettings.parameters[key]['settings']['Bank MANDIRI']['backup']["Bank BNI"]="BNI VA"
            elif key == 'other':
                featureSettings.parameters[key]['settings']['Bank MAYBANK']['backup']["Bank BNI"]="BNI VA"
            
            featureSettings.parameters[key]['settings']['PERMATA Bank']['backup']["Bank BNI"]="BNI VA"

        featureSettings.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_traffic_management_feature_setting, migrations.RunPython.noop)
    ]
