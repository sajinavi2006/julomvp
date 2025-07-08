import logging
from typing import Tuple

from juloserver.antifraud.client import get_anti_fraud_http_client
from juloserver.antifraud.constant.binary_checks import (
    BinaryCheckType,
)
from juloserver.antifraud.constant.binary_checks import StatusEnum
from juloserver.antifraud.constant.transport import Path
from juloserver.fraud_security.constants import FraudChangeReason
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting, ApplicationHistory
from juloserver.julo.statuses import ApplicationStatusCodes

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()
anti_fraud_http_client = get_anti_fraud_http_client()


def get_anti_fraud_binary_check_status(
    status: int,
    application_id: int,
    loan_id: int = None,
) -> StatusEnum:
    """
    This function serves as a call-wrapper for doing binary checks with the antifraud service

    Args:
        application_id (int): application_id
        loan_id (int): loan_id

    Returns:
        ABCStatus: status of the antifraud binary checks
    """

    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ANTIFRAUD_BINARY_CHECK,
        is_active=True,
    ).last()
    if not fs:
        logger.info(
            {
                "action": "antifraud_binary_checks.get_antifraud_binary_check_status",
                "message": "Feature setting for antifraud binary check is not active",
                "application_id": application_id,
            },
        )
        return StatusEnum.DO_NOTHING

    params = {
        "status": status,
        "type": BinaryCheckType.APPLICATION,
        "application_id": application_id
    }
    if loan_id:
        params["type"] = BinaryCheckType.LOAN
        params["loan_id"] = loan_id

    try:
        response = anti_fraud_http_client.get(
            path=Path.ANTI_FRAUD_BINARY_CHECK,
            params=params,
        )
    except Exception as e:
        logger.error(
            {
                "action": "antifraud_binary_checks.get_antifraud_binary_checks",
                "error": e,
            }
        )
        sentry_client.captureException()
        return StatusEnum.ERROR

    try:
        binary_check_status = response.json().get("data", {}).get("status", None)
    except Exception as e:
        logger.error(
            {
                "action": "antifraud_binary_checks.get_antifraud_binary_checks",
                "error": e,
                "response": response,
            }
        )
        sentry_client.captureException()
        return StatusEnum.ERROR

    if binary_check_status is None:
        return StatusEnum.ERROR

    return StatusEnum(binary_check_status)


def get_application_old_status_code(
    application_id: int, application_status
) -> Tuple[ApplicationHistory, int, bool]:
    if application_status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS:
        application_history = ApplicationHistory.objects.filter(
            application=application_id,
            status_new=application_status,
            change_reason=FraudChangeReason.ANTI_FRAUD_API_UNAVAILABLE,
        ).last()
        if not application_history:
            return None, application_status, False
        logger.info(
            {
                "action": "get_application_old_status_code",
                "application_id": application_id,
                "status_old": application_history.status_old,
            },
        )
        return application_history, application_history.status_old, True
    else:
        return None, application_status, False
