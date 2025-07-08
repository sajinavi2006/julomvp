from datetime import datetime, timedelta
from django.utils import timezone
import logging
from django.db.models.query import QuerySet
from juloserver.grab.models import GrabFeatureSetting, GrabMasterLock
from juloserver.grab.constants import (
    GrabApiLogConstants,
    GrabFeatureNameConst,
    GrabMasterLockReasons,
    GrabMasterLockConstants,
)
from juloserver.julo.models import Loan

logger = logging.getLogger(__name__)


class CRSFailedValidationService(object):
    def get_grab_feature_setting_crs_flow_blocker(self) -> GrabFeatureSetting:
        return GrabFeatureSetting.objects.filter(
            feature_name=GrabFeatureNameConst.GRAB_CRS_FLOW_BLOCKER, is_active=True
        ).last()

    def check_crs_failed_exists(self, auth_log: QuerySet, loan: Loan) -> bool:
        now = timezone.localtime(timezone.now())
        crs_failed_log_exists = False
        log_from_grab_master_lock = self.get_crs_failed_in_grab_master_lock(
            loan.customer_id, loan.application_id2
        )
        if not log_from_grab_master_lock:
            crs_failed_log_exists = auth_log.filter(
                response__icontains=GrabApiLogConstants.FAILED_CRS_VALIDATION_ERROR_RESPONSE
            ).exists()
        elif not log_from_grab_master_lock.expire_ts < now:
            crs_failed_log_exists = True
        return crs_failed_log_exists

    def get_crs_failed_in_grab_master_lock(self, customer_id, application_id) -> GrabMasterLock:
        return GrabMasterLock.objects.filter(
            customer_id=customer_id,
            application_id=application_id,
            lock_reason=GrabMasterLockReasons.FAILED_CRS_VALIDATION,
        ).last()

    def create_crs_failed_validation_in_grab_master_lock(
        self, customer_id: int, application_id: int, expiry_time: datetime
    ) -> GrabMasterLock:
        lock_reason = GrabMasterLockReasons.FAILED_CRS_VALIDATION
        grab_master_lock = GrabMasterLock.objects.create(
            customer_id=customer_id,
            application_id=application_id,
            expire_ts=expiry_time,
            lock_reason=lock_reason,
        )
        return grab_master_lock

    def create_or_update_crs_failed_data(self, loan: Loan):
        grab_feature_setting_crs_flow_blocker = self.get_grab_feature_setting_crs_flow_blocker()
        surplus_hour = GrabMasterLockConstants.DEFAULT_EXPIRY_HOURS
        if (
            grab_feature_setting_crs_flow_blocker
            and grab_feature_setting_crs_flow_blocker.parameters
        ):
            failed_crs_parameter = grab_feature_setting_crs_flow_blocker.parameters.get(
                'failed_crs'
            )
            if failed_crs_parameter:
                surplus_hour = failed_crs_parameter

        now = timezone.localtime(timezone.now())
        expiry_time = now + timedelta(hours=surplus_hour)

        logger.info(
            {
                "task": "create_or_update_crs_failed_data",
                "message": "trying to create or update crs failed data",
                "loan_id": loan.id,
                "expiry_time": expiry_time,
            }
        )

        crs_failed_data_from_grab_master_lock = self.get_crs_failed_in_grab_master_lock(
            loan.customer_id, loan.application_id2
        )
        if not crs_failed_data_from_grab_master_lock:
            self.create_crs_failed_validation_in_grab_master_lock(
                loan.customer_id, loan.application_id2, expiry_time
            )
        else:
            is_crs_validation_expire = (
                True if crs_failed_data_from_grab_master_lock.expire_ts < now else False
            )
            if is_crs_validation_expire:
                crs_failed_data_from_grab_master_lock.update_safely(expire_ts=expiry_time)

        return crs_failed_data_from_grab_master_lock
