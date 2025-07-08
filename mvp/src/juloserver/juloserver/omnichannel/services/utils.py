from datetime import datetime, timedelta, date
from juloserver.julo.services2 import (
    encrypt,
)
from django.conf import settings
from juloserver.urlshortener.services import shorten_url
from typing import (
    Union,
    Any,
)
from dateutil.parser import parse

from typing import List
from juloserver.omnichannel.models import OmnichannelCustomerSync
from juloserver.omnichannel.services.settings import (
    get_omnichannel_integration_setting,
    OmnichannelIntegrationSetting,
)
from juloserver.omnichannel.constants import CommChannelEnum
from juloserver.omnichannel.models import OmnichannelExclusionCommsBlock
from juloserver.julo.models import Application
from juloserver.account_payment.models import AccountPayment
from urllib.parse import urlencode


def count_days_till_today(
    date_source: datetime.date,
) -> int:
    today = datetime.date.today()
    delta = (today - date_source).days
    return int(delta)


def format_number(number: int) -> str:
    formatted_number = "{:,}".format(number)
    return formatted_number.replace(",", ".")


def get_payment_url_raw(model, with_http: bool = False, additional_params: dict = None) -> str:
    encrypttext = encrypt()
    account_id = encrypttext.encode_string(str(model.id))
    url = settings.PAYMENT_DETAILS + str(account_id)
    if additional_params:
        url += '?' + urlencode(additional_params)
    shortened_url = ''
    shortened_url = shorten_url(url)
    if not with_http:
        shortened_url = shortened_url.replace('https://', '')
    return shortened_url


def to_rfc3339(date_str: str) -> Union[str, None]:
    # ref:https://www.rfc-editor.org/rfc/rfc3339
    if not date_str or date_str == 'None':
        return None

    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_obj = date_obj.replace(hour=0, minute=0, second=0)

    if not date_obj.tzinfo:
        return date_obj.strftime('%Y-%m-%dT%H:%M:%SZ')  # return as-is, assuming no TZ == UTC

    date_obj_utc = date_obj - timedelta(hours=date_obj.utcoffset().total_seconds() // 3600)

    return date_obj_utc.strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_to_datetime(val: Any) -> Union[datetime, None]:
    if isinstance(val, str):
        try:
            return parse(val)
        except (ValueError, OverflowError):
            return None

    if isinstance(val, datetime):
        return val

    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())

    return None


def get_omnichannel_customer_ids() -> List[int]:
    return list(OmnichannelCustomerSync.objects.filter().values_list('customer_id', flat=True))


def get_omnichannel_account_ids() -> List[int]:
    return list(OmnichannelCustomerSync.objects.filter().values_list('account_id', flat=True))


def get_exclusion_omnichannel_account_ids(
    exclusion_req: OmnichannelExclusionCommsBlock,
) -> List[int]:
    if not exclusion_req.is_excluded:
        return []

    if exclusion_req.is_full_rollout:
        return list(OmnichannelCustomerSync.objects.filter().values_list('account_id', flat=True))

    rollout_channels = [exclusion_req.comm_type]
    field = get_update_omnichannel_customer_sync_field(
        rollout_channels=rollout_channels, is_included=True
    )

    return list(
        OmnichannelCustomerSync.objects.filter(**field).values_list('account_id', flat=True)
    )


def get_omnichannel_comms_block_active(
    comms_type: OmnichannelIntegrationSetting.CommsType,
) -> OmnichannelExclusionCommsBlock:
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return OmnichannelExclusionCommsBlock(
            is_excluded=False, is_full_rollout=None, comm_type=comms_type
        )

    fs_is_full_rollout = fs.is_full_rollout
    full_rollout_channels = fs.full_rollout_channels()

    is_full_rollout = not fs_is_full_rollout and comms_type in full_rollout_channels

    if fs_is_full_rollout and comms_type in full_rollout_channels:
        return OmnichannelExclusionCommsBlock(
            is_excluded=False, is_full_rollout=is_full_rollout, comm_type=comms_type
        )

    return OmnichannelExclusionCommsBlock(
        is_excluded=fs.is_comms_block_active(comms_type=comms_type),
        is_full_rollout=is_full_rollout,
        comm_type=comms_type,
    )


