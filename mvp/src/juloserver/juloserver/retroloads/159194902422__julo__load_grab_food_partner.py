# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes, ProductLineManager
from django.contrib.auth.hashers import make_password

from juloserver.julo.models import Partner


from django.contrib.auth.models import User


from django.contrib.auth.models import Group


def load_grab_partner(apps, schema_editor):
    
    group = Group.objects.get(name="julo_partners")

    
    hash_password = make_password('grabfoodtest')
    user = User.objects.create(username=PartnerConstant.GRAB_FOOD_PARTNER,
        email='cs@grab.com', password=hash_password)
    user.groups.add(group)

    
    Partner.objects.create(
        user=user, name=PartnerConstant.GRAB_FOOD_PARTNER, email='cs@grab.com',
        phone='+628111111111')

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_grab_partner, migrations.RunPython.noop)
    ]
