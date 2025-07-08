# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

def lender_insurance_data(apps, _schema_editor):
    LenderInsurance = apps.get_model("followthemoney", "LenderInsurance")
    LenderInsurance.objects.get_or_create(name="PT. Asuransi Simas Insurtech")


class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0036_lender_insurance'),
    ]

    operations = [
        migrations.RunPython(lender_insurance_data, migrations.RunPython.noop)
    ]