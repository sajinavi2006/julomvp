# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def update_mantri_code(apps, schema_editor):
    Mantri = apps.get_model("julo", "Mantri")
    mantri_list = Mantri.objects.all()
    for mantri in mantri_list:
        mantri.code = 'BRI' + mantri.code
        mantri.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0169_auto_20171227_1157'),
    ]

    operations = [
        migrations.RunPython(update_mantri_code),
    ]
