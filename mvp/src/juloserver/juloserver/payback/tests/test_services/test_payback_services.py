from django.test.testcases import TestCase

from juloserver.payback.models import GopayRepaymentTransaction
from juloserver.julo.models import (
    PaybackTransactionStatusHistory, 
    PaybackTransaction,
)
from juloserver.payback.services.payback import (
    create_pbt_status_history, 
    record_transaction_data_for_autodebet_gopay,
)
from juloserver.payback.tests.factories import (
    GopayAccountLinkStatusFactory, 
    GopayAutodebetTransactionFactory,
)
from juloserver.julo.tests.factories import CustomerFactory, PaymentMethodFactory
from juloserver.account.tests.factories import AccountwithApplicationFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.autodebet.constants import VendorConst


class TestPaybackServices(TestCase):
    def setUp(self):
        pass

    def test_create_pbt_status_history(self):
        pbt = PaybackTransaction.objects.create()
        pbt.save()
        create_pbt_status_history(pbt, 1, 2)
        pbt_stt_history = PaybackTransactionStatusHistory.objects.filter(
            payback_transaction_id=pbt.id).first()
        self.assertIsNotNone(pbt_stt_history)

    def test_record_transaction_data_for_autodebet_gopay(self):
        customer = CustomerFactory()
        account = AccountwithApplicationFactory(customer=customer)
        account_payment = AccountPaymentFactory(account=account)
        payment_method =PaymentMethodFactory(
            payment_method_name='Autodebet GOPAY',
            customer=customer
        )
        gopay_account_link_status = GopayAccountLinkStatusFactory(
            account=account,
        )
        GopayAutodebetTransactionFactory(
            amount=400000,
            gopay_account=gopay_account_link_status,
            customer=customer,
            account_payment=account_payment
        )
        AutodebetAccountFactory(account=account, vendor=VendorConst.GOPAY)
        data = {}
        transaction = record_transaction_data_for_autodebet_gopay(data)
        self.assertEqual(transaction, None)

        data = {
            "transaction_time": "2023-06-21 10:47:15",
            "transaction_status": "deny",
            "transaction_id": "c21fed79-99c5-4608-9f8d-2a8f250d24e1",
            "subscription_id": "d98a63b8-97e4-4059-825f-0f62340407e9",
            "status_message": "midtrans payment notification",
            "status_code": "202",
            "signature_key": "9dfbcbb3894bf29fc69ada4b92927a9c2b16198f6c63f6a8d51cb16211dee20a55a29d4d24a845072056d5491d9e335b2741a20c6e12245a439dd4db44801c41",
            "payment_type": "gopay",
            "order_id": "juni-subscription-16873191771684640821",
            "merchant_id": "G094279605",
            "gross_amount": "400000",
            "fraud_status": "accept",
            "expiry_time": "2023-06-21 11:02:15",
            "currency": "IDR",
            "channel_response_message": "NOT_ENOUGH_BALANCE",
            "channel_response_code": "201"
        }
        transaction = record_transaction_data_for_autodebet_gopay(data)
        self.assertEqual(transaction, None)
        self.assertFalse(PaybackTransaction.objects.filter(
            transaction_id=data['order_id']).exists()
        )
        self.assertTrue(GopayRepaymentTransaction.objects.filter(
            transaction_id=data['order_id']).exists()
        )

        data['transaction_status'] = 'settlement'
        transaction = record_transaction_data_for_autodebet_gopay(data)
        self.assertEqual(transaction.payment_method, payment_method)
        self.assertTrue(PaybackTransaction.objects.filter(
            transaction_id=data['order_id']).exists()
        )
        self.assertTrue(GopayRepaymentTransaction.objects.filter(
            transaction_id=data['order_id']).exists()
        )
