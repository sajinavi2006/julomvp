import logging

from celery.task import task
from django.conf import settings
from django.template.loader import render_to_string

from juloserver.julo.clients.sms import PartnershipSMSClient
from juloserver.julo.models import OtpRequest, Customer, EmailHistory, SmsHistory
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.partnership.clients import get_partnership_email_client

logger = logging.getLogger(__name__)


@task(queue='partner_leadgen_global_queue')
def send_email_otp_token(customer_id, otp_id, custom_email=None):
    otp_request = OtpRequest.objects.get(pk=otp_id)
    customer = Customer.objects.get_or_none(pk=customer_id)
    customer_full_name = '' if not customer else customer.fullname
    subject = "Ini Kode OTP Kamu"
    template = "email/leadgen_standard_otp_request_email.html"
    target_email = custom_email if custom_email else customer.email
    cs_email = "cs@julo.co.id"

    context = {
        'banner_url': settings.EMAIL_STATIC_FILE_PATH
        + 'banner-leadgen-standard-otp-request-email.png',
        'full_name': '' if not customer_full_name else customer_full_name,
        'otp_token': otp_request.otp_token,
        'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
        'ojk_icon': settings.EMAIL_STATIC_FILE_PATH + 'ojk.png',
        'afpi_icon': settings.EMAIL_STATIC_FILE_PATH + 'afpi.png',
        'afj_icon': settings.EMAIL_STATIC_FILE_PATH + 'afj.png',
        'cs_email': cs_email,
        'cs_phone': "021-5091 9034 | 021-5091 9035",
        'cs_image': settings.EMAIL_STATIC_FILE_PATH + 'customer_service_icon.png',
        'mail_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-mail.png',
        'phone_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-phone.png',
    }
    msg = render_to_string(template, context)
    email_to = target_email

    # Process send email
    status, body, headers = get_partnership_email_client().send_email(
        subject,
        msg,
        email_to,
        email_from=cs_email,
        email_cc=None,
        name_from="JULO",
        reply_to=cs_email,
    )

    email_history = EmailHistory.objects.create(
        status=status,
        customer=customer,
        sg_message_id=headers['X-Message-Id'],
        to_email=target_email,
        subject=subject,
        message_content=msg,
        template_code="leadgen_standard_otp_request",
    )

    # Save email history to otp request
    otp_request.update_safely(email_history=email_history)

    logger.info(
        "email_otp_history_created|customer_id={}, otp_request_id={}, "
        "email_history_id={}".format(customer_id, otp_id, email_history.id)
    )


@task(queue='partner_leadgen_global_queue')
def leadgen_send_sms_otp_token(phone_number, text, customer_id, otp_id, template_code=None):
    otp = OtpRequest.objects.get_or_none(pk=otp_id)
    if not otp:
        logger.error(
            {
                'action': 'leadgen_send_sms_otp_token',
                'message': 'otp not found',
                'mobile_number': phone_number,
                'customer_id': customer_id,
            }
        )

    customer = Customer.objects.filter(pk=customer_id).last() if customer_id else None
    mobile_number = format_e164_indo_phone_number(phone_number)
    sms_client = PartnershipSMSClient(
        settings.PARTNERSHIP_SMS_API_KEY,
        settings.PARTNERSHIP_SMS_API_SECRET,
        settings.PARTNERSHIP_SMS_API_BASE_URL,
    )
    message_id = sms_client.send_sms(mobile_number, text, template_code, 'leadgen_phone_number_otp')
    sms_history = SmsHistory.objects.get_or_none(message_id=message_id)

    if not sms_history:
        logger.error(
            {
                'action': 'leadgen_send_sms_otp_token',
                'message': 'failed send sms otp',
                'mobile_number': mobile_number,
                'customer_id': customer_id,
            }
        )
    else:
        # Update SMS history
        sms_history.update_safely(
            customer=customer, is_otp=True, phone_number_type="mobile_phone_1"
        )

        # Save sms history to otp request
        otp.update_safely(sms_history=sms_history)

        logger.info(
            {
                'action': 'leadgen_send_sms_otp_token',
                'message': 'success send sms otp',
                'mobile_number': mobile_number,
                'customer_id': customer_id,
                'sms_history_id': sms_history.id,
                'message_id': sms_history.message_id,
            }
        )


@task(queue='partner_leadgen_global_queue')
def send_email_otp_token_register(email: str, otp_id: int):
    otp_request = OtpRequest.objects.get(pk=otp_id)
    subject = "Ini Kode OTP Kamu"
    template = "email/leadgen_standard_otp_request_email.html"
    target_email = email
    cs_email = "cs@julo.co.id"

    context = {
        'banner_url': settings.EMAIL_STATIC_FILE_PATH
        + 'banner-leadgen-standard-otp-request-email.png',
        'full_name': '',
        'otp_token': otp_request.otp_token,
        'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
        'ojk_icon': settings.EMAIL_STATIC_FILE_PATH + 'ojk.png',
        'afpi_icon': settings.EMAIL_STATIC_FILE_PATH + 'afpi.png',
        'afj_icon': settings.EMAIL_STATIC_FILE_PATH + 'afj.png',
        'cs_email': cs_email,
        'cs_phone': "021-5091 9034 | 021-5091 9035",
        'cs_image': settings.EMAIL_STATIC_FILE_PATH + 'customer_service_icon.png',
        'mail_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-mail.png',
        'phone_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-phone.png',
    }
    msg = render_to_string(template, context)
    email_to = target_email

    # Process send email
    status, body, headers = get_partnership_email_client().send_email(
        subject,
        msg,
        email_to,
        email_from=cs_email,
        email_cc=None,
        name_from="JULO",
        reply_to=cs_email,
    )

    email_history = EmailHistory.objects.create(
        status=status,
        sg_message_id=headers['X-Message-Id'],
        to_email=target_email,
        subject=subject,
        message_content=msg,
        template_code="leadgen_standard_otp_request_register",
    )

    # Save email history to otp request
    otp_request.update_safely(email_history=email_history)

    logger.info(
        "email_otp_history_created|email={}, otp_request_id={}, "
        "email_history_id={}".format(target_email, otp_id, email_history.id)
    )
