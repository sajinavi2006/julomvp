# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-04-12 04:38
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.streamlined_communication.models import (
    CardProperty,
    InfoCardProperty,
    StreamlinedMessage,
    StreamlinedCommunication
)
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.julo.models import StatusLookup, Image


class ImageNames(object):
    BG = 'info-card/CARD_BACKGROUND_IMAGE_WEB105.png'


def create_image(image_source_id, image_type, image_url):
    image = Image()
    image.image_source = image_source_id
    image.image_type = image_type
    image.url = image_url
    image.save()


def set_nonactive_for_old_infocard(_apps, _schema_editor):
    """
    To set non-active if infocard x107 is exists.
    """

    info_card_190 = StreamlinedCommunication.objects.filter(
        status_code=ApplicationStatusCodes.LOC_APPROVED,
        extra_conditions=None,
        product="jstarter",
        is_active=True,
    ).last()
    if info_card_190:
        info_card_190.update_safely(is_active=False)


def update_107_inforcard_message(_apps, _schema_editor):
    info_card_107 = StreamlinedCommunication.objects.filter(
        status_code=ApplicationStatusCodes.OFFER_REGULAR,
        is_active=True,
    ).last()
    if info_card_107:
        message = info_card_107.message
        message.update_safely(
            message_content='Tenang, kamu masih bisa ajukan JULO Kredit Digital, kok. '
                            'Ajukan sekarang!'
        )


def update_135_info_card(_apps, _schema_editor):
    info_card_135 = StreamlinedCommunication.objects.filter(
        communication_platform=CommunicationPlatform.INFO_CARD,
        extra_conditions='ALREADY_ELIGIBLE_TO_REAPPLY',
        status_code_id=ApplicationStatusCodes.APPLICATION_DENIED,
        product="jstarter",
        is_active=True
    ).last()
    if info_card_135:
        message = info_card_135.message
        card_property = message.info_card_property
        message.update_safely(
            message_content='Tenang, kamu masih bisa coba ajukan JULO Kredit Digital, kok. Ajukan sekarang!',
        )
        card_property.update_safely(
            title='Pengajuan JULO Turbo Belum Berhasil'
        )


def retroload_cards_data_jstarter(_apps, _schema_editor):
    data_to_be_loaded = [
        {
            'status': ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            'additional_condition': None,
            'title': 'Pengajuan Kamu Belum Berhasil',
            'content': 'Berdasarkan analisa oleh pihak JULO, kamu belum memenuhi kriteria untuk '
                       'mengajukan JULO Turbo dan JULO Kredit Digital.',
            'button': [],
            'button_name': [],
            'click_to': [],
            'template_type': '2',
            'card_number': 1,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': ImageNames.BG,
            'additional_images': [],
            'button_url': [],
            'product': 'jstarter'
        },
        {
            'status': ApplicationStatusCodes.LOC_APPROVED,
            'additional_condition': None,
            'title': '',
            'content': '',
            'button': [],
            'button_name': [],
            'click_to': 'turbo_to_j1',
            'template_type': '1',
            'card_number': 1,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': 'info-card/CARD_BACKGROUND_IMAGE_190_UPGRADE_J1.png',
            'additional_images': [],
            'button_url': [],
            'product': 'jstarter'
        },
    ]
    for data in data_to_be_loaded:
        button_1_properties = {'card_type': '8',
                               'title': data['title'],
                               'title_color': data['title_colour'],
                               'text_color': data['text_colour'],
                               'card_order_number': data['card_number'],
                               'card_destination': data['click_to'],
                               'card_action': CardProperty.APP_DEEPLINK
                               }
        button_2_properties = {'card_type': '2',
                               'title': data['title'],
                               'title_color': data['title_colour'],
                               'text_color': data['text_colour'],
                               'card_order_number': data['card_number']}

        info_card = None
        if data['template_type'] == '1':
            info_card = InfoCardProperty.objects.create(**button_1_properties)
        elif data['template_type'] == '2':
            info_card = InfoCardProperty.objects.create(**button_2_properties)

        data_streamlined_message = {
            'message_content': data['content'],
            'info_card_property': info_card
        }
        message = StreamlinedMessage.objects.create(**data_streamlined_message)
        status = StatusLookup.objects.filter(status_code=data['status']).last()
        data_for_streamlined_comms = {'status_code': status,
                                      'status': data['status'],
                                      'communication_platform': CommunicationPlatform.INFO_CARD,
                                      'message': message,
                                      'description': 'retroloaded_card_information',
                                      'is_active': True,
                                      'product': data['product'],
                                      'extra_conditions': data['additional_condition']}
        streamlined_communication = StreamlinedCommunication.objects.create(**data_for_streamlined_comms)
        # create image for background
        if data['background_url']:
            create_image(info_card.id, CardProperty.IMAGE_TYPE.card_background_image, data['background_url'])



class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(set_nonactive_for_old_infocard, migrations.RunPython.noop),
        migrations.RunPython(update_135_info_card, migrations.RunPython.noop),
        migrations.RunPython(update_107_inforcard_message, migrations.RunPython.noop),
        migrations.RunPython(retroload_cards_data_jstarter, migrations.RunPython.noop),
    ]
