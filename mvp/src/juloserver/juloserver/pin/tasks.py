import logging
from builtins import str

from celery import task
from django.conf import settings
from django.template.loader import get_template
from django.utils import timezone

from juloserver.julo.clients import (
    get_julo_email_client,
    get_julo_sms_client,
    get_julo_sentry_client,
)
from juloserver.julo.models import (
    Application,
    Customer,
    EmailHistory,
)
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.julovers.constants import JuloverPageConst
from juloserver.julovers.services.core_services import JuloverPageMapping
from juloserver.pin.clients import get_julo_pin_email_client, get_julo_pin_sms_client
from juloserver.urlshortener.services import shorten_url
from juloserver.pin.utils import get_first_name

from .services import CustomerPinChangeService
from .signals import login_success
from ..antifraud.services.pii_vault import detokenize_pii_antifraud_data
from ..julo.exceptions import EmailNotSent
from ..pii_vault.constants import PiiSource

logger = logging.getLogger(__name__)


@task(queue='application_high')
def send_reset_pin_email(email, reset_pin_key, new_julover=False, customer=None):
    reset_pin_page_link = settings.RESET_PIN_JULO_ONE_LINK_HOST + reset_pin_key + '/'

    if customer and not customer.phone:
        reset_pin_page_link = (
            settings.RESET_PIN_PHONE_VERIFICATION_JULO_ONE_LINK_HOST + reset_pin_key + '/'
        )

    logger.info(
        {
            'status': 'reset_pin_page_link_created',
            'action': 'sending_email',
            'email': email,
            'reset_pin_page_link': reset_pin_page_link,
        }
    )
    time_now = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
    subject = "JULO: Reset PIN (%s) - %s" % (email, time_now)
    template = get_template('email/email_reset_pin.html')
    first_name = 'pelanggan setia JULO'
    if customer:
        first_name = get_first_name(customer)
    variable = {"link": reset_pin_page_link, "first_name": first_name}
    html_content = template.render(variable)
    template_code = 'email_reset_pin'
    app = None
    message_id = None
    error_message = None
    status = 'error'

    if new_julover:
        template_code = None
        app = Application.objects.filter(email__iexact=email).last()
        subject, html_content = JuloverPageMapping.get_julover_page_content(
            title=JuloverPageConst.EMAIL_AT_190,
            application=app,
            reset_pin_key=reset_pin_key,
        )

    try:
        status, _, headers = get_julo_email_client().send_email(
            subject,
            html_content,
            email,
            settings.EMAIL_FROM,
        )
        if status == 202:
            status = 'sent_to_sendgrid'
            error_message = None
        message_id = headers['X-Message-Id']
    except Exception as e:
        error_message = str(e)
        if not isinstance(e, EmailNotSent):
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.exception('reset_pin_send_email_failed, data={} | err={}'.format(customer, e))

    EmailHistory.objects.create(
        to_email=email,
        subject=subject,
        sg_message_id=message_id,
        template_code=template_code,
        application=app,
        customer=customer,
        status=str(status),
        error_message=error_message,
    )

    customer_pin_change_service = CustomerPinChangeService()
    customer_pin_change_service.update_email_status_to_sent(reset_pin_key)


@task(queue='application_high')
def send_reset_pin_sms(customer, phone_number, reset_pin_key):
    reset_pin_page_link = (
        settings.RESET_PIN_BY_PHONE_NUMBER_JULO_ONE_LINK_HOST + reset_pin_key + '/'
    )

    logger.info(
        {
            'status': 'reset_pin_page_link_created',
            'action': 'sending_e',
            'phone_number': phone_number,
            'reset_pin_page_link': reset_pin_page_link,
        }
    )
    julo_sms_client = get_julo_sms_client()
    reset_pin_page_link = shorten_url(reset_pin_page_link)
    msg = 'Silakan klik link berikut ini untuk reset password kamu ' + reset_pin_page_link
    phone_number = format_e164_indo_phone_number(phone_number)
    message, response = julo_sms_client.send_sms(phone_number, msg)
    response = response['messages'][0]

    if response["status"] != "0":
        logger.exception(
            {
                "send_status": response["status"],
                "message_id": response.get("message-id"),
                "sms_client_method_name": "send_reset_pin_sms",
                "error_text": response.get("error-text"),
            }
        )
    else:
        customer_pin_change_service = CustomerPinChangeService()
        customer_pin_change_service.update_phone_number_status_to_sent(reset_pin_key)
    template_code = 'reset_pin_by_sms'
    sms = create_sms_history(
        response=response,
        customer=customer,
        message_content=msg,
        to_mobile_phone=format_e164_indo_phone_number(phone_number),
        phone_number_type="mobile_phone_1",
        template_code=template_code,
    )
    if sms:
        logger.info(
            {
                "status": "sms_created",
                "sms_history_id": sms.id,
                "message_id": sms.message_id,
            }
        )


