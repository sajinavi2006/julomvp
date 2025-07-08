
from typing import List
from django.db import transaction
from django.utils import timezone
from juloserver.julocore.constants import DbConnectionAlias
from bulk_update.helper import bulk_update

from juloserver.loyalty.constants import (
    MissionProgressStatusConst,
    MissionCategoryConst,
    MissionTargetTypeConst,
)
from juloserver.loyalty.data import TransactionMissionData
from juloserver.loyalty.models import (
    MissionConfig,
    MissionProgress,
    MissionTargetProgress,
)
from juloserver.loyalty.services.services import (
    update_loyalty_point_for_claim_mission_reward
)
from juloserver.loyalty.services.mission_related import (
    GeneralMissionCriteriaChecking,
    ResetMissionProgressChecking,
    TransactionMissionCriteriaChecking,
    CalculateMissionPointRewards,
)
from juloserver.moengage.services.use_cases import (
    send_loyalty_mission_progress_data_event_to_moengage
)


class TransactionMissionProgressService:
    def __init__(self, loan):
        self.loan = loan
        self.customer = loan.customer

    def get_and_blocking_exists_mission_progresses(self, m_config_ids):
        """
        return dict(
            mission_config_id_1: mission_progress object,
            ....
        )
        """
        qs = (
            MissionProgress.objects
            .select_for_update()
            .prefetch_related('missiontargetprogress_set')
            .filter(
                customer_id=self.customer.id,
                is_latest=True,
                mission_config_id__in=m_config_ids,
            )
            .exclude(status__in=[MissionProgressStatusConst.EXPIRED, MissionProgressStatusConst.DELETED])
        )

        data = {}
        for m_progress in qs:
            m_config_id = m_progress.mission_config_id
            data[m_config_id] = m_progress

        return data

    def get_transaction_mission_config_qs(self):
        return MissionConfig.objects.get_valid_mission_config_queryset().filter(
            category=MissionCategoryConst.TRANSACTION,
        ).prefetch_related('targets')

    def process(self):
        """
        *** MAIN METHOD ***
        This is a main function for processing create/update mission progress:
            - create_new_mission_progresses:
                + create new mission_progress
                + create repeat mission_progress
            - update_mission_progresses
                + update mission target progress -> status and completion_date
                + update reference_data
        """
        with transaction.atomic(using=DbConnectionAlias.UTILIZATION_DB):
            # Get mission config and lock mission progress for atomic
            m_config_qs = self.get_transaction_mission_config_qs()
            m_config_ids = list(m_config_qs.values_list('id', flat=True))
            m_progresses_dict = self.get_and_blocking_exists_mission_progresses(m_config_ids=m_config_ids)

            new_mission_data, repeat_mission_data, in_progress_mission_data = \
                self.filter_and_categorize_mission_data(m_config_qs, m_progresses_dict)
            all_mission_data = [*new_mission_data, *repeat_mission_data, *in_progress_mission_data]

            # process original repeat mission progress
            self.update_latest_flag_repeat_mission_progresses(repeat_mission_data)
            self.process_mission_progress_to_claim(repeat_mission_data)

            # create new progress for NEW and REPEAT case
            self.create_new_mission_progresses([*new_mission_data, *repeat_mission_data])

            # update mission progress
            self.update_progress_mission_data_list(all_mission_data)

        # prepare data and send notification
        self.send_notification(all_mission_data)

    def filter_and_categorize_mission_data(self, mission_config_qs, mission_progresses_dict):
        new_mission_data = []
        repeat_mission_data = []
        in_progress_mission_data = []

        for mission_config in mission_config_qs:
            if not check_transaction_mission_criteria(
                mission_config=mission_config,
                loan=self.loan
            ):
                continue

            mission_progress = mission_progresses_dict.get(mission_config.id)
            data = TransactionMissionData(
                mission_config=mission_config,
                mission_progress=mission_progress
            )
            if not mission_progress:
                if mission_config.is_active:
                    new_mission_data.append(data)
            elif check_repeat_transaction_mission(mission_progress, self.customer):
                repeat_mission_data.append(data)
            elif mission_progress.status == MissionProgressStatusConst.IN_PROGRESS:
                in_progress_mission_data.append(data)

        return new_mission_data, repeat_mission_data, in_progress_mission_data

    def update_latest_flag_repeat_mission_progresses(
        self, repeat_mission_data: List[TransactionMissionData]
    ):
        now = timezone.localtime(timezone.now())
        mission_progresses = []
        for data in repeat_mission_data:
            mission_progress = data.mission_progress
            mission_progress.is_latest = False
            mission_progress.udate = now
            mission_progresses.append(mission_progress)

        bulk_update(mission_progresses, using='utilization_db', update_fields=['is_latest', 'udate'])

    def create_new_mission_progresses(self, mission_data_list: List[TransactionMissionData]):
        for data in mission_data_list:
            repeat_number = 1

            # if data.mission_progress, it means it is the repeat mission progress
            if data.mission_progress:
                repeat_number = data.mission_progress.repeat_number + 1

            data.mission_progress = MissionProgress(
                status=MissionProgressStatusConst.IN_PROGRESS,
                repeat_number=repeat_number,
                customer_id=self.customer.id,
                mission_config=data.mission_config,
                is_latest=True,
                reference_data={'loan_ids': []},
            )
            data.mission_progress.save()
            self._update_progress_status_tracking(data, data.mission_progress)

    def update_progress_mission_data_list(self, mission_data_list: List[TransactionMissionData]):
        for data in mission_data_list:
            data.mission_progress.reference_data['loan_ids'].append(self.loan.id)
            self._update_mission_target_progress(data)

            checklist = list(map(
                lambda item: item.value >= item.mission_target.value,
                data.mission_target_progresses
            ))
            if all(checklist):
                data.mission_progress.status = MissionProgressStatusConst.COMPLETED
                data.mission_progress.completion_date = timezone.localtime(timezone.now())
                self._update_progress_status_tracking(data, data.mission_progress)

            data.mission_progress.save()

    def process_mission_progress_to_claim(self, mission_data_list: List[TransactionMissionData]):
        for data in mission_data_list:
            mission_progress = data.mission_progress
            if mission_progress.status != MissionProgressStatusConst.COMPLETED:
                continue

            point_reward = CalculateMissionPointRewards(
                data.mission_config, mission_progress
            ).calculate()
            point_earning, _ = update_loyalty_point_for_claim_mission_reward(
                mission_progress, point_reward
            )
            mission_progress.status = MissionProgressStatusConst.CLAIMED
            mission_progress.point_earning = point_earning
            mission_progress.save()

            self._update_progress_status_tracking(data, mission_progress)

    def send_notification(self, mission_data_list: List[TransactionMissionData]):
        moengage_data = [
            {'mission_progress_id': mission_progress_id, 'status': status_list[-1]}
            for data in mission_data_list
            for mission_progress_id, status_list in data.mission_progress_tracking_status.items()
            if status_list
        ]

        if moengage_data:
            send_loyalty_mission_progress_data_event_to_moengage.delay(
                self.customer.id, moengage_data
            )

    def _update_mission_target_progress(self, data: TransactionMissionData):
        # get or create mission_target_progress
        data.mission_target_progresses = list(
            data.mission_progress.missiontargetprogress_set.all()
        )
        if not data.mission_target_progresses:
            mission_targets = data.mission_config.targets.all()
            for mission_target in mission_targets:
                obj = MissionTargetProgress(
                    category=mission_target.category,
                    type=mission_target.type,
                    value=MissionTargetTypeConst.DEFAULT_VALUES[mission_target.type],
                    mission_target=mission_target,
                    mission_progress=data.mission_progress
                )
                data.mission_target_progresses.append(obj)

        # update mission_target_progress
        target_type_value_mapping = {
            MissionTargetTypeConst.RECURRING: 1,
            MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT: self.loan.loan_amount,
        }
        for mission_target_progress in data.mission_target_progresses:
            mission_target_progress.value += \
                target_type_value_mapping[mission_target_progress.type]

            mission_target_progress.save()

    def _update_progress_status_tracking(
        self, mission_data: TransactionMissionData, mission_progress: MissionProgress
    ):
        tracking_status = mission_data.mission_progress_tracking_status
        tracking_status[mission_progress.id].append(mission_progress.status)


def check_transaction_mission_criteria(mission_config, loan):
    general_checking = GeneralMissionCriteriaChecking(mission_config, loan.customer, loan)
    transaction_checking = TransactionMissionCriteriaChecking(mission_config, loan)
    return general_checking.check() and transaction_checking.check()


def check_repeat_transaction_mission(m_progress, customer):
    if m_progress.status not in MissionProgressStatusConst.ALLOWED_RESET_STATUSES:
        return False

    reset_checking = ResetMissionProgressChecking(
        mission_config=m_progress.mission_config,
        customer=customer,
        latest_mission_progress=m_progress
    )

    return reset_checking.check_latest_mission_progress_resetable()
