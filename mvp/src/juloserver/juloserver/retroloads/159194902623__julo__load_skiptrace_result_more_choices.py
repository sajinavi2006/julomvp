from __future__ import unicode_literals
from django.db import migrations, models

from juloserver.julo.models import SkiptraceResultChoice


def load_skiptrace_result_choice(apps, schema_editor):
    data = [('Busy', '-1'),
            ('Salah Nomor', '-1'),
            ('Tidak Diangkat', '-1'),
            ('Mesin Fax', '-1'),
            ('Positive Voice', '-1'),
            ('Answering Machine - System', '-1'),
            ('Trying to Reach', '-1'),
            ('No Contact / End of Campaign', '-1'),
            ('Unreachable', '-1'),
            ('No Interaction Status', '-1'),
            ('Reallocated', '-1'),
            ('Reassigned', '-1'),
            ('Disconnect by System', '-1'),
            ('NULL', '-1'),
            ('Abandoned by System', '-1'),
            ('Abandoned by Customer', '-1'),
            ('Abandoned by Agent', '-1'),
            ('Disconnect By Network', '-1'),
            ('Call Failed', '-1'),
            ('Not Active', '-1'),
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
