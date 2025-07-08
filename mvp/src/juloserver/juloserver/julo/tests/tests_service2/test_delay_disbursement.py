from juloserver.julo.models import FeatureSetting
from factory.django import DjangoModelFactory


class FeatureSettingDelayD(DjangoModelFactory):
    class Meta(object):
        model = FeatureSetting

    feature_name = "delay_disbursement"
    category = "feature stting"
    is_active = True
    parameters = {}
