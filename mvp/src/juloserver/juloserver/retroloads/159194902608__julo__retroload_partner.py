# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-12-12 13:15
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.models import Partner
from juloserver.julo.models import PartnerOriginationData
from django.contrib.auth.models import Group, User


class Migration(migrations.Migration):


    def update_partner(apps, schema_editor):
        group = Group.objects.get(name="julo_partners")

        user = User.objects.create(username=PartnerConstant.AXIATA_PARTNER, email='cs@axiata.com')
        user.groups.add(group)

        partner_axiata = Partner.objects.create(
            user=user, name=PartnerConstant.AXIATA_PARTNER, email='cs@axiata.com',
            phone='+628111111111')

        datas = [0, 9, 12, 13, 14]
        partners = PartnerOriginationData.objects.filter(pk__in=datas)
        for partner in partners:
            partner.partner = partner_axiata
            partner.save()


    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_partner)
    ]
