from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.loan.constants import LoanFeatureNameConst


def global_cap_percentage(apps, schema_editor):
    parameters = {
        'default': 0.2,
        'tenure_thresholds': {
            "1": 0.2,
            "2": 0.2,
            "3": 0.2,
            "4": 0.2,
            "5": 0.2,
            "6": 0.266,
            "7": 0.266,
            "8": 0.266,
            "9": 0.266,
            "10": 0.4,
            "11": 0.4,
            "12": 0.4,
        }
    }
    FeatureSetting.objects.create(
        feature_name=LoanFeatureNameConst.GLOBAL_CAP_PERCENTAGE,
        is_active=False,
        parameters=parameters,
        category='credit_matrix',
        description='daily Global cap percentage with tenure configuration for interest rates'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(global_cap_percentage, migrations.RunPython.noop)
    ]
