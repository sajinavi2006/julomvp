# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-10-13 11:11
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FaqSection, FaqItem

FAQ_DATA = [
    {
        "section_title": "Keamanan",
        "order_priority": 5,
        "is_security_faq": True,
        "items": [
            {
                "question": "Apakah informasi pribadi saya aman bersama JULO?",
                "description": 'Tentu saja. Sudah menjadi prioritas kami untuk mengamankan informasi pribadi milik kamu. Kami juga tidak menjual atau menyewakan informasi kamu kepada siapapun, kecuali dibutuhkan oleh instansi berwenang atau perlu diberikan kepada regulator.',
                "order_priority": 1,
                "show_security_faq_report_button": False
            },
            {
                "question": "Bagaimana cara saya terhindar dari penipuan berkedok JULO?",
                "description": 'Berikut 5 tips utama dari JULO supaya kamu terhindar dari penipuan berkedok JULO:\r\n\r\n1.Ingat bahwa JULO hanya akan menghubungi kamu melalui e-mail resmi dengan @julo.co.id, @juloperdana.co.id, atau @mkt.julo.co.id.\r\n2.Lakukan transaksi hanya dengan akun dan nomor Virtual Account yang tercantum pada aplikasi JULO. Jangan lakukan transaksi di luar aplikasi JULO.\r\n3.JULO tidak pernah meminta OTP atau PIN kamu.\r\n4.Mohon diperhatikan bahwa seluruh informasi dan komunikasi dari JULO terkait promosi, undian, maupun penanganan keluhan hanya akan dilakukan melalui halaman website, aplikasi, media komunikasi resmi, dan media sosial resmi JULO.\r\n5.Media sosial resmi JULO sebagai berikut:\r\n- Facebook @JULOIndonesia\r\n- Instagram @juloindonesia\r\n- Tiktok @juloindonesia\r\n- Linkedin JULO\r\n- Twitter @juloindonesia\r\n- Blog JULO',
                "order_priority": 2,
                "show_security_faq_report_button": True
            },
            {
                "question": "Bagaimana cara menghubungi Customer Service JULO?",
                "description": 'Kamu dapat menghubungi Customer Service JULO melalui:\r\n\r\n-Email : cs@julo.co.id\r\n-Live chat via aplikasi JULO\r\n-Call Center : 021 5091 9034 / 021 5091 9035\r\n-Whatsapp : 0813 1778 2070 / 0813 1778 2065 (Chat only)',
                "order_priority": 3,
                "show_security_faq_report_button": False
            },
        ]
    },
]


def add_security_faq_pre_populate_data(apps, schema_editor):
    # store new data
    for section in FAQ_DATA:
        section_obj = FaqSection.objects.get_or_create(title=section['section_title'],
                                                       order_priority=section['order_priority'],
                                                       is_security_faq=section['is_security_faq'])
        for item in section['items']:
            FaqItem.objects.get_or_create(
                section=section_obj[0],
                question=item['question'],
                defaults={
                    'description': item['description'],
                    'order_priority': item['order_priority'],
                    'show_security_faq_report_button': item['show_security_faq_report_button']
                }

            )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_security_faq_pre_populate_data, migrations.RunPython.noop),

    ]
