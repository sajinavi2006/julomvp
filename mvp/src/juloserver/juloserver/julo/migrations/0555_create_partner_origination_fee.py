# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-12-05 00:22
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


class Migration(migrations.Migration):

    def partner_origination_data(apps, _schema_editor):
        FeatureSetting = apps.get_model("julo", "PartnerOriginationData")
        FeatureSetting.objects.create(id=0,
                                      distributor_name='Prima',
                                      origination_fee=0.015)
        FeatureSetting.objects.create(id=9,
                                      distributor_name='Dawang',
                                      origination_fee=0.01)
        FeatureSetting.objects.create(id=12,
                                      distributor_name='Dawang(1 bio)',
                                      origination_fee=0.01)
        FeatureSetting.objects.create(id=13,
                                      distributor_name='Tristar',
                                      origination_fee=0.01)
        FeatureSetting.objects.create(id=14,
                                      distributor_name='Boost',
                                      origination_fee=0.01)

    dependencies = [
        ('julo', '0554_initial_collection_face_rekognition'),
    ]

    operations = [
        migrations.CreateModel(
            name='PartnerOriginationData',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.IntegerField(db_column='partner_origination_data_id', primary_key=True, serialize=False, unique=True)),
                ('distributor_name', models.CharField(default='-', max_length=100)),
                ('origination_fee', models.FloatField(default=0.01)),
            ],
            options={
                'db_table': 'partner_origination_data',
            },
        ),
        migrations.RunPython(partner_origination_data, migrations.RunPython.noop)
    ]
