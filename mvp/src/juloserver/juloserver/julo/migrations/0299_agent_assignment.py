# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-10-19 09:19
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from ..constants import FeatureNameConst
from django.contrib.auth.models import Group

def add_assign_agent_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD61_DPD90,
                                        category="agent",
                                        description="https://trello.com/c/sK96QE61"
                                        )
    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.AGENT_ASSIGNMENT_DPD91PLUS,
                                        category="agent",
                                        description="https://trello.com/c/sK96QE61"
                                        )
    dpd1_dpd30 = FeatureSetting.objects.get(feature_name=FeatureNameConst.ASSIGN_AGENT_DPD1_DPD30)
    dpd31plus = FeatureSetting.objects.get(feature_name=FeatureNameConst.ASSIGN_AGENT_DPD31PLUS)
    dpd1_dpd30.feature_name = FeatureNameConst.AGENT_ASSIGNMENT_DPD1_DPD30
    dpd31plus.feature_name = FeatureNameConst.AGENT_ASSIGNMENT_DPD31_DPD60
    dpd1_dpd30.save()
    dpd31plus.save()

def create_collection_agent_4_and_5(apps, schema_editor):
    new_group_collection_agent_4, _ = Group.objects.get_or_create(name='collection_agent_4')
    new_group_collection_agent_5, _ = Group.objects.get_or_create(name='collection_agent_5')
    

class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('julo', '0298_loanagent'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='loanagent',
            name='agent',
        ),
        migrations.RemoveField(
            model_name='loanagent',
            name='loan',
        ),
        migrations.DeleteModel(
            name='LoanAgent',
        ),
        migrations.CreateModel(
            name='AgentAssignment',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='agent_assignment_id', primary_key=True, serialize=False)),
                ('assign_time', models.DateTimeField(blank=True, null=True)),
                ('unassign_time', models.DateTimeField(blank=True, null=True)),
                ('type', models.CharField(blank=True, max_length=50, null=True)),
                ('agent', models.ForeignKey(db_column='agent_id', on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, blank=True, null=True)),
                ('application', models.ForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application', blank=True, null=True)),
                ('collected_by',models.ForeignKey(blank=True, db_column='collected_by', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='collected_by', to=settings.AUTH_USER_MODEL)),
                ('collect_date', models.DateField(blank=True, null=True)),
                ('loan', models.ForeignKey(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan', blank=True, null=True)),
                ('payment', models.ForeignKey(db_column='payment_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment', blank=True, null=True)),
            ],
            options={
                'db_table': 'agent_assignment',
            },
        ),
        migrations.RunSQL(
            "ALTER TABLE agent_assignment ALTER COLUMN loan_id TYPE bigint;"),
        migrations.RunSQL(
            "ALTER TABLE agent_assignment ALTER COLUMN payment_id TYPE bigint;"),
        migrations.RunSQL(
            "ALTER TABLE agent_assignment ALTER COLUMN application_id TYPE bigint;"),
        migrations.RunPython(add_assign_agent_settings, migrations.RunPython.noop),
        migrations.RunPython(create_collection_agent_4_and_5, migrations.RunPython.noop),
    ]
