from datetime import datetime

from django.test import Client
from django.http import HttpResponse
from django.conf import settings
from rest_framework.test import APIClient
from mock import patch
from django.test.testcases import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth.models import User

from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    PaymentMethodFactory,
    LoanFactory,
    CustomerFactory,
    ApplicationFactory,
    PaybackTransactionFactory,
    AuthUserFactory,
    AccountingCutOffDateFactory,
    PaymentFactory,
    AccountingCutOffDateFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.utils import generate_sha512
from juloserver.payback.tests.factories import CashbackPromoFactory
from juloserver.payback.constants import FeatureSettingNameConst

from juloserver.julo.tests.factories import FeatureSettingFactory


class TestTransactionView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def test_transaction_view(self):
        loan = LoanFactory()
        payment = loan.payment_set.first()
        payback_transaction = PaybackTransactionFactory(
            customer=self.customer,
            payment=payment,
            loan=loan,
        )
        result = self.client.get('/api/payback/v1/transactions/')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()), 1)


class TestGopayView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(customer=self.customer, application=self.application)

        self.payment_method_gopay = PaymentMethodFactory(
            loan=self.loan, customer=self.customer, payment_method_code='1002'
        )
        self.payment_method_gopay_tokenization = PaymentMethodFactory(
            loan=self.loan, customer=self.customer, payment_method_code='1004'
        )

    @patch('juloserver.payback.views.process_gopay_initial_for_account')
    @patch('juloserver.payback.views.GopayServices')
    def test_gopay_init(self, mock_gopay_service, mock_process_gopay_initial_for_account):
        # for non julo one
        payment = self.loan.payment_set.first()
        data = {'payment_method_id': self.payment_method_gopay.id, 'amount': 10000}
        payback_transaction = PaybackTransactionFactory(
            customer=self.customer,
            payment=payment,
            loan=self.loan,
        )
        mock_gopay_service().init_transaction.return_value = {
            'gopay': 'test_init_transaction_data',
            'transaction': payback_transaction
        }
        response = self.client.post('/api/payback/v1/gopay/init/', data)
        self.assertEqual(response.status_code, 201)

        # for julo one
        account = AccountFactory(customer=self.customer)
        account.status_id = 421
        account.save()
        mock_process_gopay_initial_for_account.return_value = HttpResponse(status=201)
        response = self.client.post('/api/payback/v1/gopay/init/', data)
        self.assertEqual(response.status_code, 201)

    def test_current_status(self):
        # transaction not found
        response = self.client.get('/api/payback/v1/gopay/request-status/9999999/')
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.payback.views.GopayServices')
    def test_gopay_tokenization_init(self, mock_gopay_service):
        """
        In this test case, we make sure that if payment_method is Gopay Tokenization,
        we have to move payment_method into Gopay only.
        """

        payment = self.loan.payment_set.first()
        data = {'payment_method_id': self.payment_method_gopay_tokenization.id, 'amount': 20000}
        payback_transaction = PaybackTransactionFactory(
            customer=self.customer,
            payment=payment,
            payment_method=self.payment_method_gopay,
            loan=self.loan,
            amount=data['amount'],
        )
        mock_gopay_service().init_transaction.return_value = {
            'gopay': 'test_init_transaction_data',
            'transaction': payback_transaction,
        }
        response = self.client.post('/api/payback/v2/gopay/init/', data)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(data["payment_method"], self.payment_method_gopay.id)
        self.assertEqual(data["amount"], 20000)


