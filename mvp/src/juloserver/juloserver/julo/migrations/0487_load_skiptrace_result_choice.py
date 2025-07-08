from __future__ import unicode_literals
from django.db import migrations, models

def load_skiptrace_result_choice(apps, schema_editor):
    data = [('Short Call', '4'),
            ('RPC - Regular', '3'),
            ('RPC - PTP', '3'),
            ('RPC - HTP', '3'),
            ('RPC - Broken Promise', '3'),
            ('RPC - Call Back', '3'),
            ('WPC - Regular', '-20'),
            ('WPC - Left Message', '-20'),
            ('Answering Machine', '-1'),
            ('Busy Tone', '-1'),
            ('Ringing', '-1'),
            ('Dead Call', '-1'),
            ('Whatsapp - Text', '5'),
            ]
    SkiptraceResultChoice = apps.get_model("julo", "SkiptraceResultChoice")
    for name, weight in data:
        obj = SkiptraceResultChoice(name=name, weight=weight)
        obj.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0486_create_ops_team_lead_status_change_table'),
    ]

    operations = [
        migrations.RunPython(load_skiptrace_result_choice,
                             migrations.RunPython.noop)
    ]
