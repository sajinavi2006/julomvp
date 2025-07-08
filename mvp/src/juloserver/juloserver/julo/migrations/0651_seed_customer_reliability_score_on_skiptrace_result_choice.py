# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from datetime import datetime


def seed_customer_reliability_score(apps, schema_editor):
    reliability_score_dict = {
        'Cancel': 0,
        'Not Connected': -1,
        'Rejected/Busy': -1,
        'No Answer': -1,
        'WPC': -10,
        'RPC': 5,
        'NO CONTACTED': -1,
        'HANG UP': -3,
        'Ringing no pick up / Busy': -1,
        'Busy Tone': 0,
        'Hard To Pay': -5,
        'Call Back': -1,
        'Broken Promise': -10,
        'PTPR': 5,
        'Short Call': -1,
        'RPC - Regular': 5,
        'RPC - PTP': 10,
        'RPC - HTP': -5,
        'RPC - Broken Promise': -10,
        'RPC - Call Back': -1,
        'WPC - Regular': -10,
        'WPC - Left Message': -5,
        'Answering Machine': -3,
        'Busy Tone': 0,
        'Ringing': -1,
        'Dead Call': 0,
        'Whatsapp - Text': 0,
        'Busy': 0,
        'Salah Nomor': -10,
        'Tidak Diangkat': -1,
        'Mesin Fax': -3,
        'Positive Voice': -1,
        'Answering Machine - System': -3,
        'Trying to Reach': -1,
        'No Contact / End of Campaign': 0,
        'No Interaction Status': 0,
        'Reallocated': 0,
        'Reassigned': 0,
        'Disconnect by System': 0,
        'NULL': 0,
        'Abandoned by System': 0,
        'Abandoned by Customer': 0,
        'Abandoned by Agent': 0,
        'Disconnect By Network': 0,
        'Call Failed': 0,
        'Not Active': -10
    }
    SkiptraceResultChoice = apps.get_model("julo", "SkiptraceResultChoice")
    skiptrace_choices = SkiptraceResultChoice.objects.all()

    for skiptrace_choice in skiptrace_choices:
        if skiptrace_choice.name in reliability_score_dict:
            skiptrace_choice.customer_reliability_score = reliability_score_dict[skiptrace_choice.name]
            skiptrace_choice.save()


class Migration(migrations.Migration):
    dependencies = [
        ('julo', '0650_alter_skiptrace_result_choice_table'),
    ]

    operations = [
        migrations.RunPython(seed_customer_reliability_score, migrations.RunPython.noop)
    ]
