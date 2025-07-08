from builtins import str
from django.core.management.base import BaseCommand

from juloserver.julo.models import Payment


class Command(BaseCommand):
    help = 'update_attribute_payment'

    def handle(self, *args, **options):
        file_data = '../../ojk_retroload_data/payment_transaction.csv'

        self.stdout.write(self.style.SUCCESS("======================update attribute payment begin======================"))
        failed_count = 0
        failed_data = {}
        success_count = 0
        skip_count = 0
        skip_data = {}

        with open(file_data, 'r') as opened_file:
            list_data = opened_file.readlines()

        for index, row in enumerate(list_data):
            row = row.replace("\n", "")
            row_splited = row.split(",")

            if row_splited[0].strip() == 'payment_id':
                continue

            payment_id = row_splited[0].strip()
            paid_principal = int(row_splited[1])
            paid_interest = int(row_splited[2])
            paid_latefee = int(row_splited[3])

            try:
                payment = Payment.objects.get_or_none(pk=payment_id)
                if payment.paid_interest == paid_interest and payment.paid_principal == paid_principal and payment.paid_late_fee == paid_latefee:
                    skip_count += 1
                    skip_data[payment_id] = "Payment id has been skiped"
                    continue

                if not payment:
                    failed_count += 1
                    failed_data[payment_id] = "payment id not exist"
                    continue

                payment.update_safely(paid_interest=paid_interest, paid_principal=paid_principal, paid_late_fee=paid_latefee)
                self.stdout.write(self.style.SUCCESS("payment id {} has been success updated".format(payment_id)))
                success_count += 1
            except Exception as e:
                failed_count += 1
                failed_data[payment_id] = str(e)

        self.stdout.write(self.style.SUCCESS("=====================update attribute payment finished====================="))
        self.stdout.write(self.style.SUCCESS("[ " + str(success_count) + " success update attribute payment ]"))
        self.stdout.write(self.style.SUCCESS("[ " + str(skip_count) + " skip update attribute payment ]"))
        self.stdout.write(self.style.SUCCESS("[ " + str(skip_data) + " ]"))
        self.stdout.write(self.style.ERROR("[ " + str(failed_count) + " failed update attribute payment ]"))
        self.stdout.write(self.style.ERROR("[ " + str(failed_data) + " ]"))
