from __future__ import unicode_literals
from django.db import migrations

from juloserver.streamlined_communication.constant import CommunicationPlatform


def update_comms_data_is_active(apps, schema_editor):
    StreamlinedCommunication = \
        apps.get_model("streamlined_communication", "StreamlinedCommunication")
    template_codes_in_email_update_to_automated = (
        'email_reminder_in4', 'stl_email_reminder_in4', 'email_reminder_in2',
        'stl_email_reminder_in2', 'email_reminder_in+4', 'email_reminder_ptp_-1-3-5'
    )
    for template_code in template_codes_in_email_update_to_automated:
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.EMAIL,
                   template_code=template_code,
                   is_automated=True).update(is_active=False)
    for i in [1, 3, 5, 7, 10, 21]:
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='mtl_sms_dpd_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_mtl_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_pedemtl_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='pedemtl_sms_dpd_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_pedestl_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='pedestl_sms_dpd_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='stl_sms_dpd_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_stl_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='laku6mtl_sms_dpd_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.SMS,
                   template_code='sms_ptp_laku6_+{}'.format(i),
                   dpd=i, is_automated=True).update(is_active=False)
    template_codes_in_robocall_update_to_automated = (
        'nexmo_robocall_mtl_-3', 'nexmo_robocall_stl_-3', 'nexmo_robocall_stl_-5',
        'nexmo_robocall_mtl_-5', 'nexmo_robocall_PEDEMTL_-3', 'nexmo_robocall_PEDESTL_-3',
        'nexmo_robocall_PEDESTL_-5', 'nexmo_robocall_PEDEMTL_-5'
    )
    for template_code in template_codes_in_robocall_update_to_automated:
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.ROBOCALL,
                   template_code=template_code,
                   is_automated=True).update(is_active=False)
    template_codes_in_pn_update_to_automated = (
        'MTL_T-5', 'MTL_T-4', 'MTL_T-3', 'MTL_T-2', 'MTL_T-1', 'MTL_T0', 'MTL_T1',
        'MTL_T2', 'MTL_T3', 'MTL_T4', 'MTL_T5', 'MTL_T30', 'MTL_T60', 'MTL_T90',
        'MTL_T120', 'MTL_T150', 'MTL_T180', 'STL_T-5', 'STL_T-4', 'STL_T-3',
        'STL_T-2', 'STL_T-1', 'STL_T0', 'STL_T1', 'STL_T2', 'STL_T3', 'STL_T4',
        'STL_T5', 'STL_T30', 'STL_T60', 'STL_T90', 'STL_T120', 'STL_T150', 'STL_T180',
        'MTL_PTP-1'
    )
    for template_code in template_codes_in_pn_update_to_automated:
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.PN,
                   template_code=template_code,
                   is_automated=True).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0042_addfield_to_parameterlist'),
    ]

    operations = [
        migrations.RunPython(update_comms_data_is_active,
                             migrations.RunPython.noop)
    ]
