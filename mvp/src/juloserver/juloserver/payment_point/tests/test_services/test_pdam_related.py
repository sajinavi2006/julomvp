import mock
from datetime import datetime

from django.utils import timezone
from django.test.testcases import TestCase
from juloserver.julo.tests.factories import SepulsaProductFactory
from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    SepulsaProductType,
)

from juloserver.payment_point.tests.factories import PdamOperatorFactory
from juloserver.payment_point.services.sepulsa import (
    SepulsaLoanService,
    get_sepulsa_partner_amount,
)
from juloserver.payment_point.services.pdam_related import (
    get_pdam_operator,
    get_pdam_bill_information,
)
from juloserver.payment_point.services.pdam_related import *
from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
)
from juloserver.julo.tests.factories import (
    SepulsaProductFactory,
)


class TestPdamRelatedServices(TestCase):
    def setUp(self):
        self.pdam = PdamOperatorFactory()
        self.sepulsa_product = SepulsaProductFactory(
            product_desc='pdam_ex',
            product_name='PDAM ex',
            is_active=True,
            is_not_blocked=True,
            type=SepulsaProductType.PDAM,
            category=SepulsaProductCategory.WATER_BILL,
        )

    @mock.patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.send_request')
    def test_inquire_pdam_operator(self, mock_api_call):
        sepulsa_client = SepulsaLoanService()
        mock_api_call.return_value = None
        self.assertIsNone(sepulsa_client.inquire_pdam_operator(None))

    @mock.patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.send_request')
    def test_inquire_pdam(self, mock_api_call):
        sepulsa_client = SepulsaLoanService()
        mock_api_call.return_value = None
        self.assertIsNone(sepulsa_client.inquire_pdam(None))

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_pdam_operator"
    )
    def test_get_pdam_operator(self, mock_sepulsa_pdam_api):
        operators, error = get_pdam_operator(None)
        self.assertEqual(operators[0]["code"], "pdam_ex")
        self.assertIsNone(error)

        operators, error = get_pdam_operator("a")
        self.assertEqual(operators[0]["code"], "pdam_ex")
        self.assertIsNone(error)

        self.pdam.is_popular_operator = False
        self.pdam.save()
        operators, error = get_pdam_operator("pdam_aetra")
        self.assertEqual(operators, [])
        self.assertEqual(error, "Operator not found")

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_pdam"
    )
    def test_get_pdam_bill(self, mock_sepulsa_pdam_api):
        sepulsa_product = SepulsaProductFactory(
            product_id='87',
            product_name='pdam',
            admin_fee=2500,
            type=SepulsaProductType.PDAM,
            category=SepulsaProductCategory.WATER_BILL,
            is_active=True,
            is_not_blocked=True,
        )
        mock_sepulsa_pdam_api.return_value = (None,True)
        bills, error = get_pdam_bill_information(None, sepulsa_product)
        self.assertEqual(error, True)
        self.assertIsNone(bills)
        mock_sepulsa_pdam_api.return_value = (
            {
                "amount": "",
                "name": "SEPULSA",
                "bills": [
                        {
                        "bill_amount": ["59500"],
                        "bill_date": ["201709"],
                        "info_text": "Angsuran Ke-1",
                        "waterusage_bill": "41000",
                        "total_fee": "",
                        "penalty": [""],
                        }
                    ],
                    "status": True,
            },
            None,
        )
        bills, error = get_pdam_bill_information(None, sepulsa_product)
        self.assertEqual(bills["admin_fee"], 2500)
        self.assertIsNone(error)
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
        bills, error = get_pdam_bill_information(None, sepulsa_product)
        self.assertEqual(bills["admin_fee"], 2500)
        self.assertIsNone(error)
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
                    "status": False,
            },
            None,
        )
        bills, error = get_pdam_bill_information(None, sepulsa_product)
        self.assertEqual(bills["amount"], '59500')
        self.assertIsNone(error)

    @mock.patch(
            "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_pdam"
        )
    def test_pdam_inquery_bill_not_found(self, mock_sepulsa_pdam_api):
        sepulsa_product = SepulsaProductFactory(
                id=1,
                product_id='87',
                product_name='pdam',
                admin_fee=2500,
                type=SepulsaProductType.PDAM,
                category=SepulsaProductCategory.WATER_BILL,
                is_active=True,
                is_not_blocked=True,
            )
        mock_sepulsa_pdam_api.return_value = (
                {
                    "amount": "59500",
                    "name": "SEPULSA",
                    "bills":[],
                    "status": True,
                },
                None,
            )
        bills, error = get_pdam_bill_information(None, sepulsa_product)
        self.assertEqual(bills, [])
        self.assertEqual(error, "Bill not found")


    def test_get_sepulsa_partner_amount(self):
        sepulsa_product = SepulsaProductFactory(
            id=1,
            product_id='87',
            product_name='pdam',
            admin_fee=2500,
            service_fee=500,
            type=SepulsaProductType.PDAM,
            category=SepulsaProductCategory.WATER_BILL,
            is_active=True,
            is_not_blocked=True,
        )

        customer_amount = 10000
        pdam_service_fee = 500
        partner_amount = get_sepulsa_partner_amount(
            customer_amount,
            sepulsa_product,
            pdam_service_fee,
        )
        self.assertEqual(partner_amount, 10500)
