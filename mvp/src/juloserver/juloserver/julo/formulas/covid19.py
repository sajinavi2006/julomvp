from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
def compute_affordability_covid19_adjusted(affordability_amount):
    active_setting = FeatureSetting.objects.filter(
        is_active=True,
        feature_name=FeatureNameConst.AFFORDABILITY_VALUE_DISCOUNT,
    ).last()
    if not active_setting:
        return affordability_amount
    buffer_value = active_setting.parameters.get('buffer_value')
    if not buffer_value:
        return affordability_amount
    return affordability_amount - int(buffer_value)
