# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-04-16 07:11
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julo.models


from juloserver.julo.models import FrontendView



def create_initial_data(apps, schema_editor):
    

    FrontendView.objects.create(
        label_name='TKB90',
        label_value='90.54%')

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_initial_data, migrations.RunPython.noop)
    ]
