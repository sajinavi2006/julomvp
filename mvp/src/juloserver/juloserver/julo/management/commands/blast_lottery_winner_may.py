from __future__ import print_function
import logging
import sys
import csv

from django.core.management.base import BaseCommand
from juloserver.julo.clients import get_julo_email_client
from django.template.loader import render_to_string
from juloserver.julo.models import EmailHistory
from juloserver.julo.models import Application
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
                email_client = get_julo_email_client()
                template_name = 'email_lottery_winner_may_2019'
                try:
                    application = Application.objects.filter(email=row['email']).last()
                    if not application:
                        print('Application not found {}'.format(row['email']))
                        continue
                    title = 'Bapak' if application.gender == 'Pria' else 'Ibu'
                    fullname_with_title = '{} {}'.format(title, row['fullname'])
                    context = {
                        'fullname_with_title': fullname_with_title,
                    }
                    message = render_to_string(template_name + '.html', context)
                    subject = 'Pengumuman Pemenang Undian Periode 17 April 2019 - 8 Mei 2019'
                    status, body, headers = email_client.send_email(
                        subject=subject,
                        content=message,
                        email_to=row['email']
                    )
                    message_id = headers['X-Message-Id']
                    email = EmailHistory.objects.create(
                        application=application,
                        customer=application.customer,
                        sg_message_id=message_id,
                        to_email=row['email'],
                        subject=subject,
                        message_content=message,
                        template_code=template_name,
                    )
                except Exception as e:
                    pass
        except IOError:
            logger.error("could not open given file " + path)
            return
