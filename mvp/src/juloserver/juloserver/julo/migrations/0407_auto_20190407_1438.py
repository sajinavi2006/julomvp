# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-04-07 07:38
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0406_whatsapp_history_20190405_1519'),
    ]

    operations = [
        migrations.AlterField(
            model_name='creditscore',
            name='application',
            field=models.OneToOneField(db_column='application_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application'),
        ),
    ]
