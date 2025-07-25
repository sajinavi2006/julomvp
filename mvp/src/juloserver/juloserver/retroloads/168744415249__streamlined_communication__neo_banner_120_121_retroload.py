# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-22 14:29
from __future__ import unicode_literals

from django.db import migrations

from juloserver.streamlined_communication.models import NeoBannerCard
from juloserver.julo.utils import upload_file_to_oss
from juloserver.julo.models import Image


class ImageNames(object):
    BANNER_120 = 'neo-banner/JULO-System_Icon_24-02.jpg'
    BANNER_121 = 'neo-banner/JULO-System_Icon_24-03.jpg'
    EXTENDED_BANNER = 'neo-banner/In_App_Approval_Potential_Limit_Illustration.png'


def create_image(image_source_id, image_type, image_url):
    image = Image()
    image.image_source = image_source_id
    image.image_type = image_type
    image.url = image_url
    image.save()


def retroload_neobanner_j1(_apps, _schema_editor):

    data_to_be_loaded = [
        {
            'statuses': '[120]',
            'product': 'J1',
            'template_card': 'B_BUTTON',
            'top_image': ImageNames.BANNER_120,
            'top_title': 'Tinggal Sedikit Lagi, Nih!',
            'top_message': 'Yuk, lampirkan dokumen yang dibutuhkan agar akunmu segera aktif dan dapat limit!',
            'button_text': 'Lengkapi Formulir',
            'button_action': 'document_mandatory_submission',
            'extended_image': ImageNames.EXTENDED_BANNER,
            'extended_title': 'Pasti kamu hepi, limit yang bisa kamu dapatkan hingga',
            'extended_message': None,
            'extended_button_text': 'Selengkapnya',
            'extended_button_action': 'pontential_limit_desc',
        },
        {
            'statuses': '[121]',
            'product': 'J1',
            'template_card': 'B_INFO',
            'top_image': ImageNames.BANNER_121,
            'top_title': 'Santai, Datamu Lagi Diverifikasi',
            'top_message': 'Cek kembali status pengajuanmu maksimum dalam 1 hari kerja, ya!',
            'button_text': 'Akunmu sedang diverifikasi',
            'button_action': None,
            'extended_image': ImageNames.EXTENDED_BANNER,
            'extended_title': 'Kalau udah terverifikasi, kamu bisa dapat limit hingga',
            'extended_message': None,
            'extended_button_text': 'Selengkapnya',
            'extended_button_action': 'pontential_limit_desc',
        }
    ]

    for data in data_to_be_loaded:
        neo_banner_card = NeoBannerCard.objects.create(**data)

        if data['top_image']:
            create_image(neo_banner_card.id, 'NEO_BANNER_TOP_BACKGROUND_IMAGE', data['top_image'])

        if data['extended_image']:
            create_image(neo_banner_card.id, 'NEO_BANNER_EXTENDED_BACKGROUND_IMAGE', data['extended_image'])


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_neobanner_j1, migrations.RunPython.noop)
    ]
