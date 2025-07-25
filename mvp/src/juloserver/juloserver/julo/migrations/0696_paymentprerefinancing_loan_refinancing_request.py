# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-07-13 07:44
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loan_refinancing', '0037_create_model_collection_offer_eligibility'),
        ('julo', '0695_change_login_logut_ts_format'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentprerefinancing',
            name='loan_refinancing_request',
            field=models.ForeignKey(blank=True, db_column='loan_refinancing_request_id',
                                    null=True, on_delete=django.db.models.deletion.DO_NOTHING,
                                    to='loan_refinancing.LoanRefinancingRequest'),
        )
    ]
