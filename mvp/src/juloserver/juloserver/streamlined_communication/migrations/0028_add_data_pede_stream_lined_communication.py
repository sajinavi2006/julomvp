# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-02-16 15:52
from __future__ import unicode_literals
from django.db import migrations, models
import django.contrib.postgres.fields
from juloserver.streamlined_communication.constant import CommunicationPlatform

def update_sms_messages(apps, schema_editor):

    StreamlinedCommunication = apps.get_model("streamlined_communication", "StreamlinedCommunication")
    StreamlinedMessage = apps.get_model("streamlined_communication", "StreamlinedMessage")

    robocall_pedemtl_tminus3 = \
        StreamlinedMessage.objects.create(
            message_content='[{"action": "talk","voiceName": "Damayanti","text": "Selamat {{greet}}'
                            '{{ name_with_title }}, pelunasan JULO Anda {{ due_amount }} rupiah akan jatuh tempo dalam '
                            '{{ days_before_due_date }} hari."},{"action": "talk","voiceName": "Damayanti","text":'
                            '"Mohon bayar sebelum jatuh tempo. Tekan 1 untuk konfirmasi. '
                            '{{ promo_message }}"},{"action": "talk","voiceName": "Damayanti","text":"Terima kasih"},'
                            '{"action": "input","maxDigits": 1,"eventUrl": ["{{input_webhook_url}}"]}]',
            parameter="{greet,name_with_title,due_amount,days_before_due_date,"
                      "promo_message,input_webhook_url}"
        )
    streamlined_communication_for_robocall_pedemtl_tminus3 = StreamlinedCommunication.objects.get_or_create(
        message=robocall_pedemtl_tminus3,
        status="Robocall customer when dpd -3",
        communication_platform=CommunicationPlatform.ROBOCALL,
        template_code='voice_reminder_T-3_PEDEMTL',
        dpd=-3,
        product='nexmo_pedemtl', type='Payment Reminder',
        attempts=3, is_automated=True,
        call_hours="{8:0,10:0,12:0}",
        function_name="{send_voice_payment_reminder,retry_send_voice_payment_reminder1,"
                      "retry_send_voice_payment_reminder2}",
        description="this Robocall is send on  dpd=-3 for pedemtl"
    )

    robocall_pedemtl_tminus5 = \
        StreamlinedMessage.objects.create(
            message_content='[{"action": "talk","voiceName": "Damayanti","text":'
                            '"Selamat {{greet}} {{ name_with_title }}, pelunasan JULO Anda'
                            '{{ due_amount }} rupiah akan jatuh tempo dalam {{ days_before_due_date }} hari."},'
                            '{"action": "talk","voiceName": "Damayanti","text": "Tekan 1 untuk konfirmasi. '
                            '{{ promo_message }}"},{"action": "talk","voiceName": "Damayanti","text":"Terima kasih"},'
                            '{"action": "input","maxDigits": 1,"eventUrl": ["{{input_webhook_url}}"]}]',
            parameter="{greet,name_with_title,due_amount,days_before_due_date,"
                      "promo_message,input_webhook_url}"
        )
    streamlined_communication_for_robocall_pedemtl_tminus5 = StreamlinedCommunication.objects.get_or_create(
        message=robocall_pedemtl_tminus5,
        status="Robocall customer when dpd -5",
        communication_platform=CommunicationPlatform.ROBOCALL,
        template_code='voice_reminder_T-5_PEDEMTL',
        dpd=-5,
        product='nexmo_pedemtl', type='Payment Reminder',
        attempts=3, is_automated=True,
        call_hours="{8:0,10:0,12:0}",
        function_name="{send_voice_payment_reminder,retry_send_voice_payment_reminder1,"
                      "retry_send_voice_payment_reminder2}",
        description="this Robocall is send on  dpd=-5 for pedemtl"
    )

    robocall_pedestl_tminus5 = \
        StreamlinedMessage.objects.create(
            message_content='[{"action": "talk","voiceName": "Damayanti","text":'
                            '"Selamat {{greet}} {{ name_with_title }}, pelunasan JULO Anda'
                            '{{ due_amount }} rupiah akan jatuh tempo dalam {{ days_before_due_date }} hari."},'
                            '{"action": "talk","voiceName": "Damayanti","text": "Tekan 1 untuk konfirmasi. '
                            '{{ promo_message }}"},{"action": "talk","voiceName": "Damayanti","text":"Terima kasih"},'
                            '{"action": "input","maxDigits": 1,"eventUrl": ["{{input_webhook_url}}"]}]',
            parameter="{greet,name_with_title,due_amount,days_before_due_date,"
                      "promo_message,input_webhook_url}"
        )
    streamlined_communication_for_robocall_pedestl_tminus5 = StreamlinedCommunication.objects.get_or_create(
        message=robocall_pedestl_tminus5,
        status="Robocall customer when dpd -5",
        communication_platform=CommunicationPlatform.ROBOCALL,
        template_code='voice_reminder_T-5_PEDESTL',
        dpd=-5,
        product='nexmo_pedestl', type='Payment Reminder',
        attempts=3, is_automated=True,
        call_hours="{8:0,10:0,12:0}",
        function_name="{send_voice_payment_reminder,retry_send_voice_payment_reminder1,"
                      "retry_send_voice_payment_reminder2}",
        description="this Robocall is send on  dpd=-5 for pedestl"
    )
    robocall_pedestl_tminus3 = \
        StreamlinedMessage.objects.create(
            message_content='[{"action": "talk","voiceName": "Damayanti","text": "Selamat {{greet}}'
                            '{{ name_with_title }}, pelunasan JULO Anda {{ due_amount }} rupiah akan jatuh tempo dalam '
                            '{{ days_before_due_date }} hari."},{"action": "talk","voiceName": "Damayanti","text":'
                            '"Mohon bayar sebelum jatuh tempo. Tekan 1 untuk konfirmasi. '
                            '{{ promo_message }}"},{"action": "talk","voiceName": "Damayanti","text":"Terima kasih"},'
                            '{"action": "input","maxDigits": 1,"eventUrl": ["{{input_webhook_url}}"]}]',
            parameter="{greet,name_with_title,due_amount,days_before_due_date,"
                      "promo_message,input_webhook_url}"
        )
    streamlined_communication_for_robocall_pedestl_tminus3 = StreamlinedCommunication.objects.get_or_create(
        message=robocall_pedestl_tminus3,
        status="Robocall customer when dpd -3",
        communication_platform=CommunicationPlatform.ROBOCALL,
        template_code='voice_reminder_T-3_PEDESTL',
        dpd=-3,
        product='nexmo_pedestl', type='Payment Reminder',
        attempts=3, is_automated=True,
        call_hours="{8:0,10:0,12:0}",
        function_name="{send_voice_payment_reminder,retry_send_voice_payment_reminder1,"
                      "retry_send_voice_payment_reminder2}",
        description="this Robocall is send on  dpd=-3 for pedestl"
    )


class Migration(migrations.Migration):
    dependencies = [
        ('streamlined_communication', '0027_add_data_stream_lined_communication_parameter'),
    ]

    operations = [
        migrations.RunPython(update_sms_messages,
                             migrations.RunPython.noop)
    ]
