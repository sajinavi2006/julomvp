# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-02-20 05:56
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='DBSChannelingApplicationJob',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='dbs_channeling_application_job_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('job_industry', models.CharField(blank=True, max_length=100, null=True)),
                ('job_description', models.CharField(blank=True, max_length=100, null=True)),
                ('is_exclude', models.BooleanField(default=False)),
                ('aml_risk_rating', models.CharField(blank=True, max_length=6, null=True)),
                ('job_code', models.CharField(blank=True, max_length=2, null=True)),
                ('job_industry_code', models.CharField(blank=True, max_length=2, null=True)),
            ],
            options={
                'db_table': 'dbs_channeling_application_job',
            },
        ),
        migrations.AlterIndexTogether(
            name='dbschannelingapplicationjob',
            index_together=set([('job_industry', 'job_description')]),
        ),
    ]
