from __future__ import print_function
from builtins import str
import logging
import os
import sys
from django.core.management.base import BaseCommand

from juloserver.graduation.models import GraduationCustomerHistory2
from juloserver.sales_ops.utils import chunker


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'migrate graduation data from GraduationCustomerHistory to GraduationCustomerHistory2'

    def handle(self, *args, **options):
        # Get all old records
        old_graduation_customer_list = GraduationCustomerHistory2.objects.all().iterator()
        self.stdout.write(self.style.SUCCESS(
            'Migrate graduation data --BEGIN--'))
        # Start migrate
        for old_graduation_batch in chunker(old_graduation_customer_list):
            migrated_new_graduation_list = []
            for old_graduation in old_graduation_batch:
                migrated_new_graduation_list.append(
                    GraduationCustomerHistory2(
                        cdate=old_graduation.cdate,
                        udate=old_graduation.udate,
                        account_id=old_graduation.account_id,
                        graduation_type=old_graduation.graduation_type,
                        available_limit_history_id=old_graduation.available_limit_history_id,
                        max_limit_history_id=old_graduation.max_limit_history_id,
                        set_limit_history_id=old_graduation.set_limit_history_id,
                        latest_flag=old_graduation.latest_flag,
                    )
                )
            GraduationCustomerHistory2.objects.bulk_create(migrated_new_graduation_list)
        self.stdout.write(self.style.SUCCESS(
            'Successfully migrate all graduation data to new table'))
