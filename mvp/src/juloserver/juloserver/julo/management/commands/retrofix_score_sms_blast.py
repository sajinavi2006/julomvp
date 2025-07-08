from builtins import str
import logging, sys

from django.core.management.base import BaseCommand

from os import listdir
from os.path import isfile, join
from django.conf import settings
from ...clients import get_julo_sms_client
from ...clients import get_julo_pn_client
from ...models import Application, SmsHistory
from ...utils import format_e164_indo_phone_number

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retrofix credit score sms and pn last'

    def handle(self, *args, **options):
        # API KEY for sendgrid message

        folder = '../../email_blast/credit_score_retrofix_sms_pn/'
        files = [f for f in listdir(folder) if isfile(join(folder, f))]

        self.stdout.write(self.style.SUCCESS("======================SMS and PN Blast begin======================"))
        sent_count = 0
        skip_count = 0
        bad_app_id_count = 0
        bad_app_id = []
        for file in files:
            self.stdout.write(self.style.WARNING("read app id list on : " + file))
            with open(folder + file, 'r') as opened_file:
                listapp =  opened_file.readlines()
                if len(listapp[0].split(",")) == 1:
                    listapp[0] = listapp[0].replace("\n", "") + ",result\n"
            with open(folder + file, 'w') as saving_file:
                    saving_file.writelines(listapp)

            for index, row in enumerate(listapp):
                row =  row.replace("\n", "")
                if row.split(",")[0].strip() != "application_id":
                    if len(row.split(",")) == 1:
                        app_id = row.strip()
                    else:
                        app_id = row.split(",")[0].strip()
                    try:
                        row_splited = row.split(",")
                        row_splited[1]
                        if row_splited[1].strip() == "Sent":
                            processed_row =True
                        else:
                            processed_row = False
                    except:
                        processed_row = False

                    if not processed_row:
                        self.stdout.write(self.style.WARNING("Kirim sms dan pn ke : " + app_id + "....................."))
                        application = Application.objects.get_or_none(pk=app_id)
                        if application:

                            # push notif
                            device = application.device
                            if device:
                                logger.info({
                                    'action': 'send_pn_alert_retrofix_credit_score',
                                    'application_id': application.id,
                                    'device_id': device.id,
                                    'gcm_reg_id': device.gcm_reg_id
                                })

                                julo_pn_client = get_julo_pn_client()
                                julo_pn_client.alert_retrofix_credit_score(device.gcm_reg_id, application.id)

                            # call sms client
                            customer = application.customer
                            phone_number = application.mobile_phone_1
                            mobile_number = format_e164_indo_phone_number(phone_number)
                            if phone_number:
                                get_julo_sms = get_julo_sms_client()
                                text = "Selamat! JULO skor Anda terupdate, kunjungi aplikasi JULO bit.ly/juloapp dan dapatkan Solusi Pinjaman Tanpa Jaminan MUDAH & MURAH! Ajukan skrng! bit.ly/juloapp"
                                txt_msg, response = get_julo_sms.sms_custom_payment_reminder(mobile_number, text)

                                if response['status'] != '0':
                                    bad_app_id.append(app_id)
                                    bad_app_id_count += 1
                                    self.stdout.write(
                                        self.style.ERROR("Skiping app_id : " + app_id + " gagal kirim SMS ke " + phone_number+" -- " + response.get('error-text')))
                                    if len(row_splited) == 1:
                                        row_splited.append("Failed")
                                    else:
                                        row_splited[1] = "Failed --" + response.get('error-text')
                                    listapp[index] = ','.join(row_splited) + "\n"
                                    with open(folder + file, 'w') as saving_file:
                                        saving_file.writelines(listapp)
                                    continue
                                else:
                                    if len(row_splited) == 1:
                                        row_splited.append("Sent")
                                    else:
                                        row_splited[1] = "Sent"
                                    listapp[index] = ','.join(row_splited) + "\n"
                                    with open(folder + file, 'w') as saving_file:
                                        saving_file.writelines(listapp)
                                    sent_count += 1

                                sms = SmsHistory.objects.create(
                                    customer=customer,
                                    message_id=response['message-id'],
                                    message_content=txt_msg,
                                    to_mobile_phone=format_e164_indo_phone_number(response['to']),
                                    phone_number_type='mobile_phone_1'
                                )

                                logger.info({
                                    'status': 'sms_created',
                                    'sms_history_id': sms.id,
                                    'message_id': sms.message_id
                                })
                            else:
                                self.stdout.write(
                                    self.style.ERROR("Skiping app_id : " + app_id + " (phone_number tidak ditemukan)"))
                        else:
                            self.stdout.write(
                                self.style.ERROR("Skiping app_id : " + app_id + " (tidak ditemukan)"))
                    else:
                        self.stdout.write(self.style.ERROR("Skiping app_id : " + app_id + " (sudah pernah dikirim sebelumnya)"))
                        skip_count += 1
        self.stdout.write(self.style.SUCCESS("=====================SMS and PN Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ "+str(sent_count)+" sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " skiped ]"))
        self.stdout.write(self.style.ERROR("[ " + str(bad_app_id_count) + "  failed ]"))
        self.stdout.write(self.style.ERROR("[ " + " ,".join(bad_app_id) + " ]"))
