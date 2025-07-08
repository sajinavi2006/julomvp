# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.core.validators
from django.conf import settings


def create_default_number(apps, _schema_editor):
    robocall_calling_number = apps.get_model("nexmo", "RobocallCallingNumberChanger")

    robocall_calling_number.objects.create(
        name='default_number', default_number=settings.NEXMO_PHONE_NUMBER
    )


class Migration(migrations.Migration):

    dependencies = [
        ('nexmo', '0001_create_robocall_calling_number_changer'),
    ]

    operations = [
        migrations.AlterField(
            model_name='robocallcallingnumberchanger',
            name='default_number',
            field=models.CharField(blank=True, max_length=120, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AlterField(
            model_name='robocallcallingnumberchanger',
            name='new_calling_number',
            field=models.CharField(blank=True, max_length=120, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AlterField(
            model_name='robocallcallingnumberchanger',
            name='test_to_call_number',
            field=models.CharField(blank=True, max_length=120, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.RunPython(create_default_number, migrations.RunPython.noop)
    ]
