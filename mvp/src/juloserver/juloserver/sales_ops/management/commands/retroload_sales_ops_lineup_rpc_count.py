from django.core.management import BaseCommand
from juloserver.sales_ops.utils import chunker
from juloserver.sales_ops.models import SalesOpsLineup


class Command(BaseCommand):
    help = "Retro load the sales_ops_lineup rpc_count column."
    query_limit = 2000

    def handle(self, *args, **options):
        from juloserver.sales_ops.tasks import update_sales_ops_lineup_rpc_count
        lineup_ids = SalesOpsLineup.objects.values_list('id', flat=True)
        self.stdout.write('-----Updating rpc_count column in SalesOpsLineup Table-----', ending='\n')
        for sub_lineup_ids in chunker(lineup_ids.iterator(), self.query_limit):
            update_sales_ops_lineup_rpc_count.delay(sub_lineup_ids)

        self.stdout.write(self.style.SUCCESS('Retro load for RPC count is successful .'))
