import logging

from celery import task
from django.template.loader import render_to_string

from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import Customer, EmailHistory, FeatureSetting, OtpRequest
from juloserver.julocore.python2.utils import py2round
from juloserver.otp.constants import (
    EmailOTP,
    FeatureSettingName,
    SessionTokenAction,
)

from juloserver.otp.clients import get_julo_otpless_client
from juloserver.otp.exceptions import OTPLessException
from juloserver.otp.utils import format_otpless_phone_number

logger = logging.getLogger(__name__)


@task(queue='application_high')
def send_email_otp_token(customer_id, otp_id, custom_email=None, is_email_otp_prefill=False):
    otp_request = OtpRequest.objects.get(pk=otp_id)
    customer = Customer.objects.get_or_none(pk=customer_id)
    customer_full_name = '' if not customer else customer.fullname
    subject = EmailOTP.SUBJECT
    template = EmailOTP.TEMPLATE
    email_from = EmailOTP.EMAIL_FROM
    target_email = custom_email if custom_email else customer.email

    email_otp_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.EMAIL_OTP, is_active=True
    )
    if not email_otp_setting:
        logger.warning(
            'send email otp token feature is not active|'
            'customer_id={}, otp_id={}'.format(customer_id, otp_id)
        )
        return
    life_time_seconds = email_otp_setting.parameters.get('wait_time_seconds')
    life_time_minutes = int(py2round(life_time_seconds / 60))

    if otp_request.action_type == SessionTokenAction.VERIFY_SUSPICIOUS_LOGIN:
        header_text = EmailOTP.SUSPICIOUS_LOGIN_HEADER.format(life_time_minutes=life_time_minutes)
        template_code = EmailOTP.FRAUD_OTP_TEMPLATE_CODE
    elif otp_request.action_type in {
        SessionTokenAction.REGISTER,
        SessionTokenAction.PAYLATER_REGISTER,
    }:
        header_text = EmailOTP.VERIFY_REGISTER_HEADER.format(life_time_minutes=life_time_minutes)
        template_code = EmailOTP.REGISTER
    elif otp_request.action_type == SessionTokenAction.PAYLATER_LINKING:
        subject = EmailOTP.PAYLATER_LINKING_SUBJECT
        template = EmailOTP.PAYLATER_LINKING_TEMPLATE
        header_text = EmailOTP.PAYLATER_LINKING_EMAIL_HEADER.format(
            life_time_minutes=life_time_minutes
        )
        template_code = EmailOTP.PAYLATER_LINKING_TEMPLATE_CODE
    elif otp_request.action_type in SessionTokenAction.OTP_SWITCH_ACTIONS:
        header_text = EmailOTP.OTP_SWITCH_HEADER
        customer_full_name = '' if not customer_full_name else customer_full_name
        template_code = EmailOTP.OTP_SWITCH
        subject = EmailOTP.OTP_SWITCH_SUBJECT
    else:
        header_text = EmailOTP.NEW_EMAIL_OTP_HEADER_TEXT
        template_code = EmailOTP.CHANGE_OTP_TEMPLATE_CODE

    context = {
        'banner_url': EmailOTP.BANNER_URL,
        'footer_url': EmailOTP.FOOTER_URL,
        'full_name': customer_full_name,
        'otp_token': otp_request.otp_token,
        'contact_email': email_from,
        'contact_phone_displays': EmailOTP.CONTACT_PHONE_DISPLAYS,
        'header_text': header_text,
        'deeplink': f'https://r.julo.co.id/1mYI/v9f14vfr?code={otp_request.otp_token}',
        'footer_text': EmailOTP.NEW_EMAIL_OTP_FOOTER_TEXT,
        'is_email_otp_prefill': is_email_otp_prefill,
    }

    if is_email_otp_prefill:
        context['header_text'] = EmailOTP.PREFILL_EMAIL_OTP_HEADER_TEXT
        context['footer_text'] = EmailOTP.PREFILL_EMAIL_OTP_FOOTER_TEXT

    template = EmailOTP.DEEPLINK_TEMPLATE
    template_code = EmailOTP.DEEPLINK_TEMPLATE_CODE
    msg = render_to_string(template, context)
    email_to = target_email
    name_from = EmailOTP.NAME_FROM
    reply_to = EmailOTP.REPLY_TO
    email_client = get_julo_email_client()

    sendgrid_bounce_list_takeout_setting = FeatureSetting.objects.filter(
        feature_name=FeatureSettingName.SENDGRID_BOUNCE_TAKEOUT, is_active=True
    ).last()
    if sendgrid_bounce_list_takeout_setting:
        email_client.delete_email_from_bounce(email_to)

    status, body, headers = email_client.send_email(
        subject,
        msg,
        email_to,
        email_from=email_from,
        email_cc=None,
        name_from=name_from,
        reply_to=reply_to,
    )

    email_history = EmailHistory.objects.create(
        status=status,
        customer=customer,
        sg_message_id=headers['X-Message-Id'],
        to_email=target_email,
        subject=subject,
        message_content=msg,
        template_code=template_code,
    )

    # Save email history to otp request
    otp_request.update_safely(email_history=email_history)

    logger.info(
        "email_otp_history_created|customer_id={}, otp_request_id={}, "
        "email_history_id={}".format(customer_id, otp_id, email_history.id)
    )


