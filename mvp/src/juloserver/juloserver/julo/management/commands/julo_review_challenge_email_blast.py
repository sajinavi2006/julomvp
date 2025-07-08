from builtins import str
import logging, sys

from django.core.management.base import BaseCommand

from os import listdir
from os.path import isfile, join

from ...clients import get_julo_email_client



logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'blast email for julo review challenge'

    def handle(self, *args, **options):
        folder = '../../email_blast/julo_review_challenge_emails/'
        files = [f for f in listdir(folder) if isfile(join(folder, f))]
        log_file = '../../email_blast/julo_review_challenge_sents.txt'
        sent_emails = [line.rstrip('\n') for line in open(log_file)]
        emails = []
        for file in files:
            listemail = [line.rstrip('\n') for line in open(folder + file)]
            filtered_emails = list([x for x in listemail if x.strip() not in sent_emails])
            emails.extend(filtered_emails)
            self.stdout.write(self.style.WARNING("read email list on : " + file))
            self.stdout.write(str(len(filtered_emails)) + " Emails to proccess")
        self.stdout.write(self.style.SUCCESS("======================email Blast begin======================"))
        for email in emails:
            email = email.strip()
            self.stdout.write("Kirim email ke : " + email + ".....................")
            julo_email_client = get_julo_email_client()
            status, headers, subject, content = julo_email_client.email_julo_review_challenge_blast(email)

            if status == 202:
                to_email = email
                message_id = headers['X-Message-Id']

                # EmailHistory.objects.create(
                #     customer=customer,
                #     sg_message_id=message_id,
                #     to_email=to_email,
                #     subject=subject,
                #     message_content=content,
                # )

                logger.info({
                    'status': status,
                    'message_id': message_id,
                    'to_email': to_email
                })
                with open(log_file, 'a') as log:
                    log.write(email + '\n')
        self.stdout.write(self.style.SUCCESS("=====================email Blast finished====================="))
