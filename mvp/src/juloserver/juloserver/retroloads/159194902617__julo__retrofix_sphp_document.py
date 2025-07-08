# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import Document



def retrofix_document_source_type(apps, schema_editor):
    
    Document.objects.filter(document_type="sphp").update(document_type="sphp_digisign")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retrofix_document_source_type),
    ]
