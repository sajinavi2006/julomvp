import logging
from typing import Tuple
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from juloserver.autodebet.models import AutodebetIdfyVideoCall
from juloserver.account.models import Account
from juloserver.julo.models import FeatureSetting, FeatureNameConst
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Customer,
)
from juloserver.julo.clients.idfy import (
    IDfyApiClient,
    IDfyTimeout,
    IDfyProfileCreationError,
    IDfyOutsideOfficeHour,
    IDfyServerError,
    IDFyGeneralMessageError,
)
from juloserver.autodebet.constants import (
    LabelFieldsIDFyConst,
    RedisKey,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.autodebet.tasks import send_pn_idfy_unfinished_autodebet_activation

logger = logging.getLogger(__name__)
sentry = get_julo_sentry_client()


def get_idfy_instruction():
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.AUTODEBIT_IDFY_INSTRUCTION_PAGE, is_active=True
    )
    if not feature_setting:
        return None

    try:
        return feature_setting.parameters
    except Exception:
        sentry.captureException()
        return None


def is_office_hours_agent_for_idfy() -> Tuple[bool, str]:
    """
    To check still in office hours or not
    for video call IDFy Autodebet.
    """
    message = None
    today = timezone.localtime(timezone.now())
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS, is_active=True
    ).last()
    if not fs:
        logger.warn(
            {
                'action': 'is_office_hours_agent_for_autodebit_idfy',
                'message': 'Office hours feature setting is off',
                'result': False,
            }
        )
        message = 'Video call tidak tersedia saat ini'
        return False, message

    day_of_week = today.weekday()
    office_hours = fs.parameters['holidays'] if day_of_week >= 5 else fs.parameters['weekdays']

    open_gate = today.replace(
        hour=office_hours['open']['hour'],
        minute=office_hours['open']['minute'],
    )
    closed_gate = today.replace(
        hour=office_hours['close']['hour'],
        minute=office_hours['close']['minute'],
    )

    if open_gate <= today <= closed_gate:
        logger.info(
            {
                'action': 'is_office_hours_agent_for_autodebet_idfy',
                'message': 'In office hours and not completed video call',
                'result': True,
                'open_gate': str(open_gate),
                'closed_gate': str(closed_gate),
            }
        )
        return True, message

    logger.warn(
        {
            'action': 'is_office_hours_agent_for_autodebet_idfy',
            'message': 'Outside office hours',
            'result': False,
            'open_gate': str(open_gate),
            'closed_gate': str(closed_gate),
        }
    )

    message = (
        'Video call hanya bisa dilakukan pada jam {0:02d}.{1:02d} - {2:02d}.{3:02d} WIB'.format(
            office_hours['open']['hour'],
            office_hours['open']['minute'],
            office_hours['close']['hour'],
            office_hours['close']['minute'],
        )
    )

    return False, message


def create_idfy_profile(customer: Customer) -> Tuple[str, str]:
    account = Account.objects.filter(customer=customer).last()
    if not account:
        logger.warn(
            {
                'action': 'create_autodebit_idfy_profile',
                'message': 'Account not found for video call',
                'customer': customer.id if customer else None,
            }
        )
        raise IDFyGeneralMessageError('Account not found for video call')

    features_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_IDFY_CONFIG_ID, is_active=True
    ).last()
    if not features_setting:
        logger.warn(
            {
                'action': 'create_autodebit_idfy_profile',
                'message': 'Config ID not available',
                'customer': customer.id if customer else None,
            }
        )
        raise IDfyProfileCreationError('IDfy Feature setting not active')

    # check for office hour
    is_office_hours, error_message = is_office_hours_agent_for_idfy()
    if not is_office_hours:
        logger.warn(
            {
                'action': 'create_autodebit_idfy_profile',
                'message': 'Outside office hour in return same profile',
                'account': account.id,
                'is_office_hours': is_office_hours,
            }
        )
        raise IDfyOutsideOfficeHour(error_message)

    idfy_query = AutodebetIdfyVideoCall.objects.filter(
        account=account,
        profile_url__isnull=False,
    )

    total_profile = idfy_query.count()

    max_days_idfy_alive = timezone.localtime(timezone.now()) - timedelta(
        days=LabelFieldsIDFyConst.MAX_DAYS_IDFY_ALIVE
    )
    idfy_profile = idfy_query.filter(
        status__in=(
            LabelFieldsIDFyConst.KEY_CAPTURE_PENDING,
            LabelFieldsIDFyConst.KEY_RECAPTURE_PENDING,
        ),
        cdate__gte=max_days_idfy_alive,
    ).last()

    if idfy_profile:
        logger.info(
            {
                'action': 'create_autodebit_idfy_profile',
                'message': 'return profile url in office hours',
                'account': account.id,
                'status_idfy': idfy_profile.status,
                'is_office_hours': is_office_hours,
            }
        )

        return idfy_profile.profile_url, idfy_profile.profile_id

    idfy_client = IDfyApiClient(
        settings.AUTODEBET_IDFY_API_KEY,
        features_setting.parameters['config_id'],
        settings.AUTODEBET_IDFY_BASE_URL,
    )
    try:
        fullname = customer.fullname.split()
        first_name = fullname[0].title()
        last_name = fullname[-1].title() if len(fullname) > 1 else ''

        reference_id = '{}_{}'.format(str(customer.id), str(total_profile + 1).zfill(3))
        response = idfy_client.create_profile(
            reference_id, first_name, last_name, customer.email, customer.phone
        )
    except (IDfyServerError, IDfyTimeout) as e:
        logger.warn(
            {
                'action': 'create_autodebit_idfy_profile',
                'message': 'IDfyServerError/IDfyTimeout - {}'.format(str(e)),
                'customer': customer.id if customer else None,
                'account': account.id,
                'idfy_reference_id': reference_id,
            }
        )
        raise IDfyTimeout('Error creating profile for account id {}: {}'.format(account.id, e))
    except IDfyProfileCreationError as e:
        logger.warn(
            {
                'action': 'create_autodebit_idfy_profile',
                'message': 'IDfyProfileCreationError - {}'.format(str(e)),
                'customer': customer.id if customer else None,
                'account': account.id,
                'idfy_reference_id': reference_id,
            }
        )
        raise IDfyProfileCreationError(
            'Error creating profile for account_id {}: {}'.format(account.id, e)
        )

    video_call_url = response.get('capture_link')
    profile_id = response.get('profile_id')

    if not AutodebetIdfyVideoCall.objects.filter(reference_id=reference_id).exists():
        AutodebetIdfyVideoCall.objects.create(
            reference_id=reference_id,
            account=account,
            status=LabelFieldsIDFyConst.KEY_CAPTURE_PENDING,
            profile_url=video_call_url,
            profile_id=profile_id,
        )
    return video_call_url, profile_id


