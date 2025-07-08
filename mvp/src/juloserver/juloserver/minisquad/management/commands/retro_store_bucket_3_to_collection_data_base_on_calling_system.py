import ast
import logging
import sys
from django.core.management.base import BaseCommand
from datetime import timedelta
from django.utils import timezone
from juloserver.minisquad.services2.dialer_related import \
    get_eligible_account_payment_for_dialer_and_vendor_qs
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.constants import BucketConst
from juloserver.minisquad.models import (
    SentToDialer,
    NotSentToDialer,
    CollectionBucketInhouseVendor
)
from juloserver.minisquad.constants import (
    ReasonNotSentToDialer,
    IntelixTeam
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'store existing bucket 3 data to new table base on calling system'

    def handle(self, *args, **options):
        try:
            # get all unpaid on bucket 3
            today_date = timezone.localtime(timezone.now()).date()
            unpaid_account_payment_ids = list(
                get_eligible_account_payment_for_dialer_and_vendor_qs().values_list('id', flat=True)
            )
            due_date_filter = [
                today_date - timedelta(BucketConst.BUCKET_3_DPD['to']),
                today_date - timedelta(BucketConst.BUCKET_3_DPD['from'])
            ]
            b3_unpaid_account_payments = list(
                AccountPayment.objects.filter(id__in=unpaid_account_payment_ids
                ).filter(due_date__range=due_date_filter, is_collection_called=False
                ).exclude(account__ever_entered_B5=True).values_list('id', flat=True)
            )
            # just want to make sure we not store duplicate data
            existing_data_on_new_collection_table_ids = \
                list(CollectionBucketInhouseVendor.objects.all().values_list('account_payment', flat=True))

            # check condition if account payment on inhouse
            data_on_inhouse = SentToDialer.objects.filter(
                account_payment__in=b3_unpaid_account_payments,
                bucket__in=IntelixTeam.ALL_B3_BUCKET_LIST,
                cdate__date=today_date
            ).exclude(
                account_payment__in=existing_data_on_new_collection_table_ids
            ).only('account_payment', 'bucket').distinct('account_payment_id')
            data_inhouse_to_new_tables = []
            if data_on_inhouse:
                for data in data_on_inhouse:
                    data_inhouse_to_new_table = dict(
                        account_payment=data.account_payment,
                        bucket=data.bucket,
                        vendor=False
                    )
                    data_inhouse_to_new_tables.append(
                        CollectionBucketInhouseVendor(**data_inhouse_to_new_table)
                    )

                CollectionBucketInhouseVendor.objects.bulk_create(
                    data_inhouse_to_new_tables, batch_size=1000
                )

            # check condition if account payment on vendor
            data_on_vendor = NotSentToDialer.objects.filter(
                account_payment__in=b3_unpaid_account_payments,
                bucket__in=[IntelixTeam.JULO_B3, IntelixTeam.JULO_B3_NC],
                cdate__date=today_date,
                unsent_reason=ast.literal_eval(
                    ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR'])
            ).exclude(
                account_payment__in=existing_data_on_new_collection_table_ids
            ).only('account_payment', 'bucket').distinct('account_payment_id')
            data_vendor_to_new_tables = []
            if data_on_vendor:
                for data in data_on_vendor:
                    data_vendor_to_new_table = dict(
                        account_payment=data.account_payment,
                        bucket=data.bucket,
                        vendor=True
                    )
                    data_vendor_to_new_tables.append(
                        CollectionBucketInhouseVendor(**data_vendor_to_new_table)
                    )

                CollectionBucketInhouseVendor.objects.bulk_create(
                    data_vendor_to_new_tables, batch_size=1000
                )
        
        except Exception as e:
            logger.error("there are some issue with message: {}".format(str(e)))
            return
