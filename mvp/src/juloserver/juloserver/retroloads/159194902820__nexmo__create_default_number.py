# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.core.validators
from django.conf import settings


from juloserver.nexmo.models import RobocallCallingNumberChanger



def create_default_number(apps, _schema_editor):

    RobocallCallingNumberChanger.objects.create(
        name='default_number', default_number=settings.NEXMO_PHONE_NUMBER
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_default_number, migrations.RunPython.noop)
    ]
