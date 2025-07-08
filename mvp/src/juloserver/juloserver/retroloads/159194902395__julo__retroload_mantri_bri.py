# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import Mantri



def update_mantri_code(apps, schema_editor):
    
    mantri_list = Mantri.objects.all()
    for mantri in mantri_list:
        mantri.code = 'BRI' + mantri.code
        mantri.save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_mantri_code),
    ]
