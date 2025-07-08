import logging
import sys
import csv

from django.core.management.base import BaseCommand
from datetime import datetime, timedelta
from django.utils.dateparse import parse_datetime
import pytz

from juloserver.collection_vendor.models import (
    CollectionVendor,
    CollectionVendorAssignment,
    CollectionVendorRatio
)
from juloserver.collection_vendor.services import get_current_sub_bucket
from juloserver.julo.models import Loan, Application
from juloserver.collection_vendor.constant import (
    CollectionVendorCodes,
    CollectionVendorAssignmentConstant
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retroload data b5 existing on vendor selaras insert to collection assignment vendor'

    def handle(self, *args, **options):
        csv_file_name = 'misc_files/csv/payments_assign_to_vendor_selaras.csv'
        self.stdout.write(self.style.WARNING(
            'Start read csv')
        )
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            for row in rows:
                if row['application_xid'] in [
                    '3225255039', '1000061694', '1532020761', '5405116040'
                ]:
                    continue
                application = Application.objects.get_or_none(
                    application_xid=int(row['application_xid'])
                )
                if not application:
                    self.stdout.write(self.style.ERROR(
                        'application not found for application_xid {}'.format(
                            row['application_xid']
                        ))
                    )
                    continue
                loan = Loan.objects.get_or_none(application=application)
                if not loan:
                    self.stdout.write(self.style.ERROR(
                        'loan not found for application id {}'.format(application.id))
                    )
                    continue
                payment = loan.get_oldest_unpaid_payment()
                if not payment:
                    self.stdout.write(self.style.ERROR(
                        'payment not found for loan id {}'.format(loan.id))
                    )
                    continue
                if payment.due_late_days > 720:
                    self.stdout.write(self.style.ERROR(
                        'payment id {} DPD greater than 720'.format(payment.id))
                    )
                    continue
                assign_date = parse_datetime(row['assign_date'])
                today_subbucket = get_current_sub_bucket(payment)
                collection_vendor = CollectionVendor.objects.filter(
                    vendor_name='Selaras'
                ).last()
                vendor_type = CollectionVendorCodes.VENDOR_TYPES.get('special')
                if today_subbucket.sub_bucket in [1, 2]:
                    vendor_type = CollectionVendorCodes.VENDOR_TYPES.get('general')
                elif today_subbucket.sub_bucket == 3:
                    vendor_type = CollectionVendorCodes.VENDOR_TYPES.get('final')

                assign_date_expire = assign_date + timedelta(
                    days=CollectionVendorAssignmentConstant.EXPIRATION_DAYS_BY_VENDOR_TYPE.__dict__[
                        vendor_type.lower()
                    ]
                )
                utc = pytz.UTC
                release_date = utc.localize(datetime(2020, 11, 10))
                if assign_date_expire < release_date:
                    assign_date = release_date

                collection_vendor_ratio = CollectionVendorRatio.objects.filter(
                    collection_vendor=collection_vendor,
                    vendor_types=vendor_type
                ).last()

                CollectionVendorAssignment.objects.create(
                    vendor=collection_vendor,
                    sub_bucket_assign_time=today_subbucket,
                    payment=payment,
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
