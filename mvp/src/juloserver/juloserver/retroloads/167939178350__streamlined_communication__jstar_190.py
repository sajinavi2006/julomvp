from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import upload_file_to_oss
from juloserver.streamlined_communication.models import (InfoCardButtonProperty,
                                                         CardProperty,
                                                         InfoCardProperty,
                                                         StreamlinedMessage,
                                                         StreamlinedCommunication)
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.julo.models import StatusLookup, Image
from django.conf import settings
hourglass_emoji = '\U000023F3'
R_BUTTON = 'R.BUTTON'


class ImageNames(object):
    BG_107 = 'info-card/CARD_BACKGROUND_IMAGE_WEB190.png'
    BG_120_149 = 'info-card/CARD_BACKGROUND_IMAGE_WEB105.png'
    LIMIT_MAX_JULO_STARTER = 'info-card/limit_max_julo_starter.png'
    BUTTON = 'info-card/button_107.png'


def create_image(image_source_id, image_type, image_url):
    image = Image()
    image.image_source = image_source_id
    image.image_type = image_type
    image.url = image_url
    image.save()


def retroload_julo_starter_infocard(_apps, _schema_editor):
    data_to_be_loaded = [
        {
            'status': ApplicationStatusCodes.LOC_APPROVED,
            'additional_condition': None,
            'title': 'Mau Tarik Dana dan Naikkan Limit?',
            'content': 'Upgrade ke JULO Kredit Digital aja. '
            		   'Limit hingga Rp15juta, bisa tarik dana ke rekening juga!',
            'button': ['Upgrade Sekarang'],
            'button_name': [R_BUTTON],
            'click_to': ['turbo_to_j1'],
            'template_type': '1',
            'card_number': 1,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': ImageNames.BG_107,
            'additional_images': [ImageNames.LIMIT_MAX_JULO_STARTER],
            'button_url': [ImageNames.BUTTON],
            'product': 'jstarter'
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
                button_info_card['action_type'] = CardProperty.APP_DEEPLINK
                button_info_card['destination'] = data['click_to'][idx]
                button_info_card['text_color'] = data['text_colour']
                button, _ = InfoCardButtonProperty.objects.get_or_create(**button_info_card)
                create_image(button.id, CardProperty.IMAGE_TYPE.button_background_image, data['button_url'][idx])


        data_streamlined_message = {'message_content': data['content'],
                                    'info_card_property': info_card}
        message = StreamlinedMessage.objects.create(**data_streamlined_message)
        status = StatusLookup.objects.filter(status_code=data['status']).last()
        data_for_streamlined_comms = {'status_code': status,
                                      'status': data['status'],
                                      'communication_platform': CommunicationPlatform.INFO_CARD,
                                      'message': message,
                                      'description': 'retroload_julo_starter_infocard',
                                      'is_active': True,
                                      'extra_conditions': data['additional_condition'],
                                      'product': data['product']}
        streamlined_communication = StreamlinedCommunication.objects.create(**data_for_streamlined_comms)
        # create image for background
        if data['background_url']:
            create_image(info_card.id, CardProperty.IMAGE_TYPE.card_background_image, data['background_url'])

        if data['additional_images']:
            additional_image_url = data['additional_images']
            additional_image_url = additional_image_url[0]
            create_image(info_card.id, CardProperty.IMAGE_TYPE.card_optional_image, str(additional_image_url))


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retroload_julo_starter_infocard, migrations.RunPython.noop)
    ]
