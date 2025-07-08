# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.partners import PartnerConstant
from django.contrib.auth.hashers import make_password
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.julo.models import Partner


from juloserver.julo.models import ApplicationOriginal


from juloserver.julo.models import Partner


from juloserver.julo.models import Application


from juloserver.julo.models import Partner


from django.contrib.auth.models import User


from django.contrib.auth.models import Group


def load_bri_partner(apps, schema_editor):
    
    group = Group.objects.get(name="julo_partners")

    
    hash_password = make_password('britest')
    user = User.objects.create(username=PartnerConstant.BRI_PARTNER,
        email='cs@bri.com', password=hash_password)
    user.groups.add(group)

    
    Partner.objects.create(
        user=user, name=PartnerConstant.BRI_PARTNER, email='cs@bri.com',
        phone='+628111111111')

from juloserver.julo.models import Partner


from juloserver.julo.models import ApplicationOriginal


from juloserver.julo.models import Partner


from juloserver.julo.models import Application


from juloserver.julo.models import Partner


from django.contrib.auth.models import User


from django.contrib.auth.models import Group


def retroload_bri_partner_to_application(apps, schema_editor):
    
    
    partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
    applications = Application.objects.filter(product_line__product_line_code__in = ProductLineCodes.bri())
    for application in applications:
        application.partner = partner
        application.save()
        
def retroload_bri_partner_to_applicationoriginal(apps, schema_editor):
    
    
    partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
    applications = ApplicationOriginal.objects.filter(product_line__product_line_code__in = ProductLineCodes.bri())
    for application in applications:
        application.partner = partner
        application.save()

    
class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_bri_partner, migrations.RunPython.noop),
        migrations.RunPython(retroload_bri_partner_to_application, migrations.RunPython.noop),
        migrations.RunPython(retroload_bri_partner_to_applicationoriginal, migrations.RunPython.noop)
    ]
