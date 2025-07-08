from django.test import TestCase
from factory import Iterator
from requests import ReadTimeout
from rest_framework.test import APIClient
from datetime import datetime
import mock

from factory import Iterator
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    SepulsaProductFactory,
    SepulsaTransactionFactory,
    MobileOperatorFactory,
    ProductLookupFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    ProductLineFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory
)
from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
    SepulsaMessage,
    InternetBillCategory,
)
from juloserver.payment_point.views.views_api_v2 import date_validation
from juloserver.julo.clients.sepulsa import JuloSepulsaClient
from juloserver.payment_point.services.internet_related import InternetBillService


class TestPaymentPointViews(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.sepulsa_product = SepulsaProductFactory(
            product_id='1',
            product_name='Token 20000',
            product_nominal=25000,
            product_label='Token 20000',
            product_desc='Token 20000',
            type=SepulsaProductType.ELECTRICITY,
            category=SepulsaProductCategory.ELECTRICITY_PREPAID,
            partner_price=20000,
            customer_price=26000,
            is_active=True,
            customer_price_regular=21000,
            is_not_blocked=True,
            admin_fee=1000,
            service_fee=2000,
            collection_fee=1000
        )
        self.mobile_operator = MobileOperatorFactory(
            name='XL',
            initial_numbers=['0817', '0812'],
            is_active=True,
        )
        self.product_lookup = ProductLookupFactory()
        self.product_line = ProductLineFactory(product_line_code=1)
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.product_line,
            max_duration=8,
            min_duration=1,
        )

    @mock.patch(
        'juloserver.payment_point.views.views_api_v1.'
        'get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_get_product(self, mock_get_credit_matrix_and_credit_matrix_product_line):
        mock_get_credit_matrix_and_credit_matrix_product_line.return_value = \
            self.credit_matrix, self.credit_matrix_product_line
        res = self.client.get('/api/payment-point/v1/product?type=electricity&category=prepaid')
        assert res.status_code == 200

    def test_get_mobile_operator(self):
        res = self.client.get('/api/payment-point/v1/mobile-operator?mobile_phone=08172567')
        assert res.status_code == 200

    @mock.patch(
        'juloserver.payment_point.views.views_api_v1.get_julo_sepulsa_loan_client'
    )
    def test_inquiry_electricity(self, mock_get_julo_sepulsa_client):
        self.sepulsa_product.type = SepulsaProductType.ELECTRICITY
        self.sepulsa_product.category = SepulsaProductCategory.ELECTRICITY_PREPAID
        self.sepulsa_product.save()
        mock_get_julo_sepulsa_client.return_value.get_account_electricity.return_value = dict(
            response_code='00',
            subscriber_id='012312',
            subscriber_name='budi',
            subscriber_segmentation='R1',
            admin_charge=10000
        )
        res = self.client.get(
            '/api/payment-point/v1/inquiry-electricity'
            '?customer_number=01428800700&product_id={}'.format(self.sepulsa_product.product_id)
        )
        assert res.status_code == 200

    @mock.patch(
        'juloserver.payment_point.views.views_api_v2.get_julo_sepulsa_loan_client'
    )
    def test_inquiry_electricity_postpaid(self, mock_get_julo_sepulsa_client):
        self.sepulsa_product.category = SepulsaProductCategory.ELECTRICITY_POSTPAID
        self.sepulsa_product.save()
        mock_get_julo_sepulsa_client.return_value.inquire_electricity_postpaid_information.return_value = (
            True,
            200,
            dict(
                response_code='00',
                subscriber_id='012312',
                subscriber_name='budi',
                subscriber_segmentation='R1',
                admin_charge=10000,
                blth_summary="DES09, JAN10, FEB10",
                amount=100000,
                power=900,
                bills=[
                    {
                        'due_date': '20200101'
                    },
                    {
                        'due_date': '20200202'
                    },
                    {
                        'due_date': '20200303'
                    },
                ]
            )
        )
        res = self.client.get(
            '/api/payment-point/v2/inquire/electricity/postpaid'
            '?customer_number=01428800700&product_id={}'.format(self.sepulsa_product.product_id)
        )

        assert res.status_code == 200

    @mock.patch(
        'juloserver.julo.clients.sepulsa.requests.post',
    )
    def test_inquiry_electricity_postpaid_fail(self, mock_inquire_electricity_postpaid_information):
        self.sepulsa_product.category = SepulsaProductCategory.ELECTRICITY_POSTPAID
        self.sepulsa_product.save()
        mock_inquire_electricity_postpaid_information.side_effect = ReadTimeout()

        res = self.client.get(
            '/api/payment-point/v2/inquire/electricity/postpaid'
            '?customer_number=01428800700&product_id={}'.format(self.sepulsa_product.product_id)
        )

        assert res.status_code == 400
        assert res.json()['errors'] == ['Terjadi kesalahan, coba lagi nanti']

    @mock.patch('juloserver.julo.clients.sepulsa.requests.post')
    def test_inquiry_electricity_postpaid_data_error(self, mock_get_julo_sepulsa_client):
        self.sepulsa_product.category = SepulsaProductCategory.ELECTRICITY_POSTPAID
        self.sepulsa_product.save()
        mock_get_julo_sepulsa_client.return_value.status_code = 406
        mock_get_julo_sepulsa_client.return_value.body = '406 Invalid parameter value'

        res = self.client.get(
            '/api/payment-point/v2/inquire/electricity/postpaid'
            '?customer_number=01428800700&product_id={}'.format(self.sepulsa_product.product_id)
        )

        assert res.status_code == 400
        assert res.json()['errors'] == ['Terjadi kesalahan, data tidak valid']

    @mock.patch('juloserver.julo.clients.sepulsa.requests.post')
    def test_inquiry_electricity_postpaid_product_closed_temporarily(
            self, mock_get_julo_sepulsa_client
    ):
        self.sepulsa_product.category = SepulsaProductCategory.ELECTRICITY_POSTPAID
        self.sepulsa_product.save()
        mock_get_julo_sepulsa_client.return_value.status_code = 450
        mock_get_julo_sepulsa_client.return_value.body = '450 Product Closed Temporarily'

        res = self.client.get(
            '/api/payment-point/v2/inquire/electricity/postpaid'
            '?customer_number=01428800700&product_id={}'.format(self.sepulsa_product.product_id)
        )

        assert res.status_code == 400
        assert res.json()['errors'] == ['Produk sedang diperbarui, silakan coba lagi nanti']

    @mock.patch(
        'juloserver.payment_point.views.views_api_v2.get_julo_sepulsa_loan_client'
    )
    def test_inquiry_bpjs(self, mock_get_julo_sepulsa_client):
        self.sepulsa_product.type = SepulsaProductType.BPJS
        self.sepulsa_product.category = SepulsaProductCategory.BPJS_KESEHATAN[0]
        self.sepulsa_product.save()
        mock_get_julo_sepulsa_client.return_value.inquire_bpjs.return_value = dict(
            response_code='00',
            premi='100000',
            name='budi',
        )
        res = self.client.get(
            '/api/payment-point/v2/inquire/bpjs'
            '?bpjs_number=01428800700&bpjs_times=1&product_id={}'.format(
                self.sepulsa_product.id)
        )

        assert res.status_code == 200

    @mock.patch('juloserver.payment_point.services.views_related.is_applied_xfers_switching_flow')
    @mock.patch('juloserver.payment_point.services.views_related.is_applied_ayc_switching_flow')
    def test_get_ewallet_category(self, mock_is_applied_ayc, mock_is_applied_xfers):
        mock_is_applied_ayc.return_value = False
        mock_is_applied_xfers.return_value = False

        self.sepulsa_product.type = SepulsaProductType.EWALLET
        self.sepulsa_product.category = SepulsaProductCategory.OVO
        self.sepulsa_product.save()
        res = self.client.get('/api/payment-point/v2/ewallet/category')

        assert res.status_code == 200

    @mock.patch(
        'juloserver.payment_point.views.views_api_v2.get_julo_sepulsa_loan_client'
    )
    def test_inquiry_mobile_postpaid(self, mock_get_julo_sepulsa_client):
        bill_amount = 100000
        self.sepulsa_product.type = SepulsaProductType.MOBILE
        self.sepulsa_product.category = SepulsaProductCategory.POSTPAID[0]
        self.sepulsa_product.operator = self.mobile_operator
        self.sepulsa_product.save()
        mock_get_julo_sepulsa_client.return_value.inquire_mobile_postpaid.return_value = dict(
            response_code='00',
            bill_amount=str(bill_amount),
            bill_periode='202001',
            customer_name='budi',
        )
        res = self.client.get(
            '/api/payment-point/v2/inquire/phone/postpaid'
            '?mobile_number=01428800700&product_id={}'.format(
                self.sepulsa_product.id)
        )
        assert res.status_code == 200

        # test include admin fee
        self.sepulsa_product.admin_fee = 2500
        self.sepulsa_product.save()

        res = self.client.get(
            '/api/payment-point/v2/inquire/phone/postpaid'
            '?mobile_number=01428800700&product_id={}'.format(
                self.sepulsa_product.id)
        )
        data = res.json()['data']
        assert data['price'] == bill_amount + self.sepulsa_product.admin_fee

    def test_date_validation(self):
        raw_date = '20170201'
        date = date_validation(raw_date)
        assert date == datetime(2017, 2, 1, 0, 0)
        raw_date = '01022017'
        date = date_validation(raw_date)
        assert date == datetime(2017, 2, 1, 0, 0)

    def test_validate_phone_number(self):
        # failed
        res = self.client.get(
            '/api/payment-point/v1/mobile-phone-validate?mobile_phone=0832'
        )
        assert res.json()['errors'][0] == 'Phone tidak valid'

        # success
        res = self.client.get(
            '/api/payment-point/v1/mobile-phone-validate?mobile_phone=083212332112'
        )
        assert res.status_code == 200

    def test_get_sepulsa_transaction_histories(self):
        sepulsa_product_1 = SepulsaProductFactory(
            product_name='Telkomsel Rp 50,000', product_nominal=50000, category='pulsa'
        )
        sepulsa_product_2 = SepulsaProductFactory(
            product_name='9 Product for test mobile pulsa test',
            product_nominal=100000,
            category='pulsa',
        )
        sepulsa_product_3 = SepulsaProductFactory(
            product_name='9 Product for test mobile paket data test',
            product_nominal=100000,
            category='paket_data'
        )
        self.sepulsa_transactions = list(
            SepulsaTransactionFactory.create_batch(
                6,
                customer=self.customer,
                id=Iterator([6, 5, 4, 3, 2, 1]),
                phone_number=Iterator(
                    [
                        '081220275465',
                        '081220275465',
                        '081220275465',
                        '081234567982',
                        '08123456789',
                        '081234567681',
                    ]
                ),
                transaction_status=Iterator(
                    ['success', 'success', 'success', 'success', 'failed', 'success']
                ),
                product=Iterator(
                    [
                        sepulsa_product_1,
                        sepulsa_product_2,
                        sepulsa_product_2,
                        sepulsa_product_2,
                        sepulsa_product_1,
                        sepulsa_product_2,
                    ]
                ),
            )
        )

        response = self.client.get('/api/payment-point/v1/pulsa-transaction-histories')
        #  item 3 duplicate, item 5 is failed transaction
        expected_response = [
            {
                "phone_number": "081220275465",
                "product_id": sepulsa_product_1.id,
                "product_name": "Telkomsel Rp 50,000",
                "mobile_operator_name": "XL",
                "nominal_amount": 50000,
            },
            {
                "phone_number": "081220275465",
                "product_id": sepulsa_product_2.id,
                "product_name": "9 Product for test mobile pulsa test",
                "mobile_operator_name": "XL",
                "nominal_amount": 100000,
            },
            {
                "phone_number": "081234567982",
                "product_id": sepulsa_product_2.id,
                "product_name": "9 Product for test mobile pulsa test",
                "mobile_operator_name": "XL",
                "nominal_amount": 100000,
            },
            {
                "phone_number": "081234567681",
                "product_id": sepulsa_product_2.id,
                "product_name": "9 Product for test mobile pulsa test",
                "mobile_operator_name": "XL",
                "nominal_amount": 100000,
            },
        ]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], expected_response)

        self.sepulsa_transactions = list(SepulsaTransactionFactory.create_batch(
            6,
            customer=self.customer,
            id=Iterator([
                12, 11, 10, 9, 8, 7
            ]),
            phone_number=Iterator([
                '081220275465', '081220275465', '081220275465', '081234567982', '08123456789',
                '081234567681'
            ]),
            transaction_status=Iterator([
                'success', 'success', 'success', 'success', 'failed', 'success'
            ]),
            product=sepulsa_product_3
        ))
        #  paket data
        response = self.client.get('/api/payment-point/v1/paket-data-transaction-histories')
        #  valid item phone 1, phone 4, phone 6, phone 2,3 duplicate, phone 5 transaction failed
        expected_response = [
            {
                "phone_number": "081220275465",
                "product_id": sepulsa_product_3.id,
                "product_name": "9 Product for test mobile paket data test",
                "mobile_operator_name": "XL",
                "nominal_amount": 100000
            },
            {
                "phone_number": "081234567982",
                "product_id": sepulsa_product_3.id,
                "product_name": "9 Product for test mobile paket data test",
                "mobile_operator_name": "XL",
                "nominal_amount": 100000
            },
            {
                "phone_number": "081234567681",
                "product_id": sepulsa_product_3.id,
                "product_name": "9 Product for test mobile paket data test",
                "mobile_operator_name": "XL",
                "nominal_amount": 100000
            }
        ]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], expected_response)

    @mock.patch('juloserver.payment_point.services.internet_related.get_julo_sepulsa_loan_client')
    def test_inquiry_internet_bill_product(self, mock_get_julo_loan_client):
        internet_category_endpoint = InternetBillService.inquiry_endpoints
        internet_response_data = {
            InternetBillCategory.TELKOM: {
                "product_type": "telkom",
                "id_pelanggan": "0218900001",
                "nama_pelanggan": "ROY GUNAWAN",
                "bulan_thn": "201611",
                "jumlah_bayar": "46500",
            },
            InternetBillCategory.POSTPAID_INTERNET: {
                "customer_id": "0218900001",
                "customer_name": "ROY GUNAWAN",
                "bill_period": "201611",
                "total_amount": "46500",
            },
        }
        product_id = 1
        for category in internet_category_endpoint:
            customer_number = '123321123'
            product_id += 1
            internet_product = SepulsaProductFactory(
                product_id=product_id,
                type=SepulsaProductType.INTERNET_BILL,
                category=category,
                is_active=True,
                is_not_blocked=True,
            )
            internet_bill = internet_response_data[category]
            mock_get_julo_loan_client.return_value.inquiry_internet_bill_info.return_value = (
                internet_bill,
                None,
            )
            # Product not found
            internet_product.is_active = False
            internet_product.save()
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )
            error_message = res.json()['errors']
            assert error_message == [SepulsaMessage.PRODUCT_NOT_FOUND]

            # Get internet bill successfully
            internet_product.is_active = True
            internet_product.save()
            expected_data = {
                'subscriber_id': '0218900001',
                'customer_name': 'ROY GUNAWAN',
                'price': '46500',
                'bill_period': ['11-2016'],
            }
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )
            data = res.json()['data']
            assert data == expected_data

            # Get failed response code 20
            error_message = "Ext: nomor telepon/idpel tidak terdaftar"
            response_data = {
                "trx_id": "",
                "rc": "20",
                "message": error_message,
                "status": False,
                "response_code": "20",
                "desc": "failed",
            }
            mock_get_julo_loan_client.return_value.inquiry_internet_bill_info.return_value = (
                response_data,
                error_message,
            )
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )

            assert [error_message] == res.json()['errors']

            # has been paid: 50
            error_message = "Gagal, tagihan sudah terbayar"
            response_data = {
                "trx_id": "",
                "rc": "50",
                "message": error_message,
                "status": False,
                "response_code": "50",
                "desc": "failed",
            }
            mock_get_julo_loan_client.return_value.inquiry_internet_bill_info.return_value = (
                response_data,
                error_message,
            )
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )
            assert [error_message] == res.json()['errors']

            # timeout: 23
            error_message = "Request timed out"
            response_data = {
                "trx_id": "",
                "rc": "23",
                "message": error_message,
                "status": False,
                "response_code": "23",
                "desc": "failed",
            }
            mock_get_julo_loan_client.return_value.inquiry_internet_bill_info.return_value = (
                response_data,
                error_message,
            )
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )
            assert [error_message] == res.json()['errors']

            # Payment over limit: 26
            error_message = "Payment Overlimit"
            response_data = {
                "trx_id": "",
                "rc": "26",
                "message": error_message,
                "status": False,
                "response_code": "26",
                "desc": "failed",
            }
            mock_get_julo_loan_client.return_value.inquiry_internet_bill_info.return_value = (
                response_data,
                error_message,
            )
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )
            assert [error_message] == res.json()['errors']

            # Closed temporary
            error_message = SepulsaMessage.PRODUCT_CLOSED_TEMPORARILY
            response_data = {
                "response_code": 450,
            }
            mock_get_julo_loan_client.return_value.inquiry_internet_bill_info.return_value = (
                response_data,
                error_message,
            )
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )
            assert [error_message] == res.json()['errors']

            # general error
            error_message = SepulsaMessage.INVALID
            response_data = {
                "response_code": '99',
            }
            mock_get_julo_loan_client.return_value.inquiry_internet_bill_info.return_value = (
                response_data,
                error_message,
            )
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )
            assert [error_message] == res.json()['errors']

            # other errors
            error_message = 'Error'
            mock_get_julo_loan_client.return_value.inquiry_internet_bill_info.return_value = (
                None,
                error_message,
            )
            res = self.client.get(
                '/api/payment-point/v1/inquiry-internet-bill?customer_number={}&product_id={}'.format(
                    customer_number, product_id
                )
            )
            assert [error_message] == res.json()['errors']

    @mock.patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.send_request')
    def test_inquiry_internet_bill_api(self, mock_api_call):
        sepulsa_client = JuloSepulsaClient("test", "test", "test")
        customer_number = '123321123'
        product_id = 82
        internet_category_endpoint = InternetBillService.inquiry_endpoints
        for category in internet_category_endpoint:
            endpoint = internet_category_endpoint[category]
            error_message = "Request timed out"
            response_data = {
                "trx_id": "",
                "rc": "23",
                "message": error_message,
                "status": False,
                "response_code": "23",
                "desc": "failed",
            }
            mock_api_call.return_value = response_data, None
            data, error = sepulsa_client.inquiry_internet_bill_info(
                customer_number, product_id, endpoint
            )
            assert error == error_message
            assert data != None

            error_message = "Ext: nomor telepon/idpel tidak terdaftar"
            response_data = {
                "trx_id": "",
                "rc": "20",
                "message": error_message,
                "status": False,
                "response_code": "20",
                "desc": "failed",
            }
            mock_api_call.return_value = response_data, None
            data, error = sepulsa_client.inquiry_internet_bill_info(
                customer_number, product_id, endpoint
            )
            assert error == error_message

            error_message = "Gagal, tagihan sudah terbayar"
            response_data = {
                "trx_id": "",
                "rc": "50",
                "message": error_message,
                "status": False,
                "response_code": "50",
                "desc": "failed",
            }
            mock_api_call.return_value = response_data, None
            data, error = sepulsa_client.inquiry_internet_bill_info(
                customer_number, product_id, endpoint
            )
            assert error == error_message

            error_message = "Payment Overlimit"
            response_data = {
                "trx_id": "",
                "rc": "26",
                "message": error_message,
                "status": False,
                "response_code": "26",
                "desc": "failed",
            }
            mock_api_call.return_value = response_data, None
            data, error = sepulsa_client.inquiry_internet_bill_info(
                customer_number, product_id, endpoint
            )
            assert error == error_message

            error_message = SepulsaMessage.PRODUCT_CLOSED_TEMPORARILY
            response_data = {
                "response_code": 450,
            }
            mock_api_call.return_value = response_data, None
            data, error = sepulsa_client.inquiry_internet_bill_info(
                customer_number, product_id, endpoint
            )
            assert error == error_message

            error_message = SepulsaMessage.INVALID
            response_data = {
                "response_code": '99',
            }
            mock_api_call.return_value = response_data, None
            data, error = sepulsa_client.inquiry_internet_bill_info(
                customer_number, product_id, endpoint
            )
            assert error == error_message

            error_message = 'Error'
            response_data = {
                "response_code": '99',
            }
            mock_api_call.return_value = response_data, error_message
            data, error = sepulsa_client.inquiry_internet_bill_info(
                customer_number, product_id, endpoint
            )
            assert error == error_message


