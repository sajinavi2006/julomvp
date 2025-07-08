from typing import List, Optional, Any

from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.channeling_loan.constants.constants import FeatureNameConst


class CreditScoreConversionSetting:
    """
    Feature setting for Credit Score Conversion
    """
    def __init__(self):
        self.setting = FeatureSettingHelper(FeatureNameConst.CREDIT_SCORE_CONVERSION)

    @property
    def is_active(self) -> bool:
        return self.setting.is_active

    def get_configuration(self, channeling_type: str) -> Optional[List[Any]]:
        return self.setting.get(channeling_type, [])
