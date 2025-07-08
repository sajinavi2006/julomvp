# coding=utf-8
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform


from juloserver.streamlined_communication.models import StreamlinedCommunication



from juloserver.streamlined_communication.models import StreamlinedMessage



def add_message(apps, schema_editor):
    
    
    # PN
    inform_payment_due_soon_template_multiple_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Cicilan ke-{{payment_number}} akan jatuh tempo, harap transfer.",
            parameter="{payment_number}",
        )
    inform_payment_due_soon_template_one_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Pelunasan akan jatuh tempo, harap transfer.",
        )
    data_inform_payment_due_soon = [
        {
            'status': 'inform payment due soon multiple payment for PTP',
            'criteria': {"product_line": ProductLineCodes.multiple_payment()},
            'description': 'this PN called when ptp {} and have multiple payment',
            'message': inform_payment_due_soon_template_multiple_payment
        },
        {
            'status': 'inform payment due soon one payment for PTP',
            'criteria': {"product_line": ProductLineCodes.one_payment()},
            'description': 'this PN called when ptp {} and have one payment',
            'message': inform_payment_due_soon_template_one_payment
        }
    ]
    for i in [-3, -1]:
        for data in data_inform_payment_due_soon:
            streamlined_communication = StreamlinedCommunication.objects.get_or_create(
                message=data['message'],
                status=data['status'],
                communication_platform=CommunicationPlatform.PN,
                template_code='inform_payment_due_soon',
                ptp=i,
                description=data['description'].format(i),
                criteria=data['criteria']
            )
    inform_payment_due_today_template_multiple_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Cicilan ke-{{payment_number}} jatuh tempo hari ini, harap transfer.",
            parameter="{payment_number}",
        )
    inform_payment_due_today_template_one_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Pelunasan jatuh tempo hari ini, harap transfer.",
        )
    data_inform_payment_due_today = [
        {
            'status': 'inform payment due today multiple payment for ptp',
            'criteria': {"product_line": ProductLineCodes.multiple_payment()},
            'description': 'this PN called when ptp 0 and have multiple payment',
            'message': inform_payment_due_today_template_multiple_payment
        },
        {
            'status': 'inform payment due today one payment for ptp',
            'criteria': {"product_line": ProductLineCodes.one_payment()},
            'description': 'this PN called when ptp 0 and have one payment',
            'message': inform_payment_due_today_template_one_payment
        }
    ]
    for data in data_inform_payment_due_today:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=data['message'],
            status=data['status'],
            communication_platform=CommunicationPlatform.PN,
            template_code='inform_payment_due_today',
            ptp=0,
            description=data['description'],
            criteria=data['criteria']
        )

    inform_payment_late_template_multiple_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Cicilan ke-{{payment_number}} terlambat, harap transfer.",
            parameter="{payment_number}",
        )
    inform_payment_late_template_one_payment, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content="Pelunasan terlambat, harap transfer.",
        )
    data_inform_payment_late = [
        {
            'status': 'inform payment late multiple payment have ptp',
            'criteria': {"product_line": ProductLineCodes.multiple_payment()},
            'description': 'this PN called when late and have ptp {} and have multiple payment',
            'message': inform_payment_late_template_multiple_payment
        },
        {
            'status': 'inform payment late one payment',
            'criteria': {"product_line": ProductLineCodes.one_payment()},
            'description': 'this PN called when late and have ptp {} and have one payment',
            'message': inform_payment_late_template_one_payment
        }
    ]
    for i in [1, 5, 30, 60, 90, 120, 150, 180, 210]:
        for data in data_inform_payment_late:
            streamlined_communication = StreamlinedCommunication.objects.get_or_create(
                message=data['message'],
                status=data['status'],
                communication_platform=CommunicationPlatform.PN,
                template_code='inform_payment_late',
                ptp=i,
                description=data['description'].format(i),
                criteria=data['criteria']
            )
    # Email
    email_reminder_ptp_1_3_5, _ = \
        StreamlinedMessage.objects.get_or_create(
            message_content='<!doctype html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office"><head><title></title><meta http-equiv="X-UA-Compatible" content="IE=edge"><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><style type="text/css">#outlook a{padding:0}.ReadMsgBody{width:100%}.ExternalClass{width:100%}.ExternalClass *{line-height:100%}body{margin:0;padding:0;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}table,td{border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt}img{border:0;height:auto;line-height:100%;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic}p{display:block;margin:13px 0}#julo-website a{color:white;text-decoration:none}</style><style type="text/css">@media only screen and (max-width:480px){@-ms-viewport{width:320px}@viewport{width:320px}}</style><link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700" rel="stylesheet" type="text/css"><style type="text/css">@import url(https://fonts.googleapis.com/css?family=Montserrat:300,400,500,700);</style><style type="text/css">@media only screen and (min-width:480px){.mj-column-per-100{width:100%!important}.mj-column-px-50{width:50px!important}}</style></head><body style="background: #E1E8ED;"><div class="mj-container"><div style="margin:0px auto;max-width:600px;background:linear-gradient(to right, #00ACF0, #13637b);"><table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:linear-gradient(to right, #00ACF0, #13637b);" align="center" border="0"><tbody><tr><td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;"><div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0"><tbody><tr><td style="word-wrap:break-word;font-size:0px;padding-left:20px;" align="left"><table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-spacing:0px;" align="left" border="0"><tbody><tr><td style="width:100px;"><img alt="" title="" height="auto" src="https://www.julo.co.id/images/JULO_logo_white.png" style="border:none;border-radius:0px;display:block;font-size:13px;outline:none;text-decoration:none;width:120%;height:auto;" width="100"></td></tr></tbody></table></td><td style="font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:12px;padding-top:25px;padding-right:25px;" align="right"><p id="julo-website" style="color:white;text-decoration:none;">www.julo.co.id</p></td></tr></tbody></table></div></td></tr></tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;"><table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0"><tbody><tr><td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;"><div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0"><tbody><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left"><div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:20px;line-height:120%;text-align:left;">Yth {{fullname}},</div></td></tr><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left"><div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Terima kasih untuk janji pembayaran yang akan Anda lakukan pada tanggal {{due_date}} sebesar {{due_amount}}</div></td></tr><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left"><div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Mohon lakukan pembayaran sesuai dengan janji yang telah Anda buat untuk menghindari kunjungan petugas kami.</div></td></tr><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left"><div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Anda dapat melakukan pembayaran ke {{bank_name}} no Virtual Account {{account_number}} a/n JULO melalui transfer ATM, mobile/internet banking, atau melalui teller secara langsung.</div></td></tr><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left"><div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Informasi mengenai pinjaman Anda bisa dicek : <a href="https://goo.gl/VeRC4O" style="color:#00acf0">https://goo.gl/VeRC4O</a></div></td></tr><tr><td style="word-wrap:break-word;font-size:0px;"><div style="font-size:1px;line-height:5px;white-space:nowrap;"> </div></td></tr></tbody></table></div></td></tr></tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;"><table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0"><tbody><tr><td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;"><div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0"><tbody><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left"><div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left; font-weight:500;">Salam,</div></td></tr><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left"><div style="cursor:auto;color:#5e5e5e;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:15px;line-height:120%;text-align:left;">JULO</div></td></tr></tbody></table></div></td></tr></tbody></table></div><div style="margin:0px auto;max-width:600px;background:white;"><table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:white;" align="center" border="0"><tbody><tr><td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;"><p style="font-size:1px;margin:0px auto;border-top:1px solid #f8f8f8;width:100%;"></p><div class="mj-column-px-NaN outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0"><tbody><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;" align="left"><div style="cursor:auto;color:grey;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:13px;line-height:120%;text-align:left;">Email ini dibuat secara otomatis. Mohon tidak mengirimkan balasan ke email ini</div></td></tr></tbody></table></div></td></tr></tbody></table></div><div style="margin:0px auto;max-width:600px;background:#222222;"><table role="presentation" cellpadding="0" cellspacing="0" style="font-size:0px;width:100%;background:#222222;" align="center" border="0"><tbody><tr><td style="text-align:center;vertical-align:top;direction:ltr;font-size:0px;padding:20px 0px;"><div class="mj-column-per-100 outlook-group-fix" style="vertical-align:top;display:inline-block;direction:ltr;font-size:13px;text-align:left;width:100%;"><table role="presentation" cellpadding="0" cellspacing="0" width="100%" border="0"><tbody><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center"><div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:10px;font-weight:400;line-height:120%;text-align:center;">Pinjaman Cerdas Dari Smartphone Anda</div><div><a href="https://play.google.com/store/apps/details?id=com.julofinance.juloapp" style="color:white;text-decoration:none;" target="_blank">Google Play Store <img src="https://www.julo.co.id/assets/images/play_store.png" alt="google-play" style="width:20%;padding-top:10px; display:inline; align:middle;text-decoration:none;border-bottom: #f6f6f6"></a></div></td></tr><tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;Border-bottom:10px" align="center"><div><table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0"><tbody><tr><td style="padding:4px;vertical-align:middle;"><table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0"><tbody><tr><td style="vertical-align:middle;"> <a href="https://www.instagram.com/juloindonesia/" target="_blank"><img alt="instagram" height="NaN" src="https://www.julo.co.id/images/icon_instagram.png" style="display:block;border-radius:3px;width:16px;" width="NaN"></a></td></tr></tbody></table></td></tr></tbody></table><table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0"><tbody><tr><td style="padding:4px;vertical-align:middle;"><table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0"><tbody><tr><td style="vertical-align:middle;"> <a href="https://www.facebook.com/juloindonesia/" target="_blank"><img alt="facebook" height="NaN" src="https://www.julo.co.id/images/icon_facebook.png" style="display:block;border-radius:3px;width:18px" width="NaN"></a></td></tr></tbody></table></tr></tbody></table><table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0"><tbody><tr><td style="padding:4px;vertical-align:middle;"><table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;width:;" border="0"><tbody><tr><td style="vertical-align:middle;"> <a href="https://twitter.com/juloindonesia" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_twitter.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a></td></tr></tbody></table></tr></tbody></table><table role="presentation" cellpadding="0" cellspacing="0" style="float:none;display:inline-table;" align="center" border="0"><tbody><tr><td style="padding:4px;vertical-align:middle;"><table role="presentation" cellpadding="0" cellspacing="0" style="border-radius:3px;" border="0"><tbody><tr><td style="vertical-align:middle;"> <a href="https://www.youtube.com/channel/UCA9WsBMIg3IHxwVA-RvSctA" target="_blank"><img alt="twitter" height="NaN" src="https://www.julo.co.id/images/icon_youtube.png" style="display:block;border-radius:3px;width:16px" width="NaN"></a></td></tr></tbody></table></tr></tbody></table></td></tr><td style="word-wrap:break-word;font-size:0px;padding:10px 25px;padding-top:0.5px;" align="center"><div style="cursor:auto;color:white;font-family:Montserrat, Roboto, Helvetica, Arial, sans-serif;font-size:9px;font-weight:300;line-height:120%;text-align:center;">©2019 JULO | All rights reserved</div></td></div></td></tr></tbody></table></div></td></tr></tbody></table></div></div></body></html>',
            parameter="{fullname,due_date,due_amount,bank_name,account_number}",
        )
    for i in [-4, -2]:
        streamlined_communication = StreamlinedCommunication.objects.get_or_create(
            message=email_reminder_ptp_1_3_5,
            status='send email reminder when ptp {}'.format(i),
            communication_platform=CommunicationPlatform.EMAIL,
            template_code='email_reminder_ptp_-1-3-5',
            ptp=i,
            description="this email send in email_payment_reminder and have ptp {}".format(i)
        )
    # delete all whatsapp streamlined_communication
    whatsapp_reminders = streamlined_communication = StreamlinedCommunication.objects\
        .filter(communication_platform=CommunicationPlatform.WA)
    if whatsapp_reminders:
        whatsapp_reminders.delete()

class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_message,
                             migrations.RunPython.noop)
    ]