class TestGopayCallbackView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    @patch('juloserver.account.models.Account.get_oldest_unpaid_account_payment')
    @patch('juloserver.payback.views.process_gopay_repayment_for_account')
    @patch('juloserver.payback.views.GopayServices')
    def test_gopay_callback_view(
            self, mock_gopay_service, mock_process_gopay_repayment_for_account,
            mock_account_payment):
        order_id = '111111'
        status_code = 200
        gross_amount = '10000'

        signature_keystring = '{}{}{}{}'.format(
            order_id,
            status_code,
            gross_amount,
            settings.GOPAY_SERVER_KEY)
        gen_signature = generate_sha512(signature_keystring)
        data = {
            'status_code': status_code,
            'status_message': 'nothing',
            'transaction_id': '111111',
            'order_id': order_id,
            'payment_type': 'test type',
            'transaction_time': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S'),
            'transaction_status': 'capture',
            'gross_amount': gross_amount,
            'signature_key': gen_signature,
        }
        loan = LoanFactory(customer=self.customer)
        payment = loan.payment_set.first()
        payback_transaction = PaybackTransactionFactory(
            customer=self.customer,
            payment=payment,
            loan=loan,
            transaction_id=order_id
        )
        # status success
        ## none julo one
        mock_gopay_service.process_loan.return_value = True
        response = self.client.post('/api/payback/v1/gopay/callback/', data)
        self.assertEqual(response.status_code, 200)

        payback_transaction.update_safely(account=self.account)
        mock_account_payment.return_value = [self.account_payment]

        ## for julo one
        account = AccountFactory(customer=self.customer)
        payback_transaction.account = account
        payback_transaction.save()
        response = self.client.post('/api/payback/v1/gopay/callback/', data)
        self.assertEqual(response.status_code, 200)
        mock_process_gopay_repayment_for_account.assert_called_once()

        # status not success
        data['status_code'] = 400
        data['transaction_status'] = 'deny'
        signature_keystring = '{}{}{}{}'.format(
            order_id,
            400,
            gross_amount,
            settings.GOPAY_SERVER_KEY)
        data['signature_key'] = generate_sha512(signature_keystring)
        mock_gopay_service.update_transaction_status.return_value = True
        response = self.client.post('/api/payback/v1/gopay/callback/', data)
        self.assertEqual(response.status_code, 200)
        payback_transaction.update_safely(is_processed=True)
        response = self.client.post('/api/payback/v1/gopay/callback/', data)
        self.assertEqual(response.status_code, 200)
        response = response.json()
        self.assertEqual(response['msg'], 'Transaction has been processed')


