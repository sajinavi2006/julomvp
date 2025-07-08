from collections import OrderedDict
from django.conf import settings
import mock
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status as rest_status

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CreditMatrixFactory,
    CustomerFactory,
    FeatureSettingFactory,
    MobileOperatorFactory,
    ProductLookupFactory,
    SepulsaProductFactory,
)
from juloserver.account.tests.factories import AccountFactory, AccountLimitFactory
from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    SepulsaProductType,
    TransactionMethodCode,
)
from juloserver.payment_point.models import SepulsaPaymentPointInquireTracking
from juloserver.payment_point.tests.factories import AYCProductFactory, XfersProductFactory


class TestPaymentPointViewsV2(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.sepulsa_product = SepulsaProductFactory(
            is_not_blocked=True,
            is_active=True,
            admin_fee=2500,
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        )

    @mock.patch(
        'juloserver.julo.clients.sepulsa.JuloSepulsaClient.inquire_electricity_postpaid_information'
    )
    def test_success_inquire_electricity_postpaid(self, mock_sepulsa_api):
        self.sepulsa_product.type = SepulsaProductType.ELECTRICITY
        self.sepulsa_product.category = SepulsaProductCategory.ELECTRICITY_POSTPAID
        self.sepulsa_product.save()
        mock_sepulsa_api.return_value = (
            True,
            200,
            {
                "amount": "47250",
                "admin_charge": "2750",
                "trx_id": "",
                "stan": "000000084849",
                "datetime": "20170104151947",
                "merchant_code": "6021",
                "bank_code": "4510017",
                "rc": "00",
                "terminal_id": "0000000000000048",
                "material_number": "",
                "subscriber_id": "512345610000",
                "subscriber_name": "SEPULSAWATI",
                "switcher_refno": "0SYM212162998631447328B515061028",
                "subscriber_segmentation": "R1",
                "power": 900,
                "outstanding_bill": "0",
                "bill_status": "1",
                "blth_summary": "JAN17",
                "stand_meter_summary": "00027135 - 00027286",
                "bills": [
                    {
                        "bill_period": "201701",
                        "produk": "PLNPOSTPAID",
                        "due_date": "20170120",
                        "meter_read_date": "00000000",
                        "total_electricity_bill": "44500",
                        "incentive": "00000000000",
                        "value_added_tax": "0000000000",
                        "penalty_fee": "000000000",
                        "previous_meter_reading1": "00027135",
                        "current_meter_reading1": "00027286",
                        "previous_meter_reading2": "00000000",
                        "current_meter_reading2": "00000000",
                        "previous_meter_reading3": "00000000",
                        "current_meter_reading3": "00000000",
                    }
                ],
                "status": True,
                "response_code": "00",
            },
        )

        response = self.client.get(
            "/api/payment-point/v2/inquire/electricity/postpaid" "?customer_number=512345610000"
        )
        self.assertEqual(response.status_code, rest_status.HTTP_200_OK)
        inquire_tracking_id = response.json()['data']['sepulsa_payment_point_inquire_tracking_id']
        self.assertIsNotNone(inquire_tracking_id)
        inquire_tracking = SepulsaPaymentPointInquireTracking.objects.get(id=inquire_tracking_id)
        self.assertEqual(inquire_tracking.account_id, self.account.id)
        self.assertEqual(
            inquire_tracking.transaction_method_id, TransactionMethodCode.LISTRIK_PLN.code
        )
        self.assertEqual(inquire_tracking.price, 47000)
        self.assertEqual(inquire_tracking.sepulsa_product.type, SepulsaProductType.ELECTRICITY)
        self.assertEqual(inquire_tracking.identity_number, '512345610000')
        self.assertEqual(inquire_tracking.other_data['customer_name'], 'SEPULSAWATI')

    @mock.patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.inquire_bpjs')
    def test_success_inquire_bpjs(self, mock_sepulsa_api):
        self.sepulsa_product.type = SepulsaProductType.BPJS
        self.sepulsa_product.category = SepulsaProductCategory.BPJS_KESEHATAN[0]
        self.sepulsa_product.save()
        mock_sepulsa_api.return_value = {
            "trx_type": "2100",
            "product_type": "BPJS-KESEHATAN",
            "stan": "90518024",
            "premi": "51000",
            "admin_charge": "2500",
            "amount": "53500",
            "datetime": "20170125123152",
            "merchant_code": "6012",
            "rc": "00",
            "no_va": "0000001430071801",
            "periode": "01",
            "name": "SEPULSAWATI (PST:  2)",
            "kode_cabang": "1101",
            "nama_cabang": "SEMARANG",
            "sisa": "000000000000",
            "va_count": "1",
            "no_va_kk": "0000001430071801",
            "kode_loket": "HTH16010028",
            "nama_loket": "PT SEPULSA TEKNOLOGI INDONESIA",
            "alamat_loket": "Jakarta",
            "phone_loket": "021912345",
            "kode_kab_kota": "2122",
            "trx_id": "",
            "status": True,
            "response_code": "00",
            "sw_reff": "22618720",
            "message": "success",
        }

        response = self.client.get(
            "/api/payment-point/v2/inquire/bpjs" "?bpjs_number=0000001430071801&bpjs_times=2"
        )
        self.assertEqual(response.status_code, rest_status.HTTP_200_OK)
        inquire_tracking_id = response.json()['data']['sepulsa_payment_point_inquire_tracking_id']
        self.assertIsNotNone(inquire_tracking_id)
        inquire_tracking = SepulsaPaymentPointInquireTracking.objects.get(id=inquire_tracking_id)
        self.assertEqual(inquire_tracking.account_id, self.account.id)
        self.assertEqual(
            inquire_tracking.transaction_method_id, TransactionMethodCode.BPJS_KESEHATAN.code
        )
        self.assertEqual(inquire_tracking.price, 53500)
        self.assertEqual(inquire_tracking.sepulsa_product.type, SepulsaProductType.BPJS)
        self.assertEqual(inquire_tracking.identity_number, '0000001430071801')
        self.assertEqual(inquire_tracking.other_data['bpjs_times'], 2)

    @mock.patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.inquire_mobile_postpaid')
    def test_success_inquire_mobile_postpaid(self, mock_sepulsa_api):
        self.sepulsa_product.operator = MobileOperatorFactory()
        self.sepulsa_product.type = SepulsaProductType.MOBILE
        self.sepulsa_product.category = SepulsaProductCategory.POSTPAID[0]
        self.sepulsa_product.save()
        mock_sepulsa_api.return_value = {
            "reference_no": "2203267",
            "customer_no": "081234000001",
            "customer_name": "SEPULSA",
            "response_code": "00",
            "bill_count": "1",
            "bill_periode": "201407",
            "bill_amount": "209294",
            "admin_fee": "2500",
            "total_amount": "211794",
            "message": "success",
            "rc": "00",
            "status": True,
            "trx_id": "",
        }

        response = self.client.get(
            "/api/payment-point/v2/inquire/phone/postpaid"
            "?mobile_number=081234000001&product_id={}".format(self.sepulsa_product.id)
        )
        self.assertEqual(response.status_code, rest_status.HTTP_200_OK)
        inquire_tracking_id = response.json()['data']['sepulsa_payment_point_inquire_tracking_id']
        self.assertIsNotNone(inquire_tracking_id)
        inquire_tracking = SepulsaPaymentPointInquireTracking.objects.get(id=inquire_tracking_id)
        self.assertEqual(inquire_tracking.account_id, self.account.id)
        self.assertEqual(
            inquire_tracking.transaction_method_id, TransactionMethodCode.PASCA_BAYAR.code
        )
        self.assertEqual(inquire_tracking.price, 211794)
        self.assertEqual(inquire_tracking.sepulsa_product.type, SepulsaProductType.MOBILE)
        self.assertEqual(inquire_tracking.identity_number, '081234000001')
        self.assertEqual(inquire_tracking.other_data['customer_name'], 'S******')


class TestEwalletCategoryV2(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    def test_case_sepulsa_no_categories(self, is_applied_xfers, is_applied_ayc):
        is_applied_ayc.return_value = False
        is_applied_xfers.return_value = False

        response = self.client.get("/api/payment-point/v2/ewallet/category")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'][0],
            (
                "Saat ini produk dompet digital sedang tidak tersedia "
                "atau sedang bermasalah, mohon cek beberapa saat lagi"
            ),
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    def test_case_ayoconnect_no_categories(self, is_applied_xfers, is_applied_ayc):
        is_applied_ayc.return_value = False
        is_applied_xfers.return_value = False

        response = self.client.get("/api/payment-point/v2/ewallet/category")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'][0],
            (
                "Saat ini produk dompet digital sedang tidak tersedia "
                "atau sedang bermasalah, mohon cek beberapa saat lagi"
            ),
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    def test_case_ayoconnect_ok(self, is_applied_xfers, is_applied_ayc):
        """
        only ayoconnect is on
        """
        is_applied_ayc.return_value = True
        is_applied_xfers.return_value = False

        # duplicate, but should still works
        AYCProductFactory.ovo_100rb()
        AYCProductFactory.ovo_100rb()

        response = self.client.get("/api/payment-point/v2/ewallet/category")
        self.assertEqual(response.status_code, 200)

        expected_data = [
            {
                "category_name": "Ovo",
                "category_logo": settings.EWALLET_LOGO_STATIC_FILE_PATH + "ovo.png",
                "category_code": "OVO",
            }
        ]

        self.assertEqual(response.data['data'], expected_data)

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    def test_case_xfers_ok(self, is_applied_xfers, is_applied_ayc):
        is_applied_ayc.return_value = False
        is_applied_xfers.return_value = True

        XfersProductFactory.dana_400rb()
        XfersProductFactory.ovo_100rb()

        response = self.client.get("/api/payment-point/v2/ewallet/category")
        self.assertEqual(response.status_code, 200)

        expected_data = [
            {
                "category_name": "Dana",
                "category_logo": settings.EWALLET_LOGO_STATIC_FILE_PATH + "dana.png",
                "category_code": "DANA",
            },
            {
                "category_name": "Ovo",
                "category_logo": settings.EWALLET_LOGO_STATIC_FILE_PATH + "ovo.png",
                "category_code": "OVO",
            },
        ]

        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['category_name'], reverse=True),
            sorted(expected_data, key=lambda x: x['category_name'], reverse=True),
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    def test_case_xfers_ayoconnect_both_on(self, is_applied_xfers, is_applied_ayc):
        is_applied_ayc.return_value = True
        is_applied_xfers.return_value = True

        # case xfers and ayo dont overlap
        # ayoconnect
        ayoconnect_product = AYCProductFactory.ovo_100rb()
        XfersProductFactory.dana_400rb()

        response = self.client.get("/api/payment-point/v2/ewallet/category")
        self.assertEqual(response.status_code, 200)

        expected_data = [
            {
                "category_name": "Dana",
                "category_logo": settings.EWALLET_LOGO_STATIC_FILE_PATH + "dana.png",
                "category_code": "DANA",
            },
            {
                "category_name": "Ovo",
                "category_logo": settings.EWALLET_LOGO_STATIC_FILE_PATH + "ovo.png",
                "category_code": "OVO",
            },
        ]

        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['category_name'], reverse=True),
            sorted(expected_data, key=lambda x: x['category_name'], reverse=True),
        )

        # Case xfers & ayo overlap, show set
        XfersProductFactory.ovo_100rb(
            sepulsa_product=ayoconnect_product.sepulsa_product,
        )

        response = self.client.get("/api/payment-point/v2/ewallet/category")
        self.assertEqual(response.status_code, 200)

        # same result if overlap
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['category_name'], reverse=True),
            sorted(expected_data, key=lambda x: x['category_name'], reverse=True),
        )


