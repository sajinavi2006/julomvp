from __future__ import print_function
import logging
import sys
import csv

from django.core.management.base import BaseCommand
from juloserver.julo.clients import get_julo_sms_client
from django.template.loader import render_to_string
from juloserver.julo.models import Application
from juloserver.julo.models import SmsHistory
from juloserver.julo.statuses import ApplicationStatusCodes
from ...utils import format_e164_indo_phone_number
from juloserver.streamlined_communication.utils import get_telco_code_and_tsp_name

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        try:
            with open(path, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                client = get_julo_sms_client()
                template_name = 'sms_cancelled_customer'
                context = {
                    'url': 'http://julo.co.id/r/sms137'
                }
                message = render_to_string(template_name + '.txt', context)
                try:
                    application = Application.objects.filter(mobile_phone_1=row['mobile_phone_1'],
                                                             application_status = ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER)\
                                                            .last()

                    if not application:
                        print('Application not found {}'.format(row['mobile_phone_1']))
                        continue
                    phone_number = format_e164_indo_phone_number(application.mobile_phone_1)
                    telco_code, tsp = get_telco_code_and_tsp_name(application.mobile_phone_1)
                    text_message, response = client.send_sms(phone_number, message)
                    response = response['messages'][0]
                    if response['status'] == '0':
                        sms = SmsHistory.objects.create(
                            customer=application.customer,
                            application=application,
                            template_code=template_name,
                            message_id=response['message-id'],
                            message_content=text_message,
                            to_mobile_phone=format_e164_indo_phone_number(response['to']),
                            phone_number_type='mobile_phone_1',
                            tsp=tsp
                        )
                except Exception as e:
                    logger.error("not able to send sms to " + row['mobile_phone_1'] )
        except IOError:
            logger.error("could not open given file " + path)
            return

