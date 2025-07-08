from builtins import str
import logging, sys

from django.core.management.base import BaseCommand

from os import listdir
from os.path import isfile, join
from ...clients import get_julo_sms_client
from ...utils import format_e164_indo_phone_number
from ...models import Customer

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'blast sms for pedagang reapply offer'

    def handle(self, *args, **options):
        folder = '../../email_blast/pedagang_reapply_sms/'
        files = [f for f in listdir(folder) if isfile(join(folder, f))]

        self.stdout.write(self.style.SUCCESS("==========SMS Blast begin============"))
        sent_count = 0
        skip_count = 0
        bad_number_count = 0
        bad_numbers = []
        for file in files:
            self.stdout.write(self.style.WARNING("read phone number list on : " + file))
            with open(folder + file, 'r') as opened_file:
                listphonenumber = opened_file.readlines()
            if len(listphonenumber[0].split(",")) == 1:
                listphonenumber[0] = listphonenumber[0].replace("\n", "") + ",result\n"
            with open(folder + file, 'w') as saving_file:
                saving_file.writelines(listphonenumber)

            for index, row in enumerate(listphonenumber):
                row = row.replace("\n", "")
                row_splited = row.split(",")
                if row_splited[0].strip() != "phone number":
                    phonenumber = row_splited[0].strip()
                    text = ("Ayo ajukan kembali & dapatkan Pinjaman s/d 8jt bunga rendah bisa dicicil hanya di JULO!"
                            " Ada cashback nya lho! Ajukan sekarang hanya 5 mnt saja! bit.ly/juloapp")
                    try:
                        row_splited[1]
                        if row_splited[1].strip() == "Sent":
                            processed_row = True
                        else:
                            processed_row = False
                    except:
                        processed_row = False

                    skip_sent = False
                    customer = Customer.objects.get_or_none(phone=phonenumber)
                    if customer:
                        last_app = customer.application_set.last()
                        if last_app.is_active():
                            skip_sent = True

                    if not processed_row and not skip_sent:
                        self.stdout.write(self.style.WARNING("Kirim sms ke : " + phonenumber + "....................."))
                        mobile_number = format_e164_indo_phone_number(phonenumber)
                        get_julo_sms = get_julo_sms_client()
                        try:
                            txt_msg, response = get_julo_sms.sms_custom_payment_reminder(mobile_number, text)
                        except Exception as e:
                            bad_numbers.append(phonenumber)
                            bad_number_count += 1
                            self.stdout.write(
                                self.style.ERROR("Skiping Number : " + phonenumber + "error: "+ str(e)))
                            if len(row_splited) == 1:
                                row_splited.append("Failed")
                            else:
                                row_splited[1] = "Failed"
                            listphonenumber[index] = ','.join(row_splited) + "\n"
                            with open(folder + file, 'w') as saving_file:
                                saving_file.writelines(listphonenumber)
                            continue
                        if response['status'] != '0':
                            bad_numbers.append(phonenumber)
                            bad_number_count += 1
                            self.stdout.write(
                                self.style.ERROR("Skiping Number : " + phonenumber + "error: " + txt_msg))
                            if len(row_splited) == 1:
                                row_splited.append("Failed")
                            else:
                                row_splited[1] = "Failed"
                            listphonenumber[index] = ','.join(row_splited) + "\n"
                            with open(folder + file, 'w') as saving_file:
                                saving_file.writelines(listphonenumber)
                            continue
                        else:
                            if len(row_splited) == 1:
                                row_splited.append("Sent")
                            else:
                                row_splited[1] = "Sent"
                            listphonenumber[index] = ','.join(row_splited) + "\n"
                            with open(folder + file, 'w') as saving_file:
                                saving_file.writelines(listphonenumber)
                            sent_count += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR("Skiping number : " + phonenumber + " (sudah pernah dikirim sebelumnya/ aplikasi active)"))
                        skip_count += 1

        self.stdout.write(self.style.SUCCESS("=====================sms Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(sent_count) + " sms sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " sms skiped ]"))
        self.stdout.write(self.style.ERROR("[ " + str(bad_number_count) + " number bad format ]"))
        self.stdout.write(self.style.ERROR("[ " + " ,".join(bad_numbers) + " ]"))
