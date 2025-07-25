# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-09-09 16:03
from __future__ import unicode_literals

from django.db import migrations

from juloserver.streamlined_communication.models import NeoBannerCard
from juloserver.julo.models import Image


class ImageNames(object):
    BANNER_155 = 'neo-banner/JULO-System_Icon_24-03.jpg'
    HOURGLASS_ICON = 'neo-banner/ic-sand-Clock.png'
    X_ICON = 'neo-banner/ic-x-circle.png'


def create_image(image_source_id, image_type, image_url):
    image = Image()
    image.image_source = image_source_id
    image.image_type = image_type
    image.url = image_url
    image.save()


def retroload_neobanner_j1(_apps, _schema_editor):

    neo_banner_cards = NeoBannerCard.objects.filter(button_text='Akunmu sedang diverifikasi')
    for neo_banner_card in neo_banner_cards:
        neo_banner_card.update_safely(
            button_text='Akunmu masuk dalam daftar tunggu',
            badge_icon=ImageNames.HOURGLASS_ICON,
            badge_color='yellow',
        )

    neo_banner_card = NeoBannerCard.objects.get(button_text='Akunmu gagal diverifikasi')
    neo_banner_card.update_safely(badge_icon=ImageNames.X_ICON, badge_color='red')

    data_to_be_loaded = {
        'statuses': '[155]',
        'product': 'J1',
        'template_card': 'B_INFO',
        'top_image': ImageNames.BANNER_155,
        'top_title': 'Cek Berkala Status Aplikasimu, Ya!',
        'top_message': 'Saat ini akunmu dalam daftar tunggu verifikasi. Tenang, kami akan kabari kamu kalau akunmu sudah diverifikasi, oke?',
        'badge_icon': ImageNames.HOURGLASS_ICON,
        'badge_color': 'yellow',
        'button_text': 'Akunmu masuk dalam daftar tunggu',
        'button_action': None,
        'extended_image': None,
        'extended_title': None,
        'extended_message': None,
        'extended_button_text': None,
        'extended_button_action': None,
    }

    neo_banner_card = NeoBannerCard.objects.create(**data_to_be_loaded)

    create_image(
        neo_banner_card.id, 'NEO_BANNER_TOP_BACKGROUND_IMAGE', data_to_be_loaded['top_image']
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(retroload_neobanner_j1, migrations.RunPython.noop)]
