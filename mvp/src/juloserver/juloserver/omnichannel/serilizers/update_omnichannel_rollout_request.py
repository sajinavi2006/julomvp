from builtins import object
from typing import List
from juloserver.omnichannel.constants import CommChannelEnum


class UpdateOmnichannelRolloutRequest(object):
    customer_ids: List[int]
    rollout_channels: List[CommChannelEnum]
    is_included: bool
    full_rollout_channel: List[str]

    def __init__(
        self,
        customer_ids: List[int] = None,
        rollout_channels: List[CommChannelEnum] = None,
        is_included: bool = None,
        full_rollout_channel: List[str] = None,
    ):
        self.customer_ids = customer_ids or []
        self.rollout_channels = rollout_channels or []
        self.is_included = is_included
        self.full_rollout_channel = full_rollout_channel
