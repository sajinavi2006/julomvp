# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-08-11 08:02
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='onboarding',
            field=models.ForeignKey(db_column='onboarding_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Onboarding'),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='onboarding',
            field=models.ForeignKey(db_column='onboarding_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Onboarding'),
        ),
    ]
