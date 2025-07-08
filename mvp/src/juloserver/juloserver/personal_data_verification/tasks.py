import logging

from celery.task import task
from django.conf import settings
from django.db import Error

from juloserver.julo.models import Application, FeatureSetting
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.personal_data_verification.clients import (
    get_dukcapil_client,
    get_dukcapil_direct_client,
)
from juloserver.personal_data_verification.constants import (
    DukcapilFeatureMethodConst,
    DukcapilResponseSourceConst,
    BureauConstants
)
from juloserver.personal_data_verification.clients import get_bureau_client

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


@task(name='notify_dukcapil_asliri_remaining_balance')
def notify_dukcapil_asliri_remaining_balance():
    try:
        from juloserver.personal_data_verification.services import get_dukcapil_verification_setting
        feature = FeatureSetting.objects.filter(
            is_active=True, feature_name='notify_dukcapil_asliri_remaining_balance'
        ).last()
        if feature:
            parameters = feature.parameters
            dukcapil_client = get_dukcapil_client()
            prod_balances, low_balance_products = dukcapil_client.get_dukcapil_remaining_balance(
                parameters=parameters
            )
            if low_balance_products:
                slack_bot = get_slack_bot_client()
                for product in low_balance_products:
                    message = """ {} <@U04EDJJTX6Y> <@URLGD516U>
                    Product '{}' balance is {}, Please consider to top-up"""
                    message = message.format(
                        settings.ENVIRONMENT,
                        product.get('url'),
                        str(product.get('remaining_balance'))
                    )
                    slack_bot.api_call(
                        "chat.postMessage", channel='#asliri_balance_reminder', text=message
                    )
                    if product.get('url') == 'verify_biometric_basic':
                        if product.get('remaining_balance') == 0:
                            logger.info({
                                'task': 'notify_dukcapil_asliri_remaining_balance',
                                'message': 'balance 0, auto change into dukcapil direct'
                            })

                            # turn off alert setting
                            feature.update_safely(is_active=False)

                            # change method to dukcapil direct
                            setting = get_dukcapil_verification_setting()
                            setting.update_safely(method=DukcapilFeatureMethodConst.DIRECT_V2)
                        else:
                            # decrement the threshold for alert
                            threshold = parameters.get('verify_biometric_basic') - 1000
                            parameters.update({'verify_biometric_basic': threshold})
                            feature.update_safely(parameters=parameters)

    except Exception as e:
        logger.info({'task': 'notify_dukcapil_asliri_remaining_balance', 'exception': str(e)})


@task(name='notify_dukcapil_direct_low_balance')
def notify_dukcapil_direct_low_balance(low_balance=27000):
    from django.conf import settings
    import requests

    try:
        url = settings.SLACK_WEBHOOK_DUKCAPIL_LOW_BALANCE_URL
        headers = {
            'Content-Type': 'application/json',
        }
        low_balance = '{:,}'.format(low_balance)
        message = "[ALERT] {} hits left in the remaining Dukcapil quota"
        message = message.format(low_balance)
        data = {"message": message}

        requests.post(
            url,
            headers=headers,
            json=data,
        )

    except Exception as e:
        logger.info({'task': 'notify_dukcapil_direct_low_balance', 'exception': str(e)})


@task(autoretry_for=(Error,), retry_backoff=60, max_retry=3)
def send_dukcapil_official_callback_data(application_id):
    """
    Will retry 3 times if there is database related error
    """
    from juloserver.julo.constants import FeatureNameConst as JuloConst
    from juloserver.personal_data_verification.services import (
        get_dukcapil_verification_feature,
        get_latest_dukcapil_response,
        get_dukcapil_verification_feature_leadgen,
    )

    logger_data = {
        'module': 'personal_data_verification',
        'action': 'send_dukcapil_official_callback_data',
        'application_id': application_id,
    }
    application = Application.objects.get(id=application_id)
    if application.is_partnership_leadgen():
        dukcapil_feature = get_dukcapil_verification_feature_leadgen(
            application.partner.name, method=DukcapilFeatureMethodConst.DIRECT
        )
    else:
        dukcapil_feature = get_dukcapil_verification_feature(DukcapilFeatureMethodConst.DIRECT)
    if not dukcapil_feature:
        logger.info({'message': 'Dukcapil direct feature is not active', **logger_data})
        return False

    logger_data.update(application_status_code=application.status)

    dukcapil_response = get_latest_dukcapil_response(
        application=application, source=DukcapilResponseSourceConst.DIRECT
    )
    if not dukcapil_response or not dukcapil_response.is_eligible():
        logger.info({'message': 'not eligible for dukcapil direct', **logger_data})
        return False

    dukcapil_client = get_dukcapil_direct_client(application=application)
    dukcapil_mock_feature = FeatureSetting.objects.get_or_none(
        feature_name=JuloConst.DUKCAPIL_CALLBACK_MOCK_RESPONSE_SET,
        is_active=True,
    )

    if (
        settings.ENVIRONMENT != 'prod'
        and dukcapil_mock_feature
        and (
            (
                'j-starter' in dukcapil_mock_feature.parameters['product']
                and application.is_julo_starter()
            )
            or (
                'j1' in dukcapil_mock_feature.parameters['product']
                and application.is_julo_one_product()
            )
        )
    ):
        is_success, note = dukcapil_client.mock_hit_dukcapil_official_store_api()
    else:
        is_success, note = dukcapil_client.hit_dukcapil_official_store_api()

    logger.info(
        {
            'message': 'Finish send dukcapil official callback data',
            'is_success': is_success,
            'note': note,
            **logger_data,
        }
    )
    return is_success


@task(queue='application_normal')
def face_recogniton(application_id, nik: str):
    from juloserver.personal_data_verification.services import DukcapilFRService
    dukcapil_fr_service = DukcapilFRService(application_id, nik)
    try:
        dukcapil_fr_service.face_recognition()
    except Exception:
        sentry_client.captureException()


@task(queue="application_normal")
def fetch_dukcapil_data(application_id):
    from juloserver.personal_data_verification.services import is_pass_dukcapil_verification

    application = Application.objects.get(pk=application_id)
    is_pass_dukcapil_verification(application)


@task(queue='fraud')
def trigger_bureau_alternative_data_services_apis(application_id: int):
    application = Application.objects.get(id=application_id)
    for service in BureauConstants.alternate_data_services():
        bureau_client = get_bureau_client(application, service)
        bureau_client.hit_bureau_api()


@task(queue='fraud')
def fetch_bureau_sdk_services_data(data: dict):
    application = Application.objects.get(id=data.get('application_id'))
    session_id = data.get('session_id')
    service = BureauConstants.DEVICE_INTELLIGENCE
    bureau_client = get_bureau_client(application, service, session_id)
    bureau_client.hit_bureau_api()
