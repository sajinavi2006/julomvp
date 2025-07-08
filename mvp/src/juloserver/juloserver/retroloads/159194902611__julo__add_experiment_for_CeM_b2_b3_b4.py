# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from builtins import range
from django.db import migrations
from juloserver.julo.constants import ExperimentConst


from juloserver.julo.models import ExperimentSetting



def cem_negative_score_feature_setting(apps, schema_editor):
    
    ExperimentSetting.objects.update_or_create(
        code=ExperimentConst.CEM_B2_B3_B4_EXPERIMENT,
        name='CeM B2,B3 and B4 experiments (collection model)',
        start_date="2019-12-27 00:00:00+00",
        end_date="2020-01-24 00:00:00+00",
        type="collection",
        criteria={"test_group_last_loan_id": list(range(4, 10)), "control_group_last_loan_id": list(range(0, 4))},
        is_active=True,
        is_permanent=False
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(cem_negative_score_feature_setting,
            migrations.RunPython.noop)
    ]
