import re
from mock import ANY, patch

from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.autodebet.models import AutodebetBRITransaction, AutodebetAccount
from juloserver.autodebet.services.authorization_services import process_bri_transaction_callback, \
    update_autodebet_bri_transaction_failed, process_bri_account_registration, \
    process_bri_registration_otp_verify, process_bri_account_revocation, \
    generate_payment_method_process, process_bri_transaction_otp_verify
from juloserver.autodebet.services.autodebet_bri_services import cancel_autodebet_bri_transaction, \
    check_and_create_debit_payment_process_after_callback
from juloserver.autodebet.services.task_services import process_fund_collection
from juloserver.autodebet.tests.factories import AutodebetAccountFactory, \
    AutodebetBRITransactionFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    AccountingCutOffDateFactory,
    PaymentFactory,
    LoanFactory,
    DeviceFactory
)

from juloserver.account_payment.tests.factories import AccountPaymentFactory

from juloserver.autodebet.tasks import collect_autodebet_account_collections_task, \
    autodebet_fund_collection_task
from juloserver.autodebet.constants import FeatureNameConst, AutodebetVendorConst, \
    BRITransactionCallbackStatus
from juloserver.autodebet.clients import AutodebetXenditClient
from juloserver.julo.models import PaymentMethod


def mock_request_xendit(method, request_path, data=None, account=None, account_payment=None, headers=None):
    data = {}
    if '/payment_methods/pm-' in request_path:
        data = {
            'id': 'pm-c30d4800-afe4-4e58-ad5f-cc006d169139',
            'type': 'DEBIT_CARD',
            'properties': {
                'id': 'la-aa620619-124f-41db-995b-66a52abe036a',
                'channel_code': 'DC_BRI',
                'currency': 'IDR',
                'card_last_four': '1234',
                'card_expiry': '06/24',
                'description': None,
            },
            'customer_id': 'ba830b92-4177-476e-b097-2ad5ae4d3e55',
            'status': 'ACTIVE',
            'created': '2020-03-19T05:34:55+0800',
            'updated': '2020-03-19T05:24:55+0800',
            'metadata': None,
        }
    elif request_path == '/customers':
        data = {
            "id": "239c16f4-866d-43e8-9341-7badafbc019f",
            "reference_id": "demo_1475801962607",
            "email": "customer@website.com",
            "mobile_number": None,
            "given_names": "John",
            "description": None,
            "middle_name": None,
            "surname": None,
            "phone_number": None,
            "nationality": None,
            "addresses": None,
            "date_of_birth": None,
            "metadata": None
        }
    elif request_path == '/linked_account_tokens/auth':
        data = {
            "id": "lat-aa620619-124f-41db-995b-66a52abe036a",
            "customer_id": "ba830b92-4177-476e-b097-2ad5ae4d3e55",
            "channel_code": "DC_BRI",
            "authorizer_url": None,
            "status": "SUCCESS",
            "metadata": None
        }
    elif request_path == '/payment_methods':
        data = {
            "id": "pm-c30d4800-afe4-4e58-ad5f-cc006d169139",
            "type": "DEBIT_CARD",
            "properties": {
                "id": "la-aa620619-124f-41db-995b-66a52abe036a",
                "channel_code": "DC_BRI",
                "currency": "IDR",
                "card_last_four": "1234",
                "card_expiry": "06/24",
                "description": None,
            },
            "customer_id": "ba830b92-4177-476e-b097-2ad5ae4d3e55",
            "status": "ACTIVE",
            "created": "2020-03-19T05:34:55+0800",
            "updated": "2020-03-19T05:24:55+0800",
            "metadata": None
        }

    elif re.match(r"/linked_account_tokens/.*/validate_otp$", request_path):
        data = {
            "id": "lat-aa620619-124f-41db-995b-66a52abe036a",
            "customer_id": "239c16f4-866d-43e8-9341-7badafbc019f",
            "channel_code": "DC_BRI",
            "status": "SUCCESS"
        }
    elif request_path == '/direct_debits':
        data = {
            "id": "ddpy-65da263a-0796-4da1-86a8-5ac0d8e52a9d",
            "reference_id": "ff1ee1e9-b77f-437e-a700-061c3e30a67d",
            "channel_code": "DC_BRI",
            "payment_method_id": "pm-c30d4800-afe4-4e58-ad5f-cc006d169139",
            "currency": "IDR",
            "amount": "300000",
            "description": None,
            "status": "PENDING",
            "basket": None,
            "failure_code": None,
            "is_otp_required": False,
            "otp_mobile_number": "+6287774441111",
            "otp_expiration_timestamp": None,
            "required_action": "",
            "checkout_url": None,
            "success_redirect_url": None,
            "failure_redirect_url": None,
            "refunded_amount": None,
            "refunds": None,
            "created": "2020-03-26T05:44:26+0800",
            "updated": None,
            "metadata": None
        }
    elif re.match(r'/direct_debits/.*/validate_otp/$', request_path):
        data = {
            "id": "ddpy-623dca10-5dad-4916-b14d-81aaa76b5d14",
            "reference_id": "e17a0ac8-6fed-11ea-bc55-0242ac130003",
            "channel_code": "BA_BPI",
            "payment_method_id": "pm-c30d4800-afe4-4e58-ad5f-cc006d169139",
            "currency": "PHP",
            "amount": "1000.00",
            "description": "",
            "status": "PENDING",
            "basket": [],
            "failure_code": "",
            "is_otp_required": True,
            "otp_mobile_number": "+63907XXXX123",
            "otp_expiration_timestamp": "2020-03-26T05:45:06+0800",
            "created": "2020-03-26T05:44:26+0800",
            "updated": "2020-03-26T05:44:46+0800",
            "metadata": {}
        }
    elif re.match(r'/linked_account_tokens/.*/accounts', request_path):
        data = [{
            'channel_code': 'DC_BRI',
            'id': 'la-8e5f5dc6-35c2-44bf-88f0-a93de6cc0456',
            'properties': {
                'account_mobile_number': '+6281212052524',
                'card_expiry': '06/24',
                'card_last_four': '8888',
                'currency': 'IDR',
                'description': ''
            },
            'type': 'DEBIT_CARD'
        }]
    elif request_path == '/payment_methods':
        data = {
            'id': 'pm-d8872b47-e18b-4d36-b70a-c89be63d69e5',
            'customer_id': '0dadfe86-5b51-42cd-a3ce-9b0d3f1c99bf',
            'type': 'DEBIT_CARD',
            'status': 'ACTIVE',
            'properties': {
                'id': 'la-82641765-0dce-460c-8183-444ddba42e4b',
                'linked_account_token_id': 'lat-73126e8c-5b82-48a9-ae5d-a0aeca52cfd0',
                'channel_code': 'DC_BRI',
                'currency': 'IDR',
                'card_expiry': '06/24',
                'card_last_four': '8888'
            },
            'metadata': {},
            'created': '2022-02-04T06:58:43.074Z',
            'updated': '2022-02-04T06:58:43.074Z'
        }
    elif re.match(r'/direct_debits/.*/validate_otp/', request_path):
        data = {
            "id": "ddpy-623dca10-5dad-4916-b14d-81aaa76b5d14",
            "reference_id": "e17a0ac8-6fed-11ea-bc55-0242ac130003",
            "channel_code": "DC_BRI",
            "payment_method_id": "pm-c30d4800-afe4-4e58-ad5f-cc006d169139",
            "currency": "IDR",
            "amount": "300000",
            "description": "",
            "status": "PENDING",
            "basket": [],
            "failure_code": "",
            "is_otp_required": True,
            "otp_mobile_number": "+63907XXXX123",
            "otp_expiration_timestamp": "2020-03-26T05:45:06+0800",
            "created": "2020-03-26T05:44:26+0800",
            "updated": "2020-03-26T05:44:46+0800",
            "metadata": {}
        }

    return data, None


