from juloserver.julo.clients import get_julo_email_client, get_julo_sentry_client
from juloserver.julo.models import EmailHistory
from juloserver.julo.exceptions import EmailNotSent
import base64
from juloserver.julo.models import Customer
from django.conf import settings
from django.utils import timezone
from django.template.loader import get_template
from juloserver.pin.utils import get_first_name
from juloserver.customer_module.utils.masking import (
    mask_email_showing_length,
    mask_value_showing_length_and_last_four_value,
)
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_timestamp_format_for_email,
)

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def send_email_with_html(
    subject: str,
    html_content: str,
    recipient_email: str,
    sender_email: str,
    template_code: str,
    attachments: list = None,
    fullname: str = None,
):
    status = None
    message_id = None
    try:
        status, _, headers = get_julo_email_client().send_email(
            subject=subject,
            content=html_content,
            email_to=recipient_email,
            email_from=sender_email,
            attachments=attachments,
            name_from=fullname,
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
            logger.exception('send_email, data={} | err={}'.format(template_code, e))

    EmailHistory.objects.create(
        to_email=recipient_email,
        subject=subject,
        sg_message_id=message_id,
        template_code=template_code,
        status=str(status),
        error_message=error_message,
    )


def generate_image_attachment(
    image,
    filename: str,
    ext: str,
):
    content = base64.b64encode(image.read()).decode('utf-8')
    mime_type = get_mime_type_by_extension(ext)

    return {
        "content": content,
        "filename": "{}.{}".format(filename, ext),
        "type": mime_type,
    }


# TODO: move this to util funcs
def get_mime_type_by_extension(
    extension: str,
):
    switcher = {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }

    return switcher.get(extension, "nothing")


def send_reset_phone_number_email(
    customer: Customer,
    reset_key: str,
) -> None:
    subject_prefix = ""
    if settings.ENVIRONMENT != "prod":
        subject_prefix = "[Squad8QAtest] "

    date_now = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    subject = "JULO: Reset Nomor Handphone (%s) - %s" % (customer.email, date_now)
    subject = subject_prefix + subject

    template = get_template("reset_phone/change_email_confirm.html")
    first_name = "pelanggan setia JULO"
    if customer:
        first_name = get_first_name(customer)
    reset_phone_number_link = settings.RESET_PHONE_NUMBER_LINK_HOST + reset_key + "/"
    variable = {"link": reset_phone_number_link, "first_name": first_name}
    html_content = template.render(variable)

    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=customer.email,
        sender_email="cs@julo.co.id",
        template_code="email_reset_phone_number",
    )

    return


def send_customer_field_change_phone_number_notification(
    customer: Customer,
    previous_value: str,
    new_value: str,
    recipient_email: str,
    timestamp: datetime = None,
) -> None:
    subject = "Perubahan Nomor HP Berhasil, Ya!"

    template = get_template("data_change/agent_phone_change_notification.html")

    title = "Bapak/Ibu"
    if customer.bapak_ibu:
        title = customer.bapak_ibu

    first_name = get_first_name(customer)

    previous_value_masked = mask_value_showing_length_and_last_four_value(str(previous_value))
    new_value_masked = mask_value_showing_length_and_last_four_value(str(new_value))
    timestamp = get_timestamp_format_for_email(timestamp)

    variable = {
        "title": title,
        "name": first_name,
        "previous_value": previous_value_masked,
        "new_value": new_value_masked,
        "timestamp": timestamp,
    }
    html_content = template.render(variable)

    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=recipient_email,
        sender_email="cs@julo.co.id",
        template_code="agent_phone_change_notification",
    )

    return


def send_customer_field_change_email_notification(
    customer: Customer,
    previous_value: str,
    new_value: str,
    recipient_email: str,
    timestamp: datetime = None,
) -> None:
    subject = "Perubahan Email Berhasil, Ya!"

    template = get_template("data_change/agent_email_change_notification.html")

    title = "Bapak/Ibu"
    if customer.bapak_ibu:
        title = customer.bapak_ibu

    first_name = get_first_name(customer)

    previous_value_masked = mask_email_showing_length(str(previous_value))
    new_value_masked = mask_email_showing_length(str(new_value))
    timestamp = get_timestamp_format_for_email(timestamp)

    variable = {
        "title": title,
        "name": first_name,
        "previous_value": previous_value_masked,
        "new_value": new_value_masked,
        "timestamp": timestamp,
    }
    html_content = template.render(variable)

    # send to old email
    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=recipient_email,
        sender_email="cs@julo.co.id",
        template_code="agent_email_change_notification",
    )

    # send to new email
    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=customer.email,
        sender_email="cs@julo.co.id",
        template_code="agent_email_change_notification",
    )

    return


def send_customer_field_change_bank_account_number_notification(
    customer: Customer,
    previous_value: int,
    new_value: int,
    recipient_email: str,
    timestamp: datetime = None,
) -> None:
    subject = "Perubahan Nomor Rekening Bank Berhasil, Ya!"

    template = get_template("data_change/agent_bank_account_no_change_notification.html")

    title = "Bapak/Ibu"
    if customer.bapak_ibu:
        title = customer.bapak_ibu

    first_name = get_first_name(customer)

    previous_value_masked = mask_value_showing_length_and_last_four_value(str(previous_value))
    new_value_masked = mask_value_showing_length_and_last_four_value(str(new_value))
    timestamp = get_timestamp_format_for_email(timestamp)

    variable = {
        "title": title,
        "name": first_name,
        "previous_value": previous_value_masked,
        "new_value": new_value_masked,
        "timestamp": timestamp,
    }

    html_content = template.render(variable)

    send_email_with_html(
        subject=subject,
        html_content=html_content,
        recipient_email=recipient_email,
        sender_email="cs@julo.co.id",
        template_code="agent_bank_account_no_change_notification",
    )

    return
