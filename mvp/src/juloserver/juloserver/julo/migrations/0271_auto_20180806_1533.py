# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-08-06 08:33
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0270_load_BCC_Experiments'),
    ]

    operations = [
        migrations.AddField(
            model_name='primodialerrecord',
            name='lead_id',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='primodialerrecord',
            name='lead_status',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='primodialerrecord',
            name='list_id',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='primodialerrecord',
            name='skiptrace',
            field=models.ForeignKey(db_column='skiptrace_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Skiptrace'),
        ),
        migrations.AlterField(
            model_name='primodialerrecord',
            name='call_status',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
