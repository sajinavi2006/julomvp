from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.services2.feature_setting import FeatureSettingHelper


class OmnichannelIntegrationSetting:
    def __init__(self):
        self.setting = FeatureSettingHelper(FeatureNameConst.OMNICHANNEL_INTEGRATION)

    class CommsType:
        EMAIL = "email"
        SMS = "sms"
        ONE_WAY_ROBOCALL = "one-way-robocall"
        PDS = "pds"
        PN = "pn"
        TWO_WAY_ROBOCALL = 'two-way-robocall'

    @property
    def is_active(self):
        return self.setting.is_active

    @property
    def batch_size(self):
        return self.setting.get('batch_size', 1000)

    @property
    def is_full_rollout(self) -> bool:
        return self.setting.get('is_full_rollout', False)

    def is_comms_block_active(
        self,
        comms_type: CommsType,
    ):
        return self.setting.get('exclude_comms', {}).get(comms_type, False)

    def full_rollout_channels(self):
        return self.setting.get('full_rollout_channels', [])


def get_omnichannel_integration_setting():
    return OmnichannelIntegrationSetting()
