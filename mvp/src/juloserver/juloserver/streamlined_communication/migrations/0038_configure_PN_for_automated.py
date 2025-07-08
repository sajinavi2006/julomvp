from __future__ import unicode_literals
from django.db import migrations, models
import django.contrib.postgres.fields
from juloserver.streamlined_communication.constant import CommunicationPlatform


def update_pn_time_sent(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")
    template_codes_for_update_to_automated = (
        'MTL_T-5', 'MTL_T-4', 'MTL_T-3', 'MTL_T-2', 'MTL_T-1', 'MTL_T0', 'MTL_T1', 'MTL_T2', 'MTL_T3', 'MTL_T4',
        'MTL_T5', 'MTL_T30', 'MTL_T60', 'MTL_T90', 'MTL_T120', 'MTL_T150', 'MTL_T180', 'STL_T-5', 'STL_T-4', 'STL_T-3',
        'STL_T-2', 'STL_T-1', 'STL_T0', 'STL_T1', 'STL_T2', 'STL_T3', 'STL_T4', 'STL_T5', 'STL_T30', 'STL_T60',
        'STL_T90', 'STL_T120', 'STL_T150', 'STL_T180'
    )
    for template_code in template_codes_for_update_to_automated:
        StreamlinedCommunication.objects. \
            filter(communication_platform=CommunicationPlatform.PN,
                   template_code=template_code)\
            .update(product=template_code[:3].lower(), type='Payment Reminder', time_sent='9:30',
                    is_automated=True, heading_title='JULO Reminder'
                    )

    # create one template for handle PTP on PN
    inform_payment_due_soon_template_one_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Pelunasan akan jatuh tempo, harap transfer.",
        )
    ptp_streamlined = StreamlinedCommunication.objects.get_or_create(
        message=inform_payment_due_soon_template_one_payment,
        status='inform payment MTL for PTP -1',
        communication_platform=CommunicationPlatform.PN,
        template_code='MTL_PTP-1',
        ptp=-1,
        description='this PN called when ptp -1',
        product='mtl', type='Payment Reminder', time_sent='9:30',
        is_automated=True, heading_title='JULO Reminder'
    )


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0037_streamlinedcommunication_heading_title'),
    ]

    operations = [
        migrations.RunPython(update_pn_time_sent,
                             migrations.RunPython.noop)
    ]