class TestDokuCallbackView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        AccountingCutOffDateFactory()
        self.customer = CustomerFactory(user=self.user, fullname="Mawang")
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(
            customer=self.customer, loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        )
        self.payments = []
        total_due_amount = 0
        total_interest_amount = 0
        total_principal_amount = 0
        total_late_fee_amount = 0
        for i in range(2):
            payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
            )
            self.payments.append(payment)
            total_due_amount += payment.due_amount
            total_interest_amount += payment.installment_interest
            total_principal_amount += payment.installment_principal
            total_late_fee_amount += payment.late_fee_amount

        self.account_payment.due_amount = total_due_amount
        self.account_payment.interest_amount = total_interest_amount
        self.account_payment.principal_amount = total_principal_amount
        self.account_payment.late_fee_amount = total_late_fee_amount
        self.account_payment.status_id = 320
        self.account_payment.paid_amount = 0
        self.account_payment.save()
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureSettingNameConst.CHANGE_DOKU_SNAP_CREDENTIALS,
            is_active=False,
        )
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    @patch('juloserver.payback.views.get_redis_client')
    @patch('juloserver.payback.views.verify_asymmetric_signature')
    def test_doku_access_token_b2b(self, mock_verify_asymmetric_signature, mock_redis_client):
        mock_redis_client.return_value.get.return_value = None
        data = {
            "grantType": "client_credentials",
        }
        x_timestamp = timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M:%S+07:00')
        mock_verify_asymmetric_signature.return_value = True
        response = self.client.post(
            '/api/payback/doku/authorization/v1/access-token/b2b',
            data,
            HTTP_X_TIMESTAMP=x_timestamp,
        )
        mock_verify_asymmetric_signature.assert_called_once()
        self.assertEqual(response.status_code, 200)

        # unauthorized
        mock_verify_asymmetric_signature.return_value = False
        response = self.client.post(
            '/api/payback/doku/authorization/v1/access-token/b2b',
            data,
            HTTP_X_TIMESTAMP=x_timestamp,
        )
        self.assertEqual(response.status_code, 401)

    @patch('juloserver.payback.views.get_snap_expiry_token')
    @patch('juloserver.payback.views.is_expired_snap_token')
    @patch('juloserver.payback.views.authenticate_snap_request')
    @patch('juloserver.payback.views.get_redis_client')
    @patch('juloserver.payback.views.get_active_loan')
    def test_doku_inquiry(
        self,
        mock_get_active_loan,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):

        self.client.credentials(HTTP_X_EXTERNAL_ID='externalid1')
        additional_info = {
            "channel": "VIRTUAL_ACCOUNT_BANK_MANDIRI",
        }
        data = {
            "partnerServiceId": "   88899",
            "customerNo": "908800314524",
            "virtualAccountNo": "   88899908800314524",
            "trxDateInit": "2024-08-27T09:16:00+07:00",
            "channelCode": "6011",
            "language": "ID",
            "inquiryRequestId": "DIPCVA002T240827091600904TZZWn8j2IWd",
            "additionalInfo": additional_info,
        }

        self.payment_method = PaymentMethodFactory(
            customer=self.customer,
            virtual_account="88899908800314524",
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
        )
        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = None
        mock_get_active_loan.return_value = True

        inquiry_reason = {"english": "successful", "indonesia": "sukses"}
        total_amount = {"value": "0.00", "currency": "IDR"}
        virtual_account_data = {
            "inquiryStatus": "00",
            "inquiryReason": inquiry_reason,
            "partnerServiceId": "   88899",
            "customerNo": "908800314524",
            "virtualAccountNo": "   88899908800314524",
            "virtualAccountName": "Mawang",
            "inquiryRequestId": "DIPCVA002T240827091600904TZZWn8j2IWd",
            "totalAmount": total_amount,
            "virtualAccountTrxType": "O",
        }
        expected_additional_info = {"channel": "VIRTUAL_ACCOUNT_BANK_MANDIRI", "trxId": "JULO-1"}
        expected_response = {
            "responseCode": "2002400",
            "responseMessage": "Successful",
            "virtualAccountData": virtual_account_data,
            "additionalInfo": expected_additional_info,
        }

        response = self.client.post(
            '/api/payback/doku/v1.1/transfer-va/inquiry', data, format="json"
        )
        response_json = response.json()
        self.assertEqual(
            response_json["virtualAccountData"]["inquiryRequestId"],
            "DIPCVA002T240827091600904TZZWn8j2IWd",
        )
        self.assertEqual(response_json["virtualAccountData"]["totalAmount"], total_amount)
        self.assertEqual(response_json["responseCode"], expected_response["responseCode"])
        self.assertEqual(response.status_code, 200)

        # duplicate external id
        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = "externalid1"  # already on redis
        mock_get_active_loan.return_value = True

        response = self.client.post(
            '/api/payback/doku/v1.1/transfer-va/inquiry', data, format="json"
        )
        self.assertEqual(response.status_code, 409)

        # expired access token
        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = True  # expired
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = None
        mock_get_active_loan.return_value = True

        response = self.client.post(
            '/api/payback/doku/v1.1/transfer-va/inquiry', data, format="json"
        )
        self.assertEqual(response.status_code, 401)

    @patch('juloserver.payback.views.get_snap_expiry_token')
    @patch('juloserver.payback.views.is_expired_snap_token')
    @patch('juloserver.payback.views.authenticate_snap_request')
    @patch('juloserver.payback.views.get_redis_client')
    def test_doku_payment_notification(
        self,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):

        request_data = {
            "partnerServiceId": "   88899",
            "customerNo": "908800314524",
            "virtualAccountNo": "   88899908800314524",
            "virtualAccountName": "Mawang",
            "trxId": "23219829713",
            "paidAmount": {"value": "200000.00", "currency": "IDR"},
            "paymentRequestId": "DIPCVA002T240827091600904TZZWn8j2IWd",
            "trxDateTime": "2024-08-01T10:55:00+07:00",
        }

        self.client.credentials(HTTP_X_EXTERNAL_ID='externalid1')

        self.payment_method = PaymentMethodFactory(
            customer=self.customer,
            virtual_account="88899908800314524",
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
        )

        self.payback_trx = PaybackTransactionFactory(
            customer=self.customer,
            account=self.account,
            transaction_date=datetime.today(),
            payment_method=self.payment_method,
            transaction_id='DIPCVA002T240827091600904TZZWn8j2IWd',
            is_processed=False,
        )

        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = None

        response = self.client.post(
            '/api/payback/doku/v1.1/transfer-va/payment', data=request_data, format='json'
        )
        self.assertEqual(response.status_code, 200, response.content)

    @patch('juloserver.payback.views.get_snap_expiry_token')
    @patch('juloserver.payback.views.is_expired_snap_token')
    @patch('juloserver.payback.views.authenticate_snap_request')
    @patch('juloserver.payback.views.get_redis_client')
    def test_doku_payment_notification_invalid_field(
        self,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):
        request_data = {
            "partnerServiceID": "   88899",
            "customerNo": "908800314524",
            "virtualAccountNo": "   88899908800314524",
            "virtualAccountName": "Mawang",
            "trxId": "23219829713",
            "paidAmount": {"value": "300000.00", "currency": "IDR"},
            "paymentRequestId": "DIPCVA002T240827091600904TZZWn8j2IWd",
        }
        self.client.credentials(HTTP_X_EXTERNAL_ID='externalid1')

        mock_redis_client.return_value.get.return_value = None
        mock_is_expired_snap_token.return_value = False
        mock_get_snap_expiry_token.return_value = True
        mock_authenticate_snap_request.return_value = True
        response = self.client.post(
            '/api/payback/doku/v1.1/transfer-va/payment', data=request_data, format='json'
        )
        self.assertEqual(response.status_code, 400, response.content)


