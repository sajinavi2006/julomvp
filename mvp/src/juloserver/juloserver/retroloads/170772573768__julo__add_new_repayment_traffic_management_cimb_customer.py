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
                "cimb":
                {
                    "title": "CIMB Customer",
                    "settings":
                    {
                        "Bank CIMB Niaga":
                        {
                            "prob": 100,
                            "title": "CIMB VA",
                            "selected": ["PERMATA Bank", "Bank BCA", "Bank BRI", "Bank MAYBANK", "Bank MANDIRI"],
                            "backup":
                            {
                                "PERMATA Bank": "Permata VA",
                                "Bank BCA": "BCA VA",
                                "Bank BRI": "BRI VA",
                                "Bank MAYBANK": "Maybank VA",
                                "Bank MANDIRI": "Mandiri VA",
                                "Bank BNI": "BNI VA"
                            }
                        },
                        "PERMATA Bank":
                        {
                            "prob": 0,
                            "title": "Permata VA",
                            "selected": ["Bank CIMB Niaga", "Bank MANDIRI", "Bank BCA", "Bank BRI", "Bank MAYBANK"],
                            "backup":
                            {
                                "Bank CIMB Niaga": "CIMB VA",
                                "Bank BCA": "BCA VA",
                                "Bank BRI": "BRI VA",
                                "Bank MAYBANK": "Maybank VA",
                                "Bank MANDIRI": "Mandiri VA",
                                "Bank BNI": "BNI VA"
                            }
                        }
                    }
                }
            })
        
        for key,value in featureSettings.parameters.items():
            if key == 'cimb':
                continue
            elif key == 'bca':
                featureSettings.parameters[key]['settings']['Bank BCA']['backup']["Bank CIMB Niaga"]="CIMB VA"
                featureSettings.parameters[key]['settings']['Bank BCA']['selected'].append("Bank CIMB Niaga")
            elif key == 'bri':
                featureSettings.parameters[key]['settings']['Bank BRI']['backup']["Bank CIMB Niaga"]="CIMB VA"
                featureSettings.parameters[key]['settings']['Bank BRI']['selected'].append("Bank CIMB Niaga")
            elif key == 'mandiri':
                featureSettings.parameters[key]['settings']['Bank MANDIRI']['backup']["Bank CIMB Niaga"]="CIMB VA"
                featureSettings.parameters[key]['settings']['Bank MANDIRI']['selected'].append("Bank CIMB Niaga")
            elif key == 'bni':
                featureSettings.parameters[key]['settings']['Bank BNI']['backup']["Bank CIMB Niaga"]="CIMB VA"
                featureSettings.parameters[key]['settings']['Bank BNI']['selected'].append("Bank CIMB Niaga")
            elif key == 'other':
                featureSettings.parameters[key]['settings']['Bank MAYBANK']['backup']["Bank CIMB Niaga"]="CIMB VA"
                featureSettings.parameters[key]['settings']['Bank MAYBANK']['selected'].append("Bank CIMB Niaga")

            featureSettings.parameters[key]['settings']['PERMATA Bank']['backup']["Bank CIMB Niaga"]="CIMB VA"
            featureSettings.parameters[key]['settings']['PERMATA Bank']['selected'].append("Bank CIMB Niaga")

        featureSettings.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_traffic_management_feature_setting, migrations.RunPython.noop)
    ]
