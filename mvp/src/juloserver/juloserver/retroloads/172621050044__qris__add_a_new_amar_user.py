# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-09-13 06:55
from __future__ import unicode_literals

from django.db import migrations
import string
import random
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Partner


def create_amar_partner(apps, schema_editor):
    # no need to know password. due to we only communicate with token
    random_password = ''.join(random.choices(string.ascii_letters, k=20))
    hash_password = make_password(random_password)
    user = User.objects.create(
        username=PartnerNameConstant.AMAR,
        email='tanya@amarbank.co.id',
        password=hash_password,
    )

    Partner.objects.create(
        user=user,
        name=PartnerNameConstant.AMAR,
        poc_email='tanya@amarbank.co.id',
        poc_phone='02130210700',
        is_active=True,
    )


class Migration(migrations.Migration):
    dependencies = []

    operations = [migrations.RunPython(create_amar_partner, migrations.RunPython.noop)]
