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
    help = 'blast email for retargeting'

    def handle(self, *args, **options):
        # API KEY for sendgrid message
        api_key = "--------------------------------sendgrid_API_KEY----------------------"
        if api_key == "--------------------------------sendgrid_API_KEY----------------------":
            self.stdout.write(self.style.ERROR("Error sendgrid API key belum di Setup"))
            return
        folder = '../../email_blast/retargeting_blast/'
        files = [f for f in listdir(folder) if isfile(join(folder, f))]

        self.stdout.write(self.style.SUCCESS("======================email Blast begin======================"))
        sent_count = 0
        skip_count = 0
        bad_email_count = 0
        bad_emails = []
        for file in files:
            self.stdout.write(self.style.WARNING("read email list on : " + file))
            with open(folder + file, 'r') as opened_file:
                listemail =  opened_file.readlines()
            if len(listemail[0].split(",")) == 13:
                listemail[0] = listemail[0].replace("\n", "") + ",result\n"
            with open(folder + file, 'w') as saving_file:
                    saving_file.writelines(listemail)

            for index, row in enumerate(listemail):
                row =  row.replace("\n", "")
                row_splited = row.split(",")
                if row_splited[0].strip() != "fullname":
                    email = row_splited[3].strip()
                    name = row_splited[0].strip()
                    gender = row_splited[1].strip()
                    try:
                        row_splited[13]
                        if row_splited[13].strip() == "Sent":
                            processed_row =True
                        else:
                            processed_row = False
                    except:
                        processed_row = False

                    if not processed_row:
                        self.stdout.write(self.style.WARNING("Kirim email ke : " + email + "....................."))
                        julo_email_client = get_julo_email_client_custom_api(api_key)
                        try:
                            status, headers, subject, content = julo_email_client.email_julo_promo_blast(email, name, gender)
                        except EmailNotSent:
                            bad_emails.append(email)
                            bad_email_count += 1
                            self.stdout.write(
                            self.style.ERROR("Skiping email : " + email + " format bermasalah"))
                            if len(row_splited) == 13:
                                row_splited.append("Failed")
                            else:
                                row_splited[13] = "Failed"
                            listemail[index] = ','.join(row_splited) + "\n"
                            with open(folder + file, 'w') as saving_file:
                                saving_file.writelines(listemail)
                            continue
                        if status == 202:
                            to_email = email
                            message_id = headers['X-Message-Id']

                            logger.info({
                                'status': status,
                                'message_id': message_id,
                                'to_email': to_email
                            })
                            if len(row_splited) == 13:
                                row_splited.append("Sent")
                            else:
                                row_splited[13] = "Sent"
                            listemail[index] = ','.join(row_splited) + "\n"
                            with open(folder + file, 'w') as saving_file:
                                saving_file.writelines(listemail)
                            sent_count += 1
                    else:
                        self.stdout.write(self.style.ERROR("Skiping email : " + email + " (sudah pernah dikirim sebelumnya)"))
                        skip_count += 1
        self.stdout.write(self.style.SUCCESS("=====================email Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ "+str(sent_count)+" email sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " email skiped ]"))
        self.stdout.write(self.style.ERROR("[ " + str(bad_email_count) + " email bad format ]"))
        self.stdout.write(self.style.ERROR("[ " + " ,".join(bad_emails) + " ]"))