testing_middleware = [
    'django_cookies_samesite.middleware.CookiesSameSite',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # 3rd party middleware classes
    'juloserver.julo.middleware.DeviceIpMiddleware',
    'cuser.middleware.CuserMiddleware',
    'juloserver.julocore.restapi.middleware.ApiLoggingMiddleware',
    'juloserver.standardized_api_response.api_middleware.StandardizedApiURLMiddleware',
]


@override_settings(MIDDLEWARE=testing_middleware)
class TestAdmin2(TestCase):

    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = FeatureSettingFactory(
            feature_name='special_event_binary')


class TestCashbackPromoAdd(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = FeatureSettingFactory(
            feature_name='special_event_binary')

    def test_cashback_promo_add(self):
        data = {
            'promo_name': 'test_promo',
            'department': 'Marketing',
            'pic_email': 'test@julo.co.id',
            'requester': self.user,
        }
        # post method
        res = self.client.post('/xgdfat82892ddn/cashback_promo_add/', data)
        assert res.status_code == 302

        # get method
        res = self.client.get('/xgdfat82892ddn/cashback_promo_add/', data)
        assert res.status_code == 200


class TestCashbackPromoEdit(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = FeatureSettingFactory(
            feature_name='special_event_binary')

    def test_cashback_promo_edit(self):
        data = {
            'promo_name': 'test_promo',
            'department': 'Marketing',
            'pic_email': 'test@julo.co.id',
            'requester': self.user,
        }
        cashback_promo = CashbackPromoFactory(requester=self.user)
        # post method
        res = self.client.post('/xgdfat82892ddn/cashback_promo_edit/%s' % cashback_promo.id, data)
        assert res.status_code == 302

        # get method
        res = self.client.get('/xgdfat82892ddn/cashback_promo_edit/%s' % cashback_promo.id, data)
        assert res.status_code == 200


class TestCashbackPromoReview(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = FeatureSettingFactory(
            feature_name='special_event_binary')

    def test_cashback_promo_review(self):
        cashback_promo = CashbackPromoFactory(requester=self.user)
        cashback_promo.total_money = 10000
        cashback_promo.save()
        data = {
            'promo_name': cashback_promo.promo_name,
            'department': cashback_promo.department,
            'pic_email': cashback_promo.pic_email,
            'requester': self.user,
        }
        # get method
        res = self.client.get('/xgdfat82892ddn/cashback_promo_review/%s' % cashback_promo.id, data)
        assert res.status_code == 200


class TestCashbackPromoProceed(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = FeatureSettingFactory(
            feature_name='special_event_binary')

    def test_cashback_promo_proceed(self):
        data = {
            'promo_name': 'test_promo',
            'department': 'Marketing',
            'pic_email': 'test@julo.co.id',
            'requester': self.user,
        }
        cashback_promo = CashbackPromoFactory(requester=self.user)
        # get method
        res = self.client.get('/xgdfat82892ddn/cashback_promo_proceed/%s' % cashback_promo.id, data)
        assert res.status_code == 302


class TestCashbackPromoDecision(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = FeatureSettingFactory(
            feature_name='special_event_binary')

    def test_cashback_promo_decision(self):
        data = {
            'decision': 'approved',
            'approver': self.user,
        }
        cashback_promo = CashbackPromoFactory(
            requester=self.user, approval_token='111111')
        # get method
        res = self.client.get('/api/payback/cashback-promo/%s/decision' % '111111', data)
        assert res.status_code == 200


class TestGopayAccountRepaymentView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    @patch('juloserver.payback.views.process_gopay_initial_for_account')
    @patch('juloserver.payback.views.GopayServices')
    def test_gopay_tokenization_init(self, mock_gopay_service, mock_process_gopay_initial_for_account):
        payment_method = PaymentMethodFactory(
            customer=self.customer,
            payment_method_code='1004',
            payment_method_name='GoPay Tokenization'
        )
        data = {
            'payment_method_id': payment_method.id,
            'amount': 100000
        }

        mock_gopay_service().gopay_tokenization_init_account_payment_transaction.return_value = {
            "payment_type": 'gopay',
            "gross_amount": 100000,
            "gopay": {
                "transaction_status": 'pending',
                "status_message": "GoPay transaction is created. Action(s) required",
                "payment_option_token": '778286d9-fbb0-4941-9352-3515bac14876',
                "web_linking": "http://api.midtrans.com/v2/gopay/redirect/gppd_6123269-1425-21e3-bc44-e592afafec14/charge"
            }
        }, None
        mock_process_gopay_initial_for_account.return_value = HttpResponse(status=200)
        response = self.client.post('/api/payback/v1/gopay/pay-account/init/', data)
        self.assertEqual(response.status_code, 200)


class TestGopayCreatePayAccountView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, phone='081512345678')
        self.account = AccountFactory(customer=self.customer)
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureSettingNameConst.GOPAY_CHANGE_URL,
            is_active=True,
        )

    @patch('juloserver.payback.views.GopayServices.create_pay_account')
    def test_gopay_create_pay_account_should_change_web_link_url(self, mock_create_pay_account):
        mock_create_pay_account.return_value = (
            {'account_status': 'PENDING',
             'web_linking': 'https://gopay.co.id/app/partner/web/otp?id=7ab870e3-3f9c-4adf-90e5-858e3df9b4a0'},
            None
        )
        response = self.client.get('/api/payback/v1/gopay/pay-account/')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(
            response['data']['web_linking'],
            'https://gojek.link/gopay/partner/web/otp?id=7ab870e3-3f9c-4adf-90e5-858e3df9b4a0'
        )

    @patch('juloserver.payback.views.GopayServices.create_pay_account')
    def test_gopay_create_pay_account_should_not_change_web_link_url_when_response_none(
            self, mock_create_pay_account
    ):
        mock_create_pay_account.return_value = (
            None,
            'Pastikan nomor HP di akun GoPay kamu sama '
            'dengan nomor HP utama kamu di akun JULO, ya!',
        )
        response = self.client.get('/api/payback/v1/gopay/pay-account/')
        self.assertEqual(response.status_code, 400, response.content)
        response = response.json()
        self.assertIn(
            'Pastikan nomor HP di akun GoPay kamu sama '
            'dengan nomor HP utama kamu di akun JULO, ya!',
            response['errors'],
        )

    @patch('juloserver.payback.views.GopayServices.create_pay_account')
    def test_gopay_create_pay_account_should_not_change_web_link_url_when_feature_turn_off(
            self, mock_create_pay_account
    ):
        self.feature_setting.update_safely(
            is_active=False
        )
        mock_create_pay_account.return_value = (
            {'account_status': 'PENDING',
             'web_linking': 'https://gopay.co.id/app/partner/web'
                            '/otp?id=7ab870e3-3f9c-4adf-90e5-858e3df9b4a0'},
            None
        )
        response = self.client.get('/api/payback/v1/gopay/pay-account/')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(
            response['data']['web_linking'],
            'https://gopay.co.id/app/partner/web/otp?id=7ab870e3-3f9c-4adf-90e5-858e3df9b4a0'
        )
