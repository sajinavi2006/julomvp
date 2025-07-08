# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import ExperimentConst


from juloserver.julo.models import ExperimentSetting



def cem_negative_score_feature_setting(apps, schema_editor):
    
    ExperimentSetting.objects.update_or_create(
        code=ExperimentConst.CEM_NEGATIVE_SCORE,
        name='CeM negative score experiment (collection model)',
        start_date="2019-11-25 00:00:00+00",
        end_date="2019-12-07 00:00:00+00",
        type ="collection",
        criteria ={"last_loan_id":[4,5,6]},
        is_active =True,
        is_permanent =False
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(cem_negative_score_feature_setting,
            migrations.RunPython.noop)
    ]
