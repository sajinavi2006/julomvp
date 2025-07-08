import mock
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status as rest_status

from juloserver.apiv2.tests.test_apiv2_services import ProductLineFactory
from juloserver.julo.models import StatusLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    SepulsaProductFactory,
    SepulsaTransactionFactory,
    CreditMatrixFactory,
    ProductLookupFactory,
    LoanFactory,
    FeatureSettingFactory,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountPropertyFactory,
)
from juloserver.payment_point.constants import (
    SepulsaProductCategory,
    SepulsaProductType,
)
from juloserver.payment_point.tests.factories import (
    TrainStationFactory,
    TrainTransactionFactory,
)
from juloserver.payment_point.utils import convert_string_to_datetime
from requests.exceptions import ReadTimeout
from juloserver.payment_point.constants import SepulsaMessage, TransactionMethodCode
from juloserver.payment_point.services.sepulsa import SepulsaLoanService
from juloserver.loan.services.loan_validate_with_sepulsa_payment_point_inquire import (
    is_valid_price_with_sepulsa_payment_point,
)
from juloserver.julo.constants import FeatureNameConst


class TestPaymentPointViewsV3(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.status_lookup = StatusLookup(status_code=420)
        self.account = AccountFactory(customer=self.customer, status=self.status_lookup)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_property = AccountPropertyFactory(account=self.account)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
        )
        self.sepulsa_product = SepulsaProductFactory(
            is_active=True,
            is_not_blocked=True,
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
        )
        self.train = TrainTransactionFactory(
            train_schedule_id="218201",
            reference_number="5758774642266152",
            departure_datetime=convert_string_to_datetime("2019-11-28 13:30", "%Y-%m-%d %H:%M"),
            arrival_datetime=convert_string_to_datetime("2019-11-29 04:27", "%Y-%m-%d %H:%M"),
            duration="14j57m",
            train_name="GAJAYANA",
            train_class="Eksekutif",
            train_subclass="A",
            adult_train_fare=555000,
            infant_train_fare=0,
        )
        self.loan = LoanFactory(
            loan_xid=1111,
            status=LoanStatusCodes.CURRENT,
        )
        self.sepulsa_transaction = SepulsaTransactionFactory(
            transaction_status='success', loan=self.loan
        )
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        )
        self.sepulsa_response = {
            "customer_id": "088899997001",
            "response_code": "00",
            "product": {
                "code": "332",
                "label": "Tiket KAI",
                "type": "train",
                "operator": "KAI",
            },
            "reference_number": "5758774642266152",
            "price": 562500,
            "data": {
                "booking_code": "5EW2NKI",
                "expired_at": 1473332820,
                "account": {"name": "John Hilmi", "email": "john.hilmi@gmail.com"},
                "bill_summary": {
                    "bill_count": 1,
                    "base_bill": 555000,
                    "admin_fee": 7500,
                },
                "bill_detail": {
                    "bill_usage": 555000,
                    "detail_bill_usage": {"ticket_fare": 555000, "additional_fee": 0},
                    "schedule": {
                        "schedule_id": "218201",
                        "departure_datetime": "2019-11-28 13:30",
                        "arrival_datetime": "2019-11-29 04:27",
                        "duration": "14j57m",
                        "transportation": {
                            "name": "GAJAYANA",
                            "class": "Eksekutif",
                            "subclass": "A",
                            "fare": {"adult": 555000, "infant": 0},
                        },
                        "station": {"depart": "ML", "destination": "GMR"},
                    },
                    "passenger": {
                        "number": {"adult": 1, "infant": 1},
                        "list": [
                            {
                                "type": "adult",
                                "title": "Mr",
                                "name": "John Hilmi",
                                "identity_number": "3881239912399001",
                            },
                            {
                                "type": "infant",
                                "title": "Miss",
                                "name": "Sandra Christy",
                                "identity_number": "2017123020171230",
                            },
                        ],
                    },
                    "seat": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
                },
            },
        }

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_station"
    )
    def test_success_inquire_train_station(self, mock_sepulsa_train_api):
        mock_sepulsa_train_api.return_value = (
            {
                "data": [
                    {"city": "Malang", "station_code": "ML", "station_name": "Malang"}
                ]
            },
            None,
        )
        res = self.client.get("/api/payment-point/v3/inquire/train/station?query=")
        api_response = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(api_response["data"]), 1)
        self.assertEqual(api_response["errors"], [])

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_station"
    )
    def test_failed_inquire_train_station(self, mock_sepulsa_train_api):
        mock_sepulsa_train_api.return_value = ([], "Force error")
        res = self.client.get("/api/payment-point/v3/inquire/train/station?query=")
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(api_response["data"])
        self.assertEqual(api_response["errors"], ["Force error"])

    def test_forbidden_endpoint(self):
        grab_product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application.product_line = grab_product_line
        self.application.save()
        res = self.client.post("/api/payment-point/v3/train/ticket")

        self.assertEqual(res.status_code, rest_status.HTTP_403_FORBIDDEN)

    @mock.patch(
        "juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line"
    )
    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_booking_train_ticket"
    )
    def test_success_booking_train_ticket(self, mock_book_train, mockcredit_matrix):
        # make train stations
        TrainStationFactory(code="ML")
        TrainStationFactory(code="GMR")

        product = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product)

        sepulsa_response = self.sepulsa_response
        mockcredit_matrix.return_value = (credit_matrix, None)
        mock_book_train.return_value = sepulsa_response, None
        data = {
            "customer_id": "088899997001",
            "reference_number": "5758774642266152",
            "data": {
                "schedule_id": "218201",
                "total_price": 1000,
                "account": {"name": "John Hilmi", "email": "john.hilmi@gmail.com"},
                "passenger": {
                    "number": {"adult": 1, "infant": 1},
                    "list": [
                        {
                            "type": "adult",
                            "title": "Mr",
                            "name": "John Hilmi",
                            "identity_number": "3881239912399000",
                        },
                        {
                            "type": "infant",
                            "title": "Miss",
                            "name": "Sandra Christy",
                            "identity_number": "2017123020171230",
                        },
                    ],
                },
            },
        }
        res = self.client.post(
            "/api/payment-point/v3/train/ticket",
            data=data,
            format="json",
        )
        self.assertEqual(res.status_code, rest_status.HTTP_200_OK)

    def test_product_failed_inquire_train_ticket(self):
        self.sepulsa_product.is_active = False
        self.sepulsa_product.is_not_blocked = False
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(api_response['data'])
        self.assertEqual(api_response['errors'], ['Produk tidak ditemukan'])

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_failed_inquire_train_ticket(self, mock_sepulsa_api_call):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = (None, "Force error")
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        print(api_response)
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(api_response['data'])
        self.assertEqual(api_response['errors'], ['Force error'])


    def test_product_failed_inquire_train_ticket(self):
        self.sepulsa_product.is_active = False
        self.sepulsa_product.is_not_blocked = False
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(api_response['data'])
        self.assertEqual(api_response['errors'], ['Produk tidak ditemukan'])

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_failed_inquire_train_ticket(self, mock_sepulsa_api_call):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = (None, "Force error")
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(api_response['data'])
        self.assertEqual(api_response['errors'], ['Force error'])

    @mock.patch('juloserver.julo.clients.sepulsa.requests')
    def test_api_failed_inquire_train_ticket_read_timeout(self, mock_requests):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        mock_requests.post.side_effect = ReadTimeout
        api_response, error = SepulsaLoanService().inquire_train_ticket({})
        self.assertEqual(api_response, {'response_code': '500'})

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_failed_inquire_train_ticket_read_timeout_response(self, mock_sepulsa_api_call):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = ({'response_code': '500'}, "error")
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(api_response['errors'], SepulsaMessage.READ_TIMEOUT_ERROR)

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_failed_inquire_train_ticket_product_closed_temporarily(self, mock_requests):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        mock_requests.return_value = ({'response_code': 450, "message": "failed"}, "error")
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(api_response['errors'], [SepulsaMessage.PRODUCT_CLOSED_TEMPORARILY])

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_failed_inquire_train_ticket_general_response(self, mock_sepulsa_api_call):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        mock_sepulsa_api_call.return_value = (
            {"message": "failed", "response_code": "99"},
            "Failed"
        )
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(api_response['errors'], SepulsaMessage.GENERAL_ERROR_TRAIN_TICKET)

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_route_not_found_inquire_train_ticket(self, mock_sepulsa_api_call):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = (
            {"message": "Data not found", "response_code": "50"},
            "Data not found"
        )
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(
            api_response['errors'],
            [
                "Tiket untuk Rute ini Tidak Ditemukan",
                "Coba ubah tanggal atau stasiun asal dan tujuannya, ya!"
            ]
        )

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_route_not_found_single_error_inquire_train_ticket(self, mock_sepulsa_api_call):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = (
            {"message": "Data not found", "response_code": "55"},
            "Data not found"
        )
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(api_response['errors'], ['Data not found'])

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_success_inquire_train_ticket(self, mock_sepulsa_api_call):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = (
            {
                "product": {
                    "code": "332",
                    "label": "Tiket KAI",
                    "type": "train",
                    "operator": "KAI"
                },
                "reference_number": "5758774642266152",
                "data": {
                    "station": {
                        "depart": "ML",
                        "destination": "GMR"
                    },
                    "passenger": {
                        "adult": 1,
                        "infant": 1
                    },
                    "schedule": [
                        {
                            "schedule_id": "218201",
                            "departure_datetime": "2019-11-28 13:30",
                            "arrival_datetime": "2019-11-29 04:27",
                            "duration": "14j57m",
                            "available_seat": 26,
                            "transportation": {
                            "name": "GAJAYANA",
                            "class": "Eksekutif",
                            "subclass": "A",
                            "fare": {
                                "adult": 555000,
                                "infant": 0
                            }
                            }
                        },
                        {
                            "schedule_id": "218206",
                            "departure_datetime": "2019-11-28 14:25",
                            "arrival_datetime": "2019-11-29 05:43",
                            "duration": "15j18m",
                            "available_seat": 7,
                            "transportation": {
                            "name": "BIMA",
                            "class": "Eksekutif",
                            "subclass": "I",
                            "fare": {
                                "adult": 480000,
                                "infant": 0
                            }
                            }
                        }
                    ],
                    "expired_at": 1473332820
                }
            },
            None
        )
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(api_response['data']['reference_number'], "5758774642266152")
        self.assertEqual(api_response['errors'], [])

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_api_success_inquire_train_ticket_class(self, mock_sepulsa_api_call):
        self.sepulsa_product.is_active = True
        self.sepulsa_product.is_not_blocked = True
        self.sepulsa_product.save()
        api_url = '/api/payment-point/v3/inquire/train/ticket'
        api_data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = (
            {
                "product": {
                    "code": "332",
                    "label": "Tiket KAI",
                    "type": "train",
                    "operator": "KAI"
                },
                "reference_number": "5758774642266152",
                "data": {
                    "station": {
                        "depart": "ML",
                        "destination": "GMR"
                    },
                    "passenger": {
                        "adult": 1,
                        "infant": 1
                    },
                    "schedule": [
                        {
                            "schedule_id": "218201",
                            "departure_datetime": "2019-11-28 13:30",
                            "arrival_datetime": "2019-11-29 04:27",
                            "duration": "14j57m",
                            "available_seat": 26,
                            "transportation": {
                            "name": "GAJAYANA",
                            "class": "K",
                            "subclass": "A",
                            "fare": {
                                "adult": 555000,
                                "infant": 0
                            }
                            }
                        },
                        {
                            "schedule_id": "218206",
                            "departure_datetime": "2019-11-28 14:25",
                            "arrival_datetime": "2019-11-29 05:43",
                            "duration": "15j18m",
                            "available_seat": 7,
                            "transportation": {
                            "name": "BIMA",
                            "class": "K",
                            "subclass": "I",
                            "fare": {
                                "adult": 480000,
                                "infant": 0
                            }
                            }
                        }
                    ],
                    "expired_at": 1473332820
                }
            },
            None
        )
        res = self.client.post(api_url, data=api_data)
        api_response = res.json()
        train_class = api_response['data']['schedule'][0]['transportation']['class']
        self.assertEqual(res.status_code, 200)
        self.assertEqual(train_class, "Ekonomi")
        self.assertEqual(api_response['errors'], [])

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_booking_train_ticket"
    )
    @mock.patch("juloserver.payment_point.views.views_api_v3.train_ticket_limit_validation")
    def test_api_error_booking_train_ticket(
        self, mock_book_train, mock_train_ticket_limit_validation
    ):
        # make train stations
        TrainStationFactory(code="ML")
        TrainStationFactory(code="GMR")
        mock_train_ticket_limit_validation.return_value = None

        sepulsa_response = {
            "customer_id": "088899997001",
            "response_code": "00",
            "product": {
                "code": "332",
                "label": "Tiket KAI",
                "type": "train",
                "operator": "KAI",
            },
            "reference_number": "5758774642266152",
            "price": 562500,
            "data": {
                "booking_code": "5EW2NKI",
                "expired_at": 1473332820,
                "account": {"name": "John Hilmi", "email": "john.hilmi@gmail.com"},
                "bill_summary": {
                    "bill_count": 1,
                    "base_bill": 555000,
                    "admin_fee": 7500,
                },
                "bill_detail": {
                    "bill_usage": 555000,
                    "detail_bill_usage": {"ticket_fare": 555000, "additional_fee": 0},
                    "schedule": {
                        "schedule_id": "218201",
                        "departure_datetime": "2019-11-28 13:30",
                        "arrival_datetime": "2019-11-29 04:27",
                        "duration": "14j57m",
                        "transportation": {
                            "name": "GAJAYANA",
                            "class": "Eksekutif",
                            "subclass": "A",
                            "fare": {"adult": 555000, "infant": 0},
                        },
                        "station": {"depart": "ML", "destination": "GMR"},
                    },
                    "passenger": {
                        "number": {"adult": 1, "infant": 1},
                        "list": [
                            {
                                "type": "adult",
                                "title": "Mr",
                                "name": "John Hilmi",
                                "identity_number": "38812399123990001",
                            },
                            {
                                "type": "infant",
                                "title": "Miss",
                                "name": "Sandra Christy",
                                "identity_number": "20171230",
                            },
                        ],
                    },
                    "seat": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
                },
            },
        }
        mock_book_train.return_value = sepulsa_response, "Force error"
        data = {
            "reference_number": "5758774642266152",
            "data": {
                "schedule_id": "218201",
                "account": {"name": "John Hilmi", "email": "john.hilmi@gmail.com"},
                "passenger": {
                    "number": {"adult": 1, "infant": 1},
                    "list": [
                        {
                            "type": "adult",
                            "title": "Mr",
                            "name": "John Hilmi",
                            "identity_number": "38812399123990001",
                        },
                        {
                            "type": "infant",
                            "title": "Miss",
                            "name": "Sandra Christy",
                            "identity_number": "20171230",
                        },
                    ],
                },
            },
        }
        res = self.client.post(
            "/api/payment-point/v3/train/ticket",
            data=data,
            format="json",
        )
        self.assertEqual(res.status_code, rest_status.HTTP_400_BAD_REQUEST)

    def test_failed_booking_train_ticket(self):
        self.sepulsa_product.is_active = False
        self.sepulsa_product.save()

        data = {
            "reference_number": "5758774642266152",
            "data": {
                "schedule_id": "218201",
                "account": {"name": "John Hilmi", "email": "john.hilmi@gmail.com"},
                "passenger": {
                    "number": {"adult": 1, "infant": 1},
                    "list": [
                        {
                            "type": "adult",
                            "title": "Mr",
                            "name": "John Hilmi",
                            "identity_number": "38812399123990001",
                        },
                        {
                            "type": "infant",
                            "title": "Miss",
                            "name": "Sandra Christy",
                            "identity_number": "20171230",
                        },
                    ],
                },
            },
        }
        res = self.client.post(
            "/api/payment-point/v3/train/ticket",
            data=data,
            format="json",
        )
        self.assertEqual(res.status_code, rest_status.HTTP_400_BAD_REQUEST)

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket_seat"
    )
    def test_api_train_ticket_passenger_seat(self, mock_book_train):
        TrainStationFactory(
            is_popular_station=True,
            code="ML",
            city="Malang",
            name="Malang",
        )
        SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
        )

        sepulsa_response = {
            "response_code": "00",
            "product": {"code": "332", "label": "Tiket KAI", "type": "train", "operator": "KAI"},
            "reference_number": "5758774642266152",
            "data": {
                "station": {"depart": "ML", "destination": "ML"},
                "date": "2019-11-28",
                "schedule_id": "218201",
                "seat": [
                    {
                        "wagon": "1",
                        "list": [
                            {"row": "1", "column": "A", "class": "A", "is_filled": False},
                            {"row": "3", "column": "C", "class": "A", "is_filled": True},
                        ],
                    }
                ],
            },
        }
        mock_book_train.return_value = sepulsa_response, None
        data = {"reference_number": "5758774642266152", "schedule_id": "218201"}
        res = self.client.post(
            "/api/payment-point/v3/train/passenger/seat",
            data=data,
            format="json",
        )
        api_response = res.json()
        self.assertEqual(res.status_code, rest_status.HTTP_200_OK)

        mock_book_train.return_value = sepulsa_response, None
        data = {"reference_number": "5758774642266152", "schedule_id": "2182"}
        res = self.client.post(
            "/api/payment-point/v3/train/passenger/seat",
            data=data,
            format="json",
        )
        self.assertEqual(res.status_code, rest_status.HTTP_400_BAD_REQUEST)

        # Sepulsa responds general code
        response_api = {
            "response_code": "99",
            "message": "Failed"
        }
        mock_book_train.return_value = response_api, None
        data = {"reference_number": "5758774642266152", "schedule_id": "2182"}
        res = self.client.post(
            "/api/payment-point/v3/train/passenger/seat",
            data=data,
            format="json",
        )
        data = res.json()
        assert res.status_code == rest_status.HTTP_400_BAD_REQUEST
        assert data['errors'] == SepulsaMessage.GENERAL_ERROR_TRAIN_TICKET

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_change_seats"
    )
    def test_api_train_ticket_change_passenger_seat(self, mock_book_train):
        self.train = TrainStationFactory(
            is_popular_station=True,
            code="ML",
            city="Malang",
            name="Malang",
        )

        SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
        )

        data = {
            "customer_id": "088899997001",
            "reference_number": "5758774642266152",
            "data": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
        }

        sepulsa_response = {
            "product_code": "332",
            "customer_id": "088899997001",
            "response_code": "00",
            "reference_number": "5758774642266152",
            "data": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
        }
        mock_book_train.return_value = sepulsa_response, None
        res = self.client.post(
            "/api/payment-point/v3/train/change/seat",
            data=data,
            format="json",
        )
        self.assertEqual(res.status_code, rest_status.HTTP_200_OK)

        mock_book_train.return_value = sepulsa_response, None
        data = {
            "customer_id": "088899997001",
            "reference_number": "57828",
            "data": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
        }
        res = self.client.post(
            "/api/payment-point/v3/train/passenger/seat",
            data=data,
            format="json",
        )
        self.assertEqual(res.status_code, rest_status.HTTP_400_BAD_REQUEST)

    def test_api_train_ticket_order_history(self):
        TrainStationFactory(
            id=1,
            is_popular_station=True,
            code="ML",
            city="Malang",
            name="Malang",
        )

        TrainTransactionFactory(
            depart_station_id=1,
            destination_station_id=1,
            account_email='john.hilmi@gmail.com',
            is_round_trip=True,
            customer=self.customer,
            sepulsa_transaction=self.sepulsa_transaction,
            departure_datetime=convert_string_to_datetime("2019-11-28 13:30", "%Y-%m-%d %H:%M"),
            arrival_datetime=convert_string_to_datetime("2019-11-29 04:27", "%Y-%m-%d %H:%M"),
        )
        res = self.client.get("/api/payment-point/v3/train/transaction/history")
        self.assertEqual(res.status_code, rest_status.HTTP_200_OK)

    def test_api_train_transaction_booking_info(self):
        TrainStationFactory(
            id=1,
            is_popular_station=True,
            code="ML",
            city="Malang",
            name="Malang",
        )

        TrainTransactionFactory(
            depart_station_id=1,
            destination_station_id=1,
            account_email='john.hilmi@gmail.com',
            is_round_trip=True,
            customer=self.customer,
            sepulsa_transaction=self.sepulsa_transaction,
            booking_code='1222333445',
            departure_datetime=convert_string_to_datetime("2019-11-28 13:30", "%Y-%m-%d %H:%M"),
            arrival_datetime=convert_string_to_datetime("2019-11-29 04:27", "%Y-%m-%d %H:%M"),
        )
        res = self.client.get("/api/payment-point/v3/train/booking/info/{}/".format(2222))
        self.assertEqual(res.status_code, rest_status.HTTP_400_BAD_REQUEST)

        TrainTransactionFactory(
            depart_station_id=1,
            destination_station_id=1,
            account_email='john.hilmi@gmail.com',
            is_round_trip=True,
            customer=self.customer,
            sepulsa_transaction=self.sepulsa_transaction,
            booking_code='1a2c2d23345',
            departure_datetime=convert_string_to_datetime("2019-11-28 13:30", "%Y-%m-%d %H:%M"),
            arrival_datetime=convert_string_to_datetime("2019-11-29 04:27", "%Y-%m-%d %H:%M"),
        )
        res = self.client.get("/api/payment-point/v3/train/info/{}/".format(self.loan.loan_xid))
        self.assertEqual(res.status_code, rest_status.HTTP_200_OK)

    @mock.patch('juloserver.julo.clients.sepulsa.requests')
    def test_sepulsa_service_read_timeout_request(self, mock_requests):
        mock_requests.post.side_effect = ReadTimeout
        mock_requests.get.side_effect = ReadTimeout
        sepulsa_service = SepulsaLoanService()
        api_response, error = sepulsa_service.inquire_train_station()
        assert error == SepulsaMessage.READ_TIMEOUT_ERROR

        api_response, error =sepulsa_service.inquire_booking_train_ticket({})
        assert error == SepulsaMessage.READ_TIMEOUT_ERROR

        api_response, error = sepulsa_service.get_train_transaction_detail(1)
        assert error == SepulsaMessage.READ_TIMEOUT_ERROR

        api_response, error = sepulsa_service.inquire_pdam_operator({})
        assert error == SepulsaMessage.READ_TIMEOUT_ERROR

        api_response, error = sepulsa_service.inquire_train_ticket_seat({})
        assert error == SepulsaMessage.READ_TIMEOUT_ERROR

        api_response, error = sepulsa_service.inquire_train_change_seats({})
        assert error == SepulsaMessage.READ_TIMEOUT_ERROR

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_station"
    )
    def test_success_inquire_train_station_read_timeout(self, mock_sepulsa_train_api):
        mock_sepulsa_train_api.return_value = {"response_code": "500"}, SepulsaMessage.READ_TIMEOUT_ERROR
        res = self.client.get("/api/payment-point/v3/inquire/train/station?query=")
        assert res.status_code == 400
        assert res.json()["errors"] == SepulsaMessage.READ_TIMEOUT_ERROR

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_booking_train_ticket"
    )
    def test_inquire_train_ticket_read_timeout(self, mock_sepulsa_train_api):
        mock_sepulsa_train_api.return_value = {"response_code": "500"}, SepulsaMessage.READ_TIMEOUT_ERROR
        data = {
            "customer_id": "088899997001",
            "reference_number": "5758774642266152",
            "data": {
                "schedule_id": "218201",
                "total_price": 1000,
                "account": {"name": "John Hilmi", "email": "john.hilmi@gmail.com"},
                "passenger": {
                    "number": {"adult": 1, "infant": 1},
                    "list": [
                        {
                            "type": "adult",
                            "title": "Mr",
                            "name": "John Hilmi",
                            "identity_number": "3881239912399000",
                        },
                        {
                            "type": "infant",
                            "title": "Miss",
                            "name": "Sandra Christy",
                            "identity_number": "2017123020171230",
                        },
                    ],
                },
            },
        }
        res = self.client.post(
            "/api/payment-point/v3/train/ticket",
            data=data,
            format="json",
        )
        assert res.status_code == 400
        assert res.json()["errors"] == SepulsaMessage.READ_TIMEOUT_ERROR

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket_seat"
    )
    def test_train_passenger_seat_read_timeout(self, mock_sepulsa_train_api):
        mock_sepulsa_train_api.return_value = {"response_code": "500"}, SepulsaMessage.READ_TIMEOUT_ERROR
        data = {"reference_number": "5758774642266152", "schedule_id": "218201"}
        res = self.client.post(
            "/api/payment-point/v3/train/passenger/seat",
            data=data,
            format="json",
        )
        assert res.status_code == 400
        assert res.json()["errors"] == SepulsaMessage.READ_TIMEOUT_ERROR

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_change_seats"
    )
    def test_train_change_seat_read_timeout(self, mock_sepulsa_train_api):
        mock_sepulsa_train_api.return_value = {"response_code": "500"}, SepulsaMessage.READ_TIMEOUT_ERROR
        data = {
            "customer_id": "088899997001",
            "reference_number": "5758774642266152",
            "data": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
        }
        res = self.client.post(
            "/api/payment-point/v3/train/change/seat",
            data=data,
            format="json",
        )
        assert res.status_code == 400
        assert res.json()["errors"] == SepulsaMessage.READ_TIMEOUT_ERROR

    @mock.patch(
        "juloserver.loan.services.loan_related.get_credit_matrix_and_credit_matrix_product_line"
    )
    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_booking_train_ticket"
    )
    def test_success_booking_train_ticket_with_validate_loan_amount(
        self, mock_book_train, mockcredit_matrix):
        # make train stations
        TrainStationFactory(code="ML")
        TrainStationFactory(code="GMR")

        product = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product)
        sepulsa_response = self.sepulsa_response
        price = sepulsa_response['price']
        mockcredit_matrix.return_value = (credit_matrix, None)
        mock_book_train.return_value = sepulsa_response, None
        data = {
            "customer_id": "088899997001",
            "reference_number": "5758774642266152",
            "data": {
                "schedule_id": "218201",
                "total_price": 1000,
                "account": {"name": "John Hilmi", "email": "john.hilmi@gmail.com"},
                "passenger": {
                    "number": {"adult": 1, "infant": 1},
                    "list": [
                        {
                            "type": "adult",
                            "title": "Mr",
                            "name": "John Hilmi",
                            "identity_number": "3881239912399000",
                        },
                        {
                            "type": "infant",
                            "title": "Miss",
                            "name": "Sandra Christy",
                            "identity_number": "2017123020171230",
                        },
                    ],
                },
            },
        }
        res = self.client.post(
            "/api/payment-point/v3/train/ticket",
            data=data,
            format="json",
        )
        self.assertEqual(res.status_code, rest_status.HTTP_200_OK)

        # Create Loan
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account, transaction_method_id=TransactionMethodCode.TRAIN_TICKET.code, price=price, inquire_tracking_id=None, payment_point_product_id=None
        )
        assert result == True

        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account, transaction_method_id=TransactionMethodCode.TRAIN_TICKET.code, price=price + 10, inquire_tracking_id=None, payment_point_product_id=None
        )
        assert result == False
