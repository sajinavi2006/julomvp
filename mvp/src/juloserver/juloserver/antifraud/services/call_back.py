import logging

from juloserver.antifraud.client import get_anti_fraud_http_client
from juloserver.antifraud.constant.call_back import CallBackType
from juloserver.antifraud.constant.transport import Path
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import ApplicationHistory
from juloserver.julo.utils import execute_after_transaction_safely

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()
anti_fraud_http_client = get_anti_fraud_http_client()


def hit_anti_fraud_call_back(
    call_back_type: CallBackType,
    application_id: int = None,
    new_status: str = None,
):
    """
    This function serves as a call-wrapper for doing call back (webhook) with the antifraud service

    Args:
        call_back_type: -> the type of call back
        application_id: int -> id of the application,
        new_status: str -> the new status of application,

    Returns:
        Boolean
            -> False means there is something wrong while calling the callback
            -> True means the API working properly
    """

    data = {"callback_type": call_back_type.value, "data": None}
    if call_back_type == CallBackType.MOVE_APPLICATION_STATUS:
        data["data"] = {"application_id": application_id, "new_status": new_status}

    try:
        response = anti_fraud_http_client.post(
            path=Path.CALL_BACK,
            data=data,
        )
    except Exception as e:
        logger.error(
            {
                "action": "anti_fraud_call_back",
                "error": e,
            }
        )
        sentry_client.captureException()
        return False

    if response.status_code != 200:
        return False

    response_json = response.json()
    error_response = response_json.get("error", None)
    if error_response != '' and error_response is not None:
        return False

    call_back_check_status = response_json.get("success", None)

    return call_back_check_status


def overwrite_application_history_and_call_anti_fraud_call_back(
    application_id: int,
    application_history: ApplicationHistory,
):
    if application_history:
        from juloserver.fraud_security.tasks import insert_fraud_application_bucket
        from juloserver.antifraud.constant.binary_checks import StatusEnum

        new_change_reason = (
            application_history.change_reason + " -> " + StatusEnum.MOVE_APPLICATION_TO115.value
        )
        logger.info(
            {
                "action": "overwrite_application_history_and_call_anti_fraud_call_back",
                "message": "update application history",
                "application_id": application_id,
                "new_change_reason": new_change_reason,
            },
        )
        application_history.update_safely(change_reason=new_change_reason)
        execute_after_transaction_safely(
            lambda: insert_fraud_application_bucket.delay(
                application_id,
                new_change_reason,
            )
        )

        return
    else:
        logger.info(
            {
                "action": "overwrite_application_history_and_call_anti_fraud_call_back",
                "message": "application history not found",
                "application_id": application_id,
            },
        )
        return
