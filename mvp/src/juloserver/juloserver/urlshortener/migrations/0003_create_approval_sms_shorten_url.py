# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from builtins import range

import shortuuid
from django.conf import settings
from django.db import IntegrityError, migrations
from django.utils import timezone


class UrlCollisionException(Exception):
    pass


def create_shorten_url(apps, schema_editor):
    ShortenedUrl = apps.get_model("urlshortener", "ShortenedUrl")

    retry_count = 5

    for attempt in range(0, retry_count):  # retry on short url collision
        short_uuid = shortuuid.uuid()
        short_url = short_uuid[:6]
        try:
            shortened_url = ShortenedUrl.objects.create(
                short_url=short_url, full_url=settings.LOAN_APPROVAL_SMS_URL
            )
            break
        except IntegrityError as e:
            continue
    else:
        raise UrlCollisionException("Too many short url collision on database.")


class Migration(migrations.Migration):
    dependencies = [
        ('urlshortener', '0002_auto_20190328_1426'),
    ]

    operations = [migrations.RunPython(create_shorten_url, migrations.RunPython.noop)]
