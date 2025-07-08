from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import StreamlinedCommunication



from juloserver.streamlined_communication.models import StreamlinedMessage



def change_mtl_messages(apps, schema_editor):
    
    
    sms_ptp_minus2_mtl= \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami ingtkn mgenai janji byr yg "
                            "akn Anda lakukan pd {{due_date}} sjmlh {{due_amount}}. "
                            "Mohon bayar sesuai janji. Bayar sekarang: {{url}}",
            parameter="{name,due_date,due_amount,url}"
        )

    streamlined_communication_for_sms_ptp_2_mtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_minus2_mtl,
        status="Inform customer when dpd -2 and ptp not null",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_mtl_-2',
        dpd=-2,
        description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
    )

    streamlined_communication_for_sms_ptp_2_4 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_-2_4',
            dpd=-2)
    streamlined_communication_for_sms_ptp_2_4_msg = "Yth {{name}}, Kami ingtkn kmbli mgenai jnji " \
                                                    "pbayarn yg akn Anda lakukan pd {{due_date}} " \
                                                    "sjmlh {{due_amount}}. Harap bayar ssuai janji yg dibuat. " \
                                                    "Trma kasih. Info: {{url}}"
    streamlined_communication_for_sms_ptp_2_4_param = "{name,due_date,due_amount,url}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_sms_ptp_2_4.message.id) \
        .update(message_content=streamlined_communication_for_sms_ptp_2_4_msg,
                parameter=streamlined_communication_for_sms_ptp_2_4_param)

    sms_ptp_0_mtl= \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Anda tlh melakukan janji bayar hr ini. " 
                            "Sgr bayar {{due_amount}} ke {{bank_name}} no VA: " 
                            "{{account_number}}. Bayar sekarang: julo.co.id/r/sms",
            parameter="{name,due_amount,bank_name,account_number}"
        )

    streamlined_communication_for_sms_ptp_0_mtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_0_mtl,
        status="Inform customer MTL product and have ptp",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_mtl_0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
    )

    streamlined_communication_for_sms_ptp_0 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_0',
            dpd=0)
    streamlined_communication_for_sms_ptp_0_msg = "Yth {{name}}, hr ini {{due_date}} adlh tgl " \
                                                  "pmbayaran yg Anda janjikan. " \
                                                  "Segera bayar {{due_amount}} ke {{bank_name}} no " \
                                                  "VA {{account_number}}. Trm ksh"
    streamlined_communication_for_sms_ptp_0_param = "{name,due_date,due_amount,bank_name,account_number}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_sms_ptp_0.message.id) \
        .update(message_content=streamlined_communication_for_sms_ptp_0_msg,
                parameter=streamlined_communication_for_sms_ptp_0_param)


    sms_have_ptp_dpd_plus1_mtl= \
        StreamlinedMessage.objects.create(
            message_content= "Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}" 
                             " sejumlah {{due_amount}}. Harap segera lakukan pembayaran." 
                             " Bayar sekarang: julo.co.id/r/sms",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_plus1_mtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus1_mtl,
        status="Inform customer have PTP date product dpd + 1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_mtl_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )
    sms_ptp_t1 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+1_3',
            dpd=1)
    sms_ptp_t1_msg = "Yth {{name}}, Kami blm trma pmbayaran yg Anda janjikan {{ due_date }} " \
                     "Sjmlh {{due_amount}}. Harap segera lakukan pbayaran. Trm ksh"
    sms_ptp_t1_param = "{name,due_date,due_amount}"
    StreamlinedMessage.objects.filter(id=sms_ptp_t1.message.id) \
        .update(message_content=sms_ptp_t1_msg,
                parameter=sms_ptp_t1_param)


    sms_have_ptp_dpd_plus3_mtl= \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami blm terima pembayaran yg Anda janjikan {{ due_date }}"
                            " sejumlah {{due_amount}}. Harap segera lakukan pembayaran."
                            " Bayar sekarang: julo.co.id/r/sms",
            parameter="{name,due_date,due_amount}"
        )
    streamlined_communication_for_sms_ptp_plus3_mtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus3_mtl,
        status="Inform customer have PTP date product dpd + 3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_mtl_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )
    sms_ptp_t3 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+1_3',
            dpd=3)
    sms_ptp_t3_msg = "Yth {{name}}, Kami blm trma pmbayaran yg Anda janjikan {{ due_date }} " \
                     "Sjmlh {{due_amount}}. Harap segera lakukan pbayaran. Trm ksh"
    sms_ptp_t3_param = "{name,due_date,due_amount}"
    StreamlinedMessage.objects.filter(id=sms_ptp_t3.message.id) \
        .update(message_content=sms_ptp_t3_msg,
                parameter=sms_ptp_t3_param)

    sms_have_ptp_dpd_plus5_mtl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}}. Angsuran JULO Anda sdh TERLAMBAT 5 hari." 
                            " Jaga ksmptn meminjam kmbl Anda. Hubungi kami di collections@julo.co.id," 
                            " Bayar sekarang: julo.co.id/r/sms",
            parameter="{name}"
        )
    streamlined_communication_for_sms_ptp_plus5_mtl  = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus5_mtl,
        status="Inform customer have PTP date product dpd +5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_mtl_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )

    sms_ptp_plus5 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+5',
            dpd=5)
    sms_ptp_plus5_msg = "Yth {{name}}, Kami blm trma pmbayaran Anda smp saat ini. " \
                        "Segera bayar {{due_amount}} " \
                        "sblm kami hub perusahaan & kerabat Anda. Trm ksh"
    sms_ptp_plus5_param = "{name,due_amount}"
    StreamlinedMessage.objects.filter(id=sms_ptp_plus5.message.id) \
                              .update(message_content=sms_ptp_plus5_msg,
                                      parameter=sms_ptp_plus5_param)

    sms_have_ptp_dpd_plus7_mtl= \
        StreamlinedMessage.objects.create(
            message_content="{{name}} Angsuran Anda lwt jatuh tempo sgr lunasi agar" 
                            " terhindar dr daftar hitam fintech. Hub: collections@julo.co.id." 
                            " Bayar sekarang: julo.co.id/r/sms",
            parameter="{name}"
        )
    streamlined_communication_for_sms_ptp_plus7_mtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus7_mtl,
        status="Inform customer have PTP date product dpd +7",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_mtl_+7',
        dpd=7,
        description="this SMS called in sms_payment_dpd_7"
    )

    sms_ptp_plus7 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+5',
            dpd=7)
    sms_ptp_plus7_msg = "Yth {{name}}, Kami blm trma pmbayaran Anda smp saat ini. " \
                        "Segera bayar {{due_amount}} " \
                        "sblm kami hub perusahaan & kerabat Anda. Trm ksh"
    sms_ptp_plus7_param = "{name,due_amount}"
    StreamlinedMessage.objects.filter(id=sms_ptp_plus7.message.id) \
        .update(message_content=sms_ptp_plus7_msg,
                parameter=sms_ptp_plus7_param)

    sms_ptp_plus10 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+5',
            dpd=10)
    sms_ptp_plus10_msg = "Yth {{name}}, Kami blm trma pmbayaran Anda smp saat ini. " \
                         "Segera bayar {{due_amount}} " \
                         "sblm kami hub perusahaan & kerabat Anda. Trm ksh"
    sms_ptp_plus10_param = "{name,due_amount}"
    StreamlinedMessage.objects.filter(id=sms_ptp_plus10.message.id) \
        .update(message_content=sms_ptp_plus10_msg,
                parameter=sms_ptp_plus10_param)

    sms_have_ptp_dpd_plus21_mtl = \
        StreamlinedMessage.objects.create(
            message_content="{{name}}. Lunasi angsuran Anda dan jaga kesempatan Anda" 
                             " utk mengajukan pinjaman kembali. Hubungi collections@julo.co.id." 
                             " Bayar sekarang: julo.co.id/r/sms",
            parameter="{name}"
        )
    streamlined_communication_for_sms_ptp_plus21_mtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_have_ptp_dpd_plus21_mtl,
        status="Inform customer have PTP date product dpd +21",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_mtl_+21',
        dpd=21,
        description="this SMS called in sms_payment_dpd_21"
    )
    sms_ptp_plus21 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+5',
            dpd=21)
    sms_ptp_plus21_msg = "Yth {{name}}, Kami blm trma pmbayaran Anda smp saat ini. " \
                        "Segera bayar {{due_amount}} " \
                        "sblm kami hub perusahaan & kerabat Anda. Trm ksh"
    sms_ptp_plus21_param = "{name,due_amount}"
    StreamlinedMessage.objects.filter(id=sms_ptp_plus21.message.id) \
                              .update(message_content=sms_ptp_plus21_msg,
                                      parameter=sms_ptp_plus21_param)


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(change_mtl_messages,
                             migrations.RunPython.noop)
    ]
