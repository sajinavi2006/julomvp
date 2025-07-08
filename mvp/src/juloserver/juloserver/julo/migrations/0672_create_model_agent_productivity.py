from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0671_create_payment_methods_model'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentProductivity',
            fields=[
                ('id', models.AutoField(db_column='agent_productivity_id', primary_key=True)),
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('agent_name', models.TextField(null=True, blank=True)),
                ('hourly_interval', models.TextField(blank=True, null=True)),
                ('calling_date', models.DateTimeField(null=True, blank=True)),
                ('inbound_calls_offered', models.IntegerField(blank=True, null=True)),
                ('inbound_calls_answered', models.IntegerField(blank=True, null=True)),
                ('inbound_calls_not_answered', models.IntegerField(blank=True, null=True)),
                ('outbound_calls_initiated', models.IntegerField(blank=True, null=True)),
                ('outbound_calls_connected', models.IntegerField(blank=True, null=True)),
                ('outbound_calls_not_connected', models.IntegerField(blank=True, null=True)),
                ('outbound_calls_offered', models.IntegerField(blank=True, null=True)),
                ('outbound_calls_answered', models.IntegerField(blank=True, null=True)),
                ('outbound_calls_not_answered', models.IntegerField(blank=True, null=True)),
                ('manual_in_calls_offered', models.IntegerField(blank=True, null=True)),
                ('manual_in_calls_answered', models.IntegerField(blank=True, null=True)),
                ('manual_in_calls_not_answered', models.IntegerField(blank=True, null=True)),
                ('manual_out_calls_initiated', models.IntegerField(blank=True, null=True)),
                ('manual_out_calls_connected', models.IntegerField(blank=True, null=True)),
                ('manual_out_calls_not_connected', models.IntegerField(blank=True, null=True)),
                ('internal_in_calls_offered', models.IntegerField(blank=True, null=True)),
                ('internal_in_calls_offered', models.IntegerField(blank=True, null=True)),
                ('internal_in_calls_offered', models.IntegerField(blank=True, null=True)),
                ('internal_in_calls_answered', models.IntegerField(blank=True, null=True)),
                ('internal_in_calls_not_answered', models.IntegerField(blank=True, null=True)),
                ('internal_out_calls_initiated', models.IntegerField(blank=True, null=True)),
                ('internal_out_calls_connected', models.IntegerField(blank=True, null=True)),
                ('internal_out_calls_not_connected', models.IntegerField(blank=True, null=True)),
                ('inbound_talk_time', models.TextField(blank=True, null=True)),
                ('inbound_hold_time', models.TextField(blank=True, null=True)),
                ('inbound_acw_time', models.TextField(blank=True, null=True)),
                ('inbound_handling_time', models.TextField(blank=True, null=True)),
                ('outbound_talk_time', models.TextField(blank=True, null=True)),
                ('outbound_hold_time', models.TextField(blank=True, null=True)),
                ('outbound_acw_time', models.TextField(blank=True, null=True)),
                ('outbound_handling_time', models.TextField(blank=True, null=True)),
                ('manual_out_call_time', models.TextField(blank=True, null=True)),
                ('manual_in_call_time', models.TextField(blank=True, null=True)),
                ('internal_out_call_time', models.TextField(blank=True, null=True)),
                ('internal_in_call_time', models.TextField(blank=True, null=True)),
                ('logged_in_time', models.TextField(blank=True, null=True)),
                ('available_time', models.TextField(blank=True, null=True)),
                ('aux_time', models.TextField(blank=True, null=True)),
                ('busy_time', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'agent_productivity',
            },
        ),
    ]
