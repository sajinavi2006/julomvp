# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-02 08:27
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WaiverApproval',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='waiver_approval_id', primary_key=True, serialize=False)),
                ('approver_type', models.TextField()),
                ('paid_ptp_amount', models.BigIntegerField(blank=True, null=True)),
                ('decision', models.TextField()),
                ('decision_ts', models.DateTimeField()),
                ('approved_program', models.TextField()),
                ('approved_late_fee_waiver_percentage', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('approved_interest_waiver_percentage', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('approved_principal_waiver_percentage', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('approved_waiver_amount', models.BigIntegerField()),
                ('approved_remaining_amount', models.BigIntegerField()),
                ('approved_waiver_validity_date', models.DateField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('approved_by', models.ForeignKey(blank=True, db_column='approved_by_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='waiverapproval_approved_by', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'waiver_approval',
            },
        ),
        migrations.CreateModel(
            name='WaiverPaymentApproval',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='waiver_payment_approval_id', primary_key=True, serialize=False)),
                ('outstanding_late_fee_amount', models.BigIntegerField(blank=True, null=True)),
                ('outstanding_interest_amount', models.BigIntegerField(blank=True, null=True)),
                ('outstanding_principal_amount', models.BigIntegerField(blank=True, null=True)),
                ('total_outstanding_amount', models.BigIntegerField(blank=True, null=True)),
                ('approved_late_fee_waiver_amount', models.BigIntegerField(blank=True, null=True)),
                ('approved_interest_waiver_amount', models.BigIntegerField(blank=True, null=True)),
                ('approved_principal_waiver_amount', models.BigIntegerField(blank=True, null=True)),
                ('total_approved_waiver_amount', models.BigIntegerField(blank=True, null=True)),
                ('remaining_late_fee_amount', models.BigIntegerField(blank=True, null=True)),
                ('remaining_interest_amount', models.BigIntegerField(blank=True, null=True)),
                ('remaining_principal_amount', models.BigIntegerField(blank=True, null=True)),
                ('total_remaining_amount', models.BigIntegerField(blank=True, null=True)),
                ('payment', models.ForeignKey(blank=True, db_column='payment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment')),
                ('waiver_approval', models.ForeignKey(blank=True, db_column='waiver_approval_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='loan_refinancing.WaiverApproval')),
            ],
            options={
                'db_table': 'waiver_payment_approval',
            },
        ),
        migrations.CreateModel(
            name='WaiverPaymentRequest',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='waiver_payment_request_id', primary_key=True, serialize=False)),
                ('outstanding_late_fee_amount', models.BigIntegerField(blank=True, null=True)),
                ('outstanding_interest_amount', models.BigIntegerField(blank=True, null=True)),
                ('outstanding_principal_amount', models.BigIntegerField(blank=True, null=True)),
                ('total_outstanding_amount', models.BigIntegerField(blank=True, null=True)),
                ('requested_late_fee_waiver_amount', models.BigIntegerField(blank=True, null=True)),
                ('requested_interest_waiver_amount', models.BigIntegerField(blank=True, null=True)),
                ('requested_principal_waiver_amount', models.BigIntegerField(blank=True, null=True)),
                ('total_requested_waiver_amount', models.BigIntegerField(blank=True, null=True)),
                ('remaining_late_fee_amount', models.BigIntegerField(blank=True, null=True)),
                ('remaining_interest_amount', models.BigIntegerField(blank=True, null=True)),
                ('remaining_principal_amount', models.BigIntegerField(blank=True, null=True)),
                ('total_remaining_amount', models.BigIntegerField(blank=True, null=True)),
                ('is_paid_off_after_ptp', models.NullBooleanField()),
                ('payment', models.ForeignKey(blank=True, db_column='payment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment')),
            ],
            options={
                'db_table': 'waiver_payment_request',
            },
        ),
        migrations.CreateModel(
            name='WaiverRecommendation',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='waiver_recommendation_id', primary_key=True, serialize=False)),
                ('bucket_name', models.TextField(blank=True, null=True)),
                ('program_name', models.TextField(blank=True, null=True)),
                ('is_covid_risky', models.BooleanField(default=False)),
                ('partner_product', models.TextField()),
                ('late_fee_waiver_percentage', models.DecimalField(decimal_places=2, max_digits=15)),
                ('interest_waiver_percentage', models.DecimalField(decimal_places=2, max_digits=15)),
                ('principal_waiver_percentage', models.DecimalField(decimal_places=2, max_digits=15)),
            ],
            options={
                'db_table': 'waiver_recommendation',
            },
        ),
        migrations.RenameField(
            model_name='waiverrequest',
            old_name='interest_fee_waiver_amount',
            new_name='requested_interest_waiver_amount',
        ),
        migrations.RenameField(
            model_name='waiverrequest',
            old_name='interest_fee_waiver_percentage',
            new_name='requested_interest_waiver_percentage',
        ),
        migrations.RenameField(
            model_name='waiverrequest',
            old_name='late_fee_waiver_amount',
            new_name='requested_late_fee_waiver_amount',
        ),
        migrations.RenameField(
            model_name='waiverrequest',
            old_name='late_fee_waiver_percentage',
            new_name='requested_late_fee_waiver_percentage',
        ),
        migrations.RenameField(
            model_name='waiverrequest',
            old_name='principal_waiver_amount',
            new_name='requested_principal_waiver_amount',
        ),
        migrations.RenameField(
            model_name='waiverrequest',
            old_name='principal_waiver_percentage',
            new_name='requested_principal_waiver_percentage',
        ),
        migrations.RenameField(
            model_name='waiverrequest',
            old_name='unpaid_payment_count',
            new_name='waived_payment_count',
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='agent_notes',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='approval_layer_state',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='final_approved_remaining_amount',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='final_approved_waiver_amount',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='final_approved_waiver_program',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='final_approved_waiver_validity_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='first_waived_payment',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='first_waived_payment', to='julo.Payment'),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='is_approved',
            field=models.NullBooleanField(),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='last_waived_payment',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='last_waived_payment', to='julo.Payment'),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='loan_refinancing_request',
            field=models.ForeignKey(blank=True, db_column='loan_refinancing_request_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='loan_refinancing.LoanRefinancingRequest'),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='refinancing_status',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='remaining_amount_for_waived_payment',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='requested_waiver_amount',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='waiver_type',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='waiverpaymentrequest',
            name='waiver_request',
            field=models.ForeignKey(blank=True, db_column='waiver_request_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='loan_refinancing.WaiverRequest'),
        ),
        migrations.AddField(
            model_name='waiverapproval',
            name='waiver_request',
            field=models.ForeignKey(blank=True, db_column='waiver_request_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='loan_refinancing.WaiverRequest'),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='waiver_recommendation',
            field=models.ForeignKey(blank=True, db_column='waiver_recommendation_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='loan_refinancing.WaiverRecommendation'),
        ),
    ]
