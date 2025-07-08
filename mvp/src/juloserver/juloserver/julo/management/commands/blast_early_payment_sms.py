from builtins import str
import logging, sys

from django.core.management.base import BaseCommand

from os import listdir
from os.path import isfile, join
from django.conf import settings
from django.db import connection
from ...clients import get_julo_sms_client
from ...clients import get_julo_pn_client
from ...models import Application, SmsHistory
from ...utils import format_e164_indo_phone_number

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'blast sms for early payment collections'

    def handle(self, *args, **options):
        folder = '../../email_blast/early_payment_blast/sms/'
        dues = ['t-2', 't0']

        self.stdout.write(self.style.SUCCESS("==========SMS Blast begin============"))
        sent_count = 0
        skip_count = 0
        bad_number_count = 0
        bad_numbers = []
        for due in dues:
            file = due + ".csv"
            if due == 't-2':
                text = "Pelanggan JULO! Menangkan Undian UANG TUNAI Rp 2.5 juta dgn membayar Pinjaman 2 HARI SEBELUM tanggal jatuh tempo. AYO bayar skrng! bit.ly/juloapp"
            elif due == 't0':
                text = "Pelanggan JULO! Menangkan Undian UANG TUNAI Rp 2.5 juta dgn membayar Pinjaman TEPAT WAKTU sesuai tanggal jatuh tempo. AYO bayar skrng! bit.ly/juloapp"
            self.stdout.write(self.style.WARNING("read phone number list on : " + file))
            with open(folder + file, 'r') as opened_file:
                listphonenumber = opened_file.readlines()
            if len(listphonenumber[0].split(",")) == 6:
                listphonenumber[0] = listphonenumber[0].replace("\n", "") + ",result\n"
            with open(folder + file, 'w') as saving_file:
                saving_file.writelines(listphonenumber)

            for index, row in enumerate(listphonenumber):
                row = row.replace("\n", "")
                row_splited = row.split(",")
                if row_splited[0].strip() != "variant":
                    phonenumber = row_splited[3].strip()
                    phonenumber2 = row_splited[4].strip()
                    try:
                        row_splited[6]
                        if row_splited[6].strip() == "Sent":
                            processed_row = True
                        else:
                            processed_row = False
                    except:
                        processed_row = False

                    if not processed_row:
                        self.stdout.write(self.style.WARNING("Kirim sms ke : " + phonenumber + "....................."))
                        mobile_number = format_e164_indo_phone_number(phonenumber)
                        get_julo_sms = get_julo_sms_client()
                        try:
                            txt_msg, response = get_julo_sms.sms_custom_payment_reminder(mobile_number, text)
                        except Exception as e:
                            bad_numbers.append(phonenumber)
                            bad_number_count += 1
                            self.stdout.write(
                                self.style.ERROR("Skiping Number : " + phonenumber + "error: "+ e.message))
                            if len(row_splited) == 6:
                                row_splited.append("Failed")
                            else:
                                row_splited[6] = "Failed"
                            listphonenumber[index] = ','.join(row_splited) + "\n"
                            with open(folder + file, 'w') as saving_file:
                                saving_file.writelines(listphonenumber)
                            continue
                        if response['status'] != '0':
                            bad_numbers.append(phonenumber)
                            bad_number_count += 1
                            self.stdout.write(
                                self.style.ERROR("Skiping Number : " + phonenumber + "error: " + e.message))
                            if len(row_splited) == 6:
                                row_splited.append("Failed")
                            else:
                                row_splited[6] = "Failed"
                            listphonenumber[index] = ','.join(row_splited) + "\n"
                            with open(folder + file, 'w') as saving_file:
                                saving_file.writelines(listphonenumber)
                            continue
                        else:
                            if len(row_splited) == 6:
                                row_splited.append("Sent")
                            else:
                                row_splited[6] = "Sent"
                            listphonenumber[index] = ','.join(row_splited) + "\n"
                            with open(folder + file, 'w') as saving_file:
                                saving_file.writelines(listphonenumber)
                            sent_count += 1

                        if phonenumber2:
                            self.stdout.write(
                                self.style.WARNING("Kirim sms ke : " + phonenumber2 + "....................."))
                            mobile_number2 = format_e164_indo_phone_number(phonenumber2)
                            try:
                                get_julo_sms.sms_custom_payment_reminder(mobile_number2, text)
                            except Exception as e:
                                bad_numbers.append(phonenumber)
                                bad_number_count += 1
                                self.stdout.write(
                                    self.style.ERROR("Skiping Number : " + phonenumber + "error: " + e.message))
                            if response['status'] != '0':
                                bad_numbers.append(phonenumber)
                                bad_number_count += 1
                                self.stdout.write(
                                    self.style.ERROR("Skiping Number : " + phonenumber + "error: " + e.message))
                                continue
                            else:
                                sent_count += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR("Skiping number : " + phonenumber + " (sudah pernah dikirim sebelumnya)"))
                        skip_count += 1

        self.stdout.write(self.style.SUCCESS("=====================sms Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(sent_count) + " sms sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " sms skiped ]"))
        self.stdout.write(self.style.ERROR("[ " + str(bad_number_count) + " number bad format ]"))
        self.stdout.write(self.style.ERROR("[ " + " ,".join(bad_numbers) + " ]"))
