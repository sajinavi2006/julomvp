from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


def add_message_for_sms_for_wa(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")

    wa_MTL_payment_reminder_min5and3, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{first_name}}, angsuran ke-{{payment_number}} {{due_amount}} Anda jth "
                            "tempo pd {{due_date}}. Byr melalui {{bank_name}} VA:{{account_number}} "
                            "& dptkan cashback. julo.co.id/r/sms",
            parameter="{first_name,payment_number,due_amount,due_date,bank_name,account_number}",
        )
    for i in [-5, -3]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=wa_MTL_payment_reminder_min5and3,
            status="send reminder MTL for replace wa with sms dpd {}".format(i),
            communication_platform=CommunicationPlatform.SMS,
            template_code='sms_payment_reminder_replaced_wa',
            dpd=i,
            description="this streamlined comm for replacing WA with SMS dpd {} with MTL".format(i),
            criteria={"product_line": ProductLineCodes.mtl()}
        )

    wa_MTL_payment_reminder_min1, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{first_name}}, angsuran ke-{{payment_number}} {{due_amount}} sgr jatuh tempo. "
                            "Byr sblm {{due_date}} melalui {{bank_name}} VA:{{account_number}}."
                            " Info: julo.co.id/r/sms",
            parameter="{first_name,payment_number,due_amount,due_date,bank_name,account_number}",
        )
    streamlined_communication_min1 = StreamlinedCommunication.objects.get_or_create(
        message=wa_MTL_payment_reminder_min1,
        status="send reminder for replace wa with sms dpd -1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_payment_reminder_replaced_wa',
        dpd=-1,
        description="this streamlined comm for replacing WA with SMS dpd -1",
        criteria={"product_line": ProductLineCodes.mtl()}
    )
    wa_STL_payment_reminder_min5and3, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{first_name}}, angsuran Anda {{due_amount}} jatuh tempo pada {{due_date}}. "
                            "Byr melalui {{bank_name}} VA:{{account_number}}  julo.co.id/r/sms",
            parameter="{first_name,due_amount,due_date,bank_name,account_number}",
        )
    for i in [-5, -3]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=wa_MTL_payment_reminder_min5and3,
            status="send reminder STL for replace wa with sms dpd {}".format(i),
            communication_platform=CommunicationPlatform.SMS,
            template_code='sms_payment_reminder_replaced_wa',
            dpd=i,
            description="this streamlined comm for replacing WA with SMS dpd {} and STL Product".format(i),
            criteria={"product_line": ProductLineCodes.stl()}
        )



class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0006_mapping_ptp_message'),
    ]

    operations = [
        migrations.RunPython(add_message_for_sms_for_wa,
                             migrations.RunPython.noop)
    ]
