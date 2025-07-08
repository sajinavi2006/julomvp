import mock
from datetime import datetime

from django.utils import timezone
from django.test.testcases import TestCase

from juloserver.julo.constants import MobileFeatureNameConst
from juloserver.julo.tests.factories import (
    SepulsaProductFactory,
    AuthUserFactory,
    CustomerFactory,
    SepulsaTransactionFactory,
    CreditMatrixFactory,
    ProductLookupFactory,
    MobileFeatureSettingFactory,
    LoanFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.payment_point.constants import (
    ErrorMessage,
    TransactionMethodCode,
)

from juloserver.payment_point.tests.factories import (
    TrainStationFactory,
    TrainTransactionFactory,
)
from juloserver.payment_point.services.sepulsa import SepulsaLoanService
from juloserver.payment_point.utils import (
    reformat_train_duration,
    convert_string_to_datetime,
)
from juloserver.payment_point.services.train_related import (
    get_train_station,
    get_train_ticket,
    prepare_data_from_booking_response,
    train_ticket_passenger_seat,
    get_train_transaction_history,
    train_ticket_change_passenger_seat,
    get_train_transaction_booking_info,
    train_ticket_limit_validation,
    get_train_ticket_whitelist_feature,
    is_train_ticket_whitelist_user,
)
from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
)


class TestTrainRelatedServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(id=123123)
        self.train = TrainStationFactory(is_popular_station=True)
        self.sepulsa_product = SepulsaProductFactory(
            is_active=True,
            is_not_blocked=True,
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
            booking_code="FactoryBookingCode",
        )
        self.available_limit = 1000000
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.account_limt = AccountLimitFactory(
            account=self.account, available_limit=self.available_limit
        )
        self.loan = LoanFactory(
            loan_xid=1111,
            status=LoanStatusCodes.CURRENT,
        )
        self.sepulsa_transaction = SepulsaTransactionFactory(
            transaction_status='success', loan=self.loan
        )

    @mock.patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.send_request')
    def test_inquire_train_station(self, mock_api_call):
        sepulsa_client = SepulsaLoanService()
        mock_api_call.return_value = None
        self.assertIsNone(sepulsa_client.inquire_train_station())

    @mock.patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.send_request')
    def test_inquire_train_ticket(self, mock_api_call):
        sepulsa_client = SepulsaLoanService()
        mock_api_call.return_value = None
        self.assertIsNone(sepulsa_client.inquire_train_ticket(None))

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_station"
    )
    def test_get_train_station(self, mock_sepulsa_train_api):
        stations, error = get_train_station("")
        self.assertEqual(stations[0]["station_code"], "FactoryCode")
        self.assertIsNone(error)

        stations, error = get_train_station("a")
        self.assertEqual(stations[0]["station_code"], "FactoryCode")
        self.assertIsNone(error)

        self.train.is_popular_station = False
        self.train.save()
        mock_sepulsa_train_api.return_value = ([], "Error")
        stations, error = get_train_station("Jakarta")
        self.assertEqual(stations, [])
        self.assertEqual(error, "Error")

        mock_sepulsa_train_api.return_value = (
            {
                "data": [
                    {"city": "Malang", "station_code": "ML", "station_name": "Malang"}
                ]
            },
            None,
        )
        stations, error = get_train_station("ala")
        self.assertEqual(stations[0]["station_code"], "ML")
        self.assertIsNone(error)

        stations, error = get_train_station("GMR")
        self.assertEqual(stations, [])
        self.assertEqual(error, "Stasiun tidak ditemukan")

    def test_prepare_data_from_booking_response(self):
        api_response = {
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

        res = prepare_data_from_booking_response(api_response)
        departure_datetime = timezone.localtime(
            datetime.strptime("2019-11-28 13:30", "%Y-%m-%d %H:%M")
        )
        arrival_datetime = timezone.localtime(
            datetime.strptime("2019-11-29 04:27", "%Y-%m-%d %H:%M")
        )
        expected_res = dict(
            depart_station="ML",
            destination_station="GMR",
            adult=1,
            infant=1,
            account_email="john.hilmi@gmail.com",
            account_mobile_phone="088899997001",
            reference_number="5758774642266152",
            expired_at=1473332820,
            train_schedule_id="218201",
            departure_datetime=departure_datetime,
            arrival_datetime=arrival_datetime,
            duration="14j57m",
            train_name="GAJAYANA",
            train_class="Eksekutif",
            train_subclass="A",
            adult_train_fare=555000,
            infant_train_fare=0,
            booking_code="5EW2NKI",
            price=562500,
            admin_fee=7500,
        )
        self.assertEqual(res, expected_res)

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_get_train_ticket(self, mock_sepulsa_api_call):
        sepulsa_product = SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
        )
        data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        data_mock = {
            "station": {
                "depart": "ML",
                "destination": "GMR"
            },
            "passenger": {
                "adult": 1,
                "infant": 0
             },
            "expired_at": 1473332820
        }
        mock_sepulsa_api_call.return_value = ({"data": data_mock}, None)
        response, error = get_train_ticket(data, sepulsa_product)
        self.assertEqual(response['schedule'], [])

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_get_train_ticket(self, mock_sepulsa_api_call):
        sepulsa_product = SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
        )
        data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = ({"response_code": "50", "message": "Timeout"}, None)
        response, error = get_train_ticket(data, sepulsa_product)
        self.assertEqual(response, {"response_code": "50", "message": "Timeout"})
        self.assertEqual(error, 'Timeout')

    def test_reformat_train_duration(self):
        self.assertEqual(reformat_train_duration('14'), 0)
        self.assertEqual(reformat_train_duration('14j14j'), 0)
        self.assertEqual(reformat_train_duration('1j1m1m'), 3600)

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_get_train_ticket(self, mock_sepulsa_api_call):
        sepulsa_product = SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
        )
        data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = ({"response_code": "50", "message": "Timeout"}, None)
        response, error = get_train_ticket(data, sepulsa_product)
        self.assertEqual(response, {"response_code": "50", "message": "Timeout"})
        self.assertEqual(error, 'Timeout')

    def test_reformat_train_duration(self):
        self.assertEqual(reformat_train_duration('14'), 0)
        self.assertEqual(reformat_train_duration('14j14j'), 0)
        self.assertEqual(reformat_train_duration('1j1m1m'), 3600)

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_get_train_ticket(self, mock_sepulsa_api_call):
        sepulsa_product = SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
        )
        data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = ({"response_code": "50", "message": "Timeout"}, None)
        response, error = get_train_ticket(data, sepulsa_product)
        self.assertEqual(response, {"response_code": "50", "message": "Timeout"})
        self.assertEqual(error, 'Timeout')

    def test_reformat_train_duration(self):
        self.assertEqual(reformat_train_duration('14'), 0)
        self.assertEqual(reformat_train_duration('14j14j'), 0)
        self.assertEqual(reformat_train_duration('1j1m1m'), 3600)

    @mock.patch('juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket')
    def test_get_train_ticket(self, mock_sepulsa_api_call):
        sepulsa_product = SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
        )
        data = {
            "depart": "ML", "destination": "GMR", "date": "2022-10-10", "adult": "1", "infant": "0",
        }
        mock_sepulsa_api_call.return_value = ({"response_code": "50", "message": "Timeout"}, None)
        response, error = get_train_ticket(data, sepulsa_product)
        self.assertEqual(response, {"response_code": "50", "message": "Timeout"})
        self.assertEqual(error, 'Timeout')

    def test_reformat_train_duration(self):
        self.assertEqual(reformat_train_duration('14'), 0)
        self.assertEqual(reformat_train_duration('14j14j'), 0)
        self.assertEqual(reformat_train_duration('1j1m1m'), 3600)

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_ticket_seat"
    )
    def test_train_ticket_passenger_seat(self, mock_sepulsa_api_call):
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
            "product_code": "332",
            "reference_number": "5758774642266152",
            "schedule_id": "218201",
        }

        mock_sepulsa_api_call.return_value = (
            {"response_code": "50", "message": "Timeout"},
            'Timeout',
        )
        response, error = train_ticket_passenger_seat(data)
        self.assertEqual(response, {"response_code": "50", "message": "Timeout"})
        self.assertEqual(error, 'Timeout')

        mock_sepulsa_api_call.return_value = (
            {
                "response_code": "00",
                "product": {
                    "code": "332",
                    "label": "Tiket KAI",
                    "type": "train",
                    "operator": "KAI",
                },
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
            },
            None,
        )
        data = {"product_code": "332", "reference_number": "5758774642266152", "schedule_id": "21"}

        response, error = train_ticket_passenger_seat(data)
        self.assertIsNone(response)
        self.assertEqual(error, 'Train transaction not found')

        data = {
            "product_code": "332",
            "reference_number": "5758774642266152",
            "schedule_id": "218201",
        }

        response, error = train_ticket_passenger_seat(data)
        self.assertEqual(response["adult_price"], 555000)
        self.assertIsNone(error)

        mock_sepulsa_api_call.return_value = (
            {
                "response_code": "00",
                "product": {
                    "code": "332",
                    "label": "Tiket KAI",
                    "type": "train",
                    "operator": "KAI",
                },
                "reference_number": "5758774642266152",
                "data": {
                    "station": {"depart": "JL", "destination": "ML"},
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
            },
            None,
        )

        response, error = train_ticket_passenger_seat(data)
        self.assertIsNone(response)
        self.assertEqual(error, 'Depart station not found')

        mock_sepulsa_api_call.return_value = (
            {
                "response_code": "00",
                "product": {
                    "code": "332",
                    "label": "Tiket KAI",
                    "type": "train",
                    "operator": "KAI",
                },
                "reference_number": "5758774642266152",
                "data": {
                    "station": {"depart": "ML", "destination": "JL"},
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
            },
            None,
        )

        response, error = train_ticket_passenger_seat(data)
        self.assertIsNone(response)
        self.assertEqual(error, 'Destination station not found')

        # Responding general code == 99
        response_api = {
            "response_code": "99",
            "message": "Failed"
        }
        mock_sepulsa_api_call.return_value = (response_api, None)
        response, error = train_ticket_passenger_seat(data)
        assert response == response_api
        assert error == None

    @mock.patch(
        "juloserver.payment_point.services.sepulsa.SepulsaLoanService.inquire_train_change_seats"
    )
    def test_train_ticket_change_passenger_seat(self, mock_sepulsa_api_call):
        TrainStationFactory(
            is_popular_station=True,
            code="ML",
            city="Malang",
            name="Malang",
        )

        data = {
            "customer_id": "088899997001",
            "product_code": "332",
            "reference_number": "5758774642266152",
            "schedule_id": "218201",
            "data": [{"wagon": "1","list": [{"row": "1", "column": "A"}]}]
        }

        mock_sepulsa_api_call.return_value = (
            {"response_code": "50", "message": "Timeout"},
            'Timeout',
        )
        response, error = train_ticket_change_passenger_seat(data)
        self.assertEqual(response, {"response_code": "50", "message": "Timeout"})

        mock_sepulsa_api_call.return_value = (
            {
                "product_code": "332",
                "customer_id": "088899997001",
                "response_code": "00",
                "reference_number": "5758774642266152",
                "data": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
            },
            None,
        )
        data_respon = {
            "product_code": "332",
            "customer_id": "088899997001",
            "response_code": "00",
            "reference_number": "5758774642266152",
            "data": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
        }
        response, error = train_ticket_change_passenger_seat(data)
        self.assertEqual(response['customer_id'], "088899997001")

        data = {
            "customer_id": "088899997001",
            "product_code": "332",
            "reference_number": "1111111",
            "schedule_id": "218201",
            "data": [{"wagon": "1", "list": [{"row": "1", "column": "A"}]}],
        }

        response, error = train_ticket_change_passenger_seat(data)
        self.assertIsNone(response)
        self.assertEqual(error, 'Train transaction not found')

    def test_train_transaction_history(self):
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
            customer=CustomerFactory(user=AuthUserFactory(id=292)),
            sepulsa_transaction=self.sepulsa_transaction,
            departure_datetime=convert_string_to_datetime("2019-11-28 13:30", "%Y-%m-%d %H:%M"),
            arrival_datetime=convert_string_to_datetime("2019-11-29 04:27", "%Y-%m-%d %H:%M"),
        )

        response, error = get_train_transaction_history(self.customer)
        self.assertEqual(error, "Train transaction not found")

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

        response, error = get_train_transaction_history(self.customer)
        self.assertEqual(response[0]['depart_station'], 'Malang (ML)')
        self.assertEqual(error, None)

    def test_get_train_ticket_whitelist_feature(self):
        self.assertIsNone(get_train_ticket_whitelist_feature())

    def test_is_train_ticket_whitelist_user(self):
        feature_setting = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.TRANSACTION_METHOD_WHITELIST,
            is_active=False,
            parameters={
                TransactionMethodCode.TRAIN_TICKET.name: {"application_ids": []},
            },
        )

        self.assertEqual(is_train_ticket_whitelist_user(12345), True)
        self.assertEqual(is_train_ticket_whitelist_user(12345, feature_setting), False)

    def test_get_train_transaction_booking_info(self):
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
            customer=CustomerFactory(user=AuthUserFactory(id=292)),
            sepulsa_transaction=self.sepulsa_transaction,
            booking_code='1222333445',
            departure_datetime=convert_string_to_datetime("2019-11-28 13:30", "%Y-%m-%d %H:%M"),
            arrival_datetime=convert_string_to_datetime("2019-11-29 04:27", "%Y-%m-%d %H:%M"),
        )

        response, error = get_train_transaction_booking_info(loan_xid=2222, user_id=292)
        self.assertEqual(error, "Loan not found")

        train_ticket_trans = TrainTransactionFactory(
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
        train_ticket_trans.save()
        response, error = get_train_transaction_booking_info(
            loan_xid=self.loan.loan_xid, user_id=292
        )
        self.assertEqual(response['booking_code'], '1222333445')
        self.assertEqual(error, None)

        # fail user not accessing their own data
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

        response, error = get_train_transaction_booking_info(loan_xid=self.loan.loan_xid, user_id=0)
        self.assertEqual(error, "Train transaction not found")

    @mock.patch(
        'juloserver.payment_point.services.train_related.get_credit_matrix_and_credit_matrix_product_line'
    )
    def test_train_ticket_limit_validation(self, mockcredit_matrix):
        sepulsa_product = SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
            product_nominal=1000,
        )
        product = ProductLookupFactory()
        credit_matrix = CreditMatrixFactory(product=product)
        data = {
            "customer_id": "088899997001",
            "reference_number": "5758774642266152",
            "data": {
                "schedule_id": "218201",
                "total_price": 1000,
            },
        }
        mockcredit_matrix.return_value = (credit_matrix, None)

        validation_error = train_ticket_limit_validation(self.customer, sepulsa_product, data)
        self.assertEqual(validation_error, None)

        credit_matrix = CreditMatrixFactory(product=None)
        mockcredit_matrix.return_value = (credit_matrix, None)
        validation_error = train_ticket_limit_validation(self.customer, sepulsa_product, data)
        self.assertEqual(validation_error, ErrorMessage.NOT_ELIGIBLE_FOR_THE_TRANSACTION)

        data = {
            "customer_id": "088899997001",
            "reference_number": "5758774642266152",
            "data": {
                "schedule_id": "218201",
                "total_price": 1000000000,
            },
        }
        sepulsa_product = SepulsaProductFactory(
            product_id='332',
            product_name='tiket',
            type=SepulsaProductType.TRAIN_TICKET,
            category=SepulsaProductCategory.TRAIN_TICKET,
            is_active=True,
            is_not_blocked=True,
            product_nominal=1000000000,
        )
        credit_matrix = CreditMatrixFactory(product=product)
        mockcredit_matrix.return_value = (credit_matrix, None)
        validation_error = train_ticket_limit_validation(self.customer, sepulsa_product, data)
        self.assertEqual(validation_error, ErrorMessage.AVAILABLE_LIMIT)
