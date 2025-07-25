# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-07-27 05:51
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0262_new_status_177'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApplicationScrapeAction',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='application_scrape_action_id', primary_key=True, serialize=False)),
                ('url', models.CharField(max_length=100)),
                ('scrape_type', models.CharField(max_length=10)),
                ('application', models.ForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
            ],
            options={
                'db_table': 'application_scrape_action',
            },
        ),
    ]
