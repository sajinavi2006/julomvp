from builtins import str
import logging, sys

from django.core.management.base import BaseCommand
from ...clients import get_julo_pn_client
from ...models import Application
from os import listdir
from os.path import isfile, join

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'blast push notif for early payment collections'

    def handle(self, *args, **options):
        folder = '../../email_blast/blast_coll_campaign_sept_21/pn/'
        files = [f for f in listdir(folder) if isfile(join(folder, f))]

        self.stdout.write(self.style.SUCCESS("==========PUSH notif Blast begin============"))
        sent_count = 0
        skip_count = 0
        for file in files:
            self.stdout.write(self.style.WARNING("read gcm_reg_id list on : " + file))
            with open(folder + file, 'r') as opened_file:
                list_gcm_reg_id = opened_file.readlines()
            if len(list_gcm_reg_id[0].split(",")) == 18:
                list_gcm_reg_id[0] = list_gcm_reg_id[0].replace("\n", "") + ",result\n"
            with open(folder + file, 'w') as saving_file:
                saving_file.writelines(list_gcm_reg_id)

            for index, row in enumerate(list_gcm_reg_id):
                row = row.replace("\n", "")
                row_splited = row.split(",")
                if row_splited[0].strip() != "variant":
                    variant = row_splited[0].strip()
                    gcm_reg_id = row_splited[4].strip()
                    name = row_splited[7].strip()
                    if variant == "Control: No Promo":
                        continue
                    if variant == 'Test: HP Samsung':
                        text = "Bayar Pinjaman JULO lebih cepat 2 hari dan RAIH Kesempatan Menang Undian HP SAMSUNG. Cek Email untuk info lebih lanjut."
                    elif variant == 'Test: 2 juta':
                        text = "Bayar Pinjaman JULO lebih cepat 2 hari dan RAIH Kesempatan Menang Undian UANG TUNAI Rp 2 JUTA. Cek Email untuk info lebih lanjut."
                    elif variant == 'Test: 5 juta':
                        text = "Bayar Pinjaman JULO lebih cepat 2 hari dan RAIH Kesempatan Menang Undian UANG TUNAI Rp 5 JUTA. Cek Email untuk info lebih lanjut."
                    try:
                        row_splited[18]
                        if row_splited[18].strip() == "Sent":
                            processed_row = True
                        else:
                            processed_row = False
                    except:
                        processed_row = False

                    if not processed_row:
                        self.stdout.write(self.style.WARNING("Kirim push notif ke : " + name + "....................."))

                        julo_pn_client = get_julo_pn_client()
                        julo_pn_client.early_payment_promo(gcm_reg_id, text)
                        if len(row_splited) == 18:
                            row_splited.append("Sent")
                        else:
                            row_splited[18] = "Sent"
                        list_gcm_reg_id[index] = ','.join(row_splited) + "\n"
                        with open(folder + file, 'w') as saving_file:
                            saving_file.writelines(list_gcm_reg_id)
                        sent_count += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR("Skiping customer : " + name + " (sudah pernah dikirim sebelumnya)"))
                        skip_count += 1

        self.stdout.write(self.style.SUCCESS("=====================sms Blast finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(sent_count) + " customer sent ]"))
        self.stdout.write(self.style.ERROR("[ " + str(skip_count) + " customer skiped ]"))

