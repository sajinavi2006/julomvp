# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

from juloserver.followthemoney.models import LenderInsurance


def lender_insurance_data(apps, _schema_editor):
    
    LenderInsurance.objects.get_or_create(name="PT. Asuransi Simas Insurtech")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(lender_insurance_data, migrations.RunPython.noop)
    ]