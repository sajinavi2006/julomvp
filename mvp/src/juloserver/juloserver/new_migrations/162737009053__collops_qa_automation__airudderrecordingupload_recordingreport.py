# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-07-27 07:14
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AirudderRecordingUpload',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='airruder_recording_upload_id', primary_key=True, serialize=False)),
                ('task_id', models.TextField(blank=True, null=True)),
                ('phase', models.TextField(default='INITIATED')),
                ('status', models.TextField(blank=True, null=True)),
                ('code', models.IntegerField(blank=True, null=True)),
                ('vendor_recording_detail', models.ForeignKey(blank=True, db_column='vendor_recording_detail_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='minisquad.VendorRecordingDetail')),
            ],
            options={
                'db_table': 'airudder_recording_upload',
            },
        ),
        migrations.CreateModel(
            name='RecordingReport',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='recording_report_id', primary_key=True, serialize=False)),
                ('length', models.IntegerField()),
                ('total_words', models.IntegerField()),
                ('l_channel_sentence', models.TextField()),
                ('l_channel_negative_checkpoint', models.TextField()),
                ('l_channel_negative_score', models.TextField()),
                ('l_channel_negative_score_amount', models.IntegerField()),
                ('l_channel_sop_checkpoint', models.TextField()),
                ('l_channel_sop_score', models.TextField()),
                ('l_channel_sop_score_amount', models.IntegerField()),
                ('r_channel_sentence', models.TextField()),
                ('r_channel_negative_checkpoint', models.TextField()),
                ('r_channel_negative_score', models.TextField()),
                ('r_channel_negative_score_amount', models.IntegerField()),
                ('r_channel_sop_checkpoint', models.TextField()),
                ('r_channel_sop_score', models.TextField()),
                ('r_channel_sop_score_amount', models.IntegerField()),
                ('airudder_recording_upload', models.ForeignKey(db_column='airruder_recording_upload_id', on_delete=django.db.models.deletion.DO_NOTHING, to='collops_qa_automation.AirudderRecordingUpload')),
            ],
            options={
                'db_table': 'recording_report',
            },
        ),
    ]
