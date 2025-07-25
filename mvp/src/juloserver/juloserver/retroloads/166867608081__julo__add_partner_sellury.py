# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-11-17 09:08
from __future__ import unicode_literals

from django.db import migrations
from django.contrib.auth.models import Group, User

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.models import Partner
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def create_sellury_partner(apps, schema_editor):
    group = Group.objects.get(name="julo_partners")

    user = User.objects.create(
        username=PartnerNameConstant.SELLURY,
        email='sellury@sellury.co.id',
    )

    user.groups.add(group)

    Partner.objects.create(
        user=user,
        poc_email='sellury@sellury.co.id',
        poc_phone='+6281905271012',
        name=PartnerNameConstant.SELLURY,
        email='sellury@sellury.co.id',
        phone='',
        type='referrer',
        company_name='Sellury',
        company_address='Sampoerna Strategic Square North Tower, RT.3, RT.3/RW.4, Karet Semanggi, Setiabudi, South Jakarta City, Jakarta 12930',
        business_type='Fintech Aggregator',
        is_active=True
    )

    feature_settings = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION
    ).first()

    partners = feature_settings.parameters['partners']
    if not PartnerNameConstant.SELLURY in partners:
        partners.append(PartnerNameConstant.SELLURY)
        feature_settings.parameters['partners'] = partners
        feature_settings.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_sellury_partner, migrations.RunPython.noop)
    ]
