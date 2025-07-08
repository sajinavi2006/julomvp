# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from juloserver.julo.clients import get_julo_face_rekognition
import django.core.validators
from django.db import migrations, models

def initial_add_collection(apps, _schema_editor):
    rekognition = get_julo_face_rekognition()

    try:
        rekognition.add_collection()
    except Exception as e:
        pass

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0553_add_column_mother_maiden_name'),
    ]

    operations = [
        migrations.RunPython(initial_add_collection, migrations.RunPython.noop),
    ]
