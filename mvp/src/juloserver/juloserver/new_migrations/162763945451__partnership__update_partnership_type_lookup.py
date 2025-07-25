# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-07-30 10:04
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='MerchantDistributorCategory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='merchant_distributor_category_id', primary_key=True, serialize=False)),
                ('category_name', models.TextField()),
            ],
            options={
                'db_table': 'merchant_distributor_category',
            },
        ),
        migrations.CreateModel(
            name='PartnershipType',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='partnership_type_id', primary_key=True, serialize=False)),
                ('partner_type_name', models.TextField()),
            ],
            options={
                'db_table': 'partnership_type',
            },
        ),
        migrations.RemoveField(
            model_name='partnershipconfig',
            name='partner_type',
        ),
        migrations.AddField(
            model_name='partnershipapilog',
            name='partnership_config',
            field=models.ForeignKey(blank=True, db_column='partnership_config_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='partnership.PartnershipConfig'),
        ),
        migrations.AlterField(
            model_name='distributor',
            name='distributor_category',
            field=models.ForeignKey(db_column='distributor_category_id', on_delete=django.db.models.deletion.DO_NOTHING, to='partnership.MerchantDistributorCategory'),
        ),
        migrations.AlterField(
            model_name='merchanthistoricaltransaction',
            name='amount',
            field=models.BigIntegerField(default=0),
        ),
        migrations.DeleteModel(
            name='DistributorCategory',
        ),
        migrations.AddField(
            model_name='partnershipconfig',
            name='partnership_type',
            field=models.ForeignKey(blank=True, db_column='partnership_type_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='partnership.PartnershipType'),
        ),
    ]
