from typing import List
from juloserver.omnichannel.constants import CommChannelEnum
from juloserver.omnichannel.models import OmnichannelCustomerSync
from juloserver.omnichannel.services.utils import (
    get_omnichannel_full_rollout_channels,
    get_update_omnichannel_customer_sync_field,
)
from juloserver.omnichannel.models import OmnichannelCustomer, CustomerAttribute
from datetime import (
    datetime,
)
from juloserver.omnichannel.clients import get_omnichannel_http_client
import logging

logger = logging.getLogger(__name__)


def update_omnichannel_rollout(
    customer_ids: List[int],
    rollout_channels: List[str],
    is_included: bool,
    update_db: bool = True,
    sync_all_customers: bool = True,
):
    validation = validate_rollout_channels(rollout_channels)
    if validation is not None:
        logger.error(
            {
                'action': 'update_omnicahnnel_rollout_validation_failed',
                'error': 'Invalid rollout channels: ' + validation[0],
            }
        )
        raise Exception("Invalid rollout channels: " + validation[0])

    full_rollout_channels = get_omnichannel_full_rollout_channels()

    if full_rollout_channels is None:
        logger.error(
            {
                'action': 'update_omnicahnnel_rollout_fs_failed',
                'error': 'fs not active or not found',
            }
        )
        return

    omnichannel_customer = OmnichannelCustomerSync.objects.filter(customer_id__in=customer_ids)

    if not omnichannel_customer:
        raise Exception('omnichannel_customer_sync not found')

    if update_db:
        update_omnichannel_customer_field = get_update_omnichannel_customer_sync_field(
            rollout_channels, is_included
        )
        omnichannel_customer.update(**update_omnichannel_customer_field)

    if sync_all_customers:
        omnichannel_customer = OmnichannelCustomerSync.objects.all()

    send_rollout_channels_to_omnichannel(
        omnichannel_customer=list(omnichannel_customer),
        full_rollout_channels=full_rollout_channels,
    )


def validate_rollout_channels(rollout_channels: List[str]):
    enum_value_to_dict = {member.value: member for member in CommChannelEnum}

    invalid_channels = []
    for channel in rollout_channels:
        if channel not in enum_value_to_dict:
            invalid_channels.append(channel)

    if invalid_channels:
        return invalid_channels

    return None


def send_rollout_channels_to_omnichannel(
    omnichannel_customer: List[OmnichannelCustomerSync], full_rollout_channels: List[str]
):
    customer_omnichannel = []
    index = 0
    for customer in omnichannel_customer:
        rollout_channels = get_rollout_channels(customer, full_rollout_channels)

        construct_request = OmnichannelCustomer(
            customer_attribute=CustomerAttribute(rollout_channels=rollout_channels),
            customer_id=str(customer.customer_id),
            updated_at=datetime.now(),
        )

        customer_omnichannel.append(construct_request)
        index += 1

        if index >= 10000:
            resp = update_customer(customer_omnichannel)
            logger.info({"action": "send_rollout_channels_to_omnichannel", "response": resp})
            customer_omnichannel.clear()
            index = 0

    if len(customer_omnichannel) == 0:
        return

    resp = update_customer(customer_omnichannel)
    logger.info({"action": "send_rollout_channels_to_omnichannel", "response": resp})


def get_rollout_channels(
    omnichannel_customer: OmnichannelCustomerSync, full_rollout_channels: List[str]
):
    rollout_channels = []
    if (
        omnichannel_customer.is_rollout_email
        or CommChannelEnum.EMAIL.value in full_rollout_channels
    ):
        rollout_channels.append(CommChannelEnum.EMAIL.value)

    if (
        omnichannel_customer.is_rollout_one_way_robocall
        or CommChannelEnum.ONE_WAY_ROBOCALL.value in full_rollout_channels
    ):
        rollout_channels.append(CommChannelEnum.ONE_WAY_ROBOCALL.value)

    if omnichannel_customer.is_rollout_pds or CommChannelEnum.PDS.value in full_rollout_channels:
        rollout_channels.append(CommChannelEnum.PDS.value)

    if omnichannel_customer.is_rollout_sms or CommChannelEnum.SMS.value in full_rollout_channels:
        rollout_channels.append(CommChannelEnum.SMS.value)

    if (
        omnichannel_customer.is_rollout_two_way_robocall
        or CommChannelEnum.TWO_WAY_ROBOCALL.value in full_rollout_channels
    ):
        rollout_channels.append(CommChannelEnum.TWO_WAY_ROBOCALL.value)

    if omnichannel_customer.is_rollout_pn or CommChannelEnum.PN.value in full_rollout_channels:
        rollout_channels.append(CommChannelEnum.PN.value)

    return rollout_channels


def update_customer(req: OmnichannelCustomer):
    omnichannel_client = get_omnichannel_http_client()
    resp = omnichannel_client.update_customers(req)
    resp_body = resp.json()
    return resp_body
