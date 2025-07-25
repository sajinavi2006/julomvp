# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-04-06 13:53
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import ProductLineCodes
from juloserver.julo.partners import PartnerConstant


def add_product_criteria(apps, schema_editor):
    LenderProductCriteria = apps.get_model("julo", "LenderProductCriteria")
    ProductProfile = apps.get_model("julo", "ProductProfile")
    Partner = apps.get_model("julo", "Partner")

    icare_profile = ProductProfile.objects.filter(code__in=ProductLineCodes.icare()).values_list('id', flat=True)
    if icare_profile:
        jtp = Partner.objects.filter(name=PartnerConstant.JTP_PARTNER).first()
        if jtp:
            lender_product_criteria = LenderProductCriteria.objects.filter(partner=jtp).first()
            if lender_product_criteria:
                lender_product_criteria.product_profile_list += icare_profile
                lender_product_criteria.save()


class Migration(migrations.Migration):

    dependencies = [
        ('sdk', '0018_icare_new_statuspath'),
    ]

    operations = [
        migrations.RunPython(add_product_criteria, migrations.RunPython.noop),
    ]
