from datetime import datetime

from django.test.testcases import TestCase
from rest_framework.test import APIClient
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)
import mock
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.models import StatusLookup
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    PaymentMethodFactory,
    LoanFactory,
    PaymentFactory,
    PaybackTransactionFactory,
    AccountingCutOffDateFactory,
)

from juloserver.ovo.tests.factories import (
    OvoWalletAccountFactory,
    OvoWalletTransactionFactory,
)
from juloserver.ovo.constants import (
    OvoWalletAccountStatusConst,
    OvoStatus,
    OvoBindingResponseCodeAndMessage,
)
from juloserver.ovo.models import OvoWalletTransaction


class TestLinkingResult(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, customer_xid=81467045757557)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.ovo_wallet = OvoWalletAccountFactory(
            account_id=self.account.id,
            auth_code="auth_code_test_1",
        )
        self.ovo_pm = PaymentMethodFactory(
            payment_method_name='OVO',
            is_latest_payment_method=True,  # is latest
            customer=self.customer,
        )
        self.ovo_tokenization_pm = PaymentMethodFactory(
            payment_method_name='OVO Tokenization',
            is_latest_payment_method=False,  # is not latest
            customer=self.customer,
        )

    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.get_snap_expiry_token")
    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.is_expired_snap_token")
    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.authenticate_snap_request")
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_redis_client')
    def test_linking_result_success_failed_status(
        self,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):
        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = None

        data = {
            "originalExternalId": "random",
            "additionalInfo": {
                "status": OvoStatus.FAILED,
                "custIdMerchant": "81467045757557",
                "authCode": "auth_code_test_1",
            },
        }
        response = self.client.post(
            '/webhook/ovo-tokenization/v1/binding-notification', data=data, format='json'
        )
        self.ovo_wallet.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(self.ovo_wallet.status, OvoWalletAccountStatusConst.FAILED)

    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.get_snap_expiry_token")
    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.is_expired_snap_token")
    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.authenticate_snap_request")
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_redis_client')
    def test_linking_result_failed_invalid_field(
        self,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):
        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = None

        data = {
            "originalExternalId": "random",
            "additionalInfo": {
                "status": OvoStatus.SUCCESS,
                "custIdMerchant": "",  # invalid field
                "authCode": "auth_code_test_1",
            },
        }
        response = self.client.post(
            '/webhook/ovo-tokenization/v1/binding-notification', data=data, format='json'
        )
        self.ovo_wallet.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["responseCode"],
            OvoBindingResponseCodeAndMessage.INVALID_FIELD_FORMAT.code,
        )

    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.get_snap_expiry_token")
    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.is_expired_snap_token")
    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.authenticate_snap_request")
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_redis_client')
    def test_linking_result_failed_not_found(
        self,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        data = {
            "originalExternalId": "random",
            "additionalInfo": {
                "status": OvoStatus.SUCCESS,
                "custIdMerchant": "81467045757557",
                "authCode": "auth_code_test_2",  # wrong auth code
            },
        }
        response = self.client.post(
            '/webhook/ovo-tokenization/v1/binding-notification', data=data, format='json'
        )
        self.ovo_wallet.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
        self.assertEqual(
            response.json()["responseCode"], OvoBindingResponseCodeAndMessage.NOT_FOUND.code
        )

    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.get_snap_expiry_token")
    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.is_expired_snap_token")
    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.authenticate_snap_request")
    @mock.patch("juloserver.ovo.services.ovo_tokenization_services.get_doku_snap_ovo_client")
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_redis_client')
    def test_linking_result_success(
        self,
        mock_redis_client,
        mock_get_doku_snap_ovo_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        data = {
            "originalExternalId": "random",
            "additionalInfo": {
                "status": OvoStatus.SUCCESS,
                "custIdMerchant": "81467045757557",
                "authCode": "auth_code_test_1",  # wrong auth code
            },
        }
        mock_get_doku_snap_ovo_client()._get_b2b2c_access_token.return_value = True
        response = self.client.post(
            '/webhook/ovo-tokenization/v1/binding-notification', data=data, format='json'
        )
        self.ovo_wallet.refresh_from_db()
        self.ovo_pm.refresh_from_db()
        self.ovo_tokenization_pm.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.json()["responseCode"], OvoBindingResponseCodeAndMessage.SUCCESSFUL.code
        )
        self.assertFalse(self.ovo_pm.is_latest_payment_method)  # become false
        self.assertTrue(self.ovo_tokenization_pm.is_latest_payment_method)  # become true


class TestOvoAccountStatus(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user, customer_xid=81467045757557)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.ovo_wallet = OvoWalletAccountFactory(
            # pending account
            account_id=self.account.id,
            auth_code="auth_code_test_1",
        )

    def test_account_status_pending(self):
        response = self.client.get('/api/ovo-tokenization/v1/status')
        expected_response = {
            "success": True,
            "data": {
                "account_status": OvoWalletAccountStatusConst.PENDING,
            },
            "errors": [],
        }

        self.assertEqual(response.json(), expected_response)

    @mock.patch("juloserver.ovo.views.ovo_tokenization_views.get_ovo_wallet_balance")
    def test_account_status_success(self, mock_get_ovo_wallet_balance):
        self.ovo_wallet.status = OvoWalletAccountStatusConst.ENABLED
        self.ovo_wallet.save()
        mock_get_ovo_wallet_balance.return_value = (20000, None)

        response = self.client.get('/api/ovo-tokenization/v1/status')
        expected_response = {
            "success": True,
            "data": {
                "account_status": OvoWalletAccountStatusConst.ENABLED,
                "balance": 20000,
            },
            "errors": [],
        }

        self.assertEqual(response.json(), expected_response)


class TestBindingStatus(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user, customer_xid=81467045757557)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.ovo_wallet = OvoWalletAccountFactory(
            # pending account
            account_id=self.account.id,
            auth_code="auth_code_test_1",
        )
        self.ovo_pm = PaymentMethodFactory(
            payment_method_name='OVO',
            is_latest_payment_method=True,  # is latest
            customer=self.customer,
        )
        self.ovo_tokenization_pm = PaymentMethodFactory(
            payment_method_name='OVO Tokenization',
            is_latest_payment_method=False,  # is not latest
            customer=self.customer,
        )

    def test_binding_status_invalid_status(self):
        data = {
            "status": "ANY_INVALID_STATUS",
        }
        response = self.client.post(
            '/api/ovo-tokenization/v1/binding-status', data=data, format='json'
        )
        self.ovo_wallet.refresh_from_db()
        self.ovo_pm.refresh_from_db()
        self.ovo_tokenization_pm.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["errors"], ["Status invalid value of status"])
        self.assertTrue(self.ovo_pm.is_latest_payment_method)  # stay true
        self.assertFalse(self.ovo_tokenization_pm.is_latest_payment_method)  # stay false

    @mock.patch("juloserver.ovo.services.ovo_tokenization_services.get_doku_snap_ovo_client")
    def test_binding_status_to_success(self, mock_get_doku_snap_ovo_client):
        data = {
            "status": OvoStatus.SUCCESS,
        }
        mock_get_doku_snap_ovo_client()._get_b2b2c_access_token.return_value = True
        response = self.client.post(
            '/api/ovo-tokenization/v1/binding-status', data=data, format='json'
        )
        self.ovo_wallet.refresh_from_db()
        self.ovo_pm.refresh_from_db()
        self.ovo_tokenization_pm.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(self.ovo_wallet.status, OvoWalletAccountStatusConst.ENABLED)
        self.assertFalse(self.ovo_pm.is_latest_payment_method)  # become false
        self.assertTrue(self.ovo_tokenization_pm.is_latest_payment_method)  # become true

    def test_binding_status_to_failed(self):
        data = {
            "status": OvoStatus.FAILED,
        }
        response = self.client.post(
            '/api/ovo-tokenization/v1/binding-status', data=data, format='json'
        )
        self.ovo_wallet.refresh_from_db()
        self.ovo_pm.refresh_from_db()
        self.ovo_tokenization_pm.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(self.ovo_wallet.status, OvoWalletAccountStatusConst.FAILED)
        self.assertTrue(self.ovo_pm.is_latest_payment_method)  # stay true
        self.assertFalse(self.ovo_tokenization_pm.is_latest_payment_method)  # stay false


