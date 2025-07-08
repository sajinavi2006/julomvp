from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import StreamlinedCommunication



from juloserver.streamlined_communication.models import StreamlinedMessage



def change_stl_messages(apps, schema_editor):
    
    

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_dpd_-7',
               dpd=-7).update(template_code='mtl_sms_dpd_-7')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_dpd_+1',
               dpd=1).update(template_code='mtl_sms_dpd_+1')

    streamlined_communication_for_stl_sms_plus1 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='stl_sms_dpd_+1',
            dpd=1)

    sms_stl_plus1_msg = "{{name}}, pembayaran pinjaman Anda {{due_amount}} sudah TERLAMBAT. Segera bayar melalui " \
                        "{{bank_name}} VA: {{account_number}}. Bayar sekarang: julo.co.id/r/sms"
    sms_stl_plus1_param = "{name,due_amount,bank_name,account_number}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_stl_sms_plus1.message.id) \
        .update(message_content=sms_stl_plus1_msg,
                parameter=sms_stl_plus1_param)

    streamlined_communication_for_pedemtl_sms_plus1 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedemtl_sms_dpd_+1',
            dpd=1)

    sms_pedemtl_plus1_msg = "{{name}}, kami ingatkan angsuran PEDE Pinter {{payment_number}} " \
                            "Anda {{due_amount}} sdh TERLAMBAT. Mohon segera bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedemtl_plus1_param = "{name,due_amount,payment_number}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedemtl_sms_plus1.message.id) \
        .update(message_content=sms_pedemtl_plus1_msg,
                parameter=sms_pedemtl_plus1_param)

    streamlined_communication_for_pedestl_sms_plus1 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedestl_sms_dpd_+1',
            dpd=1)

    sms_pedestl_plus1_msg = "{{name}}, kami ingatkan Pinjaman PEDE Pinter Anda {{due_amount}} " \
                            "sdh TERLAMBAT. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedestl_plus1_param = "{name,due_amount}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedestl_sms_plus1.message.id) \
        .update(message_content=sms_pedestl_plus1_msg,
                parameter=sms_pedestl_plus1_param)

    sms_have_ptp_dpd_plus1_stl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}"
                            " sejumlah {{due_amount}}. Harap segera lakukan pembayaran."
                            " Bayar sekarang: julo.co.id/r/sms",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus1_stl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus1_stl,
        status="Inform customer have STL PTP date product dpd + 1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_stl_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )

    sms_have_ptp_dpd_plus1_pedemtl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}"
                            " sjmlh {{due_amount}}. Harap sgra lakukan pembayaran."
                            " Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus1_pedemtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus1_pedemtl,
        status="Inform customer have Pede MTL PTP date product dpd + 1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedemtl_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )

    sms_have_ptp_dpd_plus1_pedestl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}"
                            " sjmlh {{due_amount}}. Harap segera lakukan pembayaran."
                            " Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus1_pedestl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus1_pedestl,
        status="Inform customer have Pede STL PTP date product dpd + 1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedestl_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )

    sms_have_ptp_dpd_plus1_laku6 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm trma pmbayaran yg Anda janjikan " \
                            "{{ due_date }} Sjmlh {{due_amount}}. Harap segera lakukan pbayaran. Trm ksh",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus1_pedestl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus1_laku6,
        status="Inform customer have LAKU6 PTP date product dpd + 1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_laku6_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_dpd_+3',
               dpd=3).update(template_code='mtl_sms_dpd_+3')

    streamlined_communication_for_stl_sms_plus3 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='stl_sms_dpd_+3',
            dpd=3)

    sms_stl_plus3_msg = "{{name}}. 99% pelanggan kami telah membayar angsuran per hari ini. " \
                        "Bayar Pinjaman Anda {{due_amount}} segera. Bayar sekarang: " \
                        "julo.co.id/r/sms"
    sms_stl_plus3_param = "{name,due_amount}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_stl_sms_plus3.message.id) \
        .update(message_content=sms_stl_plus3_msg,
                parameter=sms_stl_plus3_param)

    streamlined_communication_for_pedemtl_sms_plus3 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedemtl_sms_dpd_+3',
            dpd=3)

    sms_pedemtl_plus3_msg = "{{name}}. 99% pelanggan kami telah membayar angsuran per hari ini. " \
                            "Bayar Angsuran {{payment_number}} Anda {{due_amount}} segera. " \
                            "Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedemtl_plus3_param = "{name,due_amount,payment_number}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedemtl_sms_plus3.message.id) \
        .update(message_content=sms_pedemtl_plus3_msg,
                parameter=sms_pedemtl_plus3_param)

    streamlined_communication_for_pedestl_sms_plus3 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedestl_sms_dpd_+3',
            dpd=3)

    sms_pedestl_plus3_msg = "Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }} " \
                            "sjmlh {{due_amount}}. " \
                            "Harap segera lakukan pembayaran. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedestl_plus3_param = "{name,due_date,due_amount}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedestl_sms_plus3.message.id) \
        .update(message_content=sms_pedestl_plus3_msg,
                parameter=sms_pedestl_plus3_param)

    sms_have_ptp_dpd_plus3_stl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}"
                            " sejumlah {{due_amount}}. Harap segera lakukan pembayaran."
                            " Bayar sekarang: julo.co.id/r/sms",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus3_stl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus3_stl,
        status="Inform customer have STL PTP date product dpd + 3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_stl_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )

    sms_have_ptp_dpd_plus3_pedemtl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}"
                            " sjmlh {{due_amount}}. Harap sgra lakukan pembayaran."
                            " Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus3_pedemtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus3_pedemtl,
        status="Inform customer have Pede MTL PTP date product dpd + 3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedemtl_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )

    sms_have_ptp_dpd_plus3_pedestl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}"
                            " sjmlh {{due_amount}}. Harap segera lakukan pembayaran."
                            " Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus3_pedestl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus3_pedestl,
        status="Inform customer have Pede STL PTP date product dpd + 3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedestl_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )

    sms_have_ptp_dpd_plus3_laku6 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm trma pmbayaran yg Anda janjikan " \
                            "{{ due_date }} Sjmlh {{due_amount}}. Harap segera lakukan pbayaran. Trm ksh",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus3_lauk6 = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus3_laku6,
        status="Inform customer have LAKU6 PTP date product dpd + 3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_laku6_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_dpd_+5',
               dpd=5).update(template_code='mtl_sms_dpd_+5')

    streamlined_communication_for_stl_sms_plus5 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='stl_sms_dpd_+5',
            dpd=5)

    sms_stl_plus5_msg = "{{name}}. Pembayaran pinjaman JULO Anda sdh TERLAMBAT 5 hari. " \
                        "Jaga kesempatan meminjam kembali Anda. " \
                        "Bayar sekarang: julo.co.id/r/sms"
    sms_stl_plus5_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_stl_sms_plus5.message.id) \
        .update(message_content=sms_stl_plus5_msg,
                parameter=sms_stl_plus5_param)

    streamlined_communication_for_pedemtl_sms_plus5 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedemtl_sms_dpd_+5',
            dpd=5)

    sms_pedemtl_plus5_msg = "{{name}}. Angsuran JULO Anda sdh TERLAMBAT 5 hari. Jaga ksmptn meminjam kmbl Anda. " \
                            "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedemtl_plus5_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedemtl_sms_plus5.message.id) \
        .update(message_content=sms_pedemtl_plus5_msg,
                parameter=sms_pedemtl_plus5_param)

    streamlined_communication_for_pedestl_sms_plus5 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedestl_sms_dpd_+5',
            dpd=5)

    sms_pedestl_plus5_msg = "{{name}}. Pembayaran pinjaman JULO Anda sdh TERLAMBAT 5 hari. " \
                            "Jaga kesempatan meminjam kembali Anda. " \
                            "Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedestl_plus5_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedestl_sms_plus5.message.id) \
        .update(message_content=sms_pedestl_plus5_msg,
                parameter=sms_pedestl_plus5_param)

    sms_have_ptp_dpd_plus5_stl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}}. Angsuran JULO Anda sdh TERLAMBAT 5 hari. Jaga ksmptn meminjam kmbl Anda. "
                            "Hubungi kami di collections@julo.co.id, Bayar sekarang: julo.co.id/r/sms",
            parameter="{name}"
        )

    streamlined_communication_for_sms_ptp_plus5_stl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus5_stl,
        status="Inform customer have STL PTP date product dpd + 5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_stl_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )

    sms_have_ptp_dpd_plus5_pedemtl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}}. Angsuran JULO Anda sdh TERLAMBAT 5 hari. Jaga ksmptn meminjam kmbl Anda. "
                            "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name}"
        )

    streamlined_communication_for_sms_ptp_plus5_pedemtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus5_pedemtl,
        status="Inform customer have Pede MTL PTP date product dpd + 5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedemtl_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )

    sms_have_ptp_dpd_plus5_pedestl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}}. Pembayaran pinjaman PEDE Anda sdh TERLAMBAT 5 hari. "
                            "Jaga kesempatan meminjam kembali Anda. "
                            "Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name}"
        )

    streamlined_communication_for_sms_ptp_plus5_pedestl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus5_pedestl,
        status="Inform customer have Pede STL PTP date product dpd + 5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedestl_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )

    sms_have_ptp_dpd_plus5_laku6 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{ name }}, Kami blm trma pmbayaran Anda smp saat ini. Segera bayar " \
                            "{{due_amount}} sblm kami hub perusahaan & kerabat Anda. Trm ksh",
            parameter="{name,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus5_lauk6 = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus5_laku6,
        status="Inform customer have LAKU6 PTP date product dpd + 5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_laku6_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_dpd_+7',
               dpd=7).update(template_code='mtl_sms_dpd_+7')

    streamlined_communication_for_stl_sms_plus7 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='stl_sms_dpd_+7',
            dpd=7)

    sms_stl_plus7_msg = "{{name}} bantu kami untuk bantu Anda info kendala Anda ke collections@julo.co.id. " \
                        "Bayar skrg: julo.co.id/r/sms"
    sms_stl_plus7_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_stl_sms_plus7.message.id) \
        .update(message_content=sms_stl_plus7_msg,
                parameter=sms_stl_plus7_param)

    streamlined_communication_for_pedemtl_sms_plus7 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedemtl_sms_dpd_+7',
            dpd=7)

    sms_pedemtl_plus7_msg = "{{name}} Angsuran Anda lwt jatuh tempo sgr lunasi agr terhindar dr dftr hitam fintech. " \
                            "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedemtl_plus7_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedemtl_sms_plus7.message.id) \
        .update(message_content=sms_pedemtl_plus7_msg,
                parameter=sms_pedemtl_plus7_param)

    streamlined_communication_for_pedestl_sms_plus7 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedestl_sms_dpd_+7',
            dpd=7)

    sms_pedestl_plus7_msg = "{{name}} menunda pembayaran yang dilakukan oleh orang mampu merupakan suatu ketidakadilan," \
                            " sgra bayar kewajiban Anda. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedestl_plus7_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedestl_sms_plus7.message.id) \
        .update(message_content=sms_pedestl_plus7_msg,
                parameter=sms_pedestl_plus7_param)

    sms_have_ptp_dpd_plus7_stl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}} Angsuran Anda lwt jatuh tempo sgr lunasi agar terhindar dr daftar hitam fintech. "
                            "Hub: collections@julo.co.id. Bayar sekarang: julo.co.id/r/sms",
            parameter="{name}"
        )

    streamlined_communication_for_sms_ptp_plus7_stl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus7_stl,
        status="Inform customer have STL PTP date product dpd + 7",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_stl_+7',
        dpd=7,
        description="this SMS called in sms_payment_dpd_7"
    )

    sms_have_ptp_dpd_plus7_pedemtl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}} Angsuran Anda lwt jatuh tempo sgr lunasi agr terhindar dr dftr hitam fintech. "
                            "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name}"
        )

    streamlined_communication_for_sms_ptp_plus7_pedemtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus7_pedemtl,
        status="Inform customer have Pede MTL PTP date product dpd + 7",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedemtl_+7',
        dpd=7,
        description="this SMS called in sms_payment_dpd_7"
    )

    sms_have_ptp_dpd_plus7_pedestl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}}. Angsuran Anda lwt jatuh tempo. Lunasi agr terhindar dr daftar hitam fintech. "
                            "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name}"
        )

    streamlined_communication_for_sms_ptp_plus7_pedestl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus7_pedestl,
        status="Inform customer have Pede STL PTP date product dpd + 7",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedestl_+7',
        dpd=7,
        description="this SMS called in sms_payment_dpd_7"
    )

    sms_have_ptp_dpd_plus7_laku6 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{ name }}, Kami blm trma pmbayaran Anda smp saat ini. Segera bayar " \
                            "{{due_amount}} sblm kami hub perusahaan & kerabat Anda. Trm ksh",
            parameter="{name,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus7_lauk6 = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus7_laku6,
        status="Inform customer have LAKU6 PTP date product dpd + 7",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_laku6_+7',
        dpd=7,
        description="this SMS called in sms_payment_dpd_7"
    )

    streamlined_communication_for_mtl_sms_plus5 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='mtl_sms_dpd_+5',
            dpd=5)

    sms_mtl_plus5_msg = "{{name}}. Angsuran JULO Anda sdh TERLAMBAT 5 hari. Jaga ksmptn meminjam kmbl Anda. Hubungi kami di collections@julo.co.id," \
                        " Bayar sekarang: julo.co.id/r/sms"
    sms_mtl_plus5_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_mtl_sms_plus5.message.id) \
        .update(message_content=sms_mtl_plus5_msg,
                parameter=sms_mtl_plus5_param)

    streamlined_communication_for_stl_sms_plus10 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='stl_sms_dpd_+10',
            dpd=10)

    sms_stl_plus10_msg = "{{name}}.  Lunasi pmbyrn pinjaman Anda, jaga kesempatan utk mengajukan pinjaman kmbli. " \
                         "Hubungi collections@julo.co.id. Bayar sekarang: julo.co.id/r/sms"

    sms_stl_plus10_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_stl_sms_plus10.message.id) \
        .update(message_content=sms_stl_plus10_msg,
                parameter=sms_stl_plus10_param)

    streamlined_communication_for_pedestl_sms_plus10 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedestl_sms_dpd_+10',
            dpd=10)

    sms_pedestl_plus10_msg = "{{name}}. Lunasi pmbyrn pinjaman Anda, jaga kesempatan utk mengajukan pinjaman kmbli. " \
                             "Hubungi collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedestl_plus10_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedestl_sms_plus10.message.id) \
        .update(message_content=sms_pedestl_plus10_msg,
                parameter=sms_pedestl_plus10_param)

    sms_mtl_plus7_msg = \
        StreamlinedMessage.objects.create(
            message_content="{{ name }} Angsuran Anda lwt jatuh tempo sgr lunasi agar terhindar dr daftar hitam fintech. " \
                            "Hub: collections@julo.co.id. Bayar sekarang: julo.co.id/r/sms",
            parameter="{name}"
        )

    StreamlinedCommunication.objects.filter(communication_platform=CommunicationPlatform.SMS,
                                            template_code='mtl_sms_dpd_+7',
                                            dpd=7) \
        .update(message=sms_mtl_plus7_msg)

    sms_pedemtl_plus7_msg = \
        StreamlinedMessage.objects.create(
            message_content="{{ name }} Angsuran Anda lwt jatuh tempo sgr lunasi agr terhindar dr dftr hitam fintech. " \
                            "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name}"
        )

    StreamlinedCommunication.objects.filter(communication_platform=CommunicationPlatform.SMS,
                                            template_code='pedemtl_sms_dpd_+7',
                                            dpd=7) \
        .update(message=sms_pedemtl_plus7_msg)

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='sms_dpd_+21',
               dpd=21).update(template_code='mtl_sms_dpd_+21')

    streamlined_communication_for_pedemtl_sms_plus21 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedemtl_sms_dpd_+21',
            dpd=21)

    sms_pedemtl_plus21_msg = "{{name}} Angsuran Anda lwt jatuh tempo sgr lunasi agr terhindar dr dftr hitam fintech. " \
                             "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedemtl_plus21_param = "{name}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedemtl_sms_plus21.message.id) \
        .update(message_content=sms_pedemtl_plus21_msg,
                parameter=sms_pedemtl_plus21_param)

    sms_have_ptp_dpd_plus21_pedemtl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}}. Lunasi tunggakan Anda, jg kesempatan utk mengajukan pinjaman di aplikasi PEDE. "
                            "Hub: collections@julo.co.id. Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name}"
        )

    streamlined_communication_for_sms_ptp_plus21_pedemtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus21_pedemtl,
        status="Inform customer have Pede MTL PTP date product dpd + 21",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedemtl_+21',
        dpd=21,
        description="this SMS called in sms_payment_dpd_21"
    )

    sms_have_ptp_dpd_plus21_laku6 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{ name }}, Kami blm trma pmbayaran Anda smp saat ini. Segera bayar " \
                            "{{due_amount}} sblm kami hub perusahaan & kerabat Anda. Trm ksh",
            parameter="{name,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus21_lauk6 = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus21_laku6,
        status="Inform customer have LAKU6 PTP date product dpd + 21",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_laku6_+21',
        dpd=21,
        description="this SMS called in sms_payment_dpd_21"
    )

    sms_mtl_plus21_msg = \
        StreamlinedMessage.objects.create(
            message_content="{{ name }}. Lunasi angsuran Anda dan jaga kesempatan Anda utk mengajukan pinjaman kembali. " \
                            "Hubungi collections@julo.co.id. Bayar sekarang: julo.co.id/r/sms",
            parameter="{name}"
        )

    StreamlinedCommunication.objects.filter(communication_platform=CommunicationPlatform.SMS,
                                            template_code='mtl_sms_dpd_+21',
                                            dpd=21) \
        .update(message=sms_mtl_plus21_msg)


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(change_stl_messages,
                             migrations.RunPython.noop)
    ]
