from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


def add_message_for_sms_replace_wa_bukalapak(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")

    bukalapak_sms_pre_due_date_25, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{firstname}} Tagihan BayarNanti kamu Rp {{due_amount}} akan jatuh tempo pd {{due_date}}. "
                            "Segera bayar tagihannya agar ttp bs pk BayarNanti- bl.id/BayarNanti",
            parameter="{firstname,due_amount,due_date}",
        )
    streamlined_communication = StreamlinedCommunication.objects.get_or_create(
        message=bukalapak_sms_pre_due_date_25,
        status="Send reminder Bukalapak for replace wa with sms in 25th pre due date",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_bukalapak_payment_reminder_25',
        status_code_id=PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
        description="this streamlined comm for replacing WA with SMS bukalapak in date 25th"
                    "called in send_all_sms_on_bukalapak"
    )

    bukalapak_sms_post_due_date_4, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{firstname}}. Tagihan BayarNanti kamu Rp {{due_amount}} telah jatuh tempo pd {{due_date}}. "
                            "Segera lakukan pembayaran agar tdk kena denda- bl.id/BayarNanti",
            parameter="{firstname,due_amount,due_date}",
        )
    statuses = [
        PaymentStatusCodes.PAYMENT_1DPD,
        PaymentStatusCodes.PAYMENT_5DPD,
        PaymentStatusCodes.PAYMENT_30DPD,
        PaymentStatusCodes.PAYMENT_60DPD,
        PaymentStatusCodes.PAYMENT_90DPD,
        PaymentStatusCodes.PAYMENT_120DPD,
        PaymentStatusCodes.PAYMENT_150DPD,
        PaymentStatusCodes.PAYMENT_180DPD
        ]
    for status_code in statuses:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=bukalapak_sms_post_due_date_4,
            status="Send reminder Bukalapak for replace wa with sms in 4th",
            communication_platform=CommunicationPlatform.SMS,
            template_code='sms_bukalapak_payment_reminder_4',
            status_code_id=status_code,
            description="this streamlined comm for replacing WA with SMS bukalapak in date 4th post due date"
                        "called in send_all_sms_on_bukalapak with status_code {}".format(status_code)
        )
    bukalapak_sms_post_due_date_20, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{firstname}} Tagihan BayarNanti tlh jth tempo pd {{due_date}} sbsr Rp{{due_amount}} &"
                            " akn trs brtambah. Yuk bayar spy tdk jd beban- bl.id/BayarNanti",
            parameter="{firstname,due_date,due_amount}",
        )
    for status_code in statuses:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=bukalapak_sms_post_due_date_20,
            status="Send reminder Bukalapak for replace wa with sms in 20th post due date",
            communication_platform=CommunicationPlatform.SMS,
            template_code='sms_bukalapak_payment_reminder_20',
            status_code_id=status_code,
            description="this streamlined comm for replacing WA with SMS bukalapak in date 20th"
                        "called in send_all_sms_on_bukalapak with status_code {}".format(status_code)
        )



class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0008_fix_bug_message_sms'),
    ]

    operations = [
        migrations.RunPython(add_message_for_sms_replace_wa_bukalapak,
                             migrations.RunPython.noop)
    ]
