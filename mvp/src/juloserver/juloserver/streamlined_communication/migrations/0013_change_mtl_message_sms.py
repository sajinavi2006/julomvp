from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


def change_mtl_messages(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")

    sms_dpd_min7 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_dpd_-7',
            dpd=-7)
    sms_dpd_min7_msg = "Yth {{name}}, nikmati cashback {{payment_cashback_amount}} saat melunasi " \
                       "tagihan JULO Anda paling lambat {{due_date_in_4_days}}. Bayar sekarang: {{payment_details_url}}"
    sms_dpd_min7_param = "{name,payment_cashback_amount,due_date_in_4_days,payment_details_url}"
    StreamlinedMessage.objects.filter(id=sms_dpd_min7.message.id)\
                              .update(message_content=sms_dpd_min7_msg,
                                      parameter=sms_dpd_min7_param)

    wa_MTL_payment_reminder_min5 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_payment_reminder_replaced_wa',
            dpd=-5).last()
    wa_MTL_payment_reminder_min5_msg = "Yth {{first_name}}, angsuran ke-{{payment_number}} {{due_amount}} Anda jth " \
                                        "tempo pd {{due_date}}. Byr melalui {{bank_name}} VA:{{account_number}} " \
                                        "& dptkan cashback. {{payment_details_url}}"
    wa_MTL_payment_reminder_min5_param = "{first_name,payment_number,due_amount,due_date," \
                                         "bank_name,account_number,payment_details_url}"
    StreamlinedMessage.objects.filter(id=wa_MTL_payment_reminder_min5.message.id)\
                              .update(message_content=wa_MTL_payment_reminder_min5_msg,
                                      parameter=wa_MTL_payment_reminder_min5_param)

    wa_MTL_payment_reminder_min3 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_payment_reminder_replaced_wa',
            dpd=-3).last()
    wa_MTL_payment_reminder_min3_msg = "Yth {{first_name}}, angsuran ke-{{payment_number}} {{due_amount}} Anda jth " \
                                       "tempo pd {{due_date}}. Byr melalui {{bank_name}} VA:{{account_number}} " \
                                       "& dptkan cashback. {{payment_details_url}}"
    wa_MTL_payment_reminder_min3_param = "{first_name,payment_number,due_amount,due_date," \
                                         "bank_name,account_number,payment_details_url}"
    StreamlinedMessage.objects.filter(id=wa_MTL_payment_reminder_min3.message.id) \
                              .update(message_content=wa_MTL_payment_reminder_min3_msg,
                                      parameter=wa_MTL_payment_reminder_min3_param)

    streamlined_communication_for_sms_ptp_2_4 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_-2_4',
            dpd=-2)
    streamlined_communication_for_sms_ptp_2_4_msg = "Yth {{name}}, Kami ingtkn mgenai janji byr yg " \
                                                    "akn Anda lakukan pd {{due_date}} sjmlh {{due_amount}}. " \
                                                    "Mohon bayar sesuai janji. Bayar sekarang: {{url}}"
    streamlined_communication_for_sms_ptp_2_4_param = "{name,due_date,due_amount,url}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_sms_ptp_2_4.message.id) \
                              .update(message_content=streamlined_communication_for_sms_ptp_2_4_msg,
                                      parameter=streamlined_communication_for_sms_ptp_2_4_param)
    rudolf_friska_t2_mtl = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='rudolf_t2_mtl',
            dpd=-2)
    rudolf_friska_t2_mtl_msg = "{{name}}, sy Ani dr JULO. Dapatkan cashback " \
                                "{{cashback_multiplier}} x {{payment_cashback_amount}} " \
                                "dgn segera membayar cicilan Anda {{due_amount}} hari ini. Bayar sekarang: {{url}}"

    rudolf_friska_t2_mtl_param = "{name,cashback_multiplier,payment_cashback_amount,due_amount,url}"
    StreamlinedMessage.objects.filter(id=rudolf_friska_t2_mtl.message.id) \
                              .update(message_content=rudolf_friska_t2_mtl_msg,
                                      parameter=rudolf_friska_t2_mtl_param)

    streamlined_communication_for_sms_ptp_0 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_0',
            dpd=0)
    streamlined_communication_for_sms_ptp_0_msg = "Yth {{name}}, Anda tlh melakukan janji bayar hr ini. " \
                                                  "Sgr bayar {{due_amount}} ke {{bank_name}} no VA: " \
                                                  "{{account_number}}. Bayar sekarang: julo.co.id/r/sms"
    streamlined_communication_for_sms_ptp_0_param = "{name,due_amount,bank_name,account_number}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_sms_ptp_0.message.id) \
                              .update(message_content=streamlined_communication_for_sms_ptp_0_msg,
                                      parameter=streamlined_communication_for_sms_ptp_0_param)

    friska_rudolf_t0_mtl = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='friska_t0_mtl',
            dpd=0)
    friska_rudolf_t0_mtl_msg = "{{name}}, sy Ani dr JULO. Angsuran {{payment_number}} " \
                               "Anda {{due_amount}} tlh jatuh tempo. Byr skrg utk ksmptn cashback " \
                               "terakhir {{payment_cashback_amount}}. Bayar sekarang: julo.co.id/r/sms"
    friska_rudolf_t0_mtl_param = "{name,payment_number,due_amount,payment_cashback_amount}"
    StreamlinedMessage.objects.filter(id=friska_rudolf_t0_mtl.message.id) \
                              .update(message_content=friska_rudolf_t0_mtl_msg,
                                      parameter=friska_rudolf_t0_mtl_param)

    sms_ptp_t1 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+1_3',
            dpd=1)
    sms_ptp_t1_msg = "Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}" \
                     " sejumlah {{due_amount}}. Harap segera lakukan pembayaran." \
                     " Bayar sekarang: julo.co.id/r/sms"
    sms_ptp_t1_param = "{name,due_date,due_amount}"
    StreamlinedMessage.objects.filter(id=sms_ptp_t1.message.id) \
                              .update(message_content=sms_ptp_t1_msg,
                                      parameter=sms_ptp_t1_param)

    sms_dpd_plus1 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_dpd_+1',
            dpd=1)
    sms_dpd_plus1_msg = "{{name}}, pembayaran angsuran JULO {{payment_number}} Anda {{due_amount}} sdh "\
                        "TERLAMBAT. Sgr byr melalui {{bank_name}} no VA: {{account_number}}. "\
                        "Bayar sekarang: julo.co.id/r/sms"
    sms_dpd_plus1_param = "{name,payment_number,due_amount,bank_name,account_number}"
    StreamlinedMessage.objects.filter(id=sms_dpd_plus1.message.id) \
                              .update(message_content=sms_dpd_plus1_msg,
                                      parameter=sms_dpd_plus1_param)

    sms_dpd_plus3 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_dpd_+3',
            dpd=3)
    sms_dpd_plus3_msg = "{{name}}. 99% pelanggan kami telah membayar angsuran per hari ini. " \
                        "Bayar Angsuran {{payment_number}} Anda {{due_amount}} segera. " \
                        "Bayar sekarang: julo.co.id/r/sms"
    sms_dpd_plus3_param = "{name,payment_number,due_amount}"
    StreamlinedMessage.objects.filter(id=sms_dpd_plus3.message.id) \
                              .update(message_content=sms_dpd_plus3_msg,
                                      parameter=sms_dpd_plus3_param)

    sms_dpd_plus5 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_dpd_+5',
            dpd=5)
    sms_dpd_plus5_msg = "{{name}}. Angsuran JULO Anda sdh TERLAMBAT 5 hari. " \
                        "Jaga ksmptn meminjam kmbl Anda. Hubungi kami di collections@julo.co.id, " \
                        "Bayar sekarang: julo.co.id/r/sms"
    sms_dpd_plus5_param = "{name}"
    StreamlinedMessage.objects.filter(id=sms_dpd_plus5.message.id) \
        .update(message_content=sms_dpd_plus5_msg,
                parameter=sms_dpd_plus5_param)

    sms_dpd_plus7_msg = "{{name}} Angsuran Anda lwt jatuh tempo sgr lunasi agar terhindar dr daftar hitam fintech." \
                        " Hub: collections@julo.co.id. Bayar sekarang: julo.co.id/r/sms"
    sms_dpd_plus7_param = "{name}"
    streamline_msg_sms_dpd_plus7, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content=sms_dpd_plus7_msg,
            parameter=sms_dpd_plus7_param,
        )
    streamlined_communication = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_dpd_+7',
            dpd=7)
    streamlined_communication.message = streamline_msg_sms_dpd_plus7
    streamlined_communication.save()

    mtl_sms_dpd_plus21 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_dpd_+21',
            dpd=21)
    mtl_sms_dpd_plus21_msg = "{{name}}. Lunasi angsuran Anda dan jaga kesempatan " \
                             "Anda utk mengajukan pinjaman kembali. Hubungi " \
                             "collections@julo.co.id. Bayar sekarang: julo.co.id/r/sms"
    mtl_sms_dpd_plus21_param = "{name}"
    StreamlinedMessage.objects.filter(id=mtl_sms_dpd_plus21.message.id) \
                              .update(message_content=mtl_sms_dpd_plus21_msg,
                                      parameter=mtl_sms_dpd_plus21_param)

    sms_ptp_plus21_msg = "{{name}}. Lunasi angsuran Anda dan jaga kesempatan Anda" \
                         " utk mengajukan pinjaman kembali. Hubungi collections@julo.co.id." \
                         " Bayar sekarang: julo.co.id/r/sms"
    sms_ptp_plus21_param = "{name}"
    streamline_msg_sms_ptp_plus21, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content=sms_ptp_plus21_msg,
            parameter=sms_ptp_plus21_param,
        )
    streamlined_communication = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+5',
            dpd=21)
    streamlined_communication.message = streamline_msg_sms_ptp_plus21
    streamlined_communication.save()

    sms_ptp_plus7_msg = "{{name}} Angsuran Anda lwt jatuh tempo sgr lunasi agar" \
                        " terhindar dr daftar hitam fintech. Hub: collections@julo.co.id." \
                        " Bayar sekarang: julo.co.id/r/sms"
    sms_ptp_plus7_param = "{name}"
    streamline_msg_sms_ptp_plus7, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content=sms_ptp_plus7_msg,
            parameter=sms_ptp_plus7_param,
        )
    streamlined_communication = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+5',
            dpd=7)
    streamlined_communication.message = streamline_msg_sms_ptp_plus7
    streamlined_communication.save()

    sms_ptp_plus5_msg = "{{name}}. Angsuran JULO Anda sdh TERLAMBAT 5 hari." \
                        " Jaga ksmptn meminjam kmbl Anda. Hubungi kami di collections@julo.co.id," \
                        " Bayar sekarang: julo.co.id/r/sms"
    sms_ptp_plus5_param = "{name}"
    streamline_msg_sms_ptp_plus5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content=sms_ptp_plus5_msg,
            parameter=sms_ptp_plus5_param,
        )
    streamlined_communication = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+5',
            dpd=5)
    streamlined_communication.message = streamline_msg_sms_ptp_plus5
    streamlined_communication.save()


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0012_add_streamlined_sms_va_for_bl'),
    ]

    operations = [
        migrations.RunPython(change_mtl_messages,
                             migrations.RunPython.noop)
    ]
