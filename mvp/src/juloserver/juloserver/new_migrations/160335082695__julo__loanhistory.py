# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-22 07:13
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='LoanHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='loan_history_id', primary_key=True, serialize=False)),
                ('status_old', models.IntegerField()),
                ('status_new', models.IntegerField()),
                ('change_reason', models.TextField(default='system_triggered')),
                ('change_by_id', models.IntegerField(blank=True, null=True)),
                ('loan', models.ForeignKey(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING,
                                           to='julo.Loan')),
            ],
            options={
                'db_table': 'loan_history',
            },
        ),
        migrations.AddField(
            model_name='loan',
            name='sphp_exp_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='voicerecord',
            name='loan',
            field=models.ForeignKey(blank=True, db_column='loan_id', null=True,
                                    on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan'),
        ),
        migrations.AlterField(
            model_name='voicerecord',
            name='application',
            field=models.ForeignKey(blank=True, db_column='application_id', null=True,
                                    on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application'),
        ),
        migrations.AddField(
            model_name='signaturemethodhistory',
            name='loan',
            field=models.ForeignKey(blank=True, db_column='loan_id', null=True,
                                    on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan'),
        ),
        migrations.AddField(
            model_name='document',
            name='loan_xid',
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
    ]
