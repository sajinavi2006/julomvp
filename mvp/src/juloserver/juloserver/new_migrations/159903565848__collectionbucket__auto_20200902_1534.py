# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-02 08:34
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='collectionagenttask',
            name='loan',
            field=models.ForeignKey(blank=True, db_column='loan_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan'),
        ),
        migrations.AddField(
            model_name='collectionagenttask',
            name='payment',
            field=models.ForeignKey(blank=True, db_column='payment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment'),
        ),
    ]
