from django.test.testcases import TestCase
from mock import ANY, patch
from rest_framework.test import APIClient
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)

from juloserver.account.tests.factories import AccountFactory

from juloserver.account_payment.tests.factories import AccountPaymentFactory

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    MobileFeatureSettingFactory,
    PaybackTransactionFactory,
    PaymentMethodFactory,
)

from juloserver.ovo.tests.factories import OvoRepaymentTransactionFactory
from juloserver.ovo.constants import (
    OvoMobileFeatureName,
    OvoTransactionStatus,
)
from juloserver.julo.payment_methods import PaymentMethodCodes


class TestPaymentStatus(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account
        )
        self.account_payment = AccountPaymentFactory(account=self.account, account_payment_xid=12)
        self.ovo_repayment_transaction = OvoRepaymentTransactionFactory(
            account_payment_xid=self.account_payment,
            transaction_id=1,
            amount=1000,
            status=OvoTransactionStatus.SUCCESS
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name=OvoMobileFeatureName.OVO_REPAYMENT_COUNTDOWN,
            is_active=True,
            parameters={'countdown': 55}
        )
        self.url_payment_status = '/api/ovo/v1/payment/status/{}'
        PaybackTransactionFactory(
            payback_service='OVO',
            status_desc='OVO',
            transaction_id=1,
            account=self.account,
            amount=1000,
        )

    def test_payment_status_should_success(self):
        response = self.client.get(
            self.url_payment_status.format(self.ovo_repayment_transaction.transaction_id)
        )
        self.assertEqual(response.status_code, HTTP_200_OK)
        expected_response = {
            "success": True,
            "data": {"status": "SUCCESS", "duration": 55, "total_payment": 1000},
            "errors": []
        }
        response = response.json()
        self.assertEqual(expected_response, response)

        self.mobile_feature_setting.update_safely(parameters={'countdown': 30})
        self.ovo_repayment_transaction.update_safely(status=OvoTransactionStatus.POST_DATA_SUCCESS)
        response = self.client.get(
            self.url_payment_status.format(self.ovo_repayment_transaction.transaction_id)
        )
        self.assertEqual(response.status_code, HTTP_200_OK)
        expected_response = {
            "success": True,
            "data": {"status": "PENDING", "duration": 30, "total_payment": 1000},
            "errors": []
        }
        response = response.json()
        self.assertEqual(expected_response, response)

    def test_payment_status_should_failed_when_payment_status_not_belong_to_the_customer(self):
        self.account_payment.update_safely(account=AccountFactory())
        response = self.client.get(
            self.url_payment_status.format(self.ovo_repayment_transaction.transaction_id)
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_payment_status_should_failed_when_transaction_id_not_exists(self):
        response = self.client.get(
            self.url_payment_status.format((self.ovo_repayment_transaction.transaction_id+1))
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_payment_status_should_failed_when_mobile_feature_setting_not_exists(self):
        self.mobile_feature_setting.update_safely(feature_name='wrong')
        response = self.client.get(
            self.url_payment_status.format(self.ovo_repayment_transaction.transaction_id)
        )
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)


class TestOvoTokenizationBindingViews(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, payment_method_code=PaymentMethodCodes.OVO_TOKENIZATION
        )

    @patch('juloserver.ovo.views.ovo_tokenization_views.request_webview_url')
    def test_payment_status_should_success(self, mock_request_webview_url):
        mock_request_webview_url.return_value = (
            {
                'doku_url': 'https://sandbox.doku.com/direct-debit/ui/binding/core/1234',
                'success_url': 'https://www.julo.com/ovo-tokenization/success',
                'failed_url': 'https://www.julo.com/ovo-tokenization/failed',
            },
            None,
        )
        url = '/api/ovo-tokenization/v1/binding'
        data = {'phone_number': '6287711114100'}
        response = self.client.post(url, data, format='json')
        response_data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response_data['data']['doku_url'])
        self.assertIsNotNone(response_data['data']['success_url'])
        self.assertIsNotNone(response_data['data']['failed_url'])

    @patch('juloserver.ovo.views.ovo_tokenization_views.request_webview_url')
    def test_payment_status_should_failed(self, mock_request_webview_url):
        mock_request_webview_url.return_value = (
            {
                'doku_url': 'https://sandbox.doku.com/direct-debit/ui/binding/core/1234',
                'success_url': 'https://www.julo.com/ovo-tokenization/success',
                'failed_url': 'https://www.julo.com/ovo-tokenization/failed',
            },
            None,
        )
        url = '/api/ovo-tokenization/v1/binding'
        data = {}
        response = self.client.post(url, data, format='json')
        response_data = response.json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(response_data['errors']), 1)