def get_omnichannel_account_payment_ids(exclusion_req: OmnichannelExclusionCommsBlock) -> List[int]:
    if not exclusion_req.is_excluded:
        return []

    account_ids = []
    if exclusion_req.is_full_rollout:
        account_ids = get_omnichannel_account_ids()
    else:
        rollout_channels = [exclusion_req.comm_type]
        field = get_update_omnichannel_customer_sync_field(
            rollout_channels=rollout_channels, is_included=True
        )
        account_ids = OmnichannelCustomerSync.objects.filter(**field).values_list(
            'account_id', flat=True
        )

    if not account_ids:
        return []

    return list(
        AccountPayment.objects.filter(account_id__in=account_ids).values_list('id', flat=True)
    )


def str_to_bool(value: str) -> bool:
    if value.lower() in ('true', '1', 'True'):
        return True
    elif value.lower() in ('false', '0', 'false'):
        return False
    raise ValueError("Boolean value expected")


def get_omnichannel_full_rollout_channels() -> List[str]:
    fs = get_omnichannel_integration_setting()
    if not fs.is_active:
        return None

    return fs.full_rollout_channels()


def get_update_omnichannel_customer_sync_field(
    rollout_channels: List[str],
    is_included: bool,
):

    field = {}

    if CommChannelEnum.EMAIL.value in rollout_channels:
        field['is_rollout_email'] = is_included

    if CommChannelEnum.PN.value in rollout_channels:
        field['is_rollout_pn'] = is_included

    if CommChannelEnum.PDS.value in rollout_channels:
        field['is_rollout_pds'] = is_included

    if CommChannelEnum.SMS.value in rollout_channels:
        field['is_rollout_sms'] = is_included

    if CommChannelEnum.ONE_WAY_ROBOCALL.value in rollout_channels:
        field['is_rollout_one_way_robocall'] = is_included

    if CommChannelEnum.TWO_WAY_ROBOCALL.value in rollout_channels:
        field['is_rollout_two_way_robocall'] = is_included

    return field


def exists_in_omnichannel_customer_sync(customer_id: int) -> bool:
    """
    Check if customer_id exists in OmnichannelCustomerSync table
    Args:
        customer_id (int): The customer id
    Returns:
        bool: True if the customer_id exists in OmnichannelCustomerSync table, False otherwise
    """
    return OmnichannelCustomerSync.objects.filter(customer_id=customer_id).exists()


def is_omnichannel_customer(
    exclusion_req: OmnichannelExclusionCommsBlock,
    customer_id: int = None,
) -> bool:
    """
    Checks if the customer is eligible for omnichannel communication.
    Args:
        exclusion_req (OmnichannelExclusionCommsBlock): exclusion block rules
        customer_id (int): The customer id
    Returns:
        bool: True if the customer is eligible for omnichannel communication, False otherwise
    """
    if not customer_id:
        return False

    if exclusion_req.is_full_rollout:
        return OmnichannelCustomerSync.objects.filter(customer_id=customer_id).exists()

    rollout_channels = [exclusion_req.comm_type]
    field = get_update_omnichannel_customer_sync_field(
        rollout_channels=rollout_channels, is_included=True
    )

    return OmnichannelCustomerSync.objects.filter(customer_id=customer_id, **field).exists()


def is_omnichannel_account(
    exclusion_req: OmnichannelExclusionCommsBlock,
    account_id: int = None,
) -> bool:
    if not account_id:
        return False

    if exclusion_req.is_full_rollout:
        return OmnichannelCustomerSync.objects.filter(account_id=account_id).exists()

    rollout_channels = [exclusion_req.comm_type]
    field = get_update_omnichannel_customer_sync_field(
        rollout_channels=rollout_channels, is_included=True
    )

    return OmnichannelCustomerSync.objects.filter(account_id=account_id, **field).exists()


def is_application_owned_by_omnichannel_customer(
    exclusion_req: OmnichannelExclusionCommsBlock,
    application: Application = None,
) -> bool:
    if not application or not exclusion_req:
        return False

    customer_id = application.customer_id

    return is_omnichannel_customer(customer_id=customer_id, exclusion_req=exclusion_req)


def is_account_payment_owned_by_omnichannel_customer(
    exclusion_req: OmnichannelExclusionCommsBlock,
    account_payment: AccountPayment = None,
) -> bool:
    if not account_payment or not exclusion_req:
        return False

    account_id = account_payment.account_id

    return is_omnichannel_account(account_id=account_id, exclusion_req=exclusion_req)
