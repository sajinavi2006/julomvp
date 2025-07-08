import logging
import sys
import csv

from django.core.management.base import BaseCommand
from django.utils import timezone

from juloserver.collection_vendor.models import (
    CollectionVendor,
    CollectionVendorAssignment,
    CollectionVendorRatio
)
from juloserver.collection_vendor.services import get_current_sub_bucket
from juloserver.julo.models import Loan, Application
from juloserver.collection_vendor.constant import CollectionVendorCodes


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retroload data b5 to vendor fc insert to collection assignment vendor'

    def handle(self, *args, **options):
        csv_file_name = 'misc_files/csv/field_account.csv'
        self.stdout.write(self.style.WARNING(
            'Start read csv')
        )
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                application = Application.objects.get_or_none(pk=int(row['application_id']))
                if not application:
                    self.stdout.write(self.style.ERROR(
                        'application not found for application_id {}'.format(
                            row['application_id']
                        ))
                    )
                    logger.error({
                        'action': 'retroload_collection_vendor_reassign_to_fc',
                        'application_id': row['application_id'],
                        'message': 'application not found'
                    })
                    continue
                loan = Loan.objects.get_or_none(application=application)
                if not loan:
                    self.stdout.write(self.style.ERROR(
                        'loan not found for application id {}'.format(application.id))
                    )
                    logger.error({
                        'action': 'retroload_collection_vendor_assignment_table_reassign_to_fc',
                        'application_id': row['application_id'],
                        'message': 'loan not found'
                    })
                    continue
                payment = loan.get_oldest_unpaid_payment()
                collection_vendor_assignment = CollectionVendorAssignment.objects.filter(
                    payment=payment,
                    is_active_assignment=True
                ).last()
                if not collection_vendor_assignment:
                    self.stdout.write(self.style.ERROR(
                        'collection vendor not found for application id {}'.format(application.id))
                    )
                    logger.error({
                        'action': 'retroload_collection_vendor_reassign_to_fc',
                        'application_id': row['application_id'],
                        'loan_id': loan.id,
                        'payment_id': payment.id,
                        'message': 'collection_vendor_assignment not found'
                    })
                    continue
                collection_vendor_assignment.update_safely(
                    is_active_assignment=False,
                    unassign_time=timezone.localtime(timezone.now())
                )
                assign_date = timezone.localtime(timezone.now())
                today_subbucket = get_current_sub_bucket(payment)
                collection_vendor = CollectionVendor.objects.filter(
                    vendor_name='Field Collector'
                ).last()
                vendor_type = CollectionVendorCodes.VENDOR_TYPES.get('final')

                collection_vendor_ratio = CollectionVendorRatio.objects.filter(
                    collection_vendor=collection_vendor,
                    vendor_types=vendor_type
                ).last()

                CollectionVendorAssignment.objects.create(
                    vendor=collection_vendor,
                    sub_bucket_assign_time=today_subbucket,
                    payment=collection_vendor_assignment.payment,
                    vendor_configuration=collection_vendor_ratio,
                    dpd_assign_time=payment.due_late_days,
                    assign_time=assign_date,
                )
                self.stdout.write(self.style.SUCCESS(
                    'stored payment id {} to table collection assignment vendor'.format(payment.id))
                )
        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return
        self.stdout.write(self.style.SUCCESS(
            '=========Finish=========')
        )
