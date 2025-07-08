from builtins import str
import logging, sys

from django.core.management.base import BaseCommand

from os import listdir
from os.path import isfile, join
from django.conf import settings
from ...clients.email import JuloEmailClient
from os import remove
from juloserver.julo.exceptions import EmailNotSent

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


def get_julo_email_client_custom_api(api_key):
    return JuloEmailClient(
        api_key,
        settings.EMAIL_FROM
    )

class Command(BaseCommand):
    help = 're-blast email for julo review challenge'

    def add_arguments(self, parser):
        parser.add_argument('reset_log', type=str, nargs='?', default="no-reset")

    def handle(self, *args, **options):
        # API KEY for sendgrid message
        api_key = "--------------------------------sendgrid_API_KEY----------------------"

        reset_arg = options['reset_log']
        folder = '../../email_blast/julo_review_challenge_emails_v2/'
        files = [f for f in listdir(folder) if isfile(join(folder, f))]
        log_file = '../../email_blast/julo_review_challenge_v2_sents.txt'

        if reset_arg == "reset_log":
            try:
                file = open(log_file, 'r')
                remove(log_file)
            except IOError:
                pass

        try:
            file = open(log_file, 'r')
        except IOError:
            file = open(log_file, 'w')

        sent_emails = [line.rstrip('\n') for line in open(log_file)]
        self.stdout.write(self.style.SUCCESS("======================email Blast begin======================"))
        sent_count = 0
        skip_count = 0
        bad_email_count = 0
        bad_emails = []
        for file in files:
            self.stdout.write(self.style.WARNING("read email list on : " + file))
            listemail = [line.rstrip('\n') for line in open(folder + file)]
            for row in listemail:
                row_splited = row.split(";")
                if row_splited[0].strip() != "No":
                    email = row_splited[1].strip()
                    if email not in sent_emails:
                        self.stdout.write(self.style.WARNING("Kirim email ke : " + email + "....................."))
                        julo_email_client = get_julo_email_client_custom_api(api_key)
                        try:
                            status, headers, subject, content = julo_email_client.email_julo_review_challenge_blast(email)
                        except EmailNotSent:
                            bad_emails.append(email)
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
                            with open(log_file, 'a') as log:
                                log.write(email + '\n')
                            sent_count += 1
                    else:
                        self.stdout.write(self.style.ERROR("Skiping email : " + email + " (sudah pernah dikirim sebelumnya)"))
                        skip_count += 1
        self.stdout.write(self.style.SUCCESS("=====================email Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ "+str(sent_count)+" email sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " email skiped ]"))
        self.stdout.write(self.style.ERROR("[ " + str(bad_email_count) + " email bad format ]"))
        self.stdout.write(self.style.ERROR("[ " + " ,".join(bad_emails) + " ]"))
