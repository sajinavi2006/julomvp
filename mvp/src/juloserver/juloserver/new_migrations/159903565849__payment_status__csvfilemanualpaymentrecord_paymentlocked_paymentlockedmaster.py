# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-02 08:34
from __future__ import unicode_literals

import cuser.fields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CsvFileManualPaymentRecord',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='csv_file_manual_payment_record_id', primary_key=True, serialize=False)),
                ('filename', models.CharField(max_length=200, unique=True)),
                ('agent', cuser.fields.CurrentUserField(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'csv_file_manual_payment_record',
            },
        ),
        migrations.CreateModel(
            name='PaymentLocked',
            fields=[
                ('id', models.AutoField(db_column='payment_locked_id', primary_key=True, serialize=False)),
                ('status_code_locked', models.IntegerField(blank=True, null=True)),
                ('status_code_unlocked', models.IntegerField(blank=True, null=True)),
                ('locked', models.BooleanField(default=True)),
                ('status_obsolete', models.BooleanField(default=False)),
                ('ts_locked', models.DateTimeField(auto_now_add=True)),
                ('ts_unlocked', models.DateTimeField(auto_now=True, null=True)),
                ('payment', models.ForeignKey(db_column='payment_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment')),
                ('user_lock', models.ForeignKey(db_column='user_lock_id', on_delete=django.db.models.deletion.DO_NOTHING, related_name='payment_user_lock', to=settings.AUTH_USER_MODEL)),
                ('user_unlock', models.ForeignKey(blank=True, db_column='user_unlock_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='payment_user_unlock', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'payment_locked',
                'verbose_name_plural': 'Payment Locked',
            },
        ),
        migrations.CreateModel(
            name='PaymentLockedMaster',
            fields=[
                ('id', models.AutoField(db_column='payment_locked_master_id', primary_key=True, serialize=False)),
                ('ts_locked', models.DateTimeField(auto_now_add=True)),
                ('payment', models.OneToOneField(db_column='payment_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment')),
                ('user_lock', models.ForeignKey(db_column='user_lock_id', on_delete=django.db.models.deletion.DO_NOTHING, related_name='payment_user_lock_master', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'payment_locked_master',
                'verbose_name_plural': 'Payment Lock Master',
            },
        ),
    ]
