from __future__ import unicode_literals
from django.db import migrations, models
from django.utils import timezone
from dateutil import relativedelta
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes

def add_experiment_setting_for_loan_duration_iti(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
    ExperimentSetting.objects.get_or_create(is_active=True,
        code=FeatureNameConst.BYPASS_ITI_EXPERIMENT_122,
        name="BypassITI122",
        start_date="2019-08-26 00:00:00+00",
        end_date="2019-11-26 00:00:00+00",
        schedule="",
        action="",
        type="formula",
        criteria={"application_id": "#nth:-1:0,1,2,3,4,5,6,7,8"},
        is_permanent=True
        )

    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
    loan_duration = ExperimentSetting.objects.filter(code="LoanDurationITI")
    loan_duration.update(criteria={"application_id": "#nth:-1:0,1,2,3,4,5", "product_line": [ProductLineCodes.MTL1]})


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0484_add_experiment_setting_for_loan_duration_iti'),
    ]

    operations = [
        migrations.AddField(
            model_name='experimentsetting',
            name='is_permanent',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(add_experiment_setting_for_loan_duration_iti,
            migrations.RunPython.noop)
    ]