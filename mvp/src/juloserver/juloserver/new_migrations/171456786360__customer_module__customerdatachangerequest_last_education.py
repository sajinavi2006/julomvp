# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-05-01 12:51
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='customerdatachangerequest',
            name='last_education',
            field=models.CharField(
                blank=True,
                choices=[
                    ('SD', 'SD'),
                    ('SLTP', 'SLTP'),
                    ('SLTA', 'SLTA'),
                    ('Diploma', 'Diploma'),
                    ('S1', 'S1'),
                    ('S2', 'S2'),
                    ('S3', 'S3'),
                ],
                max_length=50,
                null=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message='characters not allowed', regex='^[ -~]+$'
                    )
                ],
                verbose_name='Pendidikan terakhir',
            ),
        ),
    ]
