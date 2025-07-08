from typing import List, Dict
from dataclasses import dataclass, field
from collections import defaultdict

from juloserver.loyalty.models import (
    MissionConfig,
    MissionProgress,
    MissionTarget,
    MissionTargetProgress
)


@dataclass
class TransactionMissionData:
    mission_config: MissionConfig
    mission_progress: MissionProgress = None
    mission_targets: List[MissionTarget] = field(default_factory=list)
    mission_target_progresses: List[MissionTargetProgress] = field(default_factory=list)
    mission_progress_tracking_status: Dict[int, List] =\
        field(default_factory=lambda: defaultdict(list))  # Ex: {mission_progress_id: ['in_progress', 'complete']}
