# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-11-02 17:47
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0028_add_pending_withdrawal'),
    ]

    operations = [
        migrations.AlterField(
            model_name='loanwriteoff',
            name='loan',
            field=models.ForeignKey(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan'),
        ),
    ]