class TestPhoneRecommendation(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.mobile_operator = MobileOperatorFactory.create_batch(
            4, name=Iterator(['viettel', 'mobifone', 'vinaphone', 'vinaphone']),
            is_active=True,
            initial_numbers=Iterator([
                ['0817', '0818', '0819', '0812', '0816'],
                ['0895', '0896', '0897', '0898', '0899'],
                ['0887', '0888', '0889', '0885', '0886'],
                ['0877', '0878', '0879', '0875', '0876'],
            ])
        )
        self.sepulsa_transaction = SepulsaTransactionFactory.create_batch(
            10, customer=self.customer,
            id=Iterator([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
            transaction_status=Iterator([
                'success', 'success', 'failed', 'success', 'pending',
                'failed', 'success', 'pending', 'success', 'success'
            ]),
            phone_number=Iterator([
                '0812345000001', '0812345000002', '0812345000003', '0812345000004', '0812345000005',
                '0812345000006', '0812345000007', '0812345000008', '0812345000009', '0812345000010'
            ])
        )

    def test_phone_recommend_phone_empty(self):
        for t in self.sepulsa_transaction:
            t.delete()

        response = self.client.get('/api/payment-point/v1/phone-recommendation')
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.json()['data']['phone_numbers'], [])

    def test_phone_recommend_mobile_operator_empty(self):
        invalid_phones = [
            '0912345000001', '0912345000002', '0912345000003', '0912345000004', '0912345000005',
            '0912345000006', '0912345000007', '0912345000008', '0912345000009', '0912345000010'
        ]
        for index, item in enumerate(self.sepulsa_transaction):
            item.update_safely(phone_number=invalid_phones[index])

        response = self.client.get('/api/payment-point/v1/phone-recommendation')
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.json()['data']['phone_numbers'], [])

    def test_duplicate_phone(self):
        SepulsaTransactionFactory.create_batch(
            5, id=Iterator([11, 12, 13, 14, 15]),
            customer=self.customer, transaction_status='success', phone_number='0812345000010'
        )
        returned_list = [
            '0812345000010', '0812345000009', '0812345000007', '0812345000004', '0812345000002'
        ]

        response = self.client.get('/api/payment-point/v1/phone-recommendation')
        result = response.json()['data']['phone_numbers']
        for index, item in enumerate(result):
            self.assertEquals(item['mobile_operator_name'], 'viettel')
            self.assertEquals(item['mobile_operator_id'], self.mobile_operator[0].id)
            self.assertEquals(item['phone_number'], returned_list[index])

    def test_phone_recommend_success(self):
        response = self.client.get('/api/payment-point/v1/phone-recommendation')
        self.assertEquals(response.status_code, 200)

        returned_list = [
            '0812345000010', '0812345000009', '0812345000007', '0812345000004', '0812345000002'
        ]

        result = response.json()['data']['phone_numbers']
        for index, item in enumerate(result):
            self.assertEquals(item['mobile_operator_name'], 'viettel')
            self.assertEquals(item['mobile_operator_id'], self.mobile_operator[0].id)
            self.assertEquals(item['phone_number'], returned_list[index])

        self.sepulsa_transaction[-1].update_safely(phone_number='0912345000001')
        response = self.client.get('/api/payment-point/v1/phone-recommendation')
        self.assertEquals(response.status_code, 200)

        returned_list = [
            '0812345000009', '0812345000007', '0812345000004', '0812345000002', '0812345000001'
        ]

        result = response.json()['data']['phone_numbers']
        for index, item in enumerate(result):
            self.assertEquals(item['mobile_operator_name'], 'viettel')
            self.assertEquals(item['mobile_operator_id'], self.mobile_operator[0].id)
            self.assertEquals(item['phone_number'], returned_list[index])
