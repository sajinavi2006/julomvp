# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-05-09 05:34
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models
import tinymce.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0429_alter_payment_history_to_date_field'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailSetting',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='email_setting_id', primary_key=True, serialize=False)),
                ('status_code', models.CharField(blank=True, max_length=10, null=True)),
                ('send_to_partner', models.BooleanField(default=False)),
                ('partner_email_content', tinymce.models.HTMLField(blank=True, null=True)),
                ('send_to_customer', models.BooleanField(default=False)),
                ('customer_email_content', tinymce.models.HTMLField(blank=True, null=True)),
                ('enabled', models.BooleanField(default=False)),
                ('partner', models.ForeignKey(blank=True, db_column='partner_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner')),
            ],
            options={
                'db_table': 'email_setting',
            },
        )
    ]
