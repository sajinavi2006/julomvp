from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import StreamlinedCommunication



from juloserver.streamlined_communication.models import StreamlinedMessage



def change_stl_messages(apps, schema_editor):
    
    

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
            template_code='friska_t0_mtl',
            dpd=0).update(template_code='friska_mtl_sms_dpd_0')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='rudolf_t0_mtl',
               dpd=0).update(template_code='rudolf_mtl_sms_dpd_0')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_t0',
               status="Inform customer PEDE MTL product",
               dpd=0).update(template_code='pedemtl_sms_dpd_0')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='pedemtl_sms_dpd_t0',
               status="Inform customer PEDE STL product dpd 0",
               dpd=0).update(template_code='pedestl_sms_dpd_0')

    StreamlinedCommunication.objects. \
        filter(communication_platform=CommunicationPlatform.SMS,
               template_code='laku6mtl_sms_dpd_0',
               dpd=0).update(template_code='laku6mtl_sms_dpd_t0')



    sms_ptp_0_stl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Anda tlh melakukan janji bayar hr ini. "
                            "Sgr bayar {{due_amount}} ke {{bank_name}} no VA: "
                            "{{account_number}}. Bayar sekarang: julo.co.id/r/sms",
            parameter="{name,due_amount,bank_name,account_number}"
        )

    streamlined_communication_for_sms_ptp_0_stl = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_0_stl,
        status="Inform customer STL product and have ptp",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_stl_0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
    )



    sms_ptp_0_pedemtl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, Anda tlh melakukan janji bayar hr ini. "
                            "Sgr bayar {{due_amount}} ke {{bank_name}} no VA: "
                            "{{account_number}}. Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name,due_amount,bank_name,account_number}"
        )

    streamlined_communication_for_sms_ptp_0_pedemtl = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_0_pedemtl,
        status="Inform customer PEDE MTL product and have ptp",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedemtl_0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
    )

    sms_ptp_0_pedestl = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, hr ini adalah hari pembayaran PEDE Pinter "
                            "yg Anda janjikan sebesar Rp {{due_amount}}."
                            " Bayar: www.pede.id/dive?moveTo=pinter",
            parameter="{name,due_amount,bank_name,account_number}"
        )

    streamlined_communication_for_sms_ptp_0_pedestl = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_0_pedestl,
        status="Inform customer PEDE STL product and have ptp",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_pedestl_0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
    )

    sms_ptp_0_laku6 = \
        StreamlinedMessage.objects.create(
            message_content="Yth {{name}}, hr ini {{ due_date }} adlh tgl" \
            " pmbayaran yg Anda janjikan. Segera bayar {{due_amount}} ke {{ bank_name }} "
            "no VA {{ account_number }}. Trm ksh",
            parameter="{name,due_date,due_amount,bank_name,account_number}"
        )

    streamlined_communication_for_sms_ptp_0_laku6 = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_0_laku6,
        status="Inform customer LAKU6 product and have ptp",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_laku6_0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
    )

    streamlined_communication_for_pedemtl_sms_dpd_t0 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedemtl_sms_dpd_0',
            status="Inform customer PEDE MTL product",
            dpd=0)
    pedemtl_sms_dpd_t0_msg = "{{name}}, sy Ani dr JULO. Angsuran {{payment_number}} PEDE Pinter {{due_amount}} " \
                             "jatuh tempo hari ini. Bayar: www.pede.id/dive?moveTo=pinter"
    pedemtl_sms_dpd_t0_param = "{name,payment_number,due_amount}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedemtl_sms_dpd_t0.message.id) \
        .update(message_content=pedemtl_sms_dpd_t0_msg,
                parameter=pedemtl_sms_dpd_t0_param)

    streamlined_communication_for_pedestl_sms_dpd_t0 = StreamlinedCommunication.objects. \
        get(communication_platform=CommunicationPlatform.SMS,
            template_code='pedestl_sms_dpd_0',
            status="Inform customer PEDE STL product dpd 0",
            dpd=0)
    pedestl_sms_dpd_t0_msg = "{{name}}, sy Ani dr JULO. Pinjaman PEDE Pinter Anda {{due_amount}} " \
                             "jatuh tempo hari ini. Bayar: www.pede.id/dive?moveTo=pinter"
    pedestl_sms_dpd_t0_param = "{name,due_amount}"
    StreamlinedMessage.objects.filter(id=streamlined_communication_for_pedestl_sms_dpd_t0.message.id) \
        .update(message_content=pedestl_sms_dpd_t0_msg,
                parameter=pedestl_sms_dpd_t0_param)



class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(change_stl_messages,
                             migrations.RunPython.noop)
    ]
