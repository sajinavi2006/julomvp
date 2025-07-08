from builtins import str
import logging, sys
import json

from django.core.management.base import BaseCommand

from ...clients import get_julo_sms_client
from ...clients import get_julo_pn_client
from ...models import Application
from ...utils import format_e164_indo_phone_number

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'blast pn and sms for spesific criteria'

    def handle(self, *args, **options):
        app_for_pn = Application.objects.filter(application_status=105, creditscore__score__in=['A-', 'B+', 'B-'] )

        self.stdout.write(self.style.SUCCESS("==========PUSH notif Blast begin============"))
        sent_count = 0
        skip_count = 0
        pn_log_file = '../../email_blast/log_for_sms_and_pn_spesific_criteria/pn.txt'
        sent_pns = [line.rstrip('\n') for line in open(pn_log_file)]
        for app in app_for_pn:
            text = 'Tinggal sedikit lagi! Dapatkan Pinjaman bersahabat di JULO! Pilih Produk Pinjaman, Isi formulir dan Unggah dokumen (hanya butuh 5 menit saja!)'
            if str(app.id) not in sent_pns:
                self.stdout.write(self.style.WARNING("Kirim push notif ke : " + str(app.id) + "....................."))
                if app.device:
                    gcm_reg_id = app.device.gcm_reg_id
                    julo_pn_client = get_julo_pn_client()
                    julo_pn_client.early_payment_promo(gcm_reg_id, text)
                    with open(pn_log_file, 'a') as log:
                        log.write(str(app.id) + '\n')
                    sent_count += 1
                else:
                    self.stdout.write(
                        self.style.ERROR("Skiping customer : " + str(app.id) + " (tidak punya device)"))
                    skip_count += 1
            else:
                self.stdout.write(
                    self.style.ERROR("Skiping customer : " + str(app.id) + " (sudah pernah dikirim sebelumnya)"))
                skip_count += 1

        self.stdout.write(self.style.SUCCESS("=====================PUSH notif Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(sent_count) + " customer sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " customer skiped ]"))


        #blast sms for 160
        app_for_sms_160 = Application.objects.filter(application_status=160)

        self.stdout.write(self.style.SUCCESS("==========SMS Blast for status 160 begin============"))
        sent_count = 0
        skip_count = 0
        app160_log_file = '../../email_blast/log_for_sms_and_pn_spesific_criteria/app160.txt'
        sent_app160s = [line.rstrip('\n') for line in open(app160_log_file)]
        for app in app_for_sms_160:
            phonenumber = app.mobile_phone_1
            text = 'Selamat! Verifikasi data selesai. Mohon update aplikasi JULO terbaru di bit.ly/juloapp. Tanda tangan Surat Perjanjian di aplikasi dan Dana akan segera CAIR!'
            if str(app.id) not in sent_app160s:
                self.stdout.write(self.style.WARNING("Kirim sms ke : " + str(phonenumber) + "....................."))
                mobile_number = format_e164_indo_phone_number(phonenumber)
                get_julo_sms = get_julo_sms_client()
                try:
                    txt_msg, response = get_julo_sms.sms_custom_payment_reminder(mobile_number, text)
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR("Skiping Number : " + str(phonenumber) + "error: "+ str(e)))
                    continue
                if response['status'] != '0':
                    self.stdout.write(
                        self.style.ERROR("Skiping Number : " + str(phonenumber) + "error: " + json.dumps(response)))
                    continue
                else:
                    with open(app160_log_file, 'a') as log:
                        log.write(str(app.id) + '\n')
                    sent_count += 1
            else:
                self.stdout.write(
                    self.style.ERROR("Skiping number : " + str(phonenumber) + " (sudah pernah dikirim sebelumnya)"))
                skip_count += 1

        self.stdout.write(self.style.SUCCESS("=====================sms Blast for status 160 finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(sent_count) + " sms sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " sms skiped ]"))

        # blast sms for update apk
        app_for_sms_update_apk = Application.objects.filter(
            application_status__in=[120, 124, 130, 141, 172, 122, 1220, 138, 1380, 125],
            app_version = '2.4.0'
        )

        self.stdout.write(self.style.SUCCESS("==========SMS Blast for update apk begin============"))
        sent_count = 0
        skip_count = 0
        app_for_sms_update_apk_log_file = '../../email_blast/log_for_sms_and_pn_spesific_criteria/app_update_apk.txt'
        sent_app_for_sms_update_apks = [line.rstrip('\n') for line in open(app_for_sms_update_apk_log_file)]
        for app in app_for_sms_update_apk:
            phonenumber = app.mobile_phone_1
            text = 'Hi Nasabah JULO! Utk kelancaran proses pengajuan, Update aplikasi JULO terbaru ver 2.4.1 di bit.ly/juloapp. Selalu cek proses pengajuan Anda di aplikasi JULO.'
            if str(app.id) not in sent_app_for_sms_update_apks:
                self.stdout.write(self.style.WARNING("Kirim sms ke : " + str(phonenumber) + "....................."))
                mobile_number = format_e164_indo_phone_number(phonenumber)
                get_julo_sms = get_julo_sms_client()
                try:
                    txt_msg, response = get_julo_sms.sms_custom_payment_reminder(mobile_number, text)
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR("Skiping Number : " + str(phonenumber) + "error: " + str(e)))
                    continue
                if response['status'] != '0':
                    self.stdout.write(
                        self.style.ERROR("Skiping Number : " + str(phonenumber) + "error: " + json.dumps(response)))
                    continue
                else:
                    with open(app_for_sms_update_apk_log_file, 'a') as log:
                        log.write(str(app.id) + '\n')
                    sent_count += 1
            else:
                self.stdout.write(
                    self.style.ERROR("Skiping number : " + str(phonenumber) + " (sudah pernah dikirim sebelumnya)"))
                skip_count += 1

        self.stdout.write(
            self.style.SUCCESS("=====================sms Blast for update apk finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(sent_count) + " sms sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " sms skiped ]"))