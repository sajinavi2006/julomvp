from builtins import str
import logging, sys

from django.core.management.base import BaseCommand

from os import listdir
from os.path import isfile, join
from django.conf import settings
from ...clients.email import JuloEmailClient


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


def get_julo_email_client_custom_api(api_key):
    return JuloEmailClient(
        api_key,
        settings.EMAIL_FROM
    )

class Command(BaseCommand):
    help = 'blast email for julo review challenge with saving calculation'

    def handle(self, *args, **options):
        # API KEY for sendgrid message
        api_key = "--------------------------------sendgrid_API_KEY----------------------"

        folder = '../../email_blast/julo_saving_review_challenge_emails/'
        files = [f for f in listdir(folder) if isfile(join(folder, f))]
        log_file = '../../email_blast/julo_saving_review_challenge_sents.txt'
        sent_emails = [line.rstrip('\n') for line in open(log_file)]
        self.stdout.write(self.style.SUCCESS("======================email Blast begin======================"))
        sent_count = 0
        skip_count = 0
        for file in files:
            self.stdout.write(self.style.WARNING("read email list on : " + file))
            listemail = [line.rstrip('\n') for line in open(folder + file)]
            for row in listemail:
                row_splited = row.split(";")
                if row_splited[0] != "customer_id":
                    email = row_splited[2].strip()
                    name =  row_splited[1]
                    saving = row_splited[6].strip()
                    if email not in sent_emails:
                        self.stdout.write(self.style.WARNING("Kirim email ke : " + email + "....................."))
                        julo_email_client = get_julo_email_client_custom_api(api_key)
                        status, headers, subject, content = julo_email_client.email_julo_review_challenge_2_blast(email, name, saving)

                        if status == 202:
                            to_email = email
                            message_id = headers['X-Message-Id']

                            logger.info({
                                'status': status,
                                'message_id': message_id,
                                'to_email': to_email
                            })
                            with open(log_file, 'a') as log:
                                log.write(email + '\n')
                            sent_count += 1
                    else:
                        self.stdout.write(self.style.ERROR("Skiping email : " + email + " (sudah pernah dikirim sebelumnya)"))
                        skip_count += 1
        self.stdout.write(self.style.SUCCESS("=====================email Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ "+str(sent_count)+"email sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + "email skiped ]"))