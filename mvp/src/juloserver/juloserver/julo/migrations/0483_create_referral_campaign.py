# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-03-27 10:45
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models
from django.db import transaction
import datetime


def create_referral_campaign(apps, schema_editor):
    ReferralCampaign = apps.get_model("julo", "ReferralCampaign")
    with transaction.atomic():
        ReferralCampaign.objects.create(
            referral_code = 'CICILBUNGA08',
            start_date = datetime.datetime.strptime('2019-08-27', '%Y-%m-%d').date(),
            end_date = datetime.datetime.strptime('2019-09-18', '%Y-%m-%d').date()
        )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0482_referral_campaign_table'),
    ]

    operations = [
        migrations.RunPython(create_referral_campaign, migrations.RunPython.noop),
    ]
