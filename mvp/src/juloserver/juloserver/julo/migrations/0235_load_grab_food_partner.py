# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from ..partners import PartnerConstant
from ..product_lines import ProductLineCodes, ProductLineManager
from django.contrib.auth.hashers import make_password

def load_grab_partner(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    group = Group.objects.get(name="julo_partners")

    User = apps.get_model("auth", "User")
    hash_password = make_password('grabfoodtest')
    user = User.objects.create(username=PartnerConstant.GRAB_FOOD_PARTNER,
        email='cs@grab.com', password=hash_password)
    user.groups.add(group)

    Partner = apps.get_model("julo", "Partner")
    Partner.objects.create(
        user=user, name=PartnerConstant.GRAB_FOOD_PARTNER, email='cs@grab.com',
        phone='+628111111111')

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0234_load_grab_food_product'),
    ]

    operations = [
        migrations.RunPython(load_grab_partner, migrations.RunPython.noop)
    ]
