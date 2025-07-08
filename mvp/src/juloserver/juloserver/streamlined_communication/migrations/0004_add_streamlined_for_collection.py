# coding=utf-8
from __future__ import unicode_literals

from builtins import range
from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


def add_message_for_collection(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")
    # PN
    # juloserver.julo.tasks.send_all_pn_payment_reminders
    inform_payment_due_soon_template_multiple_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Cicilan ke-{{payment_number}} akan jatuh tempo, harap transfer.",
            parameter="{payment_number}",
        )
    inform_payment_due_soon_template_one_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Pelunasan akan jatuh tempo, harap transfer.",
        )
    inform_payment_due_today_template_multiple_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Cicilan ke-{{payment_number}} jatuh tempo hari ini, harap transfer.",
            parameter="{payment_number}",
        )
    inform_payment_due_today_template_one_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Pelunasan jatuh tempo hari ini, harap transfer.",
        )
    inform_payment_late_template_multiple_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Cicilan ke-{{payment_number}} terlambat, harap transfer.",
            parameter="{payment_number}",
        )
    inform_payment_late_template_one_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Pelunasan terlambat, harap transfer.",
        )

    data_inform_payment_due_soon = [
        {
            'status': 'inform payment due soon multiple payment',
            'criteria': {"product_line": ProductLineCodes.multiple_payment()},
            'description': 'this PN called when dpd {} and have multiple payment',
            'message': inform_payment_due_soon_template_multiple_payment
        },
        {
            'status': 'inform payment due soon one payment',
            'criteria': {"product_line": ProductLineCodes.one_payment()},
            'description': 'this PN called when dpd {} and have one payment',
            'message': inform_payment_due_soon_template_one_payment
        }
    ]
    data_inform_payment_due_today = [
        {
            'status': 'inform payment due today multiple payment',
            'criteria': {"product_line": ProductLineCodes.multiple_payment()},
            'description': 'this PN called when dpd 0 and have multiple payment',
            'message': inform_payment_due_today_template_multiple_payment
        },
        {
            'status': 'inform payment due today one payment',
            'criteria': {"product_line": ProductLineCodes.one_payment()},
            'description': 'this PN called when dpd 0 and have one payment',
            'message': inform_payment_due_today_template_one_payment
        }
    ]
    data_inform_payment_late = [
        {
            'status': 'inform payment late multiple payment',
            'criteria': {"product_line": ProductLineCodes.multiple_payment()},
            'description': 'this PN called when late and have dpd {} and have multiple payment',
            'message': inform_payment_late_template_multiple_payment
        },
        {
            'status': 'inform payment late one payment',
            'criteria': {"product_line": ProductLineCodes.one_payment()},
            'description': 'this PN called when late and have dpd {} and have one payment',
            'message': inform_payment_late_template_one_payment
        }
    ]
    for i in [-3, -1]:
        for data in data_inform_payment_due_soon:
            streamlined_communication = StreamlinedCommunication.objects.get_or_create(
                message=data['message'],
                status=data['status'],
                communication_platform=CommunicationPlatform.PN,
                template_code='inform_payment_due_soon',
                dpd=i,
                description=data['description'].format(i),
                criteria=data['criteria']
            )
    for data in data_inform_payment_due_today:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=data['message'],
            status=data['status'],
            communication_platform=CommunicationPlatform.PN,
            template_code='inform_payment_due_today',
            dpd=0,
            description=data['description'],
            criteria=data['criteria']
        )
    for i in [1, 5, 30, 60, 90, 120, 150, 180, 210]:
        for data in data_inform_payment_late:
            streamlined_communication = StreamlinedCommunication.objects.get_or_create(
                message=data['message'],
                status=data['status'],
                communication_platform=CommunicationPlatform.PN,
                template_code='inform_payment_late',
                dpd=i,
                description=data['description'].format(i),
                criteria=data['criteria']
            )

    # juloserver.julo.tasks.send_all_pn_payment_mtl_stl_reminders
    # MTL inform_mtl_payment
    mtl_tmin5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="90% pelanggan kami sudah berhasil mendapatkan Ekstra Cashback, ayo dapatkan juga."
        )
    mtl_tmin4_until_tmin2, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Anda masih punya kesempatan dapat Ekstra Cashback. Bayar angsuran ke-{{payment_number}} sekarang.",
            parameter="{payment_number}",
        )
    mtl_tmin1_until_0, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="95% pelanggan di area Anda sudah membayar. Ayo bayar, kesempatan terakhir mendapatkan Cashback."
        )
    mtl_tplus1_until_plus4, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Masih ada kesempatan memperbaiki skor kredit. Ayo bayarkan tagihan Anda sekarang."
        )
    mtl_tplus5_and_so_on, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Jangan biarkan beban Anda bertambah, Kami carikan solusi kendala Anda. Hubungi Kami segera."
        )
    streamlined_communication_tmin5 = StreamlinedCommunication.objects.get_or_create(
        message=mtl_tmin5,
        status="Inform MTL customer when dpd-5",
        communication_platform=CommunicationPlatform.PN,
        template_code='MTL_T-5',
        dpd=-5,
        description="this PN called in inform_mtl_payment"
    )
    for i in [-4, -3, -2]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=mtl_tmin4_until_tmin2,
            status="Inform MTL customer when dpd {}".format(i),
            communication_platform=CommunicationPlatform.PN,
            template_code='MTL_T{}'.format(i),
            dpd=i,
            description="this PN called in inform_mtl_payment"
        )
    for i in [-1, 0]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=mtl_tmin1_until_0,
            status="Inform MTL customer when dpd {}".format(i),
            communication_platform=CommunicationPlatform.PN,
            template_code='MTL_T{}'.format(i),
            dpd=i,
            description="this PN called in inform_mtl_payment"
        )
    for i in range(1, 5):
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=mtl_tplus1_until_plus4,
            status="Inform MTL customer when dpd {}".format(i),
            communication_platform=CommunicationPlatform.PN,
            template_code='MTL_T{}'.format(i),
            dpd=i,
            description="this PN called in inform_mtl_payment"
        )
    for i in [5, 30, 60, 90, 120, 150, 180]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=mtl_tplus5_and_so_on,
            status="Inform MTL customer when dpd {}".format(i),
            communication_platform=CommunicationPlatform.PN,
            template_code='MTL_T{}'.format(i),
            dpd=i,
            description="this PN called in inform_mtl_payment"
        )
    #   STL
    stl_tmin5_until_t0, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="95% pelanggan di area Anda sudah membayar. Ayo ikut bayar Pinjaman Anda sekarang."
        )
    stl_t1_until_t4, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Masih ada kesempatan memperbaiki skor kredit. Ayo bayarkan tagihan Anda sekarang."
        )
    stl_t5_so_on, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Jangan biarkan beban Anda bertambah, Kami carikan solusi kendala Anda. Hubungi Kami segera."
        )
    for i in range(-5, 1):
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=stl_tmin5_until_t0,
            status="Inform STL customer when dpd {}".format(i),
            communication_platform=CommunicationPlatform.PN,
            template_code='STL_T{}'.format(i),
            dpd=i,
            description="this PN called in inform_stl_payment"
        )
    for i in range(1, 5):
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=stl_t1_until_t4,
            status="Inform STL customer when dpd {}".format(i),
            communication_platform=CommunicationPlatform.PN,
            template_code='STL_T{}'.format(i),
            dpd=i,
            description="this PN called in inform_stl_payment"
        )
    for i in [5, 30, 60, 90, 120, 150, 180]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=stl_t5_so_on,
            status="Inform STL customer when dpd {}".format(i),
            communication_platform=CommunicationPlatform.PN,
            template_code='STL_T{}'.format(i),
            dpd=i,
            description="this PN called in inform_stl_payment"
        )
    # SMS
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_due_in2
    sms_ptp_2_4, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{name}}, Kami ingtkn kmbli mgenai jnji pbayarn yg akn Anda lakukan pd {{due_date}} "
                            "sjmlh {{due_amount}}. Harap bayar ssuai janji yg dibuat. Trma kasih. Info: {{url}}",
            parameter="{name,due_date,due_amount,url}",
        )
    rudolf_friska_t2_mtl, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Dapatkan cashback {{cashback_multiplier}} x {{payment_cashback_amount}} "
                            "dgn segera membayar cicilan Anda {{due_amount}} hari ini. Cara bayar: {{url}}",
            parameter="{name,cashback_multiplier,payment_cashback_amount,due_amount,url}",
        )
    rudolf_friska_t2_stl, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Pinjaman Anda {{due_amount}} jatuh tempo pada {{due_date}}. "
                            "Segera bayar dengan cara berikut: {{url}}",
            parameter="{name,due_amount,due_date,url}",
        )
    pedemtl_sms_dpd_t2, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Angsuran PEDE Pinter {{payment_number}} Anda Rp.{{due_amount}} "
                            "jatuh tempo {{due_date}}. Info: {{url}}.",
            parameter="{name,payment_number,due_amount,due_date,url}",
        )
    pedestl_sms_dpd_t2, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Pinjaman PEDE Pinter Anda Rp.{{due_amount}} jatuh tempo {{due_date}}. "
                            "Info: {{url}}.",
            parameter="{name,payment_number,due_amount,due_date,url}",
        )
    laku6mtl_sms_dpd_t2, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Angsuran Prio Rental {{payment_number}} Anda Rp.{{due_amount}} "
                            "jatuh tempo {{due_date}}. Info: {{url}}.",
            parameter="{name,due_amount,due_date,url}",
        )
    streamlined_communication_for_sms_ptp_2_4 = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_2_4,
        status="Inform customer when dpd -2 and ptp not null",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_-2_4',
        dpd=-2,
        description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
    )
    for persona in ['friska', 'rudolf']:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=rudolf_friska_t2_mtl,
            status="Inform customer MTL when dpd -2",
            communication_platform=CommunicationPlatform.SMS,
            template_code=persona + '_t2_mtl',
            dpd=-2,
            description="this SMS called in sms_payment_due_in2 and can_notify = False and not paid yet"
        )
    for persona in ['friska', 'rudolf']:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=rudolf_friska_t2_stl,
            status="Inform customer STL when dpd -2",
            communication_platform=CommunicationPlatform.SMS,
            template_code=persona + '_t2_stl',
            dpd=-2,
            description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
        )

    streamlined_communication_for_pedemtl_sms = StreamlinedCommunication.objects.get_or_create(
        message=pedemtl_sms_dpd_t2,
        status="Inform customer PEDE MTL when dpd -2",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedemtl_sms_dpd_t2',
        dpd=-2,
        description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
    )
    streamlined_communication_for_pedestl_sms = StreamlinedCommunication.objects.get_or_create(
        message=pedestl_sms_dpd_t2,
        status="Inform customer PEDE STL when dpd -2",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedestl_sms_dpd_t2',
        dpd=-2,
        description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
    )
    streamlined_communication_for_laku6mtl = StreamlinedCommunication.objects.get_or_create(
        message=laku6mtl_sms_dpd_t2,
        status="Inform customer Laku6 MTL dpd-2",
        communication_platform=CommunicationPlatform.SMS,
        template_code='laku6mtl_sms_dpd_t2',
        dpd=-2,
        description="this SMS called in sms_payment_due_in2 can_notify = False and not paid yet"
    )
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_due_in7
    sms_dpd_min7, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{name}}, nikmati cashback {{payment_cashback_amount}} saat melunasi tagihan JULO Anda "
                            "paling lambat {{due_date_in_4_days}}. Cek info di aplikasi.",
            parameter="{name,payment_cashback_amount,due_date_in_4_days}",
        )
    streamlined_communication_for_sms_dpd_min7 = StreamlinedCommunication.objects.get_or_create(
        message=sms_dpd_min7,
        status="Inform customer MTL product payment dpd-7",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_dpd_-7',
        dpd=-7,
        description="this SMS called in sms_payment_due_in7 can_notify = False and not paid yet"
    )
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_due_today
    sms_ptp_0, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{name}}, hr ini {{due_date}} adlh tgl pmbayaran yg Anda janjikan. "
                            "Segera bayar {{due_amount}} ke {{bank_name}} no VA {{account_number}}. Trm ksh",
            parameter="{name,due_date,due_amount,bank_name,account_number}",
        )
    friska_rudolf_t0_mtl, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Angsuran {{payment_number}} Anda {{due_amount}} jatuh tempo "
                            "hari ini. Segera bayar untuk kesempatan terakhir "
                            "cashback sebesar {{payment_cashback_amount}}. Cara bayar: {{url}}",
            parameter="{name,payment_number,due_amount,payment_cashback_amount,url}",
        )
    friska_rudolf_t0_stl, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Pinjaman Anda {{due_amount}} jatuh tempo hari ini. "
                            "Segera bayar dengan cara berikut: {{url}}",
            parameter="{name,due_amount,url}",
        )
    pedemtl_sms_dpd_t0, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Angsuran {{payment_number}} PEDE Pinter {{due_amount}} "
                            "jatuh tempo hari ini. Cara bayar: {{url}} dan cek aplikasi PEDE anda.",
            parameter="{name,payment_number,due_amount,url}",
        )
    pedestl_sms_dpd_t0, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Pinjaman PEDE Pinter Anda {{due_amount}} jatuh tempo hari ini. "
                            "Cara bayar: {{url}} dan cek aplikasi PEDE anda.",
            parameter="{name,due_amount,url}",
        )
    laku6mtl_sms_dpd_t0, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, sy Ani dr JULO. Angsuran {{payment_number}} Prio Rental {{due_amount}} "
                            "jatuh tempo hari ini. Cara bayar: {{url}} dan cek aplikasi Prio Rental anda.",
            parameter="{name,payment_number,due_amount,url}",
        )
    streamlined_communication_for_sms_ptp_0 = StreamlinedCommunication.objects.get_or_create(
        message=sms_ptp_0,
        status="Inform customer MTL product and have ptp",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_ptp_0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
    )
    for persona in ['friska', 'rudolf']:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=friska_rudolf_t0_mtl,
            status="Inform customer MTL product payment dpd 0",
            communication_platform=CommunicationPlatform.SMS,
            template_code=persona + '_t0_mtl',
            dpd=0,
            description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
        )
    streamlined_communication_for_pedemtl_sms_dpd_t0 = StreamlinedCommunication.objects.get_or_create(
        message=pedemtl_sms_dpd_t0,
        status="Inform customer PEDE MTL product",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedemtl_sms_dpd_t0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet"
    )
    streamlined_communication_for_pedestl_sms_dpd_t0 = StreamlinedCommunication.objects.get_or_create(
        message=pedestl_sms_dpd_t0,
        status="Inform customer PEDE STL product dpd 0",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedemtl_sms_dpd_t0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet and PEDE STL"
    )
    streamlined_communication_for_laku6mtl_sms_dpd_t0 = StreamlinedCommunication.objects.get_or_create(
        message=laku6mtl_sms_dpd_t0,
        status="Inform customer Laku6 MTL product dpd 0",
        communication_platform=CommunicationPlatform.SMS,
        template_code='laku6mtl_sms_dpd_t0',
        dpd=0,
        description="this SMS called in sms_payment_due_today can_notify = False and not paid yet and LAKU6 MTL"
    )
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_dpd_1
    sms_ptp_plus1_3, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{name}}, Kami blm trma pmbayaran yg Anda janjikan {{due_date}} Sjmlh {{due_amount}}."
                            " Harap segera lakukan pbayaran. Trm ksh",
            parameter="{name,due_date,due_amount}",
        )
    sms_dpd_plus1, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, kami ingatkan angsuran JULO {{payment_number}} Anda {{due_amount}} sdh "
                            "TERLAMBAT. Mohon segera bayar: cek aplikasi. Abaikan jika sudah bayar.",
            parameter="{name,payment_number,due_amount}",
        )
    stl_sms_dpd_plus1, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, kami ingatkan Pinjaman JULO Anda {{due_amount}} sdh TERLAMBAT. "
                            "Mohon segera bayar: cek aplikasi. Abaikan jika sudah bayar.",
            parameter="{name,due_amount}",
        )
    pedemtl_sms_dpd_plus1, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, kami ingatkan angsuran PEDE Pinter {{payment_number}} Anda {{due_amount}} "
                            "sdh TERLAMBAT. Mohon segera bayar: cek aplikasi PEDE. Abaikan jika sudah bayar.",
            parameter="{name,payment_number,due_amount}",
        )
    pedestl_sms_dpd_plus1, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, kami ingatkan Pinjaman PEDE Pinter Anda {{due_amount}} sdh TERLAMBAT. "
                            "Mohon segera bayar: cek aplikasi. Abaikan jika sudah bayar.",
            parameter="{name,due_amount}",
        )
    laku6mtl_sms_dpd_plus1, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}, kami ingatkan angsuran JULO {{payment_number}} Anda {{due_amount}} "
                            "sdh TERLAMBAT. Mohon segera bayar: cek aplikasi Prio Rental. Abaikan jika sudah bayar.",
            parameter="{name,payment_number,due_amount}",
        )
    streamlined_communication_for_sms_dpd_plus1 = StreamlinedCommunication.objects.get_or_create(
        message=sms_dpd_plus1,
        status="Inform customer MTL product dpd +1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_dpd_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )
    streamlined_communication_for_stl_sms_dpd_plus1 = StreamlinedCommunication.objects.get_or_create(
        message=stl_sms_dpd_plus1,
        status="Inform customer STL product dpd +1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='stl_sms_dpd_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )
    streamlined_communication_for_pedemtl_sms_dpd_plus1 = StreamlinedCommunication.objects.get_or_create(
        message=pedemtl_sms_dpd_plus1,
        status="Inform customer PEDE MTL product dpd +1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedemtl_sms_dpd_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )
    streamlined_communication_for_pedestl_sms_dpd_plus1 = StreamlinedCommunication.objects.get_or_create(
        message=pedestl_sms_dpd_plus1,
        status="Inform customer PEDE STL product dpd +1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedestl_sms_dpd_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )
    streamlined_communication_for_laku6mtl_sms_dpd_plus1 = StreamlinedCommunication.objects.get_or_create(
        message=laku6mtl_sms_dpd_plus1,
        status="Inform customer Laku6 MTL product dpd +1",
        communication_platform=CommunicationPlatform.SMS,
        template_code='laku6mtl_sms_dpd_+1',
        dpd=1,
        description="this SMS called in sms_payment_dpd_1"
    )
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_dpd_3
    for i in [1, 3]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=laku6mtl_sms_dpd_plus1,
            status="Inform customer have PTP date product dpd + {}".format(i),
            communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+1_3',
            dpd=i,
            description="this SMS called in sms_payment_dpd_{}".format(i)
        )
    sms_dpd_plus3, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. 99% pelanggan kami sdh melakukan pembayaran angsuran per hari ini. "
                            "Tanggung jawab di hal kecil akan membawa kepercayaan untuk hal besar. "
                            "Bayar Angsuran {{payment_number}} Anda {{due_amount}} segera. Cara bayar,  cek aplikasi.",
            parameter="{name,payment_number,due_amount}",
        )
    stl_sms_dpd_plus3, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. 99% pelanggan kami sdh melakukan pembayaran Pinjaman per hari ini. "
                            "Tanggung jawab di hal kecil akan membawa kepercayaan untuk hal besar. "
                            "Bayar Pinjaman Anda berikut denda sebesar {{due_amount}}. Cara bayar, cek aplikasi.",
            parameter="{name,due_amount}",
        )
    pedemtl_sms_dpd_plus3, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. 99% pelanggan kami sdh melakukan pembayaran angsuran per hari ini. "
                            "Tanggung jawab di hal kecil akan membawa kepercayaan untuk hal besar. "
                            "Bayar Angsuran {{payment_number}} Pede Pinter Anda {{due_amount}} segera. Cara bayar,  "
                            "cek aplikasi.",
            parameter="{name,payment_number,due_amount}",
        )
    pedestl_sms_dpd_plus3, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. 99% pelanggan kami sdh melakukan pembayaran Pinjaman PEDE Pinter per hari ini. "
                            "Tanggung jawab di hal kecil akan membawa kepercayaan untuk hal besar. Bayar Pinjaman Anda "
                            "berikut denda sebesar {{due_amount}}. Cara bayar, cek aplikasi.",
            parameter="{name,due_amount}",
        )
    laku6mtl_sms_dpd_plus3, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. 99% pelanggan kami sdh melakukan pembayaran angsuran per hari ini. "
                            "Tanggung jawab di hal kecil akan membawa kepercayaan untuk hal besar. "
                            "Bayar Angsuran {{payment_number}} Anda {{due_amount}} segera. Cara bayar,  "
                            "cek aplikasi Prio Rental.",
            parameter="{name,payment_number,due_amount}",
        )
    streamlined_communication_for_sms_dpd_plus3 = StreamlinedCommunication.objects.get_or_create(
        message=sms_dpd_plus3,
        status="Inform customer MTL product dpd +3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_dpd_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )
    streamlined_communication_for_stl_sms_dpd_plus3 = StreamlinedCommunication.objects.get_or_create(
        message=stl_sms_dpd_plus3,
        status="Inform customer STL product dpd +3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='stl_sms_dpd_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )
    streamlined_communication_for_pedemtl_sms_dpd_plus3 = StreamlinedCommunication.objects.get_or_create(
        message=pedemtl_sms_dpd_plus3,
        status="Inform customer PEDE MTL product dpd +3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedemtl_sms_dpd_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )
    streamlined_communication_for_pedestl_sms_dpd_plus3 = StreamlinedCommunication.objects.get_or_create(
        message=pedestl_sms_dpd_plus3,
        status="Inform customer PEDE STL product dpd +3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedestl_sms_dpd_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )
    streamlined_communication_for_laku6mtl_sms_dpd_plus3 = StreamlinedCommunication.objects.get_or_create(
        message=laku6mtl_sms_dpd_plus3,
        status="Inform customer Laku6 MTL product dpd +3",
        communication_platform=CommunicationPlatform.SMS,
        template_code='laku6mtl_sms_dpd_+3',
        dpd=3,
        description="this SMS called in sms_payment_dpd_3"
    )
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_dpd_5
    sms_ptp_plus5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{name}}, Kami blm trma pmbayaran Anda smp saat ini. Segera bayar {{due_amount}} "
                            "sblm kami hub perusahaan & kerabat Anda. Trm ksh",
            parameter="{name,due_amount}",
        )
    sms_dpd_plus5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. Angsuran JULO anda sudah TERLAMBAT 5 hari. Bantu kami untuk membantu Anda, "
                            "hubungi kami di collections@julo.co.id, Segera bayar angsuran {{payment_number}} "
                            "berikut denda sebesar {{due_amount}}. Cara bayar, cek aplikasi.",
            parameter="{name,payment_number,due_amount}",
        )
    stl_sms_dpd_plus5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. Angsuran JULO anda sudah TERLAMBAT 5 hari. Bantu kami untuk membantu Anda, "
                            "hubungi kami di collections@julo.co.id, Bayar Pinjaman Anda berikut "
                            "denda sebesar {{due_amount}}. Cara bayar,  cek aplikasi.",
            parameter="{name,due_amount}",
        )
    pedemtl_sms_dpd_plus5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. Angsuran JULO anda sudah TERLAMBAT 5 hari. Bantu kami untuk membantu Anda, "
                            "hubungi kami di collections@julo.co.id, Segera bayar angsuran {{payment_number}} berikut "
                            "denda sebesar {{due_amount}}. Cara bayar, cek aplikasi PEDE.",
            parameter="{name,payment_number,due_amount}",
        )
    pedestl_sms_dpd_plus5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. Angsuran JULO anda sudah TERLAMBAT 5 hari. Bantu kami untuk membantu Anda, "
                            "hubungi kami di collections@julo.co.id, Bayar Pinjaman Anda berikut "
                            "denda sebesar {{due_amount}}. Cara bayar,  cek aplikasi PEDE.",
            parameter="{name,due_amount}",
        )
    laku6mtl_sms_dpd_plus5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. Angsuran JULO anda sudah TERLAMBAT 5 hari. Bantu kami untuk membantu Anda, "
                            "hubungi kami di collections@julo.co.id, Segera bayar angsuran {{payment_number}} "
                            "berikut denda sebesar {{due_amount}}. Cara bayar, cek aplikasi Prio Rental.",
            parameter="{name,payment_number,due_amount}",
        )
    for i in [5, 7, 10, 21]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=sms_ptp_plus5,
            status="Inform customer have PTP date product dpd +{}".format(i),
            communication_platform=CommunicationPlatform.SMS,
            template_code='sms_ptp_+5',
            dpd=i,
            description="this SMS called in sms_payment_dpd_{}".format(i)
        )
    streamlined_communication_for_sms_dpd_plus5 = StreamlinedCommunication.objects.get_or_create(
        message=sms_dpd_plus5,
        status="Inform customer MTL product dpd +5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_dpd_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )
    streamlined_communication_for_stl_sms_dpd_plus5 = StreamlinedCommunication.objects.get_or_create(
        message=stl_sms_dpd_plus5,
        status="Inform customer STL product dpd +5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='stl_sms_dpd_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )
    streamlined_communication_for_pedemtl_sms_dpd_plus5 = StreamlinedCommunication.objects.get_or_create(
        message=pedemtl_sms_dpd_plus5,
        status="Inform customer PEDE MTL product dpd +5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedemtl_sms_dpd_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )
    streamlined_communication_for_pedestl_sms_dpd_plus5 = StreamlinedCommunication.objects.get_or_create(
        message=pedestl_sms_dpd_plus5,
        status="Inform customer PEDE STL product dpd +5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedestl_sms_dpd_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )
    streamlined_communication_for_laku6mtl_sms_dpd_plus5 = StreamlinedCommunication.objects.get_or_create(
        message=laku6mtl_sms_dpd_plus5,
        status="Inform customer Laku6 MTL product dpd +5",
        communication_platform=CommunicationPlatform.SMS,
        template_code='laku6mtl_sms_dpd_+5',
        dpd=5,
        description="this SMS called in sms_payment_dpd_5"
    )
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_dpd_7
    sms_dpd_plus7, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}} menunda pembayaran yang dilakukan oleh orang mampu merupakan suatu ketidakadilan, "
                            "segera bayar kewajiban Anda, cek aplikasi.",
            parameter="{name}",
        )
    sms_pede_dpd_plus7, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}} menunda pembayaran yang dilakukan oleh orang mampu merupakan suatu ketidakadilan, "
                            "segera bayar kewajiban Anda, cek aplikasi PEDE.",
            parameter="{name}",
        )
    sms_laku6_dpd_plus7, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}} menunda pembayaran yang dilakukan oleh orang mampu merupakan suatu ketidakadilan, "
                            "segera bayar kewajiban Anda, cek aplikasi Prio Rental.",
            parameter="{name}",
        )
    for template_code, product_name in [('sms_dpd_+7', 'MTL'), ('stl_sms_dpd_+7', 'STL')]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=sms_dpd_plus7,
            status="Inform customer {} product dpd +7".format(product_name),
            communication_platform=CommunicationPlatform.SMS,
            template_code=template_code,
            dpd=7,
            description="this SMS called in sms_payment_dpd_7"
        )
    for template_code, product_name in [('pedemtl_sms_dpd_+7', 'PEDE MTL'), ('pedestl_sms_dpd_+7', 'PEDE STL')]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=sms_pede_dpd_plus7,
            status="Inform customer {} product dpd +7".format(product_name),
            communication_platform=CommunicationPlatform.SMS,
            template_code=template_code,
            dpd=7,
            description="this SMS called in sms_payment_dpd_7"
        )
    streamlined_communication_for_sms_laku6_dpd_plus7 = StreamlinedCommunication.objects.get_or_create(
        message=sms_laku6_dpd_plus7,
        status="Inform customer laku6 product dpd +7",
        communication_platform=CommunicationPlatform.SMS,
        template_code='laku6mtl_sms_dpd_+7',
        dpd=7,
        description="this SMS called in sms_payment_dpd_7"
    )
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_dpd_10
    pedestl_sms_dpd_plus10, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}} segera bayar Pinjaman PEDE Pinter Anda berikut denda sebesar {{due_amount}}. "
                            "Cara bayar, cek aplikasi PEDE.",
            parameter="{name,due_amount}",
        )
    stl_sms_dpd_plus10, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}} segera bayar Pinjaman Anda berikut denda sebesar {{due_amount}}. "
                            "Cara bayar, cek aplikasi.",
            parameter="{nam,due_amount}",
        )
    streamlined_communication_for_pedestl_sms_dpd_plus10 = StreamlinedCommunication.objects.get_or_create(
        message=pedestl_sms_dpd_plus10,
        status="Inform customer PEDE STL product dpd +10",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedestl_sms_dpd_+10',
        dpd=10,
        description="this SMS called in sms_payment_dpd_10"
    )
    streamlined_communication_for_pedestl_sms_dpd_plus10 = StreamlinedCommunication.objects.get_or_create(
        message=stl_sms_dpd_plus10,
        status="Inform customer STL product dpd +10",
        communication_platform=CommunicationPlatform.SMS,
        template_code='stl_sms_dpd_+10',
        dpd=10,
        description="this SMS called in sms_payment_dpd_10"
    )
    # juloserver.julo.clients.sms.JuloSmsClient.sms_payment_dpd_21
    pedemtl_sms_dpd_plus21, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. Lunasi tunggakan JULO Anda dan jaga kesempatan Anda untuk mengajukan pinjaman "
                            "kembali di aplikasi PEDE. Hubungi collections@julo.co.id",
            parameter="{name}",
        )
    laku6mtl_sms_dpd_plus21, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. Lunasi tunggakan JULO Anda di aplikasi Prio Rental dan jaga kesempatan Anda "
                            "untuk mengajukan pinjaman kembali. Hubungi collections@julo.co.id",
            parameter="{name}",
        )
    sms_dpd_plus21, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="{{name}}. Lunasi tunggakan JULO Anda dan jaga kesempatan Anda untuk mengajukan pinjaman "
                            "kembali. Hubungi collections@julo.co.id",
            parameter="{name}",
        )
    streamlined_communication_for_pedemtl_sms_dpd_plus21 = StreamlinedCommunication.objects.get_or_create(
        message=pedemtl_sms_dpd_plus21,
        status="Inform customer PEDE MTL product dpd +21",
        communication_platform=CommunicationPlatform.SMS,
        template_code='pedemtl_sms_dpd_+21',
        dpd=21,
        description="this SMS called in sms_payment_dpd_21"
    )
    streamlined_communication_for_sms_dpd_plus21 = StreamlinedCommunication.objects.get_or_create(
        message=sms_dpd_plus21,
        status="Inform customer Laku6 MTL product dpd +21",
        communication_platform=CommunicationPlatform.SMS,
        template_code='laku6mtl_sms_dpd_+21',
        dpd=21,
        description="this SMS called in sms_payment_dpd_21"
    )
    streamlined_communication_for_laku6mtl_sms_dpd_plus21 = StreamlinedCommunication.objects.get_or_create(
        message=laku6mtl_sms_dpd_plus21,
        status="Inform customer MTL product dpd +21",
        communication_platform=CommunicationPlatform.SMS,
        template_code='sms_dpd_+21',
        dpd=21,
        description="this SMS called in sms_payment_dpd_21"
    )
    # WA
    wa_stl_payment_reminder, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{fullname}}, sy Ani dr JULO. Mengingatkan pinjaman Anda {{due_amount}} jatuh tempo "
                            "pada {{due_date}}.\r\n\r\nSilakan lakukan pembayaran ke Virtual Account "
                            "{{bank_name}}: {{virtual_account_number}}.\r\n\r\nWhatsapp pertanyaan anda ke "
                            "{{collection_whatsapp}}. Cek aplikasi untuk metode pembayaran lainnya. "
                            "Informasi cara bayar cek di www.julo.co.id/cara-membayar.html",
            parameter="{fullname,due_amount,due_date,bank_name,virtual_account_number,collection_whatsapp}",
        )
    wa_mtl_payment_reminder, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{fullname}}, sy Ani dr JULO. Mengingatkan angsuran ke-{{payment_number}} Anda "
                            "{{due_amount}} jatuh tempo pada {{due_date}}.\r\n\r\nSilakan lakukan pembayaran ke "
                            "Virtual Account {{bank_name}}:  {{virtual_account_number}}.\r\n\r\nBayar sebelum "
                            "{{due_date_minus_4}} untuk mendapat Cashback sebesar {cashback_amount}.\r\n\r\nWhatsapp "
                            "pertanyaan anda ke {{collection_whatsapp}}. Cek aplikasi untuk metode pembayaran lainnya. "
                            "Informasi cara bayar cek di www.julo.co.id/cara-membayar.html",
            parameter="{fullname,due_amount,due_date,bank_name,virtual_account_number,due_date_minus_4,"
                      "cashback_amount,collection_whatsapp}",
        )
    wa_pede_payment_reminder, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Yth {{fullname}}, Kami dari JULO. Mengingatkan pinjaman dari Aplikasi PEDE (Ponsel Duit) "
                            "Anda angsuran ke-{{payment_number}} senilai {{due_amount}} jatuh tempo "
                            "pada {{due_date}}.\r\n\r\nSilakan lakukan pembayaran ke Virtual Account "
                            "{{bank_name}}:  {{virtual_account_number}}.\r\n\r\nWhatsapp pertanyaan anda ke "
                            "087886904744 atau email collections@julo.co.id. Cek aplikasi "
                            "com.pede.emoney://julo untuk metode pembayaran lainnya. "
                            "Informasi cara bayar cek di julo.co.id/r/pede",
            parameter="{fullname,payment_number,due_amount,due_date,bank_name,virtual_account_number}",
        )
    wa_data = [
        {
            'message': wa_stl_payment_reminder,
            'status': 'Inform customer STL product dpd {}',
            'template_code': 'wa_stl_payment_reminder'
        },
        {
            'message': wa_mtl_payment_reminder,
            'status': 'Inform customer MTL product dpd {}',
            'template_code': 'wa_mtl_payment_reminder'
        },
        {
            'message': wa_pede_payment_reminder,
            'status': 'Inform customer PEDE product dpd {}',
            'template_code': 'wa_pede_payment_reminder'
        },

    ]
    for i in [-5, -3, -1, 0]:
        for item in wa_data:
            streamlined_communication_wa = StreamlinedCommunication.objects.get_or_create(
                message=item['message'],
                status=item['status'].format(i),
                communication_platform=CommunicationPlatform.WA,
                template_code=item['template_code'],
                dpd=i,
                description="this WA called in send_wa_payment_reminder"
            )
    # EMAIL
    email_reminder_in2, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content='<!doctype html><html xmlns="http://www.w3.org/1999/xhtml" '
                            'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
                            '<head>  <title></title>  <meta http-equiv="X-UA-Compatible" content="IE=edge">  '
                            '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">  '
                            '<meta name="viewport" content="width=device-width, initial-scale=1.0">  '
                            '<style type="text/css">  #outlook a {    padding: 0;  }  .ReadMsgBody {    width: 100%;  }  .ExternalClass {    width: 100%;  }  .ExternalClass * {    line-height: 100%;  }  body {    margin: 0;    padding: 0;    -webkit-text-size-adjust: 100%;    -ms-text-size-adjust: 100%;  }  table,  td {    border-collapse: collapse;    mso-table-lspace: 0pt;    mso-table-rspace: 0pt;  }  img {    border: 0;    height: auto;    line-height: 100%;    outline: none;    text-decoration: none;    -ms-interpolation-mode: bicubic;  }  p {    display: block;    margin: 13px 0;  }  #julo-website a {    color: white;    text-decoration: none;  }  </style>  <style type="text/css">  @media only screen and (max-width:480px) {    @-ms-viewport {      width: 320px;    }    @viewport {      width: 320px;    }  }  </style><link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700" rel="stylesheet" type="text/css"><style type="text/css">@import url(https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700);</style><style type="text/css">@media only screen and (min-width:480px) {  .mj-column-per-100 {    width: 100%!important;  }  .mj-column-px-50 {    width: 50px!important;  }}</style></head><body style="background: #E1E8ED;">  <div class="mj-container">    <div style="margin:0px auto;max-width:600px;background:linear-gradient(to right, #00ACF0, #13637b);">      <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:linear-gradient(to right, #00ACF0, #13637b);" align="center" border="0">        <tbody>          <tr>            <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">              <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">                  <tbody>                    <tr>                      <td style="word-wrap:break-word;font-size:0px;padding-left:20px;" align="left">                        <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-spacing:0px;" align="left" border="0">                          <tbody>                            <tr>                              <td style="width:100px;"><img alt="" title="" height="auto" src="https://www.julo.co.id/images/JULO_logo_white.png" style="border:none;border-radius:0px;display:block;font-size:13px;outline:none;text-decoration:none;width:120%;height:auto;" width="100"></td>                            </tr>                          </tbody>                        </table>                      </td>                      <td style="font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:12px;padding-top:25px;padding-right:25px;" align="right">                      <p id="julo-website" style="color:white;text-decoration:none;">www.julo.co.id</p></td>                    </tr>                  </tbody>                </table>              </div>          </td>        </tr>      </tbody>    </table>  </div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:20px;line-height:120%;text-align:left;">Yth {{fullname}},</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Saya Ani dari JULO ingin mengingatkan hari ini terakhir untuk kesempatan Ekstra Cashback. Apabila Anda membayar angsuran tepat waktu, anda akan mendapatkan cashback sebesar {{payment_cashback_amount}}. Tapi jika anda bayarkan hari ini {{due_date_minus_2}}, Maka anda akan mendapatkan Ekstra Cashback sebesar {{cashback_multiplier}} kali lipat.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Angsuran {{payment_number}} Anda akan jatuh tempo pada {{due_date}} sejumlah {{due_amount}}.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Silakan melakukan pembayaran ke Virtual Account {{bank_code_text}} {{bank_name}}  {{account_number}}.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Untuk metode pembayaran lainnya harap cek aplikasi.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Untuk informasi cara bayar cek di <a href="http://julo.co.id/cara-membayar.html">sini</a></div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;">                    <div style="font-size:1px;line-height:5px;white-space:nowrap;"> </div>                  </td>                </tr>              </tbody>            </table>          </div>      </td>    </tr>  </tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Terima kasih dan salam,</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left;">JULO</div>                  </td>                </tr>              </tbody>            </table>          </div>      </td>    </tr>  </tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <p style="font-size:1px;margin:0px auto;border-top:1px solid #f8f8f8;width:100%;"></p>        <div class="mj-column-px-NaN outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">            <tbody>              <tr>                <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                  <div style="cursor:auto;color:grey;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:13px;line-height:120%;text-align:left;">Email ini dibuat secara otomatis. Mohon tidak mengirimkan balasan ke email ini</div>                </td>              </tr>            </tbody>          </table>        </div>    </td>  </tr></tbody></table></div><div style="margin:0px auto;max-width:600px;background:#222222;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:#222222;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center">                    <div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:10px;font-weight:400;line-height:120%;text-align:center;">Pinjaman Cerdas Dari Smartphone Anda</div>                    <div><a href="https://play.google.com/store/apps/details?id=com.julofinance.juloapp" style="color:white;text-decoration:none;" target="_blank">Google Play Store <img src="https://www.julo.co.id/assets/images/play_store.png" alt="google-play" style="width:20%;padding-top:10px; display:inline; align:middle;text-decoration:none;border-bottom: #f6f6f6"></a></div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;Border-bottom:10px" align="center">                    <div>                      <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                        <tbody>                          <tr>                            <td style="padding:4px;vertical-align:middle;">                              <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                                <tbody>                                  <tr>                                    <td style="vertical-align:middle;">                                      <a href="https://www.instagram.com/juloindonesia/" target="_blank"><img alt="instagram" height="NaN" src="https://www.julo.co.id/images/icon_instagram.png" style="display:block;border-radius:3px;width:16px;" width="NaN"></a>                                    </td>                                  </tr>                                </tbody>                              </table>                            </td>                          </tr>                        </tbody>                      </table>                    <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://www.facebook.com/juloindonesia/" target="_blank"><img alt="facebook" height="NaN" src="https://www.julo.co.id/images/icon_facebook.png" style="display:block;border-radius:3px;width:18px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;width:;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://twitter.com/juloindonesia" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_twitter.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://www.youtube.com/channel/UCA9WsBMIg3IHxwVA-RvSctA" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_youtube.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  </td></tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center">                    <div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:9px;font-weight:300;line-height:120%;text-align:center;">©2019 JULO | All rights reserved </div>                  </td>                </div>              </td>            </tr>          </tbody>        </table>      </div>  </td></tr></tbody></table></div></div></body></html>',
            parameter="{fullname,payment_cashback_amount,due_date_minus_2,cashback_multiplier,payment_number,due_date,"
                      "due_amount,bank_code_text,bank_name,account_number}",
        )
    email_reminder_in4, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content='<!doctype html><html xmlns="http://www.w3.org/1999/xhtml" '
                            'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">'
                            '<head>  <title></title>  <meta http-equiv="X-UA-Compatible" content="IE=edge">  '
                            '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">  <meta name="viewport" content="width=device-width, initial-scale=1.0">  <style type="text/css">  #outlook a {    padding: 0;  }  .ReadMsgBody {    width: 100%;  }  .ExternalClass {    width: 100%;  }  .ExternalClass * {    line-height: 100%;  }  body {    margin: 0;    padding: 0;    -webkit-text-size-adjust: 100%;    -ms-text-size-adjust: 100%;  }  table,  td {    border-collapse: collapse;    mso-table-lspace: 0pt;    mso-table-rspace: 0pt;  }  img {    border: 0;    height: auto;    line-height: 100%;    outline: none;    text-decoration: none;    -ms-interpolation-mode: bicubic;  }  p {    display: block;    margin: 13px 0;  }  #julo-website a {    color: white;    text-decoration: none;  }  </style>  <style type="text/css">  @media only screen and (max-width:480px) {    @-ms-viewport {      width: 320px;    }    @viewport {      width: 320px;    }  }  </style><link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700" rel="stylesheet" type="text/css"><style type="text/css">@import url(https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700);</style><style type="text/css">@media only screen and (min-width:480px) {  .mj-column-per-100 {    width: 100%!important;  }  .mj-column-px-50 {    width: 50px!important;  }}</style></head><body style="background: #E1E8ED;">  <div class="mj-container">    <div style="margin:0px auto;max-width:600px;background:linear-gradient(to right, #00ACF0, #13637b);">      <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:linear-gradient(to right, #00ACF0, #13637b);" align="center" border="0">        <tbody>          <tr>            <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">              <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">                  <tbody>                    <tr>                      <td style="word-wrap:break-word;font-size:0px;padding-left:20px;" align="left">                        <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-spacing:0px;" align="left" border="0">                          <tbody>                            <tr>                              <td style="width:100px;"><img alt="" title="" height="auto" src="https://www.julo.co.id/images/JULO_logo_white.png" style="border:none;border-radius:0px;display:block;font-size:13px;outline:none;text-decoration:none;width:120%;height:auto;" width="100"></td>                            </tr>                          </tbody>                        </table>                      </td>                      <td style="font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:12px;padding-top:25px;padding-right:25px;" align="right">                      <p id="julo-website" style="color:white;text-decoration:none;">www.julo.co.id</p></td>                    </tr>                  </tbody>                </table>              </div>          </td>        </tr>      </tbody>    </table>  </div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:20px;line-height:120%;text-align:left;">Yth {{fullname}},</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Saya Ani dari JULO ingin menyampaikan kabar baik! Apabila Anda membayar angsuran tepat waktu, anda akan mendapatkan cashback sebesar {{payment_cashback_amount}}. Tapi jika anda bayarkan hari ini {{due_date_minus_4}}, Anda akan mendapatkan Ekstra Cashback sebesar {{cashback_multiplier}} kali lipat.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">90% dari nasabah JULO telah berhasil mendapatkan Ekstra Cashback ini dengan membayar lebih awal.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Angsuran {{payment_number}} Anda akan jatuh tempo pada {{due_date}} sejumlah {{due_amount}}.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Silakan melakukan pembayaran ke Virtual Account {{bank_code_text}} {{bank_name}}  {{account_number}}.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Untuk metode pembayaran lainnya harap cek aplikasi.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Untuk informasi cara bayar cek di <a href="http://julo.co.id/cara-membayar.html">sini</a></div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;">                    <div style="font-size:1px;line-height:5px;white-space:nowrap;"> </div>                  </td>                </tr>              </tbody>            </table>          </div>      </td>    </tr>  </tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Terima kasih dan salam,</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left;">JULO</div>                  </td>                </tr>              </tbody>            </table>          </div>      </td>    </tr>  </tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <p style="font-size:1px;margin:0px auto;border-top:1px solid #f8f8f8;width:100%;"></p>        <div class="mj-column-px-NaN outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">            <tbody>              <tr>                <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                  <div style="cursor:auto;color:grey;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:13px;line-height:120%;text-align:left;">Email ini dibuat secara otomatis. Mohon tidak mengirimkan balasan ke email ini</div>                </td>              </tr>            </tbody>          </table>        </div>    </td>  </tr></tbody></table></div><div style="margin:0px auto;max-width:600px;background:#222222;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:#222222;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center">                    <div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:10px;font-weight:400;line-height:120%;text-align:center;">Pinjaman Cerdas Dari Smartphone Anda</div>                    <div><a href="https://play.google.com/store/apps/details?id=com.julofinance.juloapp" style="color:white;text-decoration:none;" target="_blank">Google Play Store <img src="https://www.julo.co.id/assets/images/play_store.png" alt="google-play" style="width:20%;padding-top:10px; display:inline; align:middle;text-decoration:none;border-bottom: #f6f6f6"></a></div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;Border-bottom:10px" align="center">                    <div>                      <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                        <tbody>                          <tr>                            <td style="padding:4px;vertical-align:middle;">                              <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                                <tbody>                                  <tr>                                    <td style="vertical-align:middle;">                                      <a href="https://www.instagram.com/juloindonesia/" target="_blank"><img alt="instagram" height="NaN" src="https://www.julo.co.id/images/icon_instagram.png" style="display:block;border-radius:3px;width:16px;" width="NaN"></a>                                    </td>                                  </tr>                                </tbody>                              </table>                            </td>                          </tr>                        </tbody>                      </table>                    <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://www.facebook.com/juloindonesia/" target="_blank"><img alt="facebook" height="NaN" src="https://www.julo.co.id/images/icon_facebook.png" style="display:block;border-radius:3px;width:18px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;width:;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://twitter.com/juloindonesia" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_twitter.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://www.youtube.com/channel/UCA9WsBMIg3IHxwVA-RvSctA" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_youtube.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  </td></tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center">                    <div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:9px;font-weight:300;line-height:120%;text-align:center;">©2019 JULO | All rights reserved </div>                  </td>                </div>              </td>            </tr>          </tbody>        </table>      </div>  </td></tr></tbody></table></div></div></body></html>',
            parameter="{fullname,payment_cashback_amount,due_date_minus_4,cashback_multiplier,payment_number,due_date,"
                      "due_amount,bank_code_text,bank_name,account_number}",
        )
    stl_email_reminder_in2, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content='<!doctype html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><head>  <title></title>  <meta http-equiv="X-UA-Compatible" content="IE=edge">  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">  <meta name="viewport" content="width=device-width, initial-scale=1.0">  <style type="text/css">  #outlook a {    padding: 0;  }  .ReadMsgBody {    width: 100%;  }  .ExternalClass {    width: 100%;  }  .ExternalClass * {    line-height: 100%;  }  body {    margin: 0;    padding: 0;    -webkit-text-size-adjust: 100%;    -ms-text-size-adjust: 100%;  }  table,  td {    border-collapse: collapse;    mso-table-lspace: 0pt;    mso-table-rspace: 0pt;  }  img {    border: 0;    height: auto;    line-height: 100%;    outline: none;    text-decoration: none;    -ms-interpolation-mode: bicubic;  }  p {    display: block;    margin: 13px 0;  }  #julo-website a {    color: white;    text-decoration: none;  }  </style>  <style type="text/css">  @media only screen and (max-width:480px) {    @-ms-viewport {      width: 320px;    }    @viewport {      width: 320px;    }  }  </style><link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700" rel="stylesheet" type="text/css"><style type="text/css">@import url(https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700);</style><style type="text/css">@media only screen and (min-width:480px) {  .mj-column-per-100 {    width: 100%!important;  }  .mj-column-px-50 {    width: 50px!important;  }}</style></head><body style="background: #E1E8ED;">  <div class="mj-container">    <div style="margin:0px auto;max-width:600px;background:linear-gradient(to right, #00ACF0, #13637b);">      <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:linear-gradient(to right, #00ACF0, #13637b);" align="center" border="0">        <tbody>          <tr>            <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">              <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">                  <tbody>                    <tr>                      <td style="word-wrap:break-word;font-size:0px;padding-left:20px;" align="left">                        <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-spacing:0px;" align="left" border="0">                          <tbody>                            <tr>                              <td style="width:100px;"><img alt="" title="" height="auto" src="https://www.julo.co.id/images/JULO_logo_white.png" style="border:none;border-radius:0px;display:block;font-size:13px;outline:none;text-decoration:none;width:120%;height:auto;" width="100"></td>                            </tr>                          </tbody>                        </table>                      </td>                      <td style="font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:12px;padding-top:25px;padding-right:25px;" align="right">                      <p id="julo-website" style="color:white;text-decoration:none;">www.julo.co.id</p></td>                    </tr>                  </tbody>                </table>              </div>          </td>        </tr>      </tbody>    </table>  </div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:20px;line-height:120%;text-align:left;">Yth {{fullname}},</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Saya Ani dari JULO ingin mengingatkan Pinjaman Anda akan jatuh tempo pada {{due_date}} sejumlah {{due_amount}}.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Silakan melakukan pembayaran ke Virtual Account {{bank_code_text}} {{bank_name}}  {{account_number}}.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Untuk metode pembayaran lainnya harap cek aplikasi.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Untuk informasi cara bayar cek di <a href="http://julo.co.id/cara-membayar.html">sini</a></div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;">                    <div style="font-size:1px;line-height:5px;white-space:nowrap;"> </div>                  </td>                </tr>              </tbody>            </table>          </div>      </td>    </tr>  </tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Terima kasih dan salam,</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left;">JULO</div>                  </td>                </tr>              </tbody>            </table>          </div>      </td>    </tr>  </tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <p style="font-size:1px;margin:0px auto;border-top:1px solid #f8f8f8;width:100%;"></p>        <div class="mj-column-px-NaN outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">            <tbody>              <tr>                <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                  <div style="cursor:auto;color:grey;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:13px;line-height:120%;text-align:left;">Email ini dibuat secara otomatis. Mohon tidak mengirimkan balasan ke email ini</div>                </td>              </tr>            </tbody>          </table>        </div>    </td>  </tr></tbody></table></div><div style="margin:0px auto;max-width:600px;background:#222222;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:#222222;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center">                    <div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:10px;font-weight:400;line-height:120%;text-align:center;">Pinjaman Cerdas Dari Smartphone Anda</div>                    <div><a href="https://play.google.com/store/apps/details?id=com.julofinance.juloapp" style="color:white;text-decoration:none;" target="_blank">Google Play Store <img src="https://www.julo.co.id/assets/images/play_store.png" alt="google-play" style="width:20%;padding-top:10px; display:inline; align:middle;text-decoration:none;border-bottom: #f6f6f6"></a></div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;Border-bottom:10px" align="center">                    <div>                      <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                        <tbody>                          <tr>                            <td style="padding:4px;vertical-align:middle;">                              <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                                <tbody>                                  <tr>                                    <td style="vertical-align:middle;">                                      <a href="https://www.instagram.com/juloindonesia/" target="_blank"><img alt="instagram" height="NaN" src="https://www.julo.co.id/images/icon_instagram.png" style="display:block;border-radius:3px;width:16px;" width="NaN"></a>                                    </td>                                  </tr>                                </tbody>                              </table>                            </td>                          </tr>                        </tbody>                      </table>                    <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://www.facebook.com/juloindonesia/" target="_blank"><img alt="facebook" height="NaN" src="https://www.julo.co.id/images/icon_facebook.png" style="display:block;border-radius:3px;width:18px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;width:;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://twitter.com/juloindonesia" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_twitter.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://www.youtube.com/channel/UCA9WsBMIg3IHxwVA-RvSctA" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_youtube.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  </td></tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center">                    <div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:9px;font-weight:300;line-height:120%;text-align:center;">©2019 JULO | All rights reserved </div>                  </td>                </div>              </td>            </tr>          </tbody>        </table>      '
                            '</div>  </td></tr></tbody></table></div></div></body></html>',
            parameter="{fullname,due_date,due_amount,bank_code_text,bank_name,account_number}",
        )
    stl_email_reminder_in4, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content='<!doctype html><html xmlns="http://www.w3.org/1999/xhtml" '
                            'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><head>  <title></title>  <meta http-equiv="X-UA-Compatible" content="IE=edge">  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">  <meta name="viewport" content="width=device-width, initial-scale=1.0">  <style type="text/css">  #outlook a {    padding: 0;  }  .ReadMsgBody {    width: 100%;  }  .ExternalClass {    width: 100%;  }  .ExternalClass * {    line-height: 100%;  }  body {    margin: 0;    padding: 0;    -webkit-text-size-adjust: 100%;    -ms-text-size-adjust: 100%;  }  table,  td {    border-collapse: collapse;    mso-table-lspace: 0pt;    mso-table-rspace: 0pt;  }  img {    border: 0;    height: auto;    line-height: 100%;    outline: none;    text-decoration: none;    -ms-interpolation-mode: bicubic;  }  p {    display: block;    margin: 13px 0;  }  #julo-website a {    color: white;    text-decoration: none;  }  </style>  <style type="text/css">  @media only screen and (max-width:480px) {    @-ms-viewport {      width: 320px;    }    @viewport {      width: 320px;    }  }  </style><link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700" rel="stylesheet" type="text/css"><style type="text/css">@import url(https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700);</style><style type="text/css">@media only screen and (min-width:480px) {  .mj-column-per-100 {    width: 100%!important;  }  .mj-column-px-50 {    width: 50px!important;  }}</style></head><body style="background: #E1E8ED;">  <div class="mj-container">    <div style="margin:0px auto;max-width:600px;background:linear-gradient(to right, #00ACF0, #13637b);">      <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:linear-gradient(to right, #00ACF0, #13637b);" align="center" border="0">        <tbody>          <tr>            <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">              <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">                  <tbody>                    <tr>                      <td style="word-wrap:break-word;font-size:0px;padding-left:20px;" align="left">                        <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-spacing:0px;" align="left" border="0">                          <tbody>                            <tr>                              <td style="width:100px;"><img alt="" title="" height="auto" src="https://www.julo.co.id/images/JULO_logo_white.png" style="border:none;border-radius:0px;display:block;font-size:13px;outline:none;text-decoration:none;width:120%;height:auto;" width="100"></td>                            </tr>                          </tbody>                        </table>                      </td>                      <td style="font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:12px;padding-top:25px;padding-right:25px;" align="right">                      <p id="julo-website" style="color:white;text-decoration:none;">www.julo.co.id</p></td>                    </tr>                  </tbody>                </table>              </div>          </td>        </tr>      </tbody>    </table>  </div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:20px;line-height:120%;text-align:left;">Yth {{fullname}},</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Saya Ani dari JULO ingin mengingatkan Pinjaman Anda akan jatuh tempo pada {{due_date}} sejumlah {{due_amount}}. 90% nasabah kami sudah melakukan pembayaran per hari ini.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Silakan melakukan pembayaran ke Virtual Account {{bank_code_text}} {{bank_name}}  {{account_number}}.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Untuk metode pembayaran lainnya harap cek aplikasi.</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Untuk informasi cara bayar cek di <a href="http://julo.co.id/cara-membayar.html">sini</a></div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;">                    <div style="font-size:1px;line-height:5px;white-space:nowrap;"> </div>                  </td>                </tr>              </tbody>            </table>          </div>      </td>    </tr>  </tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Terima kasih dan salam,</div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                    <div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left;">JULO</div>                  </td>                </tr>              </tbody>            </table>          </div>      </td>    </tr>  </tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <p style="font-size:1px;margin:0px auto;border-top:1px solid #f8f8f8;width:100%;"></p>        <div class="mj-column-px-NaN outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">            <tbody>              <tr>                <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left">                  <div style="cursor:auto;color:grey;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:13px;line-height:120%;text-align:left;">Email ini dibuat secara otomatis. Mohon tidak mengirimkan balasan ke email ini</div>                </td>              </tr>            </tbody>          </table>        </div>    </td>  </tr></tbody></table></div><div style="margin:0px auto;max-width:600px;background:#222222;">  <table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:#222222;" align="center" border="0">    <tbody>      <tr>        <td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;">          <div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;">            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0">              <tbody>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center">                    <div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:10px;font-weight:400;line-height:120%;text-align:center;">Pinjaman Cerdas Dari Smartphone Anda</div>                    <div><a href="https://play.google.com/store/apps/details?id=com.julofinance.juloapp" style="color:white;text-decoration:none;" target="_blank">Google Play Store <img src="https://www.julo.co.id/assets/images/play_store.png" alt="google-play" style="width:20%;padding-top:10px; display:inline; align:middle;text-decoration:none;border-bottom: #f6f6f6"></a></div>                  </td>                </tr>                <tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;Border-bottom:10px" align="center">                    <div>                      <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                        <tbody>                          <tr>                            <td style="padding:4px;vertical-align:middle;">                              <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                                <tbody>                                  <tr>                                    <td style="vertical-align:middle;">                                      <a href="https://www.instagram.com/juloindonesia/" target="_blank"><img alt="instagram" height="NaN" src="https://www.julo.co.id/images/icon_instagram.png" style="display:block;border-radius:3px;width:16px;" width="NaN"></a>                                    </td>                                  </tr>                                </tbody>                              </table>                            </td>                          </tr>                        </tbody>                      </table>                    <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://www.facebook.com/juloindonesia/" target="_blank"><img alt="facebook" height="NaN" src="https://www.julo.co.id/images/icon_facebook.png" style="display:block;border-radius:3px;width:18px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;width:;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://twitter.com/juloindonesia" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_twitter.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  <table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0">                      <tbody>                        <tr>                          <td style="padding:4px;vertical-align:middle;">                            <table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0">                              <tbody>                                <tr>                                  <td style="vertical-align:middle;">                                    <a href="https://www.youtube.com/channel/UCA9WsBMIg3IHxwVA-RvSctA" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_youtube.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a>                                  </td>                                </tr>                              </tbody>                            </table>                        </tr>                      </tbody>                    </table>                  </td></tr>                  <td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center">                    <div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:9px;font-weight:300;line-height:120%;text-align:center;">©2019 JULO | All rights reserved </div>                  </td>                </div>              </td>            </tr>          </tbody>        </table>      </div>  </td></tr></tbody></table></div></div></body></html>',
            parameter="{fullname,due_date,due_amount,bank_code_text,bank_name,account_number}",
        )
    streamlined_communication_for_email_reminder_in2 = StreamlinedCommunication.objects.get_or_create(
        message=email_reminder_in2,
        status="Inform customer MTL product dpd-2",
        communication_platform=CommunicationPlatform.EMAIL,
        template_code="email_reminder_in2",
        dpd=-2,
        description="this Email called in send_all_email_payment_reminders"
    )
    streamlined_communication_for_email_reminder_in4 = StreamlinedCommunication.objects.get_or_create(
        message=email_reminder_in4,
        status="Inform customer MTL product dpd-4",
        communication_platform=CommunicationPlatform.EMAIL,
        template_code="email_reminder_in4",
        dpd=-4,
        description="this Email called in send_all_email_payment_reminders"
    )
    streamlined_communication_for_stl_email_reminder_in2 = StreamlinedCommunication.objects.get_or_create(
        message=stl_email_reminder_in2,
        status="Inform customer STL product dpd-2",
        communication_platform=CommunicationPlatform.EMAIL,
        template_code="stl_email_reminder_in2",
        dpd=-2,
        description="this Email called in send_all_email_payment_reminders"
    )
    streamlined_communication_for_stl_email_reminder_in4 = StreamlinedCommunication.objects.get_or_create(
        message=stl_email_reminder_in4,
        status="Inform customer STL product dpd-4",
        communication_platform=CommunicationPlatform.EMAIL,
        template_code="stl_email_reminder_in4",
        dpd=-4,
        description="this Email called in send_all_email_payment_reminders"
    )


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0003_add_criteria_column'),
    ]

    operations = [
        migrations.RunPython(add_message_for_collection,
                             migrations.RunPython.noop)
    ]
