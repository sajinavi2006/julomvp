# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.conf import settings


def update_sphp_template(apps, _schema_editor):
    lla_template_dir = '/juloserver/julo/templates/mtl_sphp.html'
    with open(settings.BASE_DIR + lla_template_dir, "r") as file:
        sphp_mtl = file.read()

    SphpTemplate = apps.get_model("julo", "SphpTemplate")
    SphpTemplate.objects.filter(
        product_name__in=('MTL1', 'MTL2')
    ).update(
        sphp_template=sphp_mtl)


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0692_alter_field_is_fdc_risky'),
    ]

    operations = [
        migrations.RunPython(update_sphp_template, migrations.RunPython.noop)
    ]
