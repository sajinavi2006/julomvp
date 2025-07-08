from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


def change_stl_messages(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_payment_reminder_replaced_wa',
               status='send reminder MTL for replace wa with sms dpd -3',
               dpd=-3).update(template_code='mtl_sms_dpd_-3')

    wa_MTL_payment_reminder_min3 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{first_name}}, angsuran ke-{{payment_number}} {{due_amount}} Anda jth " \
                            "tempo pd {{due_date}}. Byr melalui {{bank_name}} VA:{{account_number}} " \
                            "& dptkan cashback. {{url}}",
            parameter="{first_name,payment_number,due_amount,due_date," \
                      "bank_name,account_number,url}"
        )

    StreamlinedCommunication.objects.filter(communication_platform=CommunicationPlatform.SMS,
                                            template_code='mtl_sms_dpd_-3',
                                            dpd=-3) \
        .update(message=wa_MTL_payment_reminder_min3)

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_payment_reminder_replaced_wa',
               status='send reminder STL for replace wa with sms dpd -3',
               dpd=-3).update(template_code='stl_sms_dpd_-3')

    wa_STL_payment_reminder_min3 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{first_name}}, pinjaman Anda {{due_amount}} akan jatuh tempo pd " \
                            "{{due_date}}. Byr melalui {{bank_name}} VA:{{account_number}}. " \
                            "Bayar sekarang: {{url}}",
            parameter="{first_name,payment_number,due_amount,due_date," \
                      "bank_name,account_number,url}"
        )

    StreamlinedCommunication.objects.filter(communication_platform=CommunicationPlatform.SMS,
                                            template_code='stl_sms_dpd_-3',
                                            dpd=-3) \
        .update(message=wa_STL_payment_reminder_min3)

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_payment_reminder_replaced_wa',
               status='send reminder MTL for replace wa with sms dpd -5',
               dpd=-5).update(template_code='mtl_sms_dpd_-5')

    wa_MTL_payment_reminder_min5 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{first_name}}, angsuran ke-{{payment_number}} {{due_amount}} Anda jth " \
                            "tempo pd {{due_date}}. Byr melalui {{bank_name}} VA:{{account_number}} " \
                            "& dptkan cashback. {{url}}",
            parameter="{first_name,url}"
        )

    StreamlinedCommunication.objects.filter(communication_platform=CommunicationPlatform.SMS,
                                            template_code='mtl_sms_dpd_-5',
                                            dpd=-5) \
        .update(message=wa_MTL_payment_reminder_min5)

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_payment_reminder_replaced_wa',
               status='send reminder STL for replace wa with sms dpd -5',
               dpd=-5).update(template_code='stl_sms_dpd_-5')

    wa_STL_payment_reminder_min5 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{first_name}}, pinjaman Anda akan segera jatuh tempo, " \
                            "mohon segera lunasi agar tidak menjadi beban Anda. " \
                            "Bayar sekarang: {{url}}",
            parameter="{first_name,url}"
        )

    StreamlinedCommunication.objects.filter(communication_platform=CommunicationPlatform.SMS,
                                            template_code='stl_sms_dpd_-5',
                                            dpd=-5) \
        .update(message=wa_STL_payment_reminder_min5)


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0017_change_stl_plus1_message_sms'),
    ]

    operations = [
        migrations.RunPython(change_stl_messages,
                             migrations.RunPython.noop)
    ]
