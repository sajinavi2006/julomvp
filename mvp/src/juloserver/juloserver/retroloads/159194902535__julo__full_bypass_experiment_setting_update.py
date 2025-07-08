from __future__ import unicode_literals
from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.julo.models import ExperimentSetting


def add_experiment_setting_for_parallel_bypass_experiments(apps, schema_editor):
    
    setting = ExperimentSetting.objects.filter(code="ParallelHighScoreBypassExperiments").last()
    setting.criteria =  {"high_probability_fpd": 0.96,
                          "low_probability_fpd":0.88,
                          "product_line_codes" : (ProductLineCodes.MTL2, ProductLineCodes.STL2),
                          "second_last_app_xid": (0,1,2,3,4),
                          "last_app_xid": (0,1,2,3,4,5)}
    setting.start_date = "2019-07-29 00:00:00+00"
    setting.end_date = "2019-09-29 00:00:00+00"
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_experiment_setting_for_parallel_bypass_experiments)
    ]