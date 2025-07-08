# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
from django.db import migrations
from django.template.loader import render_to_string


from juloserver.julo.models import SphpTemplate



def update_sphp_template(apps, _schema_editor):
    with open('juloserver/julo/templates/mtl_sphp.html', "r") as file:
        sphp_mtl = file.read()
        file.close()

    
    sphp_templates = SphpTemplate.objects.filter(
        product_name__in=('MTL1', 'MTL2')
        ).update(
            sphp_template=sphp_mtl)

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_sphp_template, migrations.RunPython.noop)
    ]