@task(queue='application_high')
def send_otpless_otp(otp_request, phone_number, redirect_uri, device_id, otpless_expiry_time):
    otpless_client = get_julo_otpless_client()
    try:
        response = (
            otpless_client.send_otp(phone_number, redirect_uri, device_id, otpless_expiry_time)
        ).json()
        if not response.get('requestIds', None):
            otp_request.update_safely(otpless_reference_id=response["message"])
            raise OTPLessException(
                {
                    "send_status": "failed requestIds",
                    "phone_number": phone_number,
                    "device_id": device_id,
                    "sms_client_method_name": "otpless",
                    "error_text": response.get('message', 'Empty error message'),
                }
            )
        if not response:
            otp_request.update_safely(otpless_reference_id=response["message"])
            raise OTPLessException(
                {
                    "send_status": "failed empty response",
                    "phone_number": phone_number,
                    "device_id": device_id,
                    "sms_client_method_name": "otpless",
                    "error_text": response.get('message', 'Empty error message'),
                }
            )
        otpless_data = {
            'otpless_reference_id': response["requestIds"][0]["value"],
            'destination_uri': response["requestIds"][0]["destinationUri"],
        }
        return otpless_data
    except Exception as e:
        logger.exception(
            {
                'action': 'send_otpless_otp',
                'messaage': 'exception rasised while request to send otp to otpless',
                'error': str(e),
            }
        )

        raise Exception(e)


@task(queue='application_high')
def validate_otpless_otp(otpless_code, phone_number):
    phone_number = format_otpless_phone_number(phone_number) if phone_number else phone_number
    otpless_client = get_julo_otpless_client()
    try:
        validate_response = (otpless_client.validate_otp(otpless_code)).json()
        if not validate_response:
            raise OTPLessException(
                {
                    "send_status": 'failed',
                    "message_id": validate_response.get('message', ''),
                    "otp_client_method_name": 'otpless',
                    "error_text": validate_response.get('message', ''),
                }
            )

        user_info = (
            otpless_client.verify_user_info(validate_response.get('access_token', ''))
        ).json()
        if not user_info:
            raise OTPLessException(
                {
                    "send_status": 'failed',
                    "message_id": user_info.get('message', ''),
                    "otp_client_method_name": 'otpless',
                    "error_text": user_info.get('message', ''),
                }
            )

        if format_otpless_phone_number(user_info.get('phone_number', '')) == phone_number:
            return True
    except Exception as e:
        logger.exception(
            {
                'action': 'validate_otpless_otp',
                'messaage': 'exception rasised while validating otp to otpless',
                'error': str(e),
            }
        )

        raise Exception(e)
    return False
