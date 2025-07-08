from builtins import range

import shortuuid
from django.conf import settings
from django.db import IntegrityError

from .models import ShortenedUrl
from juloserver.julo.services2 import encrypt


class UrlCollisionException(Exception):
    pass


def shorten_url(full_url, get_object=False):
    retry_count = 5

    for attempt in range(0, retry_count):
        try:
            shortened_url = ShortenedUrl.objects.create(
                short_url=generate_string(), full_url=full_url
            )
            break
        except IntegrityError:
            continue
    else:
        raise UrlCollisionException("Too many short url collision on database.")

    created_url = settings.URL_SHORTENER_BASE + shortened_url.short_url
    if get_object:
        return created_url, shortened_url
    return created_url


def generate_string():
    string_base = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    short_url = shortuuid.ShortUUID(string_base).random(length=11)

    return short_url


def get_payment_detail_shortened_url(payment):
    # will temporarily return earlier
    return '-'

    if payment.due_amount <= 0:
        return '-'

    encrypttext = encrypt()
    encoded_payment_id = encrypttext.encode_string(str(payment.id))
    url = settings.PAYMENT_DETAILS + str(encoded_payment_id)

    shortened_url = ShortenedUrl.objects.filter(full_url=url).last()
    return (
        settings.URL_SHORTENER_BASE + shortened_url.short_url if shortened_url else shorten_url(url)
    )
