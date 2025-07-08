from builtins import str
import logging
import sys
import csv

from django.core.management.base import BaseCommand
from collections import OrderedDict
from ...clients import get_julo_sms_client
from ...utils import format_e164_indo_phone_number

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'blast sms onboarding paylater'

    def handle(self, *args, **options):
        folder = '../../email_blast/paylater_onboarding/'

        self.stdout.write(self.style.SUCCESS("==========SMS Blast begin============"))
        sent_count = 0
        bad_number_count = 0
        bad_numbers = []
        filename = "customer-bl-paylater.csv"

        text = "Belanja dulu, BayarNanti aja di Bukalapak. Nikmati promo gratis biaya transaksi hanya selama bulan Ramadhan. Cari tahu yuk disini https://julo.co.id/r/BYrNt1"

        self.stdout.write(self.style.WARNING("read phone number list on : " + filename))
        temp_rows = []
        with open(folder + filename, 'r') as csvin:
            rows = csv.DictReader(csvin)

            for row in rows:
                if row['phone_number'] == '':
                    temp_rows.append(row)
                    continue

                if row['status'] == 'sent':
                    temp_rows.append(row)
                    continue

                phonenumber = str(row['phone_number']).strip()

                self.stdout.write(self.style.WARNING("Kirim sms ke : " + phonenumber + "....................."))
                mobile_number = format_e164_indo_phone_number(phonenumber)
                get_julo_sms = get_julo_sms_client()
                try:
                    txt_msg, response = get_julo_sms.sms_custom_payment_reminder(mobile_number, text)
                except Exception as e:
                    bad_numbers.append(phonenumber)
                    bad_number_count += 1
                    self.stdout.write(
                        self.style.ERROR("Skiping Number : " + phonenumber + "error: " + str(e)))
                    row['status'] = "failed"

                    temp_rows.append(row)
                    continue

                if response['status'] != '0':
                    bad_numbers.append(phonenumber)
                    bad_number_count += 1
                    row['status'] = "failed"
                    self.stdout.write(
                        self.style.ERROR("Skiping Number : " + phonenumber))
                else:
                    sent_count += 1
                    row['status'] = "sent"
                    self.stdout.write(
                        self.style.ERROR("Sent to Number : " + phonenumber))

                temp_rows.append(row)

            with open(folder + filename, 'w') as csvout:
                dw = csv.DictWriter(csvout,  fieldnames=('phone_number', 'status'))
                dw.writeheader()
                dw.writerows(temp_rows)

        self.stdout.write(self.style.SUCCESS("=====================sms Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(sent_count) + " sms sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(bad_number_count) + " number bad format ]"))
        self.stdout.write(self.style.ERROR("[ " + " ,".join(bad_numbers) + " ]"))
