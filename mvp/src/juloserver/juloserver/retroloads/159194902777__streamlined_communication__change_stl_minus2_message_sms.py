from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import StreamlinedCommunication



from juloserver.streamlined_communication.models import StreamlinedMessage



def change_stl_messages(apps, schema_editor):
    
    

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_t0',
               dpd=0).update(template_code='laku6mtl_sms_dpd_0')

    streamlined_communication_for_pedestl_sms_ptp_t0 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_pedestl_0',
            dpd=0)
    sms_ptp_pedestl_0_msg = "Yth {{name}}, hr ini adalah hari pembayaran PEDE Pinter " \
                            "yg Anda janjikan sebesar {{due_amount}}." \
                            " Bayar: www.pede.id/dive?moveTo=pinter"
    sms_ptp_pedestl_0_param = "{name,due_amount}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedestl_sms_ptp_t0.message.id) \
        .update(message_content=sms_ptp_pedestl_0_msg,
                parameter=sms_ptp_pedestl_0_param)

    friska_rudolf_t0_stl, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Pinjaman Anda {{due_amount}} tlh jatuh tempo. Segera bayar ke {{bank_name}} "
                            "no VA {{account_number}}. Bayar sekarang: {{url}}",
            parameter="{name,due_amount,bank_name,account_number,url}",
        )
    for persona in ['friska', 'rudolf']:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=friska_rudolf_t0_stl,
            status="Inform customer STL product payment dpd 0",
            communication_platform=CommunicationPlatform.SMS,
            template_code=persona + '_stl_sms_dpd_0',
            dpd=0,
            description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
        )

    sms_ptp_minus2_stl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami ingtkn mgenai jnji byr yg "
                            "akn Anda lakukan pd {{due_date}} sjmlh {{due_amount}}. "
                            "Mohon bayar sesuai janji. Bayar sekarang: {{url}}",
            parameter="{name,due_date,due_amount,url}"
        )

    streamlined_communication_for_sms_ptp_2_stl = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_minus2_stl,
        status="Inform customer have STL PTP date product dpd - 2",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_stl_-2',
        dpd=-2,
        description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
    )

    sms_ptp_pede_minus2_stl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami ingtkn mgenai jnji byr yg "
                            "akn Anda lakukan pd {{due_date}} sjmlh {{due_amount}}. "
                            "Mohon byr sesuai janji. Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_2_pede_stl = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_pede_minus2_stl,
        status="Inform customer have Pede STL PTP date product dpd - 2",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedestl_-2',
        dpd=-2,
        description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
    )

    sms_ptp_pede_minus2_mtl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami ingtkn mgenai jnji byr yg "
                            "akn Anda lakukan pd {{due_date}} sjmlh {{due_amount}}. "
                            "Mohon bayar sesuai janji. Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name,due_date,due_amount}"
        )

    streamlined_communication_for_sms_ptp_2_pede_mtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_pede_minus2_mtl,
        status="Inform customer have Pede MTL PTP date product dpd - 2",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedemtl_-2',
        dpd=-2,
        description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
    )

    sms_ptp_minus2_laku6 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Kami ingtkn kmbli mgenai jnji pbayarn yg akn Anda "
                            "lakukan pd {{ due_date }} sjmlh {{due_amount}}. Harap bayar ssuai "
                            "janji yg dibuat. Trma kasih. Info: {{url}}",
            parameter="{name,due_date,due_amount,url}"
        )

    streamlined_communication_for_sms_ptp_minus2_laku6 = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_minus2_laku6,
        status="Inform customer have LAKU6 PTP date product dpd - 2",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_laku6_-2',
        dpd=-2,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
    )
    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_t2',
               dpd=-2).update(template_code='laku6mtl_sms_dpd_-2')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedestl_sms_dpd_t2',
               dpd=-2).update(template_code='pedestl_sms_dpd_-2')

    streamlined_communication_for_pedestl_sms_minus2 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedestl_sms_dpd_-2',
            dpd=-2)

    sms_pedestl_minus2_msg = "{{name}}, sy Ani dr JULO. Pinjaman PEDE Pinter Anda " \
                                 "{{due_amount}} jatuh tempo {{due_date}}. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedestl_minus2_param = "{name,due_amount,due_date}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedestl_sms_minus2.message.id) \
        .update(message_content=sms_pedestl_minus2_msg,
                parameter=sms_pedestl_minus2_param)

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_t2',
               dpd=-2).update(template_code='pedemtl_sms_dpd_-2')

    streamlined_communication_for_pedemtl_sms_minus2 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedemtl_sms_dpd_-2',
            dpd=-2)

    sms_pedemtl_minus2_msg = "{{name}}, sy Ani dr JULO. Angsuran PEDE Pinter {{payment_number}} Anda {{due_amount}}" \
                             " jatuh tempo {{due_date}}. Bayar: www.pede.id/dive?moveTo=pinter"
    sms_pedemtl_minus2_param = "{name,payment_number,due_amount,due_date}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedemtl_sms_minus2.message.id) \
        .update(message_content=sms_pedemtl_minus2_msg,
                parameter=sms_pedemtl_minus2_param)

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='rudolf_t2_mtl',
               dpd=-2).update(template_code='rudolf_mtl_sms_dpd_-2')

    streamlined_communication_for_mtl_sms_minus2 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='rudolf_mtl_sms_dpd_-2',
            dpd=-2)

    sms_mtl_minus2_msg = "{{name}}, sy Ani dr JULO. Dapatkan cashback " \
                                "{{cashback_multiplier}} x {{payment_cashback_amount}} " \
                                "dgn segera membayar cicilan Anda {{due_amount}} hari ini. Bayar sekarang: {{url}}"
    sms_mtl_minus2_param = "{name,cashback_multiplier,payment_cashback_amount,due_amount,url}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_mtl_sms_minus2.message.id) \
        .update(message_content=sms_mtl_minus2_msg,
                parameter=sms_mtl_minus2_param)

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='friska_t2_mtl',
               dpd=-2).update(template_code='friska_mtl_sms_dpd_-2')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='rudolf_t2_stl',
               dpd=-2).update(template_code='rudolf_stl_sms_dpd_-2')

    streamlined_communication_for_stl_sms_minus2 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='rudolf_stl_sms_dpd_-2',
            dpd=-2)

    sms_stl_minus2_msg = "{{name}}, sy Ani dr JULO. Pinjaman Anda {{due_amount}} jatuh tempo pada {{due_date}}. " \
                            "Bayar sekarang agar tidak jadi beban. Bayar sekarang: {{url}}"
    sms_stl_minus2_param = "{name,due_amount,due_date,url}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_stl_sms_minus2.message.id) \
        .update(message_content=sms_stl_minus2_msg,
                parameter=sms_stl_minus2_param)

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='friska_t2_stl',
               dpd=-2).update(template_code='friska_stl_sms_dpd_-2')


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(change_stl_messages,
                             migrations.RunPython.noop)
    ]
