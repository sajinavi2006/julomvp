import logging

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from juloserver.account.models import Account


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Retroloads accounts(ldde=True) to False because some of them are using the old flow"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("========== Start =========="))
        current_date = timezone.localtime(timezone.now()).date()
        cursor = connection.cursor()

        cursor.execute("""
            select A.account_id
            FROM ops.account A
            JOIN LATERAL (
                select loan_id, cdate
                FROM ops.loan
                WHERE A.account_id = account_id and loan_status_code >= 220
                ORDER BY loan_id DESC limit 1
            ) as L ON true
            JOIN LATERAL (
                select payday
                FROM ops.application
                WHERE A.account_id = account_id and product_line_code = 1
                and payday between 6 and 24
                ORDER BY application_id DESC limit 1
            ) as AP ON true
            where A.is_ldde = True and A.is_payday_changed = false
            and L.cdate between '2022-10-22' and %s
        """, [current_date])

        list_account_ids = [item[0] for item in cursor.fetchall()]
        total = Account.objects.filter(pk__in=list_account_ids).update(is_ldde=False)

        logger.info({
            'command': 'retroload_update_account_is_ldde_to_false',
            'list_account_ids': list_account_ids,
            'total': len(list_account_ids)
        })
        self.stdout.write(self.style.SUCCESS(
            "========== Total updating: {} ==========".format(total))
        )
        self.stdout.write(self.style.SUCCESS("========== Update Success =========="))
