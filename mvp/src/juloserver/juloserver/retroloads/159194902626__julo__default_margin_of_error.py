# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-01-28 00:26
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


from juloserver.julo.models import MarginOfError



def default_margin_of_error(apps, _schema_editor):
    
    entries = [
        MarginOfError(min_threshold=0, max_threshold=2300000, mae=83028),
        MarginOfError(min_threshold=2300000, max_threshold=3900000, mae=216579),
        MarginOfError(min_threshold=3900000, max_threshold=9000000, mae=530180),
        MarginOfError(min_threshold=9000000, max_threshold=10000000, mae=1315847)
    ]
    MarginOfError.objects.bulk_create(entries)

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(default_margin_of_error, migrations.RunPython.noop)
    ]
