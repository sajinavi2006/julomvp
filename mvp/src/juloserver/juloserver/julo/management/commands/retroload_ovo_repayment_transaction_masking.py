import math

from django.core.management.base import BaseCommand
from django.db.models import Q
from bulk_update.helper import bulk_update

from juloserver.ovo.models import OvoRepaymentTransaction
from juloserver.ovo.utils import mask_phone_number_preserve_last_four_digits


class Command(BaseCommand):
    help = 'Helps to mask all phone number in ovo_repayment_transaction table'

    def add_arguments(self, parser):
        parser.add_argument('--start_id', type=int, help='start ovo transaction id for query')

    def handle(self, *args, **options):
        ovo_repayment_transactions = OvoRepaymentTransaction.objects.order_by("cdate")
        start_id = options.get('start_id')

        if start_id:
            ovo_repayment_transactions = ovo_repayment_transactions.filter(
                pk__gte=start_id,
            )
        ovo_repayment_transactions.all()

        self.stdout.write("COLLECTING OVO TRANSACTION DATA =============")
        try:
            ovo_repayment_update = []
            for ovo_repayment_transaction in ovo_repayment_transactions:
                ovo_repayment_transaction.phone_number = (
                    mask_phone_number_preserve_last_four_digits(
                        ovo_repayment_transaction.phone_number
                    )
                )

                ovo_repayment_update.append(ovo_repayment_transaction)
        except Exception as e:
            self.stdout.write("Error found: " + e)
            if ovo_repayment_transaction:
                self.stdout.write("last processed id: " + ovo_repayment_transaction.id)

        self.stdout.write("BULK UPDATE START =============")
        # UPDATE ALL
        bulk_update(
            ovo_repayment_update,
            update_fields=['phone_number'],
            batch_size=500,
        )
        self.stdout.write("BULK UPDATE FINISHED =============")
