from django.core.management import BaseCommand
from django.db.models import F

from juloserver.autodebet.models import AutodebetAccount, AutodebetBenefit
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


class Command(BaseCommand):
    help = 'Helps to retroload autodebet benefit'

    def handle(self, *args, **options):
        autodebet_benefit_control_feature = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.AUTODEBET_BENEFIT_CONTROL,
            is_active=True
        )

        if not autodebet_benefit_control_feature:
            return

        autodebet_benefit_values = AutodebetBenefit.objects.values_list('id', flat=True)
        batch_size = 100
        cashback_value = autodebet_benefit_control_feature.parameters['cashback']

        for start in range(0, len(autodebet_benefit_values), batch_size):
            end = start + batch_size
            benefit_ids = autodebet_benefit_values[start:end]
            AutodebetBenefit.objects.filter(id__in=benefit_ids).update(
                benefit_type='cashback',
                benefit_value=cashback_value
            )
