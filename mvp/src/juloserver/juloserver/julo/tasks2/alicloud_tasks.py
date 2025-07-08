import json
import logging

from aliyunsdkcore.acs_exception.exceptions import (
    ClientException,
    ServerException,
)
from celery import task

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import VendorConst
from juloserver.julo.exceptions import AlicloudRetryException
from juloserver.julo.models import SmsHistory

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


@task(queue='comms', name='alicloud_sms_fetch_report', rate_limit='300/s')
def fetch_alicloud_sms_report(message_id: str, retry: int = 0) -> bool:
    """
    Alicloud Short Message Service Delivery Report Query API.
    Doc: https://www.alibabacloud.com/help/en/short-message-service/latest/querymessage

    We expect one of three statuses: 1 (success), 2 (failed), 3 (pending).
    Note that these statuses conflict with the callback API.

    Args:
        message_id (str): The sms message_id to fetch.
        retry (int): Used for retrying the function.

    Returns:
        bool: If successful returns True otherwise returns False.
    """
    from juloserver.julo.clients.alicloud import JuloAlicloudClient
    from aliyunsdkcore.request import CommonRequest
    if retry > 10:
        logger.error({
            'action': 'JuloAliCloudClient.get_sms_report',
            'message': 'Max retry. Alicloud SMS status hangs at 3 (the message is being sent)',
            'retry': retry,
            'message_id': message_id
        })
        return False

    alicloud_client = JuloAlicloudClient()
    request = CommonRequest(
        domain=alicloud_client.alicloud_domain,
        version=alicloud_client.alicloud_version,
        action_name='QueryMessage'
    )
    request.set_accept_format('json')
    request.set_method('POST')
    request.set_protocol_type('https')
    request.add_query_param('RegionId', alicloud_client.alicloud_region_id)
    request.add_query_param('MessageId', message_id)

    api_response = None
    try:
        api_response = alicloud_client.client.do_action_with_exception(request)
        api_response = json.loads(api_response)

        sms_history = SmsHistory.objects.get_or_none(message_id=api_response['MessageId'],
            comms_provider__provider_name=VendorConst.ALICLOUD.capitalize())
        if sms_history is None:
            logger.info({
                'message': 'Alicloud send unregistered message_id',
                'message_id': api_response['MessageId'],
            })
            return False

        # TODO: After we officially use Alicloud as sms vendor.
        #  Need to store error details as string (delivery_error_code is integer).
        if api_response['Status'] == 2:
            sms_history.update_safely(status='FAILED')
            logger.info({
                'message': 'Alicloud returns error',
                'message_id': api_response['MessageId'],
                'error_code': api_response['ErrorCode'],
                'error_description': api_response['ErrorDescription']
            })
            return False
        elif api_response['Status'] == 1:
            sms_history.update_safely(status='DELIVERED')

            return True
        else:
            raise AlicloudRetryException('Retrying fetch report.')
    except (ServerException, ClientException, AlicloudRetryException) as e:
        sentry_client.captureException()
        logger.info({
            'message': 'Retrying alicloud sms report request.',
            'retry': retry + 1,
            'response': api_response,
            'error': str(e)
        })
        fetch_alicloud_sms_report.apply_async((message_id, retry + 1,), countdown=5 * 60)
    except Exception as e:
        logger.info({
            'message': 'Retrying alicloud sms report request fail. Unexpected exceptions.',
            'retry': retry + 1,
            'error': str(e)
        })
        raise
