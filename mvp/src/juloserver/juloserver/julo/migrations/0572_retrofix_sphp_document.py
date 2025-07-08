# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def retrofix_document_source_type(apps, schema_editor):
    Document = apps.get_model("julo", "Document")
    Document.objects.filter(document_type="sphp").update(document_type="sphp_digisign")


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0571_update_sphp'),
    ]

    operations = [
        migrations.RunPython(retrofix_document_source_type),
    ]
