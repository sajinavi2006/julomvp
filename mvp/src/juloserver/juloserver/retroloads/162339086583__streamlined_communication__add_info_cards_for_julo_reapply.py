# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-06-11 05:54
# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-30 08:56
from __future__ import unicode_literals

from builtins import str
from builtins import object
from django.db import migrations
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.utils import upload_file_to_oss
from juloserver.streamlined_communication.models import (InfoCardButtonProperty,
                                                         CardProperty,
                                                         InfoCardProperty,
                                                         StreamlinedMessage,
                                                         StreamlinedCommunication)
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.julo.models import StatusLookup, Image
from juloserver.streamlined_communication.services import create_and_upload_image_assets_for_streamlined
from django.conf import settings
praying_emoji = '\U0001F64F'
party_popper_emoji = '\U0001F389'
hourglass_emoji = '\U000023F3'
warning_emoji = '\U000026A0'
smile_emoji = '\U0001F642'
L_BUTTON = 'L.BUTTON'
R_BUTTON = 'R.BUTTON'
M_BUTTON = 'M.BUTTON'


class ImageNames(object):
    DESIGNS_REAL = 'info-card/data_bg.png'
    GROUP_3500 = 'info-card/group_3500.png'
    LAYER_3 = 'info-card/layer_3.png'
    LAYER_4 = 'info-card/layer_4.png'
    LAYER_5 = 'info-card/layer_5.png'
    LAYER_6 = 'info-card/layer_6.png'
    RECTANGLE_1489 = 'info-card/rectangle_1489.png'
    RECTANGLE_1489_2 = 'info-card/rectangle_1489_2.png'


def create_image(image_source_id, image_type, image_url):
    image = Image()
    image.image_source = image_source_id
    image.image_type = image_type
    image.url = image_url
    image.save()


def retroload_cards_data_grab(_apps, _schema_editor):
    data_to_be_loaded = [
        {
            # 'status': ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            'additional_condition': 'GRAB_INFO_CARD_JULO_CUSTOMER',
            'title': 'Form Anda telah kadaluarsa',
            'content': 'Silahkan lakukan pengisian form kembali untuk melanjutkan proses pengajuan.',
            'button': ["Ajukan Kembali"],
            'button_name': [M_BUTTON],
            'click_to': ["/reregister_grab_customer"],
            'template_type': '2',
            'card_number': 1,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': ImageNames.DESIGNS_REAL,
            'additional_images': [],
            'button_url': ['nil']
        },
        {
            # 'status': ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
            'additional_condition': 'GRAB_INFO_CARD_JULO_CUSTOMER_FAILED',
            'title': 'Mohon maaf🙏🏻',
            'content': 'Anda belum sesuai kriteria untuk dapat melakukan pinjaman.',
            'button': [],
            'button_name': [],
            'click_to': [],
            'template_type': '2',
            'card_number': 2,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': ImageNames.DESIGNS_REAL,
            'additional_images': [],
            'button_url': []
        },
    ]
    for data in data_to_be_loaded:
        button_1_properties = {'card_type': '1',
                               'title': data['title'],
                               'title_color': data['title_colour'],
                               'text_color': data['text_colour'],
                               'card_order_number': data['card_number']}
        button_2_properties = {'card_type': '2',
                               'title': data['title'],
                               'title_color': data['title_colour'],
                               'text_color': data['text_colour'],
                               'card_order_number': data['card_number']}
        button_3a_properties = {'card_type': '3a',
                                'card_destination': data['click_to'],
                                'title': data['title'],
                                'title_color': data['title_colour'],
                                'text_color': data['text_colour'],
                                'card_order_number': data['card_number']}
        button_3b_properties = {'card_type': '3b',
                                'title': data['title'],
                                'title_color': data['title_colour'],
                                'text_color': data['text_colour'],
                                'card_order_number': data['card_number']}
        if data['template_type'] == '1':
            info_card = InfoCardProperty.objects.create(**button_1_properties)
        elif data['template_type'] == '2':
            info_card = InfoCardProperty.objects.create(**button_2_properties)
        elif data['template_type'] == '3':
            info_card = InfoCardProperty.objects.create(**button_3b_properties)
        button_info_card = dict()
        if data['button']:
            for idx, image_url in enumerate(data['button']):
                button_info_card['info_card_property'] = info_card
                button_info_card['text'] = data['button'][idx]
                button_info_card['button_name'] = data['button_name'][idx]
                button_info_card['action_type'] = CardProperty.WEBPAGE
                button_info_card['destination'] = data['click_to'][idx]
                button_info_card['text_color'] = data['text_colour']
                button, _ = InfoCardButtonProperty.objects.get_or_create(**button_info_card)
                # create_image(button.id, CardProperty.IMAGE_TYPE.button_background_image, data['button_url'][idx])

        data_streamlined_message = {'message_content': data['content'],
                                    'info_card_property': info_card}
        message = StreamlinedMessage.objects.create(**data_streamlined_message)
        # status = StatusLookup.objects.filter(status_code=data['status']).last()
        data_for_streamlined_comms = {'status_code': None,
                                      'status': None,
                                      'communication_platform': CommunicationPlatform.INFO_CARD,
                                      'message': message,
                                      'description': 'retroloaded_card_information',
                                      'is_active': True,
                                      'extra_conditions': data['additional_condition']}
        streamlined_communication = StreamlinedCommunication.objects.create(**data_for_streamlined_comms)
        # create image for background
        if data['background_url']:
            create_image(info_card.id, CardProperty.IMAGE_TYPE.card_background_image, data['background_url'])

        if data['additional_images']:
            additional_image_url = data['additional_images']
            additional_image_url = additional_image_url[0]
            create_image(info_card.id, CardProperty.IMAGE_TYPE.card_optional_image, str(additional_image_url))

    # upload image
    images_list = (
        'designs_real.png', 'group_3500.png', 'layer_3.png', 'layer_4.png',
        'layer_5.png', 'layer_6.png', 'rectangle_1489.png', 'rectangle_1489_2.png',
        'data_bg.png'
    )
    for image_name in images_list:
        remote_path = 'info-card/{}'.format(image_name)
        upload_file_to_oss(
            settings.OSS_PUBLIC_ASSETS_BUCKET,
            settings.STATICFILES_DIRS[0] + '/images/info_card/{}'.format(image_name),
            remote_path
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_cards_data_grab, migrations.RunPython.noop)
    ]
