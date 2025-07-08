from builtins import str
import csv
import logging
import sys
from django.core.management.base import BaseCommand
from ...clients import get_julo_email_client
from ...exceptions import EmailNotSent


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'blast email for December Lottery Winner'

    def handle(self, *args, **options):
        files = '../../email_blast/blast_lottery_winner_list.csv'
        datas = []
        with open(files, 'r') as csvfile:
            r = csv.DictReader(csvfile)
            for row in r:
                data = {}
                data['email'] = row['email']
                data['fullname'] = row['fullname']
                data['gender'] = row['gender']
                datas.append(data)
        bad_email_count = 0
        sent_count = 0
        email_client = get_julo_email_client()
        self.stdout.write(
            self.style.SUCCESS(
                "==========Email Blast begin total: {}============".format(len(datas))))
        for data in datas:
            title = 'Bapak' if data['gender'] == 'Pria' else 'Ibu'
            fullname_with_title = '{} {}'.format(title, data['fullname'])
            email = data['email']
            try:
                status, headers, subject, content = email_client.email_lottery_winner_blast(
                    email, fullname_with_title)
            except EmailNotSent:
                bad_email_count += 1
                self.stdout.write(
                    self.style.ERROR("Skiping email : " + email + " format bermasalah"))
                continue

            if status == 202:
                to_email = email
                message_id = headers['X-Message-Id']

                logger.info({
                    'status': status,
                    'message_id': message_id,
                    'to_email': to_email
                })
                sent_count += 1

        self.stdout.write(self.style.SUCCESS("Total Email Sent : " + str(sent_count)))
        self.stdout.write(self.style.ERROR("Total Email Not Sent : " + str(bad_email_count)))
        self.stdout.write(
            self.style.SUCCESS("======================email Blast End======================"))
