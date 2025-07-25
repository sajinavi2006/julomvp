# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-02-16 15:52
from __future__ import unicode_literals
from django.db import migrations, models
import django.contrib.postgres.fields
from juloserver.streamlined_communication.constant import CommunicationPlatform

def update_sms_messages(apps, schema_editor):

    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    for i in [1, 3, 5, 7, 10, 21]:
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='mtl_sms_dpd_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_mtl_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_pedemtl_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='pedemtl_sms_dpd_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_pedestl_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='pedestl_sms_dpd_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='stl_sms_dpd_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_stl_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='laku6mtl_sms_dpd_+{}'.format(i),
                   dpd=i).update(is_automated=True)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_laku6_+{}'.format(i),
                   dpd=i).update(is_automated=True)

class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0028_add_data_pede_stream_lined_communication'),
    ]

    operations = [
        migrations.RunPython(update_sms_messages,
                             migrations.RunPython.noop)
    ]
