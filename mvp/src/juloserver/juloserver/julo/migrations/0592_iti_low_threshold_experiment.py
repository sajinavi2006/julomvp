from __future__ import unicode_literals
from juloserver.julo.constants import ExperimentConst
from django.db import migrations
from django.utils import timezone
from datetime import timedelta


def add_experiment_setting_iti_low_threshold(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")

    ExperimentSetting.objects.create(
        is_active=True,
        code=ExperimentConst.ITI_LOW_THRESHOLD,
        name="ITI Low Threshold Experiment",
        start_date=timezone.now(),
        end_date=timezone.now() + timedelta(30),
        schedule="",
        action="",
        type="formula",
        criteria={
            "product_line": [10],
            "affordability": 450000,
            "application_id": "#nth:-1:5,6,7,8,9",
            "threshold": {
                "min": 0.76,
                "max": 0.80
            },
            "n_mae": 2
        }
    )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0591_add_table_productivity_centerix_summary'),
    ]

    operations = [
        migrations.RunPython(add_experiment_setting_iti_low_threshold, migrations.RunPython.noop)
    ]

