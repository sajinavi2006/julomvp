# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-04-04 07:33
from __future__ import unicode_literals

from django.db import migrations
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from juloserver.api_token.models import ExpiryToken as Token
from juloserver.lendeast.constants import LendEastConst
from juloserver.julo.models import Partner


def add_lendeast_partner(apps, schema_editor):
    password = make_password('lendeast!@()')
    user = User.objects.create(
        username='lendeast',
        password=password,
        email='lendeast@example.com'
    )
    token, _ = Token.objects.get_or_create(user=user)
    Partner.objects.create(
        user_id=user.id,
        name=LendEastConst.PARTNER_NAME,
        email=user.email,
        type='lender',
        token=token.key
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_lendeast_partner, migrations.RunPython.noop),
    ]
