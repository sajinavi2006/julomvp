from django.core.management import BaseCommand
from django.db import connection


from juloserver.sales_ops.models import SalesOpsLineup
from juloserver.sales_ops.utils import chunker
from juloserver.sales_ops.tasks import update_sales_ops_latest_rpc_agent_assignment_task


class Command(BaseCommand):
    help = "Update latest RPC agent assignment for Sales Ops lineups."

    def handle(self, *args, **options):
        sales_ops_lineup_ids = SalesOpsLineup.objects.values_list('id', flat=True)
        for sub_sales_ops_lineup_ids in chunker(sales_ops_lineup_ids.iterator(), size=1000):
            update_sales_ops_latest_rpc_agent_assignment_task.delay(sub_sales_ops_lineup_ids)
            self.stdout.write(
                self.style.SUCCESS('Update latest RPC agent assignment is success.')
            )
