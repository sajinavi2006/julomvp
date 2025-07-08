# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


from juloserver.streamlined_communication.models import StreamlinedCommunication



def retro_template_sms(apps, _schema_editor):
    
    sms_streamline = StreamlinedCommunication.objects.filter(communication_platform='SMS')

    dpd_0_streamline = sms_streamline.filter(template_code__in=['mtl_sms_dpd_0','sms_ptp_mtl_0','stl_sms_dpd_0',
                                                                'sms_ptp_stl_0','pedemtl_sms_dpd_0','sms_ptp_pedemtl_0',
                                                                'pedestl_sms_dpd_0','sms_ptp_pedestl_0',
                                                                'laku6mtl_sms_dpd_0','sms_ptp_laku6mtl_0'])

    dpd_2_streamline = sms_streamline.filter(template_code__in=['mtl_sms_dpd_-2','sms_ptp_mtl_-2','stl_sms_dpd_-2',
                                                                'sms_ptp_stl_-2','pedemtl_sms_dpd_-2',
                                                                'sms_ptp_pedemtl_-2','pedestl_sms_dpd_-2',
                                                                'sms_ptp_pedestl_-2','laku6mtl_sms_dpd_-2',
                                                                'sms_ptp_laku6mtl_-2'])

    dpd_7_streamline = sms_streamline.filter(template_code__in=['mtl_sms_dpd_-7'])

    for sm in dpd_0_streamline:
        sm.is_automated = True
        sm.save()
        message = sm.message
        if 'url' in message.parameter:
            message.parameter.remove('url')
            message.parameter.append('how_pay_url')
            message.message_content = message.message_content.replace('url', 'how_pay_url')
            message.save()

    for sm in dpd_2_streamline:
        sm.is_automated = True
        sm.save()
        message = sm.message
        if 'url' in message.parameter:
            message.parameter.remove('url')
            message.parameter.append('payment_details_url')
            message.message_content = message.message_content.replace('url', 'payment_details_url')
            message.save()

    for sm in dpd_7_streamline:
        sm.is_automated = True
        sm.save()
        message = sm.message
        if 'due_date_in_4_days' in message.parameter:
            message.parameter.remove('due_date_in_4_days')
            message.parameter.append('due_date_minus_4')
            message.message_content = message.message_content.replace('due_date_in_4_days', 'due_date_minus_4')
            message.save()

    mtl_dpd_2 = StreamlinedCommunication.objects.filter(template_code='mtl_sms_dpd_-2', is_automated=True).last()
    if mtl_dpd_2:
        mtl_dpd_2.product = 'mtl'
        mtl_dpd_2.type = 'Payment Reminder'
        mtl_dpd_2.time_sent = '12:0'
        mtl_dpd_2.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retro_template_sms, migrations.RunPython.noop)
    ]
