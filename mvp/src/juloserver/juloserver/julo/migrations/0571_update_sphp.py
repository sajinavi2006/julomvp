# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
from django.db import migrations
from django.template.loader import render_to_string


def update_sphp_template(apps, _schema_editor):
    with open('juloserver/julo/templates/mtl_sphp.html', "r") as file:
        sphp_mtl = file.read()
        file.close()

    SphpTemplate = apps.get_model("julo", "SphpTemplate")
    sphp_templates = SphpTemplate.objects.filter(
        product_name__in=('MTL1', 'MTL2')
        ).update(
            sphp_template=sphp_mtl)

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0570_create_blacklist_table'),
    ]

    operations = [
        migrations.RunPython(update_sphp_template, migrations.RunPython.noop)
    ]
