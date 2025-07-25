# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-04-06 13:53
from __future__ import unicode_literals

from django.db import migrations, models


from juloserver.julo.models import LenderDisburseCounter



from juloserver.julo.models import Partner



def retroload_lender_disburse_counter(apps, schema_editor):
    
    
    lender_list = Partner.objects.filter(type='lender')

    for lender in lender_list:
        LenderDisburseCounter.objects.create(partner=lender,
                                             actual_count=0,
                                             rounded_count=0)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_lender_disburse_counter, migrations.RunPython.noop),
    ]
