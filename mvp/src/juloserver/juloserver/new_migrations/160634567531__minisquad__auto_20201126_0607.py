# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-11-25 23:07
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='senttodialer',
            name='loan',
            field=models.ForeignKey(blank=True, db_column='loan_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan'),
        ),
        migrations.AlterField(
            model_name='senttodialer',
            name='payment',
            field=models.ForeignKey(blank=True, db_column='payment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment'),
        ),
    ]