class TestOvoPayment(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user, customer_xid=81467045757557)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.ovo_wallet = OvoWalletAccountFactory(
            status=OvoWalletAccountStatusConst.ENABLED,
            account_id=self.account.id,
            auth_code="auth_code_test_1",
        )
        self.ovo_tokenization_pm = PaymentMethodFactory(
            payment_method_name='OVO Tokenization',
            is_latest_payment_method=False,  # is not latest
            customer=self.customer,
        )
        self.maxDiff = None

    @mock.patch("juloserver.ovo.services.ovo_tokenization_services.get_doku_snap_ovo_client")
    def test_ovo_payment_success(self, mock_get_doku_snap_ovo_client):
        data = {
            "amount": 20000,
        }

        mock_get_doku_snap_ovo_client().generate_reference_no.return_value = "random_reference_no_1"
        mock_get_doku_snap_ovo_client().payment.return_value = {
            'responseCode': '2005400',
            'responseMessage': 'Successful',
            'referenceNo': 'FBpApOioIRskGvFJUcoX6dPKT8ScZeIm',
            'webRedirectUrl': 'https://sandbox.doku.com/direct-debit/ui/payment/core/2238241212220256495107117721832140573567',
        }, None
        response = self.client.post('/api/ovo-tokenization/v1/payment', data=data, format='json')
        expected_response = {
            "success": True,
            "data": {
                "doku_url": "https://sandbox.doku.com/direct-debit/ui/payment/core/2238241212220256495107117721832140573567",
                "success_url": "https://www.julo.com/ovo-tokenization/payment/success",
                "failed_url": "https://www.julo.com/ovo-tokenization/payment/failed",
            },
            "errors": [],
        }

        ovo_wallet_transaction = OvoWalletTransaction.objects.filter(
            partner_reference_no="random_reference_no_1",
        ).last()

        self.assertEqual(response.json(), expected_response)
        self.assertIsNotNone(ovo_wallet_transaction)
        self.assertEqual(ovo_wallet_transaction.reference_no, "FBpApOioIRskGvFJUcoX6dPKT8ScZeIm")
        self.assertEqual(ovo_wallet_transaction.amount, 20000)
        self.assertEqual(response.status_code, HTTP_200_OK)


