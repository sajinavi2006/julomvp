from __future__ import unicode_literals
from django.db import migrations
from django.utils import timezone
from dateutil import relativedelta
from juloserver.julo.constants import ExperimentConst


def update_ac_bypass_test_group_value(apps, schema_editor):
    Experiment = apps.get_model("julo", "Experiment")
    experiment = Experiment.objects.filter(code=ExperimentConst.ACBYPASS141).last()
    experiment_settings = experiment.experimenttestgroup_set.first()
    if experiment_settings:
        experiment_settings.value = "#nth:-1:1,2,3,4,5,6,7,8,9,0"
        experiment_settings.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0531_cootek_robocall_experiment_v4'),
    ]

    operations = [
        migrations.RunPython(update_ac_bypass_test_group_value,
            migrations.RunPython.noop)
    ]
