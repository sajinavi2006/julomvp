# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-06-16 01:17
from __future__ import unicode_literals

from django.db import migrations
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='loanlenderhistory',
            name='loan',
            field=juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan'),
        ),
    ]
