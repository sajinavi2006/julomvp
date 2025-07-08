import ast
from django.test import TestCase
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from datetime import datetime
from mock import patch
from juloserver.minisquad.tests.factories import (
    SentToDialerFactory,
    NotSentToDialerFactory
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.minisquad.constants import ReasonNotSentToDialer
from juloserver.minisquad.models import CollectionBucketInhouseVendor
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.tests.factories import StatusLookupFactory
from juloserver.minisquad.management.commands import \
    retro_store_bucket_3_to_collection_data_base_on_calling_system


class TestRetroStoreBucket3(TestCase):
    def setUp(self):
        self.b3_account_payments = []
        self.today = timezone.localtime(timezone.now())
        self.status = StatusLookupFactory(status_code=420)
        self.account_1 = AccountFactory(ever_entered_B5=False, status=self.status)
        self.account_2 = AccountFactory(ever_entered_B5=False, status=self.status)
        self.account_payment_1 = AccountPaymentFactory(
            account=self.account_1,
            status_id=PaymentStatusCodes.PAYMENT_60DPD,
            due_date=self.today.date() - relativedelta(days=50)
        )
        self.account_payment_2 = AccountPaymentFactory(
            account=self.account_2,
            status_id=PaymentStatusCodes.PAYMENT_60DPD,
            due_date=self.today.date() - relativedelta(days=50)
        )
        inhouse_data = SentToDialerFactory(
            bucket='JULO_B3',
            account_payment=self.account_payment_1,
            cdate=datetime.now()
        )
        vendor_data = NotSentToDialerFactory(
            bucket='JULO_B3_NON_CONTACTED',
            account_payment=self.account_payment_2,
            unsent_reason=ast.literal_eval(
                ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR']),
            cdate=datetime.now()
        )

    @patch(
        'juloserver.minisquad.management.commands.retro_store_bucket_3_to_collection_data_base_on_calling_system'
        '.get_eligible_account_payment_for_dialer_and_vendor_qs')
    def test_store_data(self, mock_eligible_account_payment):
        mock_eligible_account_payment.return_value.values_list.return_value = \
            AccountPayment.objects.all().values_list('id', flat=True)
        retro_store_bucket_3_to_collection_data_base_on_calling_system.Command().handle()
        data_on_new_table = CollectionBucketInhouseVendor.objects.all()
        self.assertEqual(2, len(data_on_new_table))
