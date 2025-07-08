from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


def fix_message_for_sms_dpd_21_and_1(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")
    sms_have_ptp_dpd_plus1, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{name}}, Kami blm trma pmbayaran yg Anda janjikan {{ due_date }} Sjmlh {{due_amount}}. Harap segera lakukan pbayaran. Trm ksh",
            parameter="{name,due_date,due_amount}",
        )

    for i in [1, 3]:
        streamlined_communication = StreamlinedCommunication.objects.get(dpd=i,
                                                                         communication_platform=CommunicationPlatform.SMS,
                                                                         template_code='sms_ptp_+1_3')
        streamlined_communication.message = sms_have_ptp_dpd_plus1
        streamlined_communication.save()

    # message exchanged
    streamlined_communication_for_laku6mtl_sms_dpd_plus21 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='laku6mtl_sms_dpd_+21',
            dpd=21)
    streamlined_communication_for_sms_dpd_plus21 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_dpd_+21',
            dpd=21, )
    message_for_sms_dpd_plus21 = streamlined_communication_for_laku6mtl_sms_dpd_plus21.message
    message_for_laku6mtl_sms_dpd_plus21 = streamlined_communication_for_sms_dpd_plus21.message
    streamlined_communication_for_laku6mtl_sms_dpd_plus21.message = message_for_laku6mtl_sms_dpd_plus21
    streamlined_communication_for_sms_dpd_plus21.message = message_for_sms_dpd_plus21
    streamlined_communication_for_laku6mtl_sms_dpd_plus21.save()
    streamlined_communication_for_sms_dpd_plus21.save()

class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0007_change_wa_to_sms'),
    ]

    operations = [
        migrations.RunPython(fix_message_for_sms_dpd_21_and_1,
                             migrations.RunPython.noop)
    ]
