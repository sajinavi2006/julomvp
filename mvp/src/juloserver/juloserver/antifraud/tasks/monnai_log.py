import logging
from celery import task
from juloserver.antifraud.client import get_anti_fraud_http_client
from juloserver.antifraud.constant.transport import Path
from juloserver.julo.clients import get_julo_sentry_client


logger = logging.getLogger(__name__)
anti_fraud_http_client = get_anti_fraud_http_client()
sentry_client = get_julo_sentry_client()


@task(queue='fraud')
def store_monnai_log(data: dict, times_retried: int = 0) -> None:
    """
    This function serves as a celery task
    for store the monnai log to the fraud db
    through fraud service

    Args:
        data (dict): request body that we want to store
        times_retried (int): times retried

    Returns:
        None
    """

    success = True
    try:

        response = anti_fraud_http_client.post(
            path=Path.STORE_MONNAI_LOG,
            data=data,
        )
    except Exception as e:
        logger.error(
            {
                'action': 'anti_fraud_http_client.store_monnai_log',
                'error': str(e),
            }
        )
        sentry_client.captureException()
        success = False

    if success and response is None:
        success = False

    if success and response.status_code != 201:
        success = False

    if not success and times_retried < 3:
        store_monnai_log.apply_async(
            args=[data, times_retried + 1],
            countdown=60 * (2**times_retried),
        )
        return
    elif not success:
        logger.error(
            {'action': 'store_monnai_log', 'error': 'Failed to store_monnai_log', 'data': data},
            exc_info=True,
        )
        return

    logger.info(
        {
            'action': 'store_monnai_log',
            'message': 'Successfully store_monnai_log',
            'reference_id': data.get('reference_id'),
        }
    )

    return
