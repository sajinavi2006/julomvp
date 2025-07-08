import pickle
import zlib

from celery.task import task

from juloserver.fraud_security.tasks import process_mobile_user_action_log_checks
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.user_action_logs.models import MobileUserActionLog, WebUserActionLog
from juloserver.julolog.julolog import JuloLog

logger = JuloLog(__name__)
BATCH_SIZE = 25


@task(queue='user_action_log')
def store_mobile_user_action_log(validated_data_compressed: bytes):
    """
    Store mobile user action log data in the database.
    Compression is needed to reduce RMQ memory and disk usage.

    Args:
        validated_data_compressed (bytes): Compression using zlib from pickle encoding.
            The decoded data is a validated data from CustomMobileUserActionLogSerializer.

    Returns:
         None
    """
    validated_data_json = zlib.decompress(validated_data_compressed)
    validated_data = pickle.loads(validated_data_json)

    user_action_logs = [MobileUserActionLog(**item) for item in validated_data]

    logs = MobileUserActionLog.objects.bulk_create(user_action_logs, batch_size=BATCH_SIZE)
    try:
        log_data_list = []
        logger_view = []
        for log in logs:
            log_data = {
                'log_ts': log.log_ts,
                'customer_id': log.customer_id,
                'activity': log.activity,
                'fragment': log.fragment,
                'event': log.event,
                'view': log.view,
            }
            log_data_list.append(log_data)

            if log.view == 'btnContinue':
                additional_log_data = {
                    'android_id': log.android_id,
                    'app_version': log.app_version,
                    'device_brand': log.device_brand,
                    'device_model': log.device_model,
                    'application_id': log.application_id,
                    **log_data,
                }
                logger_view.append(additional_log_data)

        process_mobile_user_action_log_checks.apply_async(
            [
                log_data_list,
            ]
        )

        logger.info(
            {
                'message': 'Done process execute store_mobile_user_action_log',
                'data': logger_view,
            }
        )

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()
    return len(logs)


@task(queue='user_action_log')
def store_web_log(data: dict):
    WebUserActionLog.objects.create(**data)
