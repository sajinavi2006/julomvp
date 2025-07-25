# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-03-21 18:01
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='loanrefinancingrequest',
            name='source',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrefinancingrequest',
            name='source_detail',
            field=django.contrib.postgres.fields.jsonb.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='loanrefinancingapproval',
            name='approver_notes',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='loanrefinancingapproval',
            name='approver_reason',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='loanrefinancingapproval',
            name='requestor_notes',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='loanrefinancingapproval',
            name='requestor_reason',
            field=models.TextField(blank=True, null=True),
        ),
    ]
