from django.core.management import BaseCommand

from juloserver.cashback.utils import chunker_iterables
from juloserver.customer_module.models import CashbackBalance


class Command(BaseCommand):
    help = "correcting user's cashback balance " \
           "to the sum of all the verified cashback earned current balance " \
           "(found in customer wallet history -> cashback earned -> " \
           "current balance of that customer)"

    def handle(self, *args, **options):
        from juloserver.cashback.tasks import update_cashback_balance_by_batch
        customers_with_cashback = CashbackBalance.objects.values_list('customer_id', flat=True)

        self.stdout.write('-----Updating CashbackBalance Table-----', ending='\n')
        total = 0
        for sub_customer_ids in chunker_iterables([customers_with_cashback.iterator()]):
            update_cashback_balance_by_batch.delay(sub_customer_ids)
            total += 2000
            self.stdout.write('---Number of customers processed: {}'.format(total), ending='\n')

        self.stdout.write(self.style.SUCCESS('-----Finished Updating CashbackBalance Table-----'))
