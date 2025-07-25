# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-08-22 01:38
# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-22 14:29
from __future__ import unicode_literals

from django.db import migrations

from juloserver.streamlined_communication.models import NeoBannerCard
from juloserver.julo.models import Image


class ImageNames(object):
    BANNER = 'neo-banner/JULO-System_Icon_24-02.jpg'
    EXTENDED_BANNER = 'neo-banner/In_App_Approval_Potential_Limit_Illustration.png'


def create_image(image_source_id, image_type, image_url):
    image = Image()
    image.image_source = image_source_id
    image.image_type = image_type
    image.url = image_url
    image.save()


def retroload_neobanner(_apps, _schema_editor):

    data_to_be_loaded = [
        {
            'statuses': '[105_IS_AGENT_ASSISTED_SUBMISSION]',
            'product': 'J1',
            'template_card': 'B_BUTTON',
            'top_image': ImageNames.BANNER,
            'top_title': '1 Langkah Lagi untuk Bisa Dapet Limit!',
            'top_message': 'Cukup setujui Kebijakan Privasi biar akunmu diproses dan bisa dapet limit hingga Rp50 juta!',
            'button_text': 'Lihat Kebijakan Privasi',
            'button_action': '{{link_url}}',
            'button_action_type': 'redirect',
            'extended_image': None,
            'extended_title': None,
            'extended_message': None,
            'extended_button_text': None,
            'extended_button_action': None,
        },
    ]

    for data in data_to_be_loaded:
        neo_banner_card = NeoBannerCard.objects.create(**data)
        if data['top_image']:
            create_image(neo_banner_card.id, 'NEO_BANNER_TOP_BACKGROUND_IMAGE', data['top_image'])


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(retroload_neobanner, migrations.RunPython.noop)]
