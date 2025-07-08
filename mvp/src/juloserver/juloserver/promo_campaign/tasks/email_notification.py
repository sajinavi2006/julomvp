from builtins import str
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from celery import task

from juloserver.julo.models import (
    Payment,
)
from juloserver.julo.clients import get_julo_email_client
from juloserver.urlshortener.models import ShortenedUrl
from juloserver.urlshortener.services import shorten_url
from juloserver.julo.services2 import encrypt

from ..constants import (
    RamadanCampaign,
    TemplateLocation)
from ..promo import RamadanPromo
from ..utils import (
    get_email_template_from_dpd_and_product_code,
    get_email_template_for_initiative3)
from juloserver.promo.models import PromoHistory


@task(name="send_ramadan_email")
def send_ramadan_email(payment_id, initiative, reminder_type):
    payment = Payment.objects.get_or_none(pk=payment_id)

    if payment is None:
        return

    application = payment.loan.application
    loan = payment.loan
    additional_info = {}

    if initiative == RamadanCampaign.INITIATIVE2:
        template, template_code, subject = get_email_template_from_dpd_and_product_code(
            reminder_type, application.product_line_id
        )
        promo_type = RamadanCampaign.PROMO_INITIATIVE2_TYPE
        full_url = RamadanCampaign.TERMS_INITIATIVE2_URL
        short_url_code = RamadanCampaign.TERMS_INITIATIVE2_CODE
    else:
        template, template_code, subject = get_email_template_for_initiative3(
            reminder_type, application.product_line_id
        )
        promo_type = RamadanCampaign.PROMO_INITIATIVE3_TYPE
        full_url = RamadanCampaign.TERMS_INITIATIVE3_URL
        short_url_code = RamadanCampaign.TERMS_INITIATIVE3_CODE
        initiative3_start_date = (datetime.strptime(
            RamadanCampaign.EMAIL1_INITIATIVE3_DATE, '%Y-%m-%d')).date()
        additional_info = {
            'payments': loan.payment_set.exclude(
                due_date__gt=initiative3_start_date
            ).order_by('payment_number')
        }

    encrypttext = encrypt()
    encoded_payment_id = encrypttext.encode_string(str(payment.id))
    url = settings.PAYMENT_DETAILS + str(encoded_payment_id)
    shortened_url = ShortenedUrl.objects.filter(full_url=url).last()

    if not shortened_url:
        payment_short_url = shorten_url(url)
    else:
        payment_short_url = settings.URL_SHORTENER_BASE + shortened_url.short_url

    customer = payment.loan.customer
    promo_history, _ = PromoHistory.objects.get_or_create(
        customer=customer,
        loan=loan,
        promo_type=promo_type,
        payment=payment)

    terms_short_url, _ = ShortenedUrl.objects.get_or_create(
        short_url=short_url_code,
        full_url=full_url)

    terms_shortened_url = settings.URL_SHORTENER_BASE + terms_short_url.short_url
    cust_info = dict(
        customer=customer,
        application=application
    )
    payment_info = dict(
        due_date=payment.due_date - timedelta(days=3),
        payment_link=payment_short_url,
        terms_link=terms_shortened_url
    )

    payment_info.update(additional_info)

    template_info = dict(
        template=TemplateLocation.EMAIL + template,
        template_code=template_code,
        subject=subject
    )

    email_client = get_julo_email_client()
    email_client.send_ramadan_email_promo(cust_info, payment_info, template_info)


@task(name="send_ramadan_email_campaign")
def send_ramadan_email_campaign():
    today = timezone.localtime(timezone.now()).date()
    promo_start_date = (datetime.strptime(
        RamadanCampaign.EMAIL1_START_DATE, '%Y-%m-%d')).date()
    promo_end_date = (datetime.strptime(
        RamadanCampaign.EMAIL3_INITIATIVE3_DATE, '%Y-%m-%d')).date()

    if promo_start_date <= today <= promo_end_date:
        RamadanPromo.send_email()