class TestAutodebetAccountServices(TestCase):
    @classmethod
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_BRI,
            parameters={
                'minimum_amount': 10000,
                'disable': {
                    'disable_start_date_time': "04-09-2022 9:00",
                    'disable_end_date_time': "04-09-2022 11:00"
                }
            },
            is_active=True,
        )
        self.whitelist_setting = FeatureSettingFactory()
        self.account = AccountFactory()
        self.application = ApplicationFactory(account=self.account)
        self.autodebit_account = AutodebetAccountFactory(
            vendor=AutodebetVendorConst.BRI,
            account=self.account,
            is_use_autodebet=True,
            is_deleted_autodebet=False,
        )
        AccountingCutOffDateFactory()

        today = timezone.localtime(timezone.now()).date()
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=today)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.account_payment.refresh_from_db()
        self.loan = LoanFactory(account=self.account, customer=self.account.customer,
                                initial_cashback=2000)
        self.loan.loan_status_id = 220
        self.loan.save()
        self.payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
                change_due_date_interest=0,
            )
        self.device = DeviceFactory(customer=self.account.customer)

        self.callback_data = {
            "event": "direct_debit.payment",
            "timestamp": "2020-03-26T05:44:26+0800",
            "id": "ddpy-65da263a-0796-4da1-86a8-5ac0d8e52a9d",
            "reference_id": "ff1ee1e9-b77f-437e-a700-061c3e30a67d",
            "channel_code": "DC_BRI",
            "payment_method_id": "pm-c30d4800-afe4-4e58-ad5f-cc006d169139",
            "currency": "IDR",
            "amount": 300000,
            "description": "null",
            "status": "COMPLETED",
            "failure_code": "null",
            "metadata": "null"
        }

        self.registration_data = {
            "user_email": "test.email@zendit.co",
            "user_phone": "081212052524",
            "card_number": "8888",
            "expired_date": "06/24"
        }

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    @patch('juloserver.autodebet.tasks.autodebet_fund_collection_task')
    def test_collection_bri_task(self, mock_collect_autodebet_account_collections_task, mock_xendit_request):
        self.autodebit_account.payment_method_id = 'pm-c30d4800-afe4-4e58-ad5f-cc006d169139'
        self.autodebit_account.save()
        collect_autodebet_account_collections_task()
        mock_collect_autodebet_account_collections_task.delay.assert_called_once()
        today_date = timezone.localtime(timezone.now()).date()
        filter_ = {"due_date__lte": today_date}
        account_payment_ids = [self.account_payment.id]
        autodebet_fund_collection_task(account_payment_ids, AutodebetVendorConst.BRI)
        self.autodebet_bri_transaction = AutodebetBRITransaction.objects.get(account_payment=self.account_payment)
        self.autodebet_bri_transaction.transaction_id = 'ff1ee1e9-b77f-437e-a700-061c3e30a67d'
        self.autodebet_bri_transaction.autodebet_account = self.autodebit_account
        self.autodebet_bri_transaction.save()
        status_callback, account_payment, amount, account, autodebet_api_log = process_bri_transaction_callback(self.callback_data)
        if status_callback == BRITransactionCallbackStatus.COMPLETED:
            process_fund_collection(account_payment, AutodebetVendorConst.BRI, amount)
        self.account_payment.refresh_from_db()
        assert self.account_payment.status_id == 330

    def test_cancel_bri_transaction(self):
        self.autodebit_transaction = AutodebetBRITransactionFactory()
        self.autodebit_transaction.autodebet_account = self.autodebit_account
        self.autodebit_transaction.account_payment = self.account_payment
        self.autodebit_transaction.save()
        cancel_autodebet_bri_transaction(self.autodebit_account, self.account_payment)
        self.account_payment.refresh_from_db()
        self.autodebet_bri_transaction = AutodebetBRITransaction.objects.get(
            account_payment=self.account_payment)
        assert self.autodebet_bri_transaction.status == 'CANCEL'

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_check_and_create_debit_payment_process_after_callback(self, mock_xendit_request):
        check_and_create_debit_payment_process_after_callback(self.account)
        self.autodebet_bri_transaction = AutodebetBRITransaction.objects.get(autodebet_account=self.autodebit_account)
        assert self.autodebet_bri_transaction.status == 'CALLBACK PENDING'

        mock_xendit_request.return_value = {
            'result': {'error_code': 'API_VALIDATION_ERROR', 'message': "field 'idempotency_key,omitempty' is required"},
            'error': 'API_VALIDATION_ERROR'
        }

        update_autodebet_bri_transaction_failed(
            mock_xendit_request.return_value['error'], self.autodebet_bri_transaction)
        assert self.autodebet_bri_transaction.status == 'FAILED'

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_process_bri_account_registration(self, mock_xendit_request):
        self.autodebit_account.delete()
        process_bri_account_registration(self.account, self.registration_data)
        self.autodebit_account = AutodebetAccount.objects.get(account=self.account)
        self.assertEqual(self.autodebit_account.status, 'pending_registration')

        _, message = process_bri_account_registration(self.account, self.registration_data)
        self.assertEqual(message, 'Account sedang dalam proses registrasi')

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_process_bri_registration_otp_verify(self, mock_xendit_request):
        self.otp_data = {'otp': 333000}
        self.autodebit_account.linked_account_id = 'lat-a9760ec6-8be1-4d5c-a5d0-36040fe9189a'
        self.autodebit_account.save()
        process_bri_registration_otp_verify(self.account, self.otp_data)
        self.autodebit_account.refresh_from_db()
        self.assertEqual(self.autodebit_account.status, 'registered')
        payment_method = PaymentMethod.objects.filter(
            customer=self.account.customer, payment_method_name="Autodebet BRI")
        self.assertIsNotNone(payment_method)

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_process_bri_account_revocation(self, mock_xendit_request):
        error = process_bri_account_revocation(self.account)
        self.assertEqual(error, 'Account autodebet belum pernah di aktivasi')

        self.autodebit_account.is_use_autodebet = False
        self.autodebit_account.activation_ts = timezone.localtime(timezone.now())
        self.autodebit_account.save()
        error = process_bri_account_revocation(self.account)
        self.assertEqual(error, 'Account autodebet tidak aktif')

        self.autodebit_account.is_use_autodebet = True
        self.autodebit_account.save()
        error = process_bri_account_revocation(self.account)
        self.assertEqual(error, 'Account autodebet tidak aktif')

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_generate_payment_method_process(self, mock_xendit_rquest):
        generate_payment_method_process(self.account)
        self.autodebit_account.refresh_from_db()
        self.assertTrue(self.autodebit_account.payment_method_id)

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_process_bri_transaction_otp_verify(self, mock_xendit_request):
        error = process_bri_transaction_otp_verify(self.account, 333000)
        self.assertEqual(error, 'No BRI transaction pending')

        self.autodebet_bri_transaction = AutodebetBRITransactionFactory()
        self.autodebet_bri_transaction.status = 'OTP PENDING'
        self.autodebet_bri_transaction.account_payment = self.account_payment
        self.autodebet_bri_transaction.save()
        process_bri_transaction_otp_verify(self.account, 333000)
        self.autodebet_bri_transaction.refresh_from_db()
        self.assertEqual(self.autodebet_bri_transaction.status, 'SUCCESS')
