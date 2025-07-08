from mock import MagicMock, patch
import base64
from collections import namedtuple
from django.test.testcases import TestCase
from django.conf import settings

from juloserver.payback.client import GopayClient
from juloserver.payback.tests.factories import GopayAccountLinkStatusFactory
from juloserver.julo.tests.factories import (
    CustomerFactory, PaymentFactory, LoanFactory, StatusLookup)
from juloserver.account.tests.factories import AccountFactory
from juloserver.autodebet.models import AutodebetAPILog


class TestGopay(TestCase):
    def setUp(self):
        self.gopay_client = GopayClient(
            server_key='11111111',
            base_url='http://fakegopayclient.com',
            base_snap_url='http://fakesnapgopayclient.com'
        )
        self.gopay_account_link_status = GopayAccountLinkStatusFactory(
            account=AccountFactory(),
        )

    def test_build_api_header(self):
        header = self.gopay_client.build_api_header()
        self.assertEqual(header, {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % base64.b64encode(b'11111111:').decode()
        })

    @patch('juloserver.payback.client.gopay.requests')
    def test_init_transaction(self, mock_requests):
        response = MagicMock()
        response.json.return_value = {'msg': 'test data'}
        response.status_code = 201
        mock_requests.post.return_value = response
        customer = CustomerFactory()
        loan = LoanFactory()
        status_lookup = StatusLookup.objects.all().first()
        payment = PaymentFactory(loan=loan, payment_status=status_lookup)
        data = {
            'customer': customer,
            'payment': payment,
            'amount': 10000
        }
        result = self.gopay_client.init_transaction(data)
        self.assertEqual(result['amount'], 10000)

    @patch('juloserver.payback.client.gopay.requests')
    def test_iget_status(self, mock_requests):
        response = MagicMock()
        response.json.return_value = {'msg': 'test data'}
        response.status_code = 200
        mock_requests.get.return_value = response
        result = self.gopay_client.get_status({'transaction_id': '111111'})
        self.assertEqual(result, {'msg': 'test data'})

    @patch('juloserver.payback.client.gopay.requests')
    def test_get_pay_account_and_store_log_should_success(self, mock_requests):
        response = MagicMock()
        response.json.return_value = {'msg': 'test data'}
        response.status_code = 200
        mock_requests.get.return_value = response
        result = self.gopay_client.get_pay_account(
            self.gopay_account_link_status.pay_account_id,
            store_log_autodebet=True
        )
        self.assertEqual(result, {'msg': 'test data'})
        self.assertTrue(AutodebetAPILog.objects.all().exists())

    @patch('juloserver.payback.client.gopay.requests')
    def test_get_pay_account_should_success(self, mock_requests):
        response = MagicMock()
        response.json.return_value = {'msg': 'test data'}
        response.status_code = 200
        mock_requests.get.return_value = response
        result = self.gopay_client.get_pay_account(
            self.gopay_account_link_status.pay_account_id,
        )
        self.assertEqual(result, {'msg': 'test data'})
        self.assertFalse(AutodebetAPILog.objects.all().exists())
