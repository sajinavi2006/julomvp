from __future__ import unicode_literals
from juloserver.julo.constants import ExperimentConst
from django.db import migrations


def add_experiment_setting_cootek_robocall_experimentv5(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
    ExperimentSetting.objects.create(
        is_active=True,
        code=ExperimentConst.COOTEK_AI_ROBOCALL_TRIAL_V5,
        name="Cootek AI Robocall trial v5",
        start_date="2020-01-25 00:00:00+00",
        end_date="2020-02-07 00:00:00+00",
        schedule="",
        action="",
        type="payment",
        criteria={"dpd": [-2, -1, 0], "loan_id": "#last:1:7,8,9"}
    )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0581_alter_payment_id'),
    ]

    operations = [
        migrations.RunPython(add_experiment_setting_cootek_robocall_experimentv5, migrations.RunPython.noop)
    ]

