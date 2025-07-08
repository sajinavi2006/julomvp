from builtins import str
import logging, sys

from django.core.management.base import BaseCommand
from ...clients import get_julo_pn_client
from ...models import Application

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'blast push notif for early payment collections'

    def handle(self, *args, **options):
        folder = '../../email_blast/early_payment_blast/pn/'
        dues = ['t-2', 't0']

        self.stdout.write(self.style.SUCCESS("==========PUSH notif Blast begin============"))
        sent_count = 0
        skip_count = 0
        for due in dues:
            file = due + ".csv"
            if due == 't-2':
                text = "Bayar Pinjaman JULO lebih cepat 2 hari dan RAIH Kesempatan Menang Undian UANG TUNAI Rp 2.5 JUTA. Cek Email untuk info lebih lanjut."
            elif due == 't0':
                text = "Bayar Pinjaman JULO Tepat Waktu dan RAIH Kesempatan Menang Undian UANG TUNAI Rp 2.5 JUTA. Cek Email untuk info lebih lanjut."
            self.stdout.write(self.style.WARNING("read gcm_reg_id list on : " + file))
            with open(folder + file, 'r') as opened_file:
                list_gcm_reg_id = opened_file.readlines()
            if len(list_gcm_reg_id[0].split(",")) == 6:
                list_gcm_reg_id[0] = list_gcm_reg_id[0].replace("\n", "") + ",result\n"
            with open(folder + file, 'w') as saving_file:
                saving_file.writelines(list_gcm_reg_id)

            for index, row in enumerate(list_gcm_reg_id):
                row = row.replace("\n", "")
                row_splited = row.split(",")
                if row_splited[0].strip() != "variant":
                    gcm_reg_id = row_splited[5].strip()
                    app_id = row_splited[2].strip()
                    app = Application.objects.get_or_none(pk=app_id)
                    name = app.fullname_with_title
                    try:
                        row_splited[6]
                        if row_splited[6].strip() == "Sent":
                            processed_row = True
                        else:
                            processed_row = False
                    except:
                        processed_row = False

                    if not processed_row and app:
                        self.stdout.write(self.style.WARNING("Kirim push notif ke : " + name + "....................."))

                        julo_pn_client = get_julo_pn_client()
                        julo_pn_client.early_payment_promo(gcm_reg_id, text)
                        if len(row_splited) == 6:
                            row_splited.append("Sent")
                        else:
                            row_splited[6] = "Sent"
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