class TestOvoUnbinding(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user, customer_xid=81467045757557)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.ovo_wallet = OvoWalletAccountFactory(
            # pending account
            account_id=self.account.id,
            auth_code="auth_code_test_1",
        )

    @mock.patch("juloserver.ovo.services.ovo_tokenization_services.get_doku_snap_ovo_client")
    def test_account_unbinding_success(self, mock_get_doku_snap_ovo_client):
        self.ovo_wallet.status = OvoWalletAccountStatusConst.ENABLED
        self.ovo_wallet.save()
        mock_get_doku_snap_ovo_client().ovo_unbinding.return_value = {
            "responseCode": "2000900",
            "responseMessage": "Successful",
            "referenceNo": "M5bbYAzwdZZy8LURCQp",
        }, None

        response = self.client.delete('/api/ovo-tokenization/v1/unbinding')
        self.assertEqual(response.status_code, HTTP_200_OK)

    def test_account_unbinding_error_account_not_found(self):
        self.ovo_wallet.status = OvoWalletAccountStatusConst.DISABLED
        self.ovo_wallet.save()

        response = self.client.delete('/api/ovo-tokenization/v1/unbinding')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)


class TestOvoPaymentNotification(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, fullname="prod only")
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
        self.token = self.user.auth_expiry_token.key
        self.ovo_wallet = OvoWalletAccountFactory(
            # pending account
            account_id=self.account.id,
            auth_code="auth_code_test_1",
        )
        self.ovo_wallet_transaction = OvoWalletTransactionFactory(
            ovo_wallet_account=self.ovo_wallet,
            partner_reference_no='INV-0008',
            amount=99000,
            status='PENDING',
        )

    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_snap_expiry_token')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.is_expired_snap_token')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.authenticate_snap_request')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_redis_client')
    def test_ovo_payment_notification_success(
        self,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):
        request_data = {
            "originalPartnerReferenceNo": "INV-0008",
            "originalReferenceNo": "2d0nsSJ27GFllE5IWmBghVkPW6UOFhWO",
            "originalExternalId": "249319367692003199365649609468213166",
            "latestTransactionStatus": "00",
            "transactionStatusDesc": "Success",
            "amount": {"value": "99000.00", "currency": "IDR"},
            "additionalInfo": {
                "acquirerId": "OVO",
                "custIdMerchant": "julo-cust-013",
                "accountType": "WALLET",
                "channelId": "EMONEY_OVO_SNAP",
                "failedPaymentUrl": "www.merchant.com/failed",
                "successPaymentUrl": "www.merchant.com/success",
                "origin": {"apiFormat": "SNAP"},
                "paymentType": "SALE",
            },
        }

        self.client.credentials(
            HTTP_X_EXTERNAL_ID='externalid1',
            HTTP_AUTHORIZATION='Token ' + self.token,
            HTTP_AUTHORIZATION_CUSTOMER='Token ' + self.token,
        )

        self.payment_method = PaymentMethodFactory(
            customer=self.customer, payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION
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
            transaction_id='INV-0008',
            is_processed=False,
        )

        self.ovo_wallet.status = OvoWalletAccountStatusConst.ENABLED
        self.ovo_wallet.access_token = self.token
        self.ovo_wallet.save()

        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = None

        response = self.client.post(
            '/webhook/ovo-tokenization/v1/debit/notify', data=request_data, format='json'
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.payback_trx.refresh_from_db()
        self.assertEqual(self.payback_trx.is_processed, True)

    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_snap_expiry_token')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.is_expired_snap_token')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.authenticate_snap_request')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_redis_client')
    def test_payment_notification_paid_bill(
        self,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):
        request_data = {
            "originalPartnerReferenceNo": "INV-0008",
            "originalReferenceNo": "2d0nsSJ27GFllE5IWmBghVkPW6UOFhWO",
            "originalExternalId": "249319367692003199365649609468213166",
            "latestTransactionStatus": "00",
            "transactionStatusDesc": "Success",
            "amount": {"value": "99000.00", "currency": "IDR"},
            "additionalInfo": {
                "acquirerId": "OVO",
                "custIdMerchant": "julo-cust-013",
                "accountType": "WALLET",
                "channelId": "EMONEY_OVO_SNAP",
                "failedPaymentUrl": "www.merchant.com/failed",
                "successPaymentUrl": "www.merchant.com/success",
                "origin": {"apiFormat": "SNAP"},
                "paymentType": "SALE",
            },
        }

        self.client.credentials(
            HTTP_X_EXTERNAL_ID='externalid1',
            HTTP_AUTHORIZATION='Token ' + self.token,
            HTTP_AUTHORIZATION_CUSTOMER='Token ' + self.token,
        )

        self.payment_method = PaymentMethodFactory(
            customer=self.customer, payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION
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
            transaction_id='INV-0008',
            is_processed=True,
        )

        self.ovo_wallet.status = OvoWalletAccountStatusConst.ENABLED
        self.ovo_wallet.access_token = self.token
        self.ovo_wallet.save()

        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = None

        response = self.client.post(
            '/webhook/ovo-tokenization/v1/debit/notify', data=request_data, format='json'
        )
        self.assertEqual(response.status_code, 404, response.content)

    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_snap_expiry_token')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.is_expired_snap_token')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.authenticate_snap_request')
    @mock.patch('juloserver.ovo.views.ovo_tokenization_views.get_redis_client')
    def test_payment_notification_b2b2c_not_found(
        self,
        mock_redis_client,
        mock_authenticate_snap_request,
        mock_is_expired_snap_token,
        mock_get_snap_expiry_token,
    ):
        request_data = {
            "originalPartnerReferenceNo": "INV-0008",
            "originalReferenceNo": "2d0nsSJ27GFllE5IWmBghVkPW6UOFhWO",
            "originalExternalId": "249319367692003199365649609468213166",
            "latestTransactionStatus": "00",
            "transactionStatusDesc": "Success",
            "amount": {"value": "99000.00", "currency": "IDR"},
            "additionalInfo": {
                "acquirerId": "OVO",
                "custIdMerchant": "julo-cust-013",
                "accountType": "WALLET",
                "channelId": "EMONEY_OVO_SNAP",
                "failedPaymentUrl": "www.merchant.com/failed",
                "successPaymentUrl": "www.merchant.com/success",
                "origin": {"apiFormat": "SNAP"},
                "paymentType": "SALE",
            },
        }

        self.client.credentials(
            HTTP_X_EXTERNAL_ID='externalid1',
            HTTP_AUTHORIZATION='Token ' + self.token,
            HTTP_AUTHORIZATION_CUSTOMER='Token ' + self.token,
        )

        self.payment_method = PaymentMethodFactory(
            customer=self.customer, payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION
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
            transaction_id='INV-0008',
            is_processed=True,
        )

        self.ovo_wallet.status = OvoWalletAccountStatusConst.ENABLED
        self.ovo_wallet.access_token = '123'
        self.ovo_wallet.save()

        mock_get_snap_expiry_token.return_value = True
        mock_is_expired_snap_token.return_value = False
        mock_authenticate_snap_request.return_value = True
        mock_redis_client.return_value.get.return_value = None

        response = self.client.post(
            '/webhook/ovo-tokenization/v1/debit/notify', data=request_data, format='json'
        )
        self.assertEqual(response.status_code, 401, response.content)
