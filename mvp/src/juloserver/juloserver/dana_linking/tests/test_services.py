from django.test import TestCase
from mock import patch
from datetime import datetime
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.julo.tests.factories import (
    CustomerFactory,
    DeviceFactory,
    ApplicationFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.dana_linking.tests.factories import DanaWalletAccountFactory
from juloserver.dana_linking.models import DanaWalletAccount
from juloserver.dana_linking.services import (
    unbind_dana_account_linking,
    fetch_dana_other_page_details,
)


class TestDanaAccountServices(TestCase):

    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.device = DeviceFactory(customer=self.customer)
        self.token_expiry_time = datetime.strptime(
            datetime.strftime(timezone.localtime(timezone.now()), '%Y-%m-%dT%H:%M:%S%z'),
            '%Y-%m-%dT%H:%M:%S%z',
        ) + relativedelta(years=3)

        self.dana_wallet_account = DanaWalletAccountFactory(
            account=self.account,
            status='ENABLED',
            access_token='CfhFKLH1c87IIp0Q2gZ98UAwrMWMiEYYtkGv6400',
            access_token_expiry_time=self.token_expiry_time,
            refresh_token='9A0W9LK0gEpmn5v1bO4P72msiLIvK41XvegP6400',
            refresh_token_expiry_time=self.token_expiry_time,
            balance=100000
        )

    @patch('juloserver.dana_linking.services.get_dana_linking_client')
    def test_unbind_dana_account_linking(self, mock_get_dana_linking_client):
        mock_get_dana_linking_client().unbind_dana_account.return_value = {
            "responseCode": "2000900",
            "responseMessage": "Successful",
            "referenceNo": "2020102977770000000009",
            "partnerReferenceNo": "2020102900000000000001",
            "merchantId": "23489182303312",
            "subMerchantId": "23489182303312",
            "linkId": "abcd1234efgh5678ijkl9012",
            "unlinkResult": "success",
            "additionalInfo": {}
        }, None
        response, error = unbind_dana_account_linking(self.account)
        self.assertEqual(response, 'Akun Anda telah di deaktivasi')
        self.assertIsNone(error)
        self.assertTrue(
            DanaWalletAccount.objects.filter(account=self.account, status='DISABLED').exists()
        )

        response, error = unbind_dana_account_linking(self.account)
        self.assertEqual(error, 'Akun dana tidak ditemukan')
        self.assertIsNone(response)
        self.assertFalse(
            DanaWalletAccount.objects.filter(account=self.account, status='ENABLED').exists()
        )

        self.dana_wallet_account.update_safely(status='ENABLED')
        mock_get_dana_linking_client().unbind_dana_account.return_value = {
            "responseCode": "5000900",
            "responseMessage": "General Error",
            "referenceNo": "2020102977770000000009",
            "partnerReferenceNo": "2020102900000000000001",
            "merchantId": "23489182303312",
            "subMerchantId": "23489182303312",
            "linkId": "abcd1234efgh5678ijkl9012",
            "unlinkResult": "failed",
            "additionalInfo": {}
        }, None
        response, error = unbind_dana_account_linking(self.account)
        self.assertEqual(error, 'Terjadi kesalahan silahkan ulangi beberapa saat lagi')
        self.assertIsNone(response)
        self.assertFalse(
            DanaWalletAccount.objects.filter(account=self.account, status='DISABLED').exists()
        )

    @patch('juloserver.dana_linking.services.get_dana_linking_client')
    def test_fetch_dana_other_page_details(self, mock_get_dana_linking_client):
        feature_setting = FeatureSettingFactory(
            feature_name='dana_other_page_url',
            parameters={}
        )
        mock_get_dana_linking_client().apply_ott.return_value = {
            "responseCode": "2004900",
            "responseMessage": "Successful",
            "resourceType": "OTT",
            "value": "jadoijasod9879847120947201ifh0afhq08hd1038",
            "additionalInfo": {}
        }, None
        response, error = fetch_dana_other_page_details(self.account)
        self.assertEqual(error, 'Feature setting not found')
        self.assertIsNone(response)

        feature_setting.parameters = [
            {
                "title_content": "Ke MiniDana",
                "web_link": "https://m.sandbox.dana.id/m/ipg?sourcePlatform=IPG&ott=",
                "type": "link",
            },
            {
                "title_content": "Cara Top Up DANA",
                "web_link": "https://m.sandbox.dana.id/m/portal/topup?ott=",
                "type": "link",
            },
            {
                "title_content": "Hubungi CS DANA",
                "web_link": "https://m.sandbox.dana.id/m/ipg?sourcePlatform=IPG&ott=",
                "type": "link",
            },
            {
                "title_content": "Putuskan JULO dengan DANA",
                "web_link": "",
                "type": "text",
            },
        ]
        feature_setting.save()
        response, error = fetch_dana_other_page_details(self.account)
        self.assertEqual(response[0]['title_content'], 'Ke MiniDana')
        self.assertIsNone(error)

        self.dana_wallet_account.update_safely(status='DISABLED')
        response, error = fetch_dana_other_page_details(self.account)
        self.assertEqual(error, 'Akun dana tidak ditemukan')
        self.assertIsNone(response)

        mock_get_dana_linking_client().apply_ott.return_value = {
            "responseCode": "5004900",
            "responseMessage": "General Error",
            "resourceType": "OTT",
            "additionalInfo": {}
        }, None
        self.dana_wallet_account.update_safely(status='ENABLED')
        response, error = fetch_dana_other_page_details(self.account)
        self.assertEqual(error, 'Terjadi kesalahan silahkan ulangi beberapa saat lagi')
        self.assertIsNone(response)
