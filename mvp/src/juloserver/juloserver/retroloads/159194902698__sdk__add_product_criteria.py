# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-04-06 13:53
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import ProductLineCodes
from juloserver.julo.partners import PartnerConstant


from juloserver.julo.models import Partner



from juloserver.julo.models import ProductProfile



from juloserver.julo.models import LenderProductCriteria



def add_product_criteria(apps, schema_editor):
    
    
    

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
    ]

    operations = [
        migrations.RunPython(add_product_criteria, migrations.RunPython.noop),
    ]
