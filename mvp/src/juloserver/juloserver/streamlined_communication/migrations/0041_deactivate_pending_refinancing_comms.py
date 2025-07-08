# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def deactivate_communications_refinancing_pending(apps, schema_editor):
    StreamlinedCommunication = apps.get_model(
        "streamlined_communication", "StreamlinedCommunication")

    streamline_nexmo_robocall = StreamlinedCommunication.objects.filter(
        template_code="nexmo_robocall_mtl_ref_pending_dpd_3",
    )
    if streamline_nexmo_robocall:
        streamline_nexmo_robocall = streamline_nexmo_robocall.last()
        streamline_nexmo_robocall.is_active = False
        streamline_nexmo_robocall.is_automated = False
        streamline_nexmo_robocall.save()

    streamline_sms_day_2 = StreamlinedCommunication.objects.filter(
        template_code='sms_mtl_ref_pending_dpd_2',
    )
    if streamline_sms_day_2:
        streamline_sms_day_2 = streamline_sms_day_2.last()
        streamline_sms_day_2.is_active = False
        streamline_sms_day_2.is_automated = False
        streamline_sms_day_2.save()

    streamline_sms_day_5 = StreamlinedCommunication.objects.filter(
        template_code='sms_mtl_ref_pending_dpd_5',
    )
    if streamline_sms_day_5:
        streamline_sms_day_5 = streamline_sms_day_5.last()
        streamline_sms_day_5.is_active = False
        streamline_sms_day_5.is_automated = False
        streamline_sms_day_5.save()


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0040_add_schedule_for_email'),
    ]

    operations = [
        migrations.RunPython(
            deactivate_communications_refinancing_pending, migrations.RunPython.noop),
    ]
