import mock
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status as rest_status

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    SepulsaProductFactory,
    FeatureSettingFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory
)
from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
    TransactionMethodCode,
)
from juloserver.payment_point.models import SepulsaPaymentPointInquireTracking


class TestPaymentPointViewsPdamV3(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.sepulsa_product = SepulsaProductFactory(
            product_id='87',
            product_name='pdam',
            product_desc='pdam',
            is_not_blocked=True,
            is_active=True,
            admin_fee=2500,
            type=SepulsaProductType.PDAM,
            category=SepulsaProductCategory.WATER_BILL,
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        )

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_pdam_operator')
    def test_success_inquire_pdam_operator(self, mock_sepulsa_pdam_api):
        mock_sepulsa_pdam_api.return_value = (
            {
                "OperatorLists": [
                    {"code": "pdam_aetra", "description": "PDAM Aetra", "enabled": True}
                ]
            },
            None,
        )
        res = self.client.get('/api/payment-point/v3/inquire/pdam/operator?query=')
        api_response = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(api_response['data']), 1)
        self.assertEqual(api_response['errors'], [])

    def test_failed_inquire_pdam_operator(self):
        res = self.client.get('/api/payment-point/v3/inquire/pdam/operator?query=test')
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(api_response['data'])
        self.assertEqual(api_response['errors'], ['Operator not found'])

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_pdam')
    def test_product_failed_inquire_pdam_bill(self, mock_sepulsa_pdam_api):
        self.sepulsa_product.is_active = False
        self.sepulsa_product.is_not_blocked = False
        self.sepulsa_product.admin_fee = 2500
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/pdam/bill'
        api_data = {
            "customer_number": "119989000012288118811",
            "product_id": 87,
            "operator_code": "pdam",
            "operator_name": "pdam",
        }
        res = self.client.post(api_url, data=api_data)
        res_api = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(res_api['data'])
        self.assertEqual(res_api['errors'][0], 'Nomor Pelanggan Terlalu Panjang')

        api_data = {
            "customer_number": "1998900001",
            "product_id": 87,
            "operator_code": "pdam_aetra",
            "operator_name": "PDAM Aetra",
        }
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(api_response['data'])
        self.assertEqual(api_response['errors'], ['Produk yang kamu inginkan belum tersedia'])

        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_data = {
            "customer_number": "1998900001",
            "product_id": 87,
            "operator_code": "pdam",
            "operator_name": "pdam",
        }
        mock_sepulsa_pdam_api.return_value = (
            {
                "status": False,
                "response_code": "20"
            },
            True,
        )
        res = self.client.post(api_url, data=api_data)
        res_api = res.json()
        self.assertEqual(res_api['errors'][0], 'Sepertinya Ada yang Salah')
        mock_sepulsa_pdam_api.return_value = (
            {
                "status": False,
                "response_code": "20"
            },
            None,
        )
        res = self.client.post(api_url, data=api_data)
        error = [
                    'Nomor Pelanggan Tidak Ditemukan',
                    'Nomor salah atau tidak terdaftar. Harap masukkan nomer dengan benar'
                ]
        res_api = res.json()
        self.assertEqual(res_api['errors'][0], error[0])
        mock_sepulsa_pdam_api.return_value = (
            {
                "status": False,
                "response_code": "50"
            },
            None,
        )
        res = self.client.post(api_url, data=api_data)
        res_api = res.json()
        error = "Tagihan sudah terbayar"
        self.assertEqual(res_api['errors'][0], error)

        mock_sepulsa_pdam_api.return_value = (
            {
                "status": False,
                "response_code": "23"
            },
            None,
        )
        res = self.client.post(api_url, data=api_data)
        res_api = res.json()
        error = "Terdapat Masalah pada Operator"
        self.assertEqual(res_api['errors'][0], error)

        mock_sepulsa_pdam_api.return_value = (
            {
                "status": False,
                "response_code": "100",
                "desc": "Error"
            },
            None,
        )
        res = self.client.post(api_url, data=api_data)
        res_api = res.json()
        error = "Sepertinya Ada yang Salah"
        self.assertEqual(res_api['errors'][0], error)

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_pdam')
    def test_product_success_inquire_pdam_bill(self, mock_sepulsa_pdam_api):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/pdam/bill'
        mock_sepulsa_pdam_api.return_value = (
            {
                "amount": "59500",
                "name": "SEPULSA",
                "bills": [
                        {
                        "bill_amount": ["59500"],
                        "bill_date": ["201709"],
                        "info_text": "Angsuran Ke-1",
                        "waterusage_bill": "41000",
                        "total_fee": "18500",
                        "penalty": ["0"],
                        }
                    ],
                    "status": True,
            },
            None,
        )
        api_data = {
            "customer_number": "1998900001",
            "product_id": 87,
            "operator_code": "pdam",
            "operator_name": "pdam",
        }
        res = self.client.post(api_url, data=api_data)
        self.assertEqual(res.status_code, rest_status.HTTP_200_OK)
        inquire_tracking_id = res.json()['data']['sepulsa_payment_point_inquire_tracking_id']
        self.assertIsNotNone(inquire_tracking_id)
        inquire_tracking = SepulsaPaymentPointInquireTracking.objects.get(id=inquire_tracking_id)
        self.assertEqual(inquire_tracking.account_id, self.account.id)
        self.assertEqual(inquire_tracking.transaction_method_id, TransactionMethodCode.PDAM.code)
        self.assertEqual(inquire_tracking.price, 59500)
        self.assertEqual(inquire_tracking.sepulsa_product.type, SepulsaProductType.PDAM)
        self.assertEqual(inquire_tracking.identity_number, '1998900001')
        self.assertEqual(inquire_tracking.other_data['customer_name'], 'SEPULSA')

        mock_sepulsa_pdam_api.return_value = (
            {
                "amount": "59500",
                "name": "SEPULSA",
                "bills": [
                        {
                        "bill_amount": ["59500"],
                        "bill_date": ["201709"],
                        "info_text": "Angsuran Ke-1",
                        "waterusage_bill": "",
                        "total_fee": "18500",
                        "penalty": ["0"],
                        }
                    ],
                    "status": True,
            },
            None,
        )
        api_data = {
            "customer_number": "1998900001",
            "product_id": 87,
            "operator_code": "pdam",
            "operator_name": "pdam",
        }
        res = self.client.post(api_url, data=api_data)
        res_api = res.json()
        self.assertEqual(res_api['data']['bills'][0]['waterusage_bill'], '0')
