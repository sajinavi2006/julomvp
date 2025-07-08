# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from builtins import range
from django.db import migrations
from django.utils import timezone
import shortuuid
from django.db import IntegrityError
from django.conf import settings

class UrlCollisionException(Exception):
    pass

from juloserver.urlshortener.models import ShortenedUrl


def create_shorten_url(apps, schema_editor):
    

    retry_count = 5

    for attempt in range(0, retry_count):  # retry on short url collision
        short_uuid = shortuuid.uuid()
        short_url = short_uuid[:6]
        try:
            shortened_url = ShortenedUrl.objects.create(
                short_url=short_url,
                full_url=settings.LOAN_APPROVAL_SMS_URL
            )
            break
        except IntegrityError as e:
            continue
    else:
        raise UrlCollisionException("Too many short url collision on database.")


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_shorten_url, migrations.RunPython.noop)
    ]