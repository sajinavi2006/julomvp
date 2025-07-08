from juloserver.julo.models import FeatureSetting
from juloserver.healthcare.constants import FeatureNameConst


def is_allow_add_new_healthcare_platform():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ALLOW_ADD_NEW_HEALTHCARE_PLATFORM,
        is_active=True,
    ).exists()
