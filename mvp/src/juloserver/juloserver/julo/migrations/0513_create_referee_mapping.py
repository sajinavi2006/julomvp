# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-09-13 05:23
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0512_insert_data_referral_system'),
    ]

    operations = [
        migrations.CreateModel(
            name='RefereeMapping',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='referee_mapping_id', primary_key=True, serialize=False)),
            ],
            options={
                'db_table': 'referee_mapping',
            },
        ),
        migrations.AddField(
            model_name='refereemapping',
            name='referee',
            field=models.ForeignKey(db_column='referee_id', on_delete=django.db.models.deletion.DO_NOTHING, related_name='referee_id', to='julo.Customer'),
        ),
        migrations.AddField(
            model_name='refereemapping',
            name='referrer',
            field=models.ForeignKey(db_column='referrer_id', on_delete=django.db.models.deletion.DO_NOTHING, related_name='referrer_id', to='julo.Customer'),
        ),
    ]
