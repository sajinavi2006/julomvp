import logging
from django.conf import settings
from django.utils import timezone
from juloserver.julo.utils import upload_file_to_oss
from juloserver.julo.services2 import get_redis_client
from juloserver.limit_validity_timer.constants import LimitValidityTimerConsts
from juloserver.limit_validity_timer.models import LimitValidityTimer
from juloserver.portal.core import functions
from juloserver.limit_validity_timer.tasks import trigger_upload_limit_validity_timer_campaign
from juloserver.account.models import AccountLimit
from juloserver.account.constants import AccountConstant


logger = logging.getLogger(__name__)


def populate_limit_validity_campaign_on_redis(customer_ids, campaign_id, expire_at):
    redis_client = get_redis_client()
    redis_key = LimitValidityTimerConsts.LIMIT_VALIDITY_TIMER_REDIS_KEY.format(campaign_id)
    redis_client.delete_key(redis_key)
    result = redis_client.sadd(redis_key, customer_ids)
    redis_client.expireat(redis_key, expire_at)
    logger.info({
        'action': "populate_limit_validity_campaign_on_redis",
        'campaign_id': campaign_id,
        'customer_affected_count': result
    })


def delete_limit_validity_campaign_on_redis(campaign_id):
    redis_client = get_redis_client()
    redis_key = LimitValidityTimerConsts.LIMIT_VALIDITY_TIMER_REDIS_KEY.format(campaign_id)
    redis_client.delete_key(redis_key)
    logger.info({
        'action': "delete_limit_validity_campaign_on_redis",
        'campaign_id': campaign_id,
    })


def upload_csv_to_oss(obj, request_file):
    remote_path = 'limit_validity_timer/campaign{}'.format(obj.id)
    obj.update_safely(upload_url=remote_path)
    file = functions.upload_handle_media(request_file, "limit_validity_timer/campaign")
    if file:
        upload_file_to_oss(
            settings.OSS_MEDIA_BUCKET,
            file['file_name'],
            remote_path
        )


def get_soonest_campaign_for_customer_from_redis(campaign_qs, customer):
    redis_client = get_redis_client()
    for campaign in campaign_qs:
        redis_key = LimitValidityTimerConsts.LIMIT_VALIDITY_TIMER_REDIS_KEY.format(campaign.id)
        redis_data = redis_client.exists(redis_key)
        if not redis_data:
            # lost data
            trigger_upload_limit_validity_timer_campaign.delay(campaign.id)
            return None

        if redis_client.sismember(redis_key, customer.id):
            return campaign

    return None


def get_validity_campaign_timer_response(campaign):
    content = campaign.content
    response_data = dict(
        end_time=campaign.end_date,
        campaign_name=campaign.campaign_name,
        information=dict(
            title=content["title"],
            body=content["body"],
            button=content["button"],
        ),
        pop_up_message=None
    )

    if campaign.transaction_method_id:
        response_data['information']['transaction_method_id'] = campaign.transaction_method_id
    elif campaign.deeplink_url:
        response_data['information']['deeplink_url'] = campaign.deeplink_url

    return response_data