class TestPaymentProductV2(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.available_limit = 1_000_000
        self.account_limit = AccountLimitFactory(
            account=self.account,
            available_limit=self.available_limit,
        )

        product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=product_lookup)

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.calculate_available_limit')
    def test_case_sepulsa_no_mobile_operator(
        self, mock_calculate_limit, mock_is_applied_ayc, mock_is_applied_xfers
    ):
        mock_calculate_limit.return_value = 1_000_000
        mock_is_applied_ayc.return_value = False
        mock_is_applied_xfers.return_value = False

        url = "/api/payment-point/v2/product"

        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": 'GoPay',
            "mobile_operator_id": -1,
        }
        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['errors'][0],
            "Data operator seluler tidak ditemukan",
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.calculate_available_limit')
    def test_case_sepulsa_ok(
        self, mock_calculate_limit, mock_is_applied_ayc, mock_is_applied_xfers
    ):
        mock_calculate_limit.return_value = 1_000_000
        mock_is_applied_ayc.return_value = False
        mock_is_applied_xfers.return_value = False

        # data
        dana = SepulsaProductFactory.dana_400rb()
        shopee = SepulsaProductFactory.shopeepay_20k()

        url = "/api/payment-point/v2/product"

        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": SepulsaProductCategory.DANA,
        }
        expected_data = [
            {
                "id": dana.id,
                "product_id": dana.product_id,
                "product_name": dana.product_name,
                "product_label": dana.product_label,
                "customer_price_regular": dana.customer_price_regular,
                "type": dana.type,
                "category": 'Dana',
            },
        ]
        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['id'], reverse=True),
            sorted(expected_data, key=lambda x: x['id'], reverse=True),
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.calculate_available_limit')
    def test_case_ayoconnect_ok(self, mock_cm, mock_is_applied_ayc, mock_is_applied_xfers):
        mock_cm.return_value = 1_000_000
        mock_is_applied_ayc.return_value = True
        mock_is_applied_xfers.return_value = False

        ayo_product_gopay = AYCProductFactory.gopay_500rb()
        xfers_product_gopay = XfersProductFactory.gopay_500rb(
            sepulsa_product=ayo_product_gopay.sepulsa_product,
        )

        url = "/api/payment-point/v2/product"

        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": SepulsaProductCategory.GOPAY,
        }
        expected_data = [
            {
                "id": ayo_product_gopay.sepulsa_id,
                "product_id": ayo_product_gopay.product_id,
                "product_name": ayo_product_gopay.product_name,
                "product_label": None,
                "customer_price_regular": ayo_product_gopay.customer_price_regular,
                "type": ayo_product_gopay.type,
                "category": "Gopay",
            },
        ]
        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['id'], reverse=True),
            sorted(expected_data, key=lambda x: x['id'], reverse=True),
        )

        # if AYOCONNECT has no active products, show active sepulsa_product
        ayo_product_gopay.is_active = False
        ayo_product_gopay.save()

        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": SepulsaProductCategory.GOPAY,
        }
        expected_data = [
            {
                "id": ayo_product_gopay.sepulsa_product.sepulsa_id,
                "product_id": ayo_product_gopay.sepulsa_product.product_id,
                "product_name": ayo_product_gopay.sepulsa_product.product_name,
                "product_label": None,
                "customer_price_regular": ayo_product_gopay.sepulsa_product.customer_price_regular,
                "type": ayo_product_gopay.sepulsa_product.type,
                "category": "Gopay",
            },
        ]
        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['id'], reverse=True),
            sorted(expected_data, key=lambda x: x['id'], reverse=True),
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.calculate_available_limit')
    def test_case_xfers_ok(self, mock_cm, mock_is_applied_ayc, mock_is_applied_xfers):
        mock_cm.return_value = 1_000_000
        mock_is_applied_ayc.return_value = False
        mock_is_applied_xfers.return_value = True

        ayo_product_gopay = AYCProductFactory.gopay_500rb()
        xfers_product_gopay = XfersProductFactory.gopay_500rb(
            sepulsa_product=ayo_product_gopay.sepulsa_product,
        )
        xfers_product_dana = XfersProductFactory.dana_400rb()

        url = "/api/payment-point/v2/product"

        # case GOPAY
        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": SepulsaProductCategory.GOPAY,
        }

        # ayo connect is off so no ayo connect
        expected_data = [
            {
                "id": xfers_product_gopay.sepulsa_id,
                "product_id": xfers_product_gopay.product_id,
                "product_name": xfers_product_gopay.product_name,
                "product_label": None,
                "customer_price_regular": xfers_product_gopay.customer_price_regular,
                "type": xfers_product_gopay.type,
                "category": "Gopay",
            },
        ]

        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['id'], reverse=True),
            sorted(expected_data, key=lambda x: x['id'], reverse=True),
        )

        # DANA category
        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": SepulsaProductCategory.DANA,
        }

        #
        expected_data = [
            {
                "id": xfers_product_dana.sepulsa_id,
                "product_id": xfers_product_dana.product_id,
                "product_name": xfers_product_dana.product_name,
                "product_label": None,
                "customer_price_regular": xfers_product_dana.customer_price_regular,
                "type": xfers_product_dana.type,
                "category": "Dana",
            },
        ]
        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['id'], reverse=True),
            sorted(expected_data, key=lambda x: x['id'], reverse=True),
        )

        # CASE xfers with no active dana products
        xfers_product_dana.is_active = False
        xfers_product_dana.save()

        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": SepulsaProductCategory.DANA,
        }

        #
        expected_data = [
            {
                "id": xfers_product_dana.sepulsa_product.sepulsa_id,
                "product_id": xfers_product_dana.sepulsa_product.product_id,
                "product_name": xfers_product_dana.sepulsa_product.product_name,
                "product_label": None,
                "customer_price_regular": xfers_product_dana.sepulsa_product.customer_price_regular,
                "type": xfers_product_dana.sepulsa_product.type,
                "category": "Dana",
            },
        ]
        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['id'], reverse=True),
            sorted(expected_data, key=lambda x: x['id'], reverse=True),
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.calculate_available_limit')
    def test_case_both_xfers_ayoconnect_on(
        self, mock_cm, mock_is_applied_ayc, mock_is_applied_xfers
    ):
        mock_cm.return_value = 1_000_000
        mock_is_applied_ayc.return_value = True
        mock_is_applied_xfers.return_value = True

        ayoconnect_gopay = AYCProductFactory.gopay_500rb()
        xfers_gopay = XfersProductFactory.dana_400rb()

        url = "/api/payment-point/v2/product"

        # case both have same gopay product, expect ayoconnect
        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": SepulsaProductCategory.GOPAY,
        }
        expected_data = [
            {
                "id": ayoconnect_gopay.sepulsa_id,
                "product_id": ayoconnect_gopay.product_id,
                "product_name": ayoconnect_gopay.product_name,
                "product_label": None,
                "customer_price_regular": ayoconnect_gopay.customer_price_regular,
                "type": ayoconnect_gopay.type,
                "category": "Gopay",
            },
        ]
        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['id'], reverse=True),
            sorted(expected_data, key=lambda x: x['id'], reverse=True),
        )

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.calculate_available_limit')
    def test_case_both_xfers_ayoconnect_off(
        self, mock_cm, mock_is_applied_ayc, mock_is_applied_xfers
    ):
        mock_cm.return_value = 1_000_000
        mock_is_applied_ayc.return_value = False
        mock_is_applied_xfers.return_value = False

        ayoconnect_gopay = AYCProductFactory.gopay_500rb()
        xfers_ovo = XfersProductFactory.dana_400rb()
        sepulsa_ovo = xfers_ovo.sepulsa_product

        url = "/api/payment-point/v2/product"

        # both off, => show sepulsa
        data = {
            "transaction_type_code": TransactionMethodCode.DOMPET_DIGITAL.code,
            "type": SepulsaProductType.EWALLET,
            "category": SepulsaProductCategory.DANA,
        }
        expected_data = [
            {
                "id": sepulsa_ovo.sepulsa_id,
                "product_id": sepulsa_ovo.product_id,
                "product_name": sepulsa_ovo.product_name,
                "product_label": sepulsa_ovo.product_label,
                "customer_price_regular": sepulsa_ovo.customer_price_regular,
                "type": sepulsa_ovo.type,
                "category": "Dana",  # because of capitalized()
            },
        ]
        response = self.client.get(
            path=url,
            data=data,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(response.data['data'], key=lambda x: x['id'], reverse=True),
            sorted(expected_data, key=lambda x: x['id'], reverse=True),
        )
