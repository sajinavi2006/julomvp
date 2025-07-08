from __future__ import unicode_literals
from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes

def add_experiment_setting_for_parallel_bypass_experiments(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
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
        ('julo', '0465_create_new_workflow_path_from_120_to_141'),
    ]

    operations = [
        migrations.RunPython(add_experiment_setting_for_parallel_bypass_experiments)
    ]