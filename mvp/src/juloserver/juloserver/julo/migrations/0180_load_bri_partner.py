# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..partners import PartnerConstant
from django.contrib.auth.hashers import make_password
from ..product_lines import ProductLineCodes

def load_bri_partner(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    group = Group.objects.get(name="julo_partners")

    User = apps.get_model("auth", "User")
    hash_password = make_password('britest')
    user = User.objects.create(username=PartnerConstant.BRI_PARTNER,
        email='cs@bri.com', password=hash_password)
    user.groups.add(group)

    Partner = apps.get_model("julo", "Partner")
    Partner.objects.create(
        user=user, name=PartnerConstant.BRI_PARTNER, email='cs@bri.com',
        phone='+628111111111')

def retroload_bri_partner_to_application(apps, schema_editor):
    Application = apps.get_model("julo", "Application")
    Partner = apps.get_model("julo", "Partner")
    partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
    applications = Application.objects.filter(product_line__product_line_code__in = ProductLineCodes.bri())
    for application in applications:
        application.partner = partner
        application.save()
        
def retroload_bri_partner_to_applicationoriginal(apps, schema_editor):
    ApplicationOriginal = apps.get_model("julo", "ApplicationOriginal")
    Partner = apps.get_model("julo", "Partner")
    partner = Partner.objects.get(name=PartnerConstant.BRI_PARTNER)
    applications = ApplicationOriginal.objects.filter(product_line__product_line_code__in = ProductLineCodes.bri())
    for application in applications:
        application.partner = partner
        application.save()

    
class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0179_auto_20180116_1049'),
    ]

    operations = [
        migrations.RunPython(load_bri_partner, migrations.RunPython.noop),
        migrations.RunPython(retroload_bri_partner_to_application, migrations.RunPython.noop),
        migrations.RunPython(retroload_bri_partner_to_applicationoriginal, migrations.RunPython.noop)
    ]