def get_status_reason(data):
    for item in data.get('tasks', []):
        if item.get('key') == 'vkyc.assisted_vkyc':
            manual_response = item.get('result', {}).get('manual_response', {})
            return manual_response.get('status_reason', None) if manual_response else None

    return None


def proceed_the_status_complete_response(response):
    if not response:
        raise Exception('Unexpected response from IDFY')

    performed_video_by = None
    status_tasks = None
    profile_data = response['profile_data']

    notes = profile_data['notes']
    if len(profile_data['performed_by']) > 0:
        profile_items = profile_data['performed_by'][0]
        performed_video_by = profile_items['email']

    tasks_data = response['tasks']
    if len(tasks_data) > 0:
        status_tasks = tasks_data[0]['status']

    status_reason = get_status_reason(response)
    data = {
        'profile_id': response['profile_id'],
        'reference_id': response['reference_id'],
        'performed_video_call_by': performed_video_by,
        'status': response['status'],
        'status_tasks': status_tasks,
        'reviewer_action': response['reviewer_action'],
        'notes': notes,
        'reject_reason': status_reason,
    }

    idfy_record = AutodebetIdfyVideoCall.objects.filter(
        reference_id=response['reference_id'],
    ).last()
    if not idfy_record:
        raise Exception('IDFy record not found')

    idfy_record.update_safely(**data)


def proceed_the_status_dropoff_response(response):
    if not response:
        raise Exception('Unexpected response from IDFY')

    data = {
        'profile_id': response['profile_id'],
        'reference_id': response['reference_id'],
        'status': response['status'],
    }

    idfy_record = AutodebetIdfyVideoCall.objects.filter(
        reference_id=data['reference_id'],
    ).last()
    if not idfy_record:
        raise Exception('IDFy record not found')

    idfy_record.update_safely(**data)


def is_idfy_profile_exists(account: Account) -> bool:
    """
    To check user has done video call using idfy
    """
    features_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_IDFY_CONFIG_ID, is_active=True
    ).last()
    if not features_setting:
        return False

    is_exists_idfy_url = AutodebetIdfyVideoCall.objects.filter(
        account=account,
        profile_url__isnull=False,
    ).exists()

    return is_exists_idfy_url


def schedule_unfinished_activation_pn(customer: Customer, vendor: str):
    account = Account.objects.get_or_none(customer=customer)

    # PREVENT OVERLAPPING SCHEDULE
    flag_key = RedisKey.IDFY_NOTIFICATION_FLAG + str(account.id)
    redis_client = get_redis_client()
    is_already_scheduled = redis_client.get(flag_key)

    # SCHEDULE PUSH NOTIFICATION
    if not is_already_scheduled:
        idfy_pn_timer = FeatureSetting.objects.filter(
            is_active=True,
            feature_name=FeatureNameConst.AUTODEBET_IDFY_PN_TIMER,
        ).last()
        if (
            not idfy_pn_timer
            or not idfy_pn_timer.parameters
            or not idfy_pn_timer.parameters.get("interval_seconds")
        ):
            return

        interval_seconds = idfy_pn_timer.parameters.get("interval_seconds")
        send_pn_idfy_unfinished_autodebet_activation.apply_async(
            (
                customer.id,
                vendor,
            ),
            countdown=interval_seconds,
        )

        # PREVENT OVERLAPPING SCHEDULE
        redis_client.set(
            flag_key,
            "true",
            timedelta(seconds=interval_seconds),
        )

    return
