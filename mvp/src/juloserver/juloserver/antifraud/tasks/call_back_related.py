from __future__ import division

import logging

from celery import task

from juloserver.antifraud.constant.call_back import CallBackType
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Application
from juloserver.julo.product_lines import ProductLineCodes

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(queue='fraud')
def hit_anti_fraud_call_back_async(
    call_back_type: CallBackType, application_id: int = None, new_status: str = None, retry: int = 0
):
    """
    Antifraud call back api to do some action depends on the call_back_type

    Args:
        call_back_type (CallBackType): the call back type
        application_id (int): the application id
        new_status (string): the new status of application or loan
        retry (int): the number of retry

    Returns:
        None
    """
    from juloserver.antifraud.services.call_back import hit_anti_fraud_call_back

    # for now only for J1
    application = Application.objects.filter(id=application_id).last()
    if not application:
        return
    elif application.product_line_id not in [ProductLineCodes.J1, ProductLineCodes.JTURBO]:
        return

    log_data = {
        'action': 'hit_anti_fraud_call_back_async',
        'call_back_type': call_back_type,
        'application_id': application_id,
        'new_status': new_status,
    }
    max_retry = 3

    logger.info({'message': 'calling hit_anti_fraud_call_back', **log_data})
    response_status = hit_anti_fraud_call_back(call_back_type, application_id, new_status)
    logger.info(
        {'message': 'done hit_anti_fraud_call_back', 'response_status': response_status, **log_data}
    )

    if not response_status and retry <= max_retry:
        logger.info(
            {'message': 'retrying... hit_anti_fraud_call_back_async', 'retry': retry, **log_data}
        )
        countdown_in_seconds = 120 * retry
        hit_anti_fraud_call_back_async.apply_async(
            (call_back_type, application_id, new_status, retry + 1), countdown=countdown_in_seconds
        )
