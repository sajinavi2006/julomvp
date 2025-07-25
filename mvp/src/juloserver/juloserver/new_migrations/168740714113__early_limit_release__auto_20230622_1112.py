# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-22 04:12
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterModelTable(
            name='releasetracking',
            table='release_tracking',
        ),
        migrations.AddField(
            model_name='releasetracking',
            name='type',
            field=models.CharField(choices=[('early_release', 'Early release'), ('last_release', 'Last release')], default='early_release', max_length=255),
        ),
        migrations.AlterField(
            model_name='releasetracking',
            name='loan',
            field=juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING, related_name='release_trackings', to='julo.Loan'),
        ),
        migrations.AlterField(
            model_name='releasetracking',
            name='payment',
            field=juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='payment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment'),
        ),
    ]
