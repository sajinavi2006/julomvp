from datetime import datetime
from django.utils import timezone
from django.conf import settings
from celery import task

from juloserver.julo.models import (
    Payment)
from juloserver.urlshortener.models import ShortenedUrl
from juloserver.julo.clients import (
    get_julo_pn_client)
from juloserver.urlshortener.services import shorten_url
from juloserver.julo.services2 import encrypt
from ..constants import RamadanCampaign
from ..promo import RamadanPromo
from ..utils import (
    get_pn_template_and_content_from_dpd,
    get_pn_template_for_initiative3)


@task(name="send_ramadan_pn")
def send_ramadan_pn(gcm_id, initiative, reminder_type, image_url):
    if initiative == RamadanCampaign.INITIATIVE2:
        template, title, message = get_pn_template_and_content_from_dpd(reminder_type)
    else:
        template, title, message = get_pn_template_for_initiative3(reminder_type)

    pn_dict = {
        'template': template,
        'title': title,
        'message': message,
        'image_url': image_url
    }
    pn_client = get_julo_pn_client()
    pn_client.send_ramadan_pn(gcm_id, pn_dict)


@task(name="send_ramadan_pn_campaign")
def send_ramadan_pn_campaign():
    today = timezone.localtime(timezone.now()).date()
    promo_start_date = (datetime.strptime(
        RamadanCampaign.PN1_START_DATE, '%Y-%m-%d')).date()
    promo_end_date = (datetime.strptime(
        RamadanCampaign.PN5_INITIATIVE3_DATE, '%Y-%m-%d')).date()

    if promo_start_date <= today <= promo_end_date:
        RamadanPromo.send_pn()
