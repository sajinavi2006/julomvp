# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-09-12 09:41
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0285_load_guarantor_setting'),
    ]

    operations = [
        migrations.CreateModel(
            name='MobileFeatureSetting',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='mobile_feature_setting_id', primary_key=True, serialize=False)),
                ('feature_name', models.CharField(max_length=200)),
                ('is_active', models.BooleanField(default=True)),
                ('parameters', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'mobile_feature_setting',
            },
        ),
        migrations.DeleteModel(
            name='GuarantorContactSetting',
        ),
    ]
