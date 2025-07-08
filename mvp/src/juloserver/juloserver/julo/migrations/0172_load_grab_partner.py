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
    hash_password = make_password('grabtest')
    user = User.objects.create(username=PartnerConstant.GRAB_PARTNER,
        email='cs@grab.com', password=hash_password)
    user.groups.add(group)

    Partner = apps.get_model("julo", "Partner")
    Partner.objects.create(
        user=user, name=PartnerConstant.GRAB_PARTNER, email='cs@grab.com',
        phone='+628111111111')

def load_grab_product_lines(apps, schema_editor):
    for code in ProductLineCodes.grab():
        ProductLine = apps.get_model("julo", "ProductLine")
        pl = ProductLineManager.get_or_none(code)
        if pl is None:
            continue
        if ProductLine.objects.filter(product_line_code=code).first():
            continue
        ProductLine.objects.create(
            product_line_code=pl.product_line_code,
            product_line_type=pl.product_line_type,
            min_amount=pl.min_amount,
            max_amount=pl.max_amount,
            min_duration=pl.min_duration,
            max_duration=pl.max_duration,
            min_interest_rate=pl.min_interest_rate,
            max_interest_rate=pl.max_interest_rate,
            payment_frequency=pl.payment_frequency
        )

def load_product_lookups(apps, schema_editor):
    
    ProductLine = apps.get_model("julo", "ProductLine")
    product_line_grab1 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.GRAB1)
    product_line_grab2 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.GRAB2)
        
    product_lookups = [
        (27, 'I.480-O.000-L.050-C1.000-C2.000-M', 0.48, 0.000, 0.050, 0.000, 0.000, True, product_line_grab1),
        (28, 'I.480-O.000-L.050-C1.000-C2.000-M', 0.48, 0.000, 0.050, 0.000, 0.000, True, product_line_grab2),
    ]

    ProductLookup = apps.get_model("julo", "ProductLookup")
    for pl in product_lookups:
        kwargs = {
            'product_code': pl[0],
            'product_name': pl[1],
            'interest_rate': pl[2],
            'origination_fee_pct': pl[3],
            'late_fee_pct': pl[4],
            'cashback_initial_pct': pl[5],
            'cashback_payment_pct': pl[6],
            'is_active': pl[7],
            'product_line': pl[8],
            'cdate': timezone.localtime(timezone.now()),
            'udate': timezone.localtime(timezone.now())
        }
        product_lookup = ProductLookup(**kwargs)
        product_lookup.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0171_auto_20171230_1142'),
    ]

    operations = [
        migrations.RunPython(load_grab_partner, migrations.RunPython.noop),
        migrations.RunPython(load_grab_product_lines, migrations.RunPython.noop),
        migrations.RunPython(load_product_lookups, migrations.RunPython.noop)
    ]
