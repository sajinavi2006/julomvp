from typing import Dict
from juloserver.julo.models import FeatureSetting


class FeatureSettingHelper:
    """
    Helper when working with feature setting.
    """
    def __init__(self, feature_name):
        self.feature_name = feature_name
        self._setting = None
        self.qs = FeatureSetting.objects.filter(
            feature_name=feature_name,
        )

    @property
    def setting(self):
        if not self._setting:
            self._setting = self.qs.last()

        return self._setting

    @property
    def is_active(self):
        return self.setting.is_active if self.setting else False

    @property
    def params(self) -> Dict:
        return self.setting.parameters if self.setting else None

    def get(self, key, default=None):
        if not self.setting or not self.setting.parameters:
            return default

        return self.setting.parameters.get(key, default)
