from __future__ import unicode_literals
from django.db import migrations, models

from juloserver.julo.models import SkiptraceResultChoice


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
    
    for name, weight in data:
        obj = SkiptraceResultChoice(name=name, weight=weight)
        obj.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_skiptrace_result_choice,
                             migrations.RunPython.noop)
    ]
