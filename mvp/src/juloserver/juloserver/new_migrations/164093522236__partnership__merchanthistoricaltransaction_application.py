# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-12-31 07:20
from __future__ import unicode_literals

from django.db import migrations
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='merchanthistoricaltransaction',
            name='application',
            field=juloserver.julocore.customized_psycopg2.models.BigForeignKey(blank=True, db_column='application_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application'),
        ),
    ]
