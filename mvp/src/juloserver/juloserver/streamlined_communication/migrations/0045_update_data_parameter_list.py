from __future__ import unicode_literals
from django.db import migrations

from juloserver.streamlined_communication.constant import CommunicationPlatform


def update_comms_data_parameters(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication",
                                              "StreamlinedCommunication")
    StreamlinedCommunicationParameterList = apps.get_model("streamlined_communication",
                                                           "StreamlinedCommunicationParameterList")
    streamlined_communication_1 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_-2_4',
               ptp=-2).last()
    if streamlined_communication_1:
        msg1 = "Yth {{first_name_with_title_sms}}, Kami ingtkn kmbli mgenai " \
               "jnji pbayarn yg akn Anda " \
               "lakukan pd {{due_date}} sjmlh {{due_amount}}. Harap bayar ssuai janji " \
               "yg dibuat. Trma kasih. Info: {{url}}"
        param1 = "{due_amount,first_name_with_title_sms,due_date}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_1.message.id) \
            .update(message_content=msg1,
                    parameter=param1)
    streamlined_communication_2 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='mtl_sms_dpd_-2',
               dpd=-2).last()
    if streamlined_communication_2:
        msg2 = "{{first_name_with_title_sms}}, sy Ani dr JULO. Dapatkan " \
               "cashback {{cashback_multiplier}} x " \
               "Rp {{payment_cashback_amount}} dgn membayar cicilan Anda " \
               "{{due_amount}} skrg. Bayar: {{payment_details_url}}"
        param2 = "{first_name_with_title_sms,payment_details_url," \
                 "due_amount,payment_cashback_amount,cashback_multiplier}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_2.message.id) \
            .update(message_content=msg2,
                    parameter=param2)

    streamlined_communication_3 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='stl_sms_dpd_-2',
               dpd=-2).last()
    if streamlined_communication_3:
        msg3 = "{{first_name_with_title_sms}}, sy Ani dr JULO. Pinjaman Anda Rp {{due_amount}} " \
               "jatuh tempo pada {{due_date}}. Bayar sekarang agar tidak jadi " \
               "beban: {{payment_details_url}}"
        param3 = "{first_name_with_title_sms,payment_details_url," \
                 "due_amount,due_date}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_3.message.id) \
            .update(message_content=msg3,
                    parameter=param3)

    streamlined_communication_4 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_-2',
               dpd=-2).last()
    if streamlined_communication_4:
        msg4 = "{{first_name_with_title_sms}}, sy Ani dr JULO. Angsuran PEDE Pinter " \
               "{{payment_number}} Anda {{due_amount}} jatuh tempo " \
               "{{due_date}}. Bayar: www.pede.id/dive?moveTo=pinter"
        param4 = "{first_name_with_title_sms,payment_number," \
                 "due_amount,due_date}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_4.message.id) \
            .update(message_content=msg4,
                    parameter=param4)

    streamlined_communication_5 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedestl_sms_dpd_-2',
               dpd=-2).last()
    if streamlined_communication_5:
        msg5 = "{{first_name_with_title_sms}}, sy Ani dr JULO. Pinjaman PEDE Pinter Anda " \
               "{{due_amount}} jatuh tempo {{due_date}}. " \
               "Bayar: www.pede.id/dive?moveTo=pinter"
        param5 = "{first_name_with_title_sms,due_amount," \
                 "due_date}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_5.message.id) \
            .update(message_content=msg5,
                    parameter=param5)

    streamlined_communication_6 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_-2',
               dpd=-2).last()
    if streamlined_communication_6:
        msg6 = "{{first_name_with_title_sms}}, sy Ani dr JULO. Angsuran Prio Rental " \
               "{{payment_number}} Anda Rp.{{due_amount}} jatuh " \
               "tempo {{due_date}}. Info: {{payment_details_url}}."
        param6 = "{first_name_with_title_sms,payment_number," \
                 "due_amount,due_date,payment_details_url}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_6.message.id) \
            .update(message_content=msg6,
                    parameter=param6)

    streamlined_communication_7 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='mtl_sms_dpd_-7',
               dpd=-7).last()
    if streamlined_communication_7:
        msg7 = "Yth {{first_name_with_title_sms}}, nikmati cashback {{payment_cashback_amount}} " \
               "saat melunasi tagihan JULO Anda paling lambat {{due_date_minus_4}}. " \
               "Bayar sekarang: {{payment_details_url}}"
        param7 = "{first_name_with_title_sms,payment_cashback_amount," \
                 "due_date_minus_4,payment_details_url}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_7.message.id) \
            .update(message_content=msg7,
                    parameter=param7)

    streamlined_communication_8 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_0',
               ptp=0).last()
    if streamlined_communication_8:
        msg8 = "Yth {{first_name_with_title_sms}}, Anda tlh melakukan janji bayar hr ini. " \
               "Sgr byr {{due_amount}} ke {{bank_name}} no " \
               "VA: {{account_number}}. Byr skrg: julo.co.id/r/sms"
        param8 = "{first_name_with_title_sms,due_amount," \
                 "bank_name,account_number}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_8.message.id) \
            .update(message_content=msg8,
                    parameter=param8)

    streamlined_communication_9 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='mtl_sms_dpd_0',
               dpd=0).last()
    if streamlined_communication_9:
        msg9 = "{{first_name_with_title_sms}}, sy Ani dr JULO. Angsuran " \
               "{{payment_number}} {{due_amount}} tlh jatuh " \
               "tempo. Ksmptn terakhir, bayar & raih cashback " \
               "{{payment_cashback_amount}}: julo.co.id/r/sms"
        param9 = "{first_name_with_title_sms,payment_number," \
                 "due_amount,payment_cashback_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_9.message.id) \
            .update(message_content=msg9,
                    parameter=param9)

    streamlined_communication_10 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_0',
               dpd=0).last()
    if streamlined_communication_10:
        msg10 = "{{first_name_with_title_sms}}, sy Ani dr JULO. Angsuran " \
                "{{payment_number}} PEDE Pinter {{due_amount}} " \
                "jatuh tempo hari ini. Bayar: www.pede.id/dive?moveTo=pinter"
        param10 = "{first_name_with_title_sms,payment_number," \
                  "due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_10.message.id) \
            .update(message_content=msg10,
                    parameter=param10)

    streamlined_communication_11 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedestl_sms_dpd_0',
               dpd=0).last()
    if streamlined_communication_11:
        msg11 = "{{first_name_with_title_sms}}, sy Ani dr JULO. " \
                "Pinjaman PEDE Pinter Anda {{due_amount}} jatuh " \
                "tempo hari ini. Bayar: www.pede.id/dive?moveTo=pinter"
        param11 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_11.message.id) \
            .update(message_content=msg11,
                    parameter=param11)

    streamlined_communication_12 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_0',
               dpd=0).last()
    if streamlined_communication_12:
        msg12 = "{{first_name_with_title_sms}}, sy Ani dr JULO. Angsuran {{payment_number}} " \
                "Prio Rental {{due_amount}} jatuh tempo hari ini. " \
                "Cara bayar: {{how_pay_url}} dan cek aplikasi Prio Rental anda."
        param12 = "{first_name_with_title_sms,payment_number," \
                  "due_amount,how_pay_url}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_12.message.id) \
            .update(message_content=msg12,
                    parameter=param12)

    streamlined_communication_13 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='mtl_sms_dpd_+1',
               dpd=1).last()
    if streamlined_communication_13:
        msg13 = "{{first_name_with_title_sms}}, pembayaran angsuran JULO {{payment_number}} " \
                "Anda {{due_amount}} terlambat. Sgr byr lwt " \
                "{{bank_name}} no VA: {{account_number}}. Byr skrg: julo.co.id/r/sms"
        param13 = "{first_name_with_title_sms,payment_number," \
                  "due_amount,bank_name,account_number}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_13.message.id) \
            .update(message_content=msg13,
                    parameter=param13)

    streamlined_communication_14 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='stl_sms_dpd_+1',
               dpd=1).last()
    if streamlined_communication_14:
        msg14 = "{{first_name_with_title_sms}}, pembayaran pinjaman " \
                "Anda {{due_amount}} terlambat. Sgr byr " \
                "lwt {{bank_name}} VA: {{account_number}}. " \
                "Byr skrg: julo.co.id/r/sms"
        param14 = "{first_name_with_title_sms,due_amount," \
                  "bank_name,account_number}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_14.message.id) \
            .update(message_content=msg14,
                    parameter=param14)

    streamlined_communication_15 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_+1',
               dpd=1).last()
    if streamlined_communication_15:
        msg15 = "{{first_name_with_title_sms}}, kami ingatkan angsuran " \
                "PEDE Pinter {{payment_number}} Anda {{due_amount}} " \
                "sdh terlambat. Mohon segera bayar: www.pede.id/dive?moveTo=pinter"
        param15 = "{first_name_with_title_sms,payment_number," \
                  "due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_15.message.id) \
            .update(message_content=msg15,
                    parameter=param15)

    streamlined_communication_16 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedestl_sms_dpd_+1',
               dpd=1).last()
    if streamlined_communication_16:
        msg16 = "{{first_name_with_title_sms}}, kami ingatkan Pinjaman " \
                "PEDE Pinter Anda {{due_amount}} sdh terlambat. " \
                "Bayar: www.pede.id/dive?moveTo=pinter"
        param16 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_16.message.id) \
            .update(message_content=msg16,
                    parameter=param16)

    streamlined_communication_17 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_+1',
               dpd=1).last()
    if streamlined_communication_17:
        msg17 = "{{first_name_with_title_sms}}, kami ingatkan angsuran JULO {{payment_number}} " \
                "Anda {{due_amount}} sdh terlambat. Mohon segera " \
                "bayar: cek aplikasi Prio Rental. Abaikan jika sudah bayar."
        param17 = "{first_name_with_title_sms,payment_number,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_17.message.id) \
            .update(message_content=msg17,
                    parameter=param17)

    streamlined_communication_18 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='mtl_sms_dpd_+3',
               dpd=3).last()
    if streamlined_communication_18:
        msg18 = "{{first_name_with_title_sms}}. 99% pelanggan kami telah membayar " \
                "angsuran per hari ini. Bayar Angsuran {{payment_number}} " \
                "Anda {{due_amount}} segera. Bayar sekarang: julo.co.id/r/sms"
        param18 = "{first_name_with_title_sms,payment_number,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_18.message.id) \
            .update(message_content=msg18,
                    parameter=param18)
    streamlined_communication_20 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='stl_sms_dpd_+3',
               dpd=3).last()
    if streamlined_communication_20:
        msg20 = "{{first_name_with_title_sms}}. 99% pelanggan kami " \
                "telah membayar angsuran per hari ini. " \
                "Bayar Pinjaman Anda {{due_amount}} segera. Bayar sekarang: julo.co.id/r/sms"
        param20 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_20.message.id) \
            .update(message_content=msg20,
                    parameter=param20)

    streamlined_communication_21 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_+3',
               dpd=3).last()
    if streamlined_communication_21:
        msg21 = "{{first_name_with_title_sms}}. 99% pelanggan kami tlh membayar angsuran hari " \
                "ini. Bayar Angsuran {{payment_number}} Anda " \
                "{{due_amount}} segera. Bayar: www.pede.id/dive?moveTo=pinter"
        param21 = "{first_name_with_title_sms,payment_number,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_21.message.id) \
            .update(message_content=msg21,
                    parameter=param21)

    streamlined_communication_22 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedestl_sms_dpd_+3',
               dpd=3).last()
    if streamlined_communication_22:
        msg22 = "{{first_name_with_title_sms}}, Kami blm terima janji bayar Anda pd " \
                "{{ due_date }} sjmlh  {{due_amount}}. " \
                "Harap segera lakukan pembayaran. Bayar: www.pede.id/dive?moveTo=pinter"
        param22 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_22.message.id) \
            .update(message_content=msg22,
                    parameter=param22)

    streamlined_communication_23 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_+3',
               dpd=3).last()
    if streamlined_communication_23:
        msg23 = "{{first_name_with_title_sms}}. 99% pelanggan kami " \
                "sdh melakukan pembayaran angsuran per hari ini. " \
                "Tanggung jawab di hal kecil akan membawa kepercayaan " \
                "untuk hal besar. Bayar Angsuran {{payment_number}} " \
                "Anda {{due_amount}} segera. Cara bayar, cek aplikasi Prio Rental."
        param23 = "{first_name_with_title_sms,payment_number,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_23.message.id) \
            .update(message_content=msg23,
                    parameter=param23)

    streamlined_communication_24 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_+5',
               ptp=5).last()
    if streamlined_communication_24:
        msg24 = "{{first_name_with_title_sms}}. Angsuran JULO Anda terlambat 5 hari. " \
                "Jaga ksmptn pinjam Anda. Hub: collections@julo.co.id, Bayar: julo.co.id/r/sms"
        param24 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_24.message.id) \
            .update(message_content=msg24,
                    parameter=param24)

    streamlined_communication_25 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_+5',
               ptp=7).last()
    if streamlined_communication_25:
        msg25 = "Yth {{first_name_with_title_sms}}, Kami blm trma " \
                "pmbayaran Anda smp saat ini. Segera bayar {{due_amount}} " \
                "sblm kami hub perusahaan & kerabat Anda. Trm ksh"
        param25 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_25.message.id) \
            .update(message_content=msg25,
                    parameter=param25)

    streamlined_communication_26 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_+5',
               ptp=10).last()
    if streamlined_communication_26:
        msg26 = "Yth {{first_name_with_title_sms}}, Kami blm trma " \
                "pmbayaran Anda smp saat ini. Segera bayar " \
                "{{due_amount}} sblm kami hub perusahaan & kerabat Anda. Trm ksh"
        param26 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_26.message.id) \
            .update(message_content=msg26,
                    parameter=param26)

    streamlined_communication_27 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_+5',
               ptp=21).last()
    if streamlined_communication_27:
        msg27 = "Yth {{first_name_with_title_sms}}, Kami blm trma pmbayaran " \
                "Anda smp saat ini. Segera bayar {{due_amount}} " \
                "sblm kami hub perusahaan & kerabat Anda. Trm ksh"
        param27 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_27.message.id) \
            .update(message_content=msg27,
                    parameter=param27)

    streamlined_communication_28 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='mtl_sms_dpd_+5',
               dpd=5).last()
    if streamlined_communication_28:
        msg28 = "{{first_name_with_title_sms}}. Angsuran JULO Anda terlambat 5 " \
                "hari. Jaga ksmptn pinjam Anda. Hub: collections@julo.co.id, " \
                "Bayar: julo.co.id/r/sms"
        param28 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_28.message.id) \
            .update(message_content=msg28,
                    parameter=param28)

    streamlined_communication_29 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='stl_sms_dpd_+5',
               dpd=5).last()
    if streamlined_communication_29:
        msg29 = "{{first_name_with_title_sms}}. Pembayaran pinjaman JULO Anda " \
                "sdh terlambat 5 hari. Jaga kesempatan meminjam " \
                "kembali Anda. Bayar sekarang: julo.co.id/r/sms"
        param29 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_29.message.id) \
            .update(message_content=msg29,
                    parameter=param29)

    streamlined_communication_30 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_+5',
               dpd=5).last()
    if streamlined_communication_30:
        msg30 = "{{first_name_with_title_sms}}. Angsuran JULO Anda sdh terlambat 5 " \
                "hari. Jaga ksmptn meminjam Anda. Hub: collections@julo.co.id, " \
                "Bayar: www.pede.id/dive?moveTo=pinter"
        param30 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_30.message.id) \
            .update(message_content=msg30,
                    parameter=param30)

    streamlined_communication_31 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedestl_sms_dpd_+5',
               dpd=5).last()
    if streamlined_communication_31:
        msg31 = "{{first_name_with_title_sms}}. Pembayaran pinjaman " \
                "JULO Anda sdh terlambat 5 hari. Jaga kesempatan meminjam " \
                "kembali Anda. Bayar: www.pede.id/dive?moveTo=pinter"
        param31 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_31.message.id) \
            .update(message_content=msg31,
                    parameter=param31)

    streamlined_communication_32 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_+5',
               dpd=5).last()
    if streamlined_communication_32:
        msg32 = "{{first_name_with_title_sms}}. Angsuran JULO anda sudah terlambat 5 " \
                "hari. Bantu kami untuk membantu Anda, hubungi kami " \
                "di collections@julo.co.id, Segera bayar angsuran {{payment_number}} " \
                "berikut denda sebesar {{due_amount}}. Cara bayar, cek aplikasi Prio Rental."
        param32 = "{first_name_with_title_sms,payment_number,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_32.message.id) \
            .update(message_content=msg32,
                    parameter=param32)

    streamlined_communication_33 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='mtl_sms_dpd_+7',
               dpd=7).last()
    if streamlined_communication_33:
        msg33 = "{{ first_name_with_title_sms }} Angsuran Anda lwt jatuh tempo " \
                "sgr lunasi agar terhindar dr daftar hitam fintech. " \
                "Hub: collections@julo.co.id. Bayar: julo.co.id/r/sms"
        param33 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_33.message.id) \
            .update(message_content=msg33,
                    parameter=param33)

    streamlined_communication_34 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='stl_sms_dpd_+7',
               dpd=7).last()
    if streamlined_communication_34:
        msg34 = "{{first_name_with_title_sms}}, menunda kewajiban pembayaran merupakan " \
                "suatu ketidakadilan, sgra bayar kewajiban Anda. " \
                "Bayar: julo.co.id/r/sms"
        param34 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_34.message.id) \
            .update(message_content=msg34,
                    parameter=param34)

    streamlined_communication_35 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_+7',
               dpd=7).last()
    if streamlined_communication_35:
        msg35 = "{{ first_name_with_title_sms }} Angsuran Anda lwt jth tempo " \
                "lunasi agr terhindar dr dftr hitam fintech. " \
                "Hub: collections@julo.co.id. Byr: www.pede.id/dive?moveTo=pinter"
        param35 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_35.message.id) \
            .update(message_content=msg35,
                    parameter=param35)

    streamlined_communication_36 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedestl_sms_dpd_+7',
               dpd=7).last()
    if streamlined_communication_36:
        msg36 = "{{first_name_with_title_sms}}, menunda kewajiban pembayaran " \
                "merupakan suatu ketidakadilan, sgra bayar kewajiban Anda. " \
                "Bayar: www.pede.id/dive?moveTo=pinter"
        param36 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_36.message.id) \
            .update(message_content=msg36,
                    parameter=param36)
    streamlined_communication_37 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_+7',
               dpd=7).last()
    if streamlined_communication_37:
        msg37 = "{{first_name_with_title_sms}} menunda pembayaran yang dilakukan " \
                "oleh orang mampu merupakan suatu ketidakadilan, " \
                "segera bayar kewajiban Anda, cek aplikasi Prio Rental."
        param37 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_37.message.id) \
            .update(message_content=msg37,
                    parameter=param37)
    streamlined_communication_38 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedestl_sms_dpd_+10',
               dpd=10).last()
    if streamlined_communication_38:
        msg38 = "{{first_name_with_title_sms}}. Lunasi pmbyrn pinjaman " \
                "Anda, jg ksmptn utk mengajukan pinjaman kmbl. " \
                "Hub: collections@julo.co.id. Byr: www.pede.id/dive?moveTo=pinter"
        param38 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_38.message.id) \
            .update(message_content=msg38,
                    parameter=param38)

    streamlined_communication_39 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='stl_sms_dpd_+10',
               dpd=10).last()
    if streamlined_communication_39:
        msg39 = "{{first_name_with_title_sms}}. Lunasi pmbyrn pinjaman " \
                "Anda, jg ksmptn utk mengajukan pinjaman kmbli. " \
                "Hub: collections@julo.co.id. Bayar:: julo.co.id/r/sms"
        param39 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_39.message.id) \
            .update(message_content=msg39,
                    parameter=param39)
    streamlined_communication_40 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_+21',
               dpd=21).last()
    if streamlined_communication_40:
        msg40 = "{{first_name_with_title_sms}}. Angsuran Anda lwt jth tempo sgr lunasi " \
                "agr terhindar dr dftr hitam fintech. " \
                "Hub: collections@julo.co.id. Byr: www.pede.id/dive?moveTo=pinter"
        param40 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_40.message.id) \
            .update(message_content=msg40,
                    parameter=param40)

    streamlined_communication_41 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_+21',
               dpd=21).last()
    if streamlined_communication_41:
        msg41 = "{{first_name_with_title_sms}}. Lunasi tunggakan JULO Anda di aplikasi " \
                "Prio Rental dan jaga kesempatan Anda untuk mengajukan " \
                "pinjaman kembali. Hubungi collections@julo.co.id"
        param41 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_41.message.id) \
            .update(message_content=msg41,
                    parameter=param41)

    streamlined_communication_42 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='mtl_sms_dpd_+21',
               dpd=21).last()
    if streamlined_communication_42:
        msg42 = "{{ first_name_with_title_sms }}. Lunasi angsuran Anda dan jaga " \
                "kesempatan Anda utk mengajukan pinjaman kembali. " \
                "Hub collections@julo.co.id. Byr: julo.co.id/r/sms"
        param42 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_42.message.id) \
            .update(message_content=msg42,
                    parameter=param42)
    streamlined_communication_43 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_mtl_-2',
               ptp=-2).last()
    if streamlined_communication_43:
        msg43 = "{{first_name_with_title_sms}}, Mohon lakukan janji " \
                "bayar yang anda janjikan anda pada {{due_date}} " \
                "sjmlh Rp {{due_amount}}. Bayar: {{payment_details_url}}"
        param43 = "{first_name_with_title_sms,due_date,due_amount,payment_details_url}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_43.message.id) \
            .update(message_content=msg43,
                    parameter=param43)
    streamlined_communication_44 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_mtl_0',
               ptp=0).last()
    if streamlined_communication_44:
        msg44 = "Yth {{first_name_with_title_sms}}, Anda tlh " \
                "melakukan janji bayar hr ini. Sgr byr {{due_amount}} ke " \
                "{{bank_name}} no VA: {{account_number}}. Byr skrg: julo.co.id/r/sms"
        param44 = "{first_name_with_title_sms,due_amount,bank_name,account_number}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_44.message.id) \
            .update(message_content=msg44,
                    parameter=param44)
    streamlined_communication_45 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_mtl_+1',
               ptp=1).last()
    if streamlined_communication_45:
        msg45 = "{{first_name_with_title_sms}}, Kami blm terima janji byr Anda " \
                "pd {{due_date}} sejumlah {{due_amount}}. " \
                "Harap sgr lakukan pembayaran. Byr skrg: julo.co.id/r/sms"
        param45 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_45.message.id) \
            .update(message_content=msg45,
                    parameter=param45)

    streamlined_communication_46 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_mtl_+3',
               ptp=3).last()
    if streamlined_communication_46:
        msg46 = "{{first_name_with_title_sms}}, Kami blm terima janji bayar " \
                "Anda pd {{due_date}} sjmlh {{due_amount}}. " \
                "Harap segera lakukan pembayaran. Bayar: julo.co.id/r/sms"
        param46 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_46.message.id) \
            .update(message_content=msg46,
                    parameter=param46)

    streamlined_communication_47 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_mtl_+5',
               ptp=5).last()
    if streamlined_communication_47:
        msg47 = "{{first_name_with_title_sms}}. Angsuran JULO Anda sdh " \
                "terlambat 5 hari. Jaga ksmptn meminjam kmbl Anda. " \
                "Informasi: collections@julo.co.id, Bayar: julo.co.id/r/sms"
        param47 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_47.message.id) \
            .update(message_content=msg47,
                    parameter=param47)

    streamlined_communication_48 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_mtl_+7',
               ptp=7).last()
    if streamlined_communication_48:
        msg48 = "{{first_name_with_title_sms}}. Angsuran Anda lwt jth tempo sgr " \
                "lunasi agar terhindar dr daftar hitam fintech. " \
                "Hub: collections@julo.co.id. Byr: sekarang: julo.co.id/r/sms"
        param48 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_48.message.id) \
            .update(message_content=msg48,
                    parameter=param48)

    streamlined_communication_49 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_mtl_+21',
               ptp=21).last()
    if streamlined_communication_49:
        msg49 = "{{first_name_with_title_sms}}. Lunasi angsuran Anda dan jaga " \
                "ksmptn Anda utk mengajukan pinjaman kmbl. " \
                "Hub: collections@julo.co.id. Byr: julo.co.id/r/sms"
        param49 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_49.message.id) \
            .update(message_content=msg49,
                    parameter=param49)

    streamlined_communication_50 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_stl_0',
               ptp=0).last()
    if streamlined_communication_50:
        msg50 = "Yth {{first_name_with_title_sms}}, Anda tlh melakukan janji " \
                "bayar hr ini. Sgr bayar {{due_amount}} ke " \
                "{{bank_name}} no VA: {{account_number}}. Bayar sekarang: julo.co.id/r/sms"
        param50 = "{first_name_with_title_sms,due_amount,bank_name,account_number}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_50.message.id) \
            .update(message_content=msg50,
                    parameter=param50)
    streamlined_communication_51 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedemtl_0',
               ptp=0).last()
    if streamlined_communication_51:
        msg51 = "Yth {{first_name_with_title_sms}}, Anda tlh melakukan " \
                "janji byr hr ini. Sgr byr {{due_amount}} ke " \
                "{{bank_name}} no VA {{account_number}}. Byr: www.pede.id/dive?moveTo=pinter"
        param51 = "{first_name_with_title_sms,due_amount,bank_name,account_number}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_51.message.id) \
            .update(message_content=msg51,
                    parameter=param51)
    streamlined_communication_52 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedestl_0',
               ptp=0).last()
    if streamlined_communication_52:
        msg52 = "Yth {{first_name_with_title_sms}}, hr ini adalah " \
                "hari pembayaran PEDE Pinter yg Anda janjikan sebesar " \
                "{{due_amount}}. Bayar: www.pede.id/dive?moveTo=pinter"
        param52 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_52.message.id) \
            .update(message_content=msg52,
                    parameter=param52)

    streamlined_communication_53 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_laku6_0',
               ptp=0).last()
    if streamlined_communication_53:
        msg53 = "Yth {{first_name_with_title_sms}}, hr ini {{ due_date }} " \
                "adlh tgl pmbayaran yg Anda janjikan. " \
                "Segera bayar {{due_amount}} ke {{ bank_name }} no VA {{ account_number }}. Trm ksh"
        param53 = "{first_name_with_title_sms,due_date," \
                  "due_amount,bank_name,account_number}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_53.message.id) \
            .update(message_content=msg53,
                    parameter=param53)
    streamlined_communication_54 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='stl_sms_dpd_0',
               dpd=0).last()
    if streamlined_communication_54:
        msg54 = "{{first_name_with_title_sms}}, sy Ani dr JULO. " \
                "Pinjaman Anda Rp {{due_amount}} tlh jth tempo. " \
                "Sgr byr ke {{bank_name}} no VA {{account_number}}. " \
                "Byr skrg: {{how_pay_url}}"
        param54 = "{first_name_with_title_sms,due_amount,bank_name," \
                  "account_number,how_pay_url}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_54.message.id) \
            .update(message_content=msg54,
                    parameter=param54)
    streamlined_communication_55 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_stl_-2',
               ptp=-2).last()
    if streamlined_communication_55:
        msg55 = "{{first_name_with_title_sms}}, Kami ingatkan mengenai janji " \
                "byr yg akn Anda lakukan pd {{due_date}} " \
                "sejumlah {{due_amount}}. Bayar: {{payment_details_url}}"
        param55 = "{first_name_with_title_sms,due_date,due_amount,payment_details_url}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_55.message.id) \
            .update(message_content=msg55,
                    parameter=param55)

    streamlined_communication_56 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedestl_-2',
               ptp=-2).last()
    if streamlined_communication_56:
        msg56 = "Yth {{first_name_with_title_sms}}, Kami ingatkan mengenai " \
                "janji bayar yg akan Anda lakukan pd {{due_date}} " \
                "sejumlah {{due_amount}}. Bayar: www.pede.id/dive?moveTo=pinter"
        param56 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_56.message.id) \
            .update(message_content=msg56,
                    parameter=param56)

    streamlined_communication_57 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedemtl_-2',
               ptp=-2).last()
    if streamlined_communication_57:
        msg57 = "Yth {{first_name_with_title_sms}}, Kami ingatkan mengenai janji " \
                "bayar yg akan Anda lakukan pd {{due_date}} " \
                "sejumlah {{due_amount}}. Bayar: www.pede.id/dive?moveTo=pinter"
        param57 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_57.message.id) \
            .update(message_content=msg57,
                    parameter=param57)
    streamlined_communication_58 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_laku6_-2',
               ptp=-2).last()
    if streamlined_communication_58:
        msg58 = "Yth {{first_name_with_title_sms}}, Kami ingtkn kmbli mgenai jnji " \
                "pbayarn yg akn Anda lakukan pd {{ due_date }} sjmlh {{due_amount}}. " \
                "Harap bayar ssuai janji yg dibuat. Trma kasih. Info: {{url}}"
        param58 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_58.message.id) \
            .update(message_content=msg58,
                    parameter=param58)

    streamlined_communication_59 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_stl_+1',
               ptp=1).last()
    if streamlined_communication_59:
        msg59 = "Yth {{first_name_with_title_sms}}, pembayaran pinjaman Anda " \
                "{{due_amount}} terlambat. Sgr byr ke {{bank_name}} " \
                "VA: {{account_number}}. Byr skrg: julo.co.id/r/sms"
        param59 = "{first_name_with_title_sms,due_amount,bank_name,account_number}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_59.message.id) \
            .update(message_content=msg59,
                    parameter=param59)
    streamlined_communication_60 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedemtl_+1',
               ptp=1).last()
    if streamlined_communication_60:
        msg60 = "Yth {{first_name_with_title_sms}}, Kami blm terima janji byr " \
                "Anda pd {{ due_date }} sjmlh {{due_amount}}. " \
                "Harap lakukan pembayaran: www.pede.id/dive?moveTo=pinter"
        param60 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_60.message.id) \
            .update(message_content=msg60,
                    parameter=param60)
    streamlined_communication_61 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedestl_+1',
               ptp=1).last()
    if streamlined_communication_61:
        msg61 = "Yth {{first_name_with_title_sms}}, Kami blm terima janji " \
                "byr Anda pd {{ due_date }} sjmlh {{due_amount}}. " \
                "Harap lakukan pembayaran: www.pede.id/dive?moveTo=pinter"
        param61 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_61.message.id) \
            .update(message_content=msg61,
                    parameter=param61)
    streamlined_communication_62 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_laku6_+1',
               ptp=1).last()
    if streamlined_communication_62:
        msg62 = "Yth {{first_name_with_title_sms}}, Kami blm trma " \
                "pmbayaran yg Anda janjikan {{ due_date }} Sjmlh {{due_amount}}. " \
                "Harap segera lakukan pbayaran. Trm ksh"
        param62 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_62.message.id) \
            .update(message_content=msg62,
                    parameter=param62)
    streamlined_communication_63 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_stl_+3',
               ptp=3).last()
    if streamlined_communication_63:
        msg63 = "{{first_name_with_title_sms}}, Kami blm terima janji bayar Anda pd " \
                "{{due_date}} sjmlh {{due_amount}}. Harap segera " \
                "lakukan pembayaran. Bayar: julo.co.id/r/sms"
        param63 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_63.message.id) \
            .update(message_content=msg63,
                    parameter=param63)

    streamlined_communication_64 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedemtl_+3',
               ptp=3).last()
    if streamlined_communication_64:
        msg64 = "{{first_name_with_title_sms}}, Kami blm terima " \
                "janji bayar Anda pd {{due_date}} Sjmlh {{due_amount}}. " \
                "Harap segera lakukan pembayaran. Bayar: www.pede.id/dive?moveTo=pinter"
        param64 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_64.message.id) \
            .update(message_content=msg64,
                    parameter=param64)

    streamlined_communication_65 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedestl_+3',
               ptp=3).last()
    if streamlined_communication_65:
        msg65 = "{{first_name_with_title_sms}}, Kami blm terima janji bayar Anda " \
                "pd {{due_date}} sjmlh {{due_amount}}. Harap segera " \
                "lakukan pembayaran. Bayar: www.pede.id/dive?moveTo=pinter"
        param65 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_65.message.id) \
            .update(message_content=msg65,
                    parameter=param65)
    streamlined_communication_66 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_laku6_+3',
               ptp=3).last()
    if streamlined_communication_66:
        msg66 = "Yth {{first_name_with_title_sms}}, Kami blm trma pmbayaran yg " \
                "Anda janjikan {{ due_date }} Sjmlh {{due_amount}}. " \
                "Harap segera lakukan pbayaran. Trm ksh"
        param66 = "{first_name_with_title_sms,due_date,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_66.message.id) \
            .update(message_content=msg66,
                    parameter=param66)
    streamlined_communication_67 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_stl_+5',
               ptp=5).last()
    if streamlined_communication_67:
        msg67 = "{{first_name_with_title_sms}}. Angsuran JULO Anda sdh terlambat 5 " \
                "hari. Jaga ksmptn meminjam kmbl Anda. " \
                "Informasi: collections@julo.co.id, Bayar: julo.co.id/r/sms"
        param67 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_67.message.id) \
            .update(message_content=msg67,
                    parameter=param67)
    streamlined_communication_68 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedemtl_+5',
               ptp=5).last()
    if streamlined_communication_68:
        msg68 = "{{first_name_with_title_sms}}. Angsuran JULO Anda sdh " \
                "terlambat 5 hari. Jaga ksmptn meminjam Anda. " \
                "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter"
        param68 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_68.message.id) \
            .update(message_content=msg68,
                    parameter=param68)
    streamlined_communication_69 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedestl_+5',
               ptp=5).last()
    if streamlined_communication_69:
        msg69 = "{{first_name_with_title_sms}}. Angsuran JULO Anda sdh terlambat 5 hari. " \
                "Jaga ksmptn meminjam Anda. Hub: collections@julo.co.id, " \
                "Bayar: www.pede.id/dive?moveTo=pinter"
        param69 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_69.message.id) \
            .update(message_content=msg69,
                    parameter=param69)
    streamlined_communication_70 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_laku6_+5',
               ptp=5).last()
    if streamlined_communication_70:
        msg70 = "Yth {{ first_name_with_title_sms }}, Kami blm trma pmbayaran Anda" \
                "smp saat ini. Segera bayar {{due_amount}} " \
                "sblm kami hub perusahaan & kerabat Anda. Trm ksh"
        param70 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_70.message.id) \
            .update(message_content=msg70,
                    parameter=param70)
    streamlined_communication_71 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_stl_+7',
               ptp=7).last()
    if streamlined_communication_71:
        msg71 = "{{first_name_with_title_sms}}. Angsuran Anda " \
                "lwt jth tempo sgr lunasi agar terhindar dr daftar " \
                "hitam fintech. Hub: collections@julo.co.id. Byr: julo.co.id/r/sms"
        param71 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_71.message.id) \
            .update(message_content=msg71,
                    parameter=param71)
    streamlined_communication_72 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedemtl_+7',
               ptp=7).last()
    if streamlined_communication_72:
        msg72 = "{{first_name_with_title_sms}}. Angsuran Anda lwt jth tempo " \
                "lunasi agr terhindr dr dftr hitam fintech. " \
                "Hub: collections@julo.co.id. Byr: www.pede.id/dive?moveTo=pinter"
        param72 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_72.message.id) \
            .update(message_content=msg72,
                    parameter=param72)

    streamlined_communication_73 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedestl_+7',
               ptp=7).last()
    if streamlined_communication_73:
        msg73 = "{{first_name_with_title_sms}}. Pnjman Anda lwt jatuh " \
                "tempo lunasi agr terhindr dr dftr hitam fintech. " \
                "Hub: collections@julo.co.id. Byr: www.pede.id/dive?moveTo=pinter"
        param73 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_73.message.id) \
            .update(message_content=msg73,
                    parameter=param73)
    streamlined_communication_74 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_laku6_+7',
               ptp=7).last()
    if streamlined_communication_74:
        msg74 = "Yth {{ first_name_with_title_sms }}, Kami blm " \
                "trma pmbayaran Anda smp saat ini. Segera bayar " \
                "{{due_amount}} sblm kami hub perusahaan & kerabat Anda. Trm ksh"
        param74 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_74.message.id) \
            .update(message_content=msg74,
                    parameter=param74)
    streamlined_communication_75 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_pedemtl_+21',
               ptp=21).last()
    if streamlined_communication_75:
        msg75 = "{{first_name_with_title_sms}}. Lunasi angsuran Anda, " \
                "jg ksmptn utk mengajukan pnjmn di app PEDE. " \
                "Hub: collections@julo.co.id. Byr: www.pede.id/dive?moveTo=pinter"
        param75 = "{first_name_with_title_sms}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_75.message.id) \
            .update(message_content=msg75,
                    parameter=param75)
    streamlined_communication_76 = StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_ptp_laku6_+21',
               ptp=21).last()
    if streamlined_communication_76:
        msg76 = "Yth {{ first_name_with_title_sms }}, Kami blm trma " \
                "pmbayaran Anda smp saat ini. Segera bayar " \
                "{{due_amount}} sblm kami hub perusahaan & kerabat Anda. Trm ksh"
        param76 = "{first_name_with_title_sms,due_amount}"
        StreamlinedMessage.objects.filter(id=streamlined_communication_76.message.id) \
            .update(message_content=msg76,
                    parameter=param76)
    StreamlinedCommunicationParameterList.objects. \
        filter(platform=CommunicationPlatform.SMS,
               parameter_name="{{name}}") \
        .update(parameter_name="{{first_name_with_title_sms}}")


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0044_streamlinedcommunication_exclude_risky_customer'),
    ]

    operations = [
        migrations.RunPython(update_comms_data_parameters,
                             migrations.RunPython.noop)
    ]
