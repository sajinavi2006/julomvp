from builtins import str
from datetime import datetime
from django.utils import timezone
from django.conf import settings
from celery import task

from juloserver.julo.models import (
    Payment)
from juloserver.urlshortener.models import ShortenedUrl
from juloserver.julo.clients import (
    get_julo_email_client,
    get_julo_sms_client)
from juloserver.urlshortener.services import shorten_url
from juloserver.julo.services2 import encrypt
from ..constants import (
    RamadanCampaign,
    TemplateLocation)
from ..promo import RamadanPromo
from ..utils import (
    get_sms_template_from_dpd_and_product_code,
    get_sms_template_for_initiative3)


@task(name="send_ramadan_sms")
def send_ramadan_sms(payment_id, initiative, reminder_type):
    payment = Payment.objects.get_or_none(pk=payment_id)

    if payment is None:
        return

    application = payment.loan.application

    if initiative == RamadanCampaign.INITIATIVE2:
        template, template_code = get_sms_template_from_dpd_and_product_code(
            reminder_type, application.product_line_id
        )
    else:
        template, template_code = get_sms_template_for_initiative3(
            reminder_type, application.product_line_id
        )

    customer = payment.loan.customer
    encrypttext = encrypt()
    encoded_payment_id = encrypttext.encode_string(str(payment.id))
    url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
    shortened_url = ShortenedUrl.objects.filter(full_url=url).last()

    if not shortened_url:
        payment_short_url = shorten_url(url)
    else:
        payment_short_url = settings.URL_SHORTENER_BASE + shortened_url.short_url

    cust_info = dict(
        customer=customer,
        application=application,
        payment_link=payment_short_url
    )
    template_info = dict(
        template=TemplateLocation.SMS + template,
        template_code=template_code
    )
    sms_client = get_julo_sms_client()
    sms_client.send_ramadan_sms_promo(cust_info, template_info)

@task(name="send_ramadan_sms_campaign")
def send_ramadan_sms_campaign():
    today = timezone.localtime(timezone.now()).date()
    promo_start_date = (datetime.strptime(
        RamadanCampaign.SMS1_START_DATE, '%Y-%m-%d')).date()
    promo_end_date = (datetime.strptime(
        RamadanCampaign.SMS3_INITIATIVE3_DATE, '%Y-%m-%d')).date()

    if promo_start_date <= today <= promo_end_date:
        RamadanPromo.send_sms()
