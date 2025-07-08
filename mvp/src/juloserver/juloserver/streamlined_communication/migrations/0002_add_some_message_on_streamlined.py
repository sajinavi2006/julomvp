# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import ExperimentConst
from juloserver.streamlined_communication.constant import CommunicationPlatform


def add_message(apps, schema_editor):
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")
    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")
    email, _ = StreamlinedMessage.objects.get_or_create(
        message_content="Yth Bapak/ Ibu {first_name}, "
                        "pengajuan Anda telah melampaui batas waktu 2 minggu. "
                        "Mari ajukan kembali ke JULO! Kami, tim JULO, "
                        "siap melayani Anda! Salam, CS JULO 0822 1112 7334 (WA)",
    )
    sms, _ = StreamlinedMessage.objects.get_or_create(
        message_content="Yth Bpk/ Ibu {first_name}, mohon unggah {status_change_reason} "
                         "agar pengajuan segera diproses & tdk kadaluarsa. CS JULO 0822 1112 7334 (WA)"
    )
    pn, _ = StreamlinedMessage.objects.get_or_create(
        message_content="Selamat {{fullname}}! Pinjaman disetujui"
    )
    robocall, _ = StreamlinedMessage.objects.get_or_create(
        message_content="Yang terhormat {{ name_with_title }}, dapatkan ekstra kesbek "
                        "{{ cashback_multiplier }} kali lipat di julo, jika Anda membayar sebelum "
                        "{{ due_date_with_bonus }}.  Angsuran Anda ke {{ payment_number }} "
                        "sebesar {{ due_amount }} rupiah, akan jatuh tempo pada {{ due_date }}. "
                        "{{ promo_message }}. Terima Kasih. Silakan tekan 1 untuk mengkonfirmasi."
    )
    streamlinedcommunication_email = StreamlinedCommunication.objects.get_or_create(
        message=email,
        description='',
        status_code_id=111,
        communication_platform=CommunicationPlatform.EMAIL,
        status='Form submission abandoned',
    )
    streamlinedcommunication_sms = StreamlinedCommunication.objects.get_or_create(
        message=sms,
        description='',
        status_code_id=131,
        communication_platform=CommunicationPlatform.SMS,
        status='Application re-submission requested',
    )
    streamlinedcommunication_pn = StreamlinedCommunication.objects.get_or_create(
        message=pn,
        description='',
        status_code_id=140,
        communication_platform=CommunicationPlatform.PN,
        status='Offer made to customer',
    )
    streamlinedcommunication_robocall = StreamlinedCommunication.objects.get_or_create(
        message=robocall,
        description='',
        status_code_id=311,
        communication_platform=CommunicationPlatform.ROBOCALL,
        status='Payment due in 3 days',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_message,
                             migrations.RunPython.noop)
    ]
