# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-07-21 09:36
from __future__ import unicode_literals

from django.db import migrations

from juloserver.streamlined_communication.models import NeoBannerCard
from juloserver.julo.models import Image


class ImageNames(object):
    BANNER_105_NO_SCORE = 'neo-banner/JULO-System_Icon_24-01.jpg'
    EXTENDED_BANNER = 'neo-banner/In_App_Approval_Potential_Limit_Illustration.png'


def create_image(image_source_id, image_type, image_url):
    image = Image()
    image.image_source = image_source_id
    image.image_type = image_type
    image.url = image_url
    image.save()


def retroload_neobanner_j1(_apps, _schema_editor):
    data = {
            'statuses': '[105_NO_SCORE]',
            'product': 'J1',
            'template_card': 'B_INFO',
            'top_image': ImageNames.BANNER_105_NO_SCORE,
            'top_title': 'Udah Gak Sabar Pakai Limitmu, Ya?',
            'top_message': 'Cek berkala aplikasi JULO kamu untuk tahu apakah akunmu siap digunakan, oke?',
            'button_text': 'Akunmu sedang diverifikasi',
            'button_action': None,
            'extended_image': ImageNames.EXTENDED_BANNER,
            'extended_title': 'Pasti kamu hepi, kamu bisa dapat limit hingga',
            'extended_message': 'Rp10.000.000',
            'extended_button_text': 'Selengkapnya',
            'extended_button_action': 'pontential_limit_desc',
    }

    neo_banner_card = NeoBannerCard.objects.create(**data)
    create_image(neo_banner_card.id, 'NEO_BANNER_TOP_BACKGROUND_IMAGE', data['top_image'])
    create_image(neo_banner_card.id, 'NEO_BANNER_EXTENDED_BACKGROUND_IMAGE', data['extended_image'])


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_neobanner_j1, migrations.RunPython.noop)
    ]
