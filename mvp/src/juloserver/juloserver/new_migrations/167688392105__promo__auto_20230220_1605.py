# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-02-20 09:05
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PromoCodeAgentMapping',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='promo_code_agent_mapping_id', primary_key=True, serialize=False)),
                ('agent', models.ForeignKey(blank=True, db_column='agent_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Agent')),
                ('promo_code', models.ForeignKey(db_column='promo_code_id', on_delete=django.db.models.deletion.DO_NOTHING, to='promo.PromoCode')),
            ],
            options={
                'db_table': 'promo_code_agent_mapping',
            },
        ),
        migrations.AlterUniqueTogether(
            name='promocodeagentmapping',
            unique_together=set([('agent',)]),
        ),
    ]
