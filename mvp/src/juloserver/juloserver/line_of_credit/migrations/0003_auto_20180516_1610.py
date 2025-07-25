# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-05-16 09:10
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('line_of_credit', '0002_lineofcredit_next_statement_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='lineofcreditstatement',
            name='last_payment_overpaid',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='lineofcreditstatement',
            name='payment_overpaid',
            field=models.BigIntegerField(default=0),
        ),
    ]
