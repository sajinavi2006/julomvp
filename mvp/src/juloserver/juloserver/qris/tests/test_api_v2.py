from django.test import TestCase
from rest_framework.test import APIClient
from mock import MagicMock, patch
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    PartnerFactory,
    ApplicationFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.qris.constants import QrisStatusImageLinks
from juloserver.qris.services.user_related import (
    QrisListTransactionService,
)
from juloserver.qris.exceptions import QrisLinkageNotFound


class QrisTransactionListViewTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        amar_user = AuthUserFactory(username='amar', password='12345')
        self.partner = PartnerFactory(name=PartnerNameConstant.AMAR, user=amar_user)
        self.url = '/api/qris/v2/transactions?partner_name=' + PartnerNameConstant.AMAR

    @patch.object(QrisListTransactionService, 'get_all_transactions')
    def test_get_all_transactions(self, mock_get_all_transactions):
        mock_transactions = {
            '12-2024': [
                {
                    'merchant_name': 'Merchant A',
                    'transaction_date': '03-12-2024',
                    'amount': 'Rp 10.000',
                    "qris_transaction_status": "Sedang diproses",
                    "transaction_status_color": "#F69539",
                    "status_image_link": QrisStatusImageLinks.PENDING,
                },
                {
                    'merchant_name': 'Merchant B',
                    'transaction_date': '02-12-2024',
                    'amount': 'Rp 20.000',
                    "qris_transaction_status": "Gagal",
                    "transaction_status_color": "#DB4D3D",
                    "status_image_link": QrisStatusImageLinks.FAILED,
                },
            ]
        }

        mock_get_all_transactions.return_value = mock_transactions
        self.url = self.url + '&limit=10'
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], mock_transactions)

    def test_get_transactions_partner_not_found(self):
        response = self.client.get('/api/qris/v2/transactions?partner_name=invalid_name')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], 'Partner not found')

    @patch.object(QrisListTransactionService, 'get_all_transactions')
    def test_get_transactions_qris_linkage_not_found(self, mock_get_all_transactions):
        mock_get_all_transactions.side_effect = QrisLinkageNotFound()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0], 'Qris User Linkage not found')

    @patch.object(QrisListTransactionService, 'get_all_transactions')
    def test_get_transactions_with_limit(self, mock_get_all_transactions):
        mock_transactions = [
            {
                '12-2024': [
                    {
                        'merchant_name': 'Merchant A',
                        'transaction_date': '03-12-2024',
                        'amount': '-Rp 10.000',
                        "qris_transaction_status": "Sedang diproses",
                        "transaction_status_color": "#F69539",
                        "status_image_link": "https://statics.julo.co.id/qris/sedang_diproses.png",
                    },
                    {
                        'merchant_name': 'Merchant B',
                        'transaction_date': '02-12-2024',
                        'amount': 'Rp 20.000',
                        "qris_transaction_status": "Gagal",
                        "transaction_status_color": "#DB4D3D",
                        "status_image_link": "https://statics.julo.co.id/qris/gagal.png",
                    },
                ]
            }
        ]

        mock_get_all_transactions.return_value = mock_transactions
        self.url = self.url + '&limit=1'
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], mock_transactions)
        mock_get_all_transactions.assert_called_once_with(limit=1)