@task(queue='application_high')
def send_email_unlock_pin(name, email_to):
    status, subject, headers = get_julo_email_client().email_unlock_pin(name, email_to)

    message_id = headers["X-Message-Id"]
    EmailHistory.objects.create(
        sg_message_id=message_id,
        to_email=email_to,
        status=str(status),
        subject=subject,
        template_code="temporary_account_block_pin_end",
    )


@task(queue='application_high')
def send_email_lock_pin(username, max_wait, max_retry, unlock_time, email_to):
    status, subject, headers = get_julo_email_client().email_lock_pin(
        username, max_wait, max_retry, unlock_time, email_to
    )

    message_id = headers["X-Message-Id"]
    EmailHistory.objects.create(
        sg_message_id=message_id,
        to_email=email_to,
        status=str(status),
        subject=subject,
        template_code="temporary_account_block_pin_start",
    )


@task(queue='application_high')
def notify_suspicious_login_to_user_via_sms(customer, device_model_name):
    get_julo_sms = get_julo_pin_sms_client()
    mobile_phone = None

    application = customer.application_set.last()
    if application:
        mobile_phone = application.mobile_phone_1
    if device_model_name:
        manufacturer = device_model_name.split('|', 1)[0]
        template_code = 'new_device_alert_sms'
    else:
        manufacturer = None
        template_code = 'new_device_alert_sms_old_customer'
    if not mobile_phone and customer.phone:
        mobile_phone = customer.phone
    if mobile_phone:
        txt_msg, response = get_julo_sms.sms_new_device_login_alert(
            template_code, mobile_phone, manufacturer
        )
        if response["status"] != "0":
            logger.exception(
                {
                    "send_status": response["status"],
                    "message_id": response.get("message-id"),
                    "sms_client_method_name": "notify_suspicious_login_to_user_via_sms",
                    "error_text": response.get("error-text"),
                }
            )
        sms = create_sms_history(
            response=response,
            customer=customer,
            message_content=txt_msg,
            to_mobile_phone=format_e164_indo_phone_number(mobile_phone),
            phone_number_type="mobile_phone_1",
            template_code=template_code,
        )
        if sms:
            logger.info(
                {
                    "status": "sms_created",
                    "sms_history_id": sms.id,
                    "message_id": sms.message_id,
                }
            )
    else:
        logger.warning(
            {
                'action': 'notify_suspicious_login_to_user_via_sms',
                'status': "failed",
                'message_id': "The customer has no mobile number saved",
            }
        )


@task(queue='application_high')
def notify_suspicious_login_to_user_via_email(customer, device_model_name):
    detokenized_customer = detokenize_pii_antifraud_data(PiiSource.CUSTOMER, [customer])[0]
    julo_email_client = get_julo_pin_email_client()
    status, headers, subject, msg = julo_email_client.email_new_device_login_alert(
        detokenized_customer, device_model_name
    )
    if device_model_name:
        template_code = 'new_device_alert_email'
    else:
        template_code = 'old_customer_new_device_alert_email'
    if status == 202:
        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers['X-Message-Id'],
            to_email=detokenized_customer.email,
            subject=subject,
            message_content=msg,
            template_code=template_code,
        )
    else:
        logger.warning(
            {
                'action': 'notify_suspicious_login_to_user_via_email',
                'status': status,
                'message_id': headers['X-Message-Id'],
            }
        )


@task(queue='application_normal')
def trigger_login_success_signal(customer_id: int, login_data: dict):
    """
    This task Will execute all signal handlers. Any uncaught exception from any handler will not
    stop other handler because the task use `send_robust`.
    Args:
        customer_id (int): The customer primary key
        login_data (dict): See process_login() for the dict keys.

    Returns:
        None
    """
    customer = Customer.objects.get(id=customer_id)
    logger.info(
        {
            'function': 'trigger_login_success_signal',
            'customer_id': customer.id,
        }
    )

    result = login_success.send_robust(customer.__class__, customer=customer, login_data=login_data)
    sentry_client = get_julo_sentry_client()
    for receiver, response in result:
        if not isinstance(response, Exception):
            continue

        try:
            raise response
        except Exception:  # NOQA
            logger.exception(
                {
                    'message': 'Exception on trigger_login_success_signal',
                    'receiver': receiver.__name__,
                    'customer_id': customer_id,
                    'login_data': login_data,
                }
            )
            sentry_client.captureException()
