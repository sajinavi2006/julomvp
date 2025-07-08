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
from juloserver.streamlined_communication.utils import get_telco_code_and_tsp_name


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'sms blast to reapply for customer in manado area'

    def handle(self, *args, **options):
        file = 'report_sms_blast.txt'

        # Query existing customer from manado
        cursor = connection.cursor()
        cursor.execute('''select distinct c.customer_id FROM ops.address_geolocation a \
            join ana.julo_area b on ana.st_covers \
            (b.mpoly, ana.ST_SetSRID(ana.ST_MakePoint(a.Longitude, a.Latitude),4326)) \
            join ops.application c on c.application_id = a.application_id where b.julo_area_id=1''')
        customer_ids = cursor.fetchone()

        self.stdout.write(self.style.SUCCESS("==========SMS Blast begin============: {} customers".format(
            len(customer_ids))))
        sent_count = 0
        failed_count = 0
        failed_sms_customer = []
        for customer_id in customer_ids:
            application = Application.objects.filter(
                customer_id=customer_id).order_by('-cdate').first()
            self.stdout.write(self.style.WARNING("Kirim sms ke : {} .....................".format(
                customer_id)))
            phone_number = application.mobile_phone_1
            mobile_number = format_e164_indo_phone_number(phone_number)
            if phone_number:
                get_julo_sms = get_julo_sms_client()
                text = "JULO di Manado! Aplikasi JULO baru saja terupdate. Ayo ajukan Pinjaman Tanpa Jaminan hingga Rp 5 Juta, sekarang! bit.ly/juloapp"
                try:
                    txt_msg, response = get_julo_sms.sms_custom_payment_reminder(mobile_number, text)
                except Exception as e:
                    failed_sms_customer.append(customer_id)
                    failed_count += 1
                    self.stdout.write(
                        self.style.ERROR("Skiping customer : {} gagal kirim SMS ke {} -- {}".format(
                            customer_id, phone_number, str(e))))
                    with open(file, 'w') as saving_file:
                        saving_file.writelines('failed sms to customer: {} application {}'.format(
                            customer_id, application.id))
                    continue

                if response['status'] != '0':
                    failed_sms_customer.append(customer_id)
                    failed_count += 1
                    self.stdout.write(
                        self.style.ERROR("Skiping customer : {} gagal kirim SMS ke {} -- {}".format(
                            customer_id, phone_number, response.get('error-text'))))
                    with open(file, 'w') as saving_file:
                        saving_file.writelines('failed sms to customer: {} application {}'.format(
                            customer_id, application.id))
                    continue
                else:
                    with open(file, 'w') as saving_file:
                        saving_file.writelines('sent sms to customer: {} application {}'.format(
                            customer_id, application.id))
                    sent_count += 1
                    telco_code, tsp = get_telco_code_and_tsp_name(application.mobile_phone_1)

                    sms = SmsHistory.objects.create(
                        customer=application.customer,
                        message_id=response['message-id'],
                        message_content=txt_msg,
                        to_mobile_phone=format_e164_indo_phone_number(response['to']),
                        phone_number_type='mobile_phone_1',
                        tsp=tsp
                    )

                    logger.info({
                        'status': 'sms_created',
                        'sms_history_id': sms.id,
                        'message_id': sms.message_id
                    })

        self.stdout.write(self.style.SUCCESS("=====================SMS Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ "+str(sent_count)+" sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(failed_count) + "  failed ]"))
        self.stdout.write(self.style.ERROR("[ {} ]".format(failed_sms_customer)))
