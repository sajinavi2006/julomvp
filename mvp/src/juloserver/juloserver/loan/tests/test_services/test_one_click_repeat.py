import json
import operator
import datetime

import mock
from django.test import TestCase
from django.utils import timezone
from fakeredis import FakeStrictRedis, FakeServer
from factory import Iterator
from django.utils import timezone

from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.julo.tests.factories import (
    CustomerFactory,
    StatusLookupFactory,
    LoanFactory,
    ApplicationFactory,
    SepulsaProductFactory,
    SepulsaTransactionFactory,
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.loan.constants import OneClickRepeatConst
from juloserver.loan.services.loan_one_click_repeat import (
    get_latest_transactions_info,
    get_latest_transactions_info_from_db,
)
from juloserver.account.tests.factories import AccountPropertyFactory, AccountFactory
from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
    TransactionMethodCode,
)
from juloserver.payment_point.tests.factories import (
    AYCEWalletTransactionFactory,
    AYCProductFactory,
    XfersEWalletTransactionFactory,
    XfersProductFactory,
)

PACKAGE_NAME = 'juloserver.loan.services.loan_one_click_repeat'


class TestOneClickRepeat(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.name_bank_validation_1 = NameBankValidationFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, name_bank_validation=self.name_bank_validation_1, account=self.account)
        self.bank_account_destination_1 = BankAccountDestinationFactory(
            customer=self.customer, name_bank_validation=self.name_bank_validation_1)
        self.bank_account_destination = BankAccountDestinationFactory(customer=self.customer)
        self.loans = LoanFactory.create_batch(
            4, customer=self.customer, transaction_method_id=1, loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination
        )
        self.fake_redis = FakeStrictRedis(server=FakeServer())
        self.key = OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT.format(self.customer.id)
        self.key_v2 = OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT_V2.format(self.customer.id)
        self.key_v3 = OneClickRepeatConst.REDIS_KEY_CLICK_REPEAT_V3.format(self.customer.id)
        self.account_property = AccountPropertyFactory(
            account=self.account
        )

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_set_redis_value_v1(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        self.account_property.is_proven = True
        self.account_property.save()

        loan = self.loans[-1]
        expected_results = [{
            'loan_id': loan.id,
            'title': 'Rp {:,}'.format(loan.loan_amount).replace(",", "."),
            'body': '{} - {}'.format(
                loan.bank_account_destination.bank.bank_name_frontend,
                loan.bank_account_destination.account_number
            ),
            'icon': loan.transaction_method.foreground_icon_url,
            'transaction_method_id': loan.transaction_method_id,
            'product_data': {
                "transaction_method_name": loan.transaction_method.fe_display_name,
                "bank_account_destination_id": loan.bank_account_destination_id,
                "bank_account_number": loan.bank_account_destination.account_number,
                "loan_duration": loan.loan_duration,
                "loan_purpose": loan.loan_purpose,
                "loan_amount": loan.loan_amount
            }
        }]

        loan_info = get_latest_transactions_info(self.customer, True, "v1")
        self.assertEquals(self.fake_redis.get(self.key), json.dumps(expected_results).encode())
        self.assertEquals(loan_info, expected_results)

        loan_info = get_latest_transactions_info(self.customer, True, "v1")
        self.assertEquals(loan_info, expected_results)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_set_redis_value_v2(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        self.account_property.is_proven = True
        self.account_property.save()

        loan = self.loans[-1]
        expected_results = [{
            'loan_id': loan.id,
            'title': 'Rp {:,}'.format(loan.loan_amount).replace(",", "."),
            'body': '{} - {}'.format(
                loan.bank_account_destination.bank.bank_name_frontend,
                loan.bank_account_destination.account_number
            ),
            'icon': loan.transaction_method.foreground_icon_url,
            'transaction_method_id': loan.transaction_method_id,
            'product_data': {
                "transaction_method_name": loan.transaction_method.fe_display_name,
                "bank_account_destination_id": loan.bank_account_destination_id,
                "bank_account_number": loan.bank_account_destination.account_number,
                "loan_duration": loan.loan_duration,
                "loan_purpose": loan.loan_purpose,
                "loan_amount": loan.loan_amount
            }}]

        loan_info = get_latest_transactions_info(self.customer, True, "v2")
        self.assertEquals(self.fake_redis.get(self.key_v2), json.dumps(expected_results).encode())
        self.assertEquals(loan_info, expected_results)

        loan_info = get_latest_transactions_info(self.customer, True, "v2")
        self.assertEquals(loan_info, expected_results)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_set_redis_value_v3(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        self.account_property.is_proven = True
        self.account_property.save()

        loan = self.loans[-1]
        expected_results = [{
            'loan_id': loan.id,
            'title': 'Rp {:,}'.format(loan.loan_amount).replace(",", "."),
            'body': '{} - {}'.format(
                loan.bank_account_destination.bank.bank_name_frontend,
                loan.bank_account_destination.account_number
            ),
            'icon': loan.transaction_method.foreground_icon_url,
            'transaction_method_id': loan.transaction_method_id,
            'product_data': {
                "transaction_method_name": loan.transaction_method.fe_display_name,
                "bank_account_destination_id": loan.bank_account_destination_id,
                "bank_account_number": loan.bank_account_destination.account_number,
                "loan_duration": loan.loan_duration,
                "loan_purpose": loan.loan_purpose,
                "loan_amount": loan.loan_amount
            }}]

        loan_info = get_latest_transactions_info(self.customer, True, "v3")
        self.assertEquals(self.fake_redis.get(self.key_v3), json.dumps(expected_results).encode())
        self.assertEquals(loan_info, expected_results)

        loan_info = get_latest_transactions_info(self.customer, True, "v3")
        self.assertEquals(loan_info, expected_results)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_tarik_dana_with_not_proven(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        self.account_property.is_proven = False
        self.account_property.save()
        LoanFactory(
            customer=self.customer, transaction_method_id=1, loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )
        LoanFactory(
            customer=self.customer, transaction_method_id=1, loan_amount=50000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )
        LoanFactory(
            customer=self.customer, transaction_method_id=1, loan_amount=600000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )

        loan_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.SELF.code], self.application
        )
        assert len(loan_info) == 3

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_tarik_dana_with_is_proven(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        self.account_property.is_proven = True
        self.account_property.save()
        LoanFactory(
            customer=self.customer, transaction_method_id=1, loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )
        LoanFactory(
            customer=self.customer, transaction_method_id=1, loan_amount=50000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )
        LoanFactory(
            customer=self.customer, transaction_method_id=1, loan_amount=600000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )

        loan_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.SELF.code], self.application
        )
        assert len(loan_info) == 4

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_dompet_digital(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        base_timezone = timezone.localtime(timezone.now())
        cdate_times = [
            base_timezone.replace(month=12, day=1, tzinfo=None),  # 0
            base_timezone.replace(month=12, day=15, tzinfo=None),  # 3
            base_timezone.replace(month=12, day=18, tzinfo=None),  # 5
            base_timezone.replace(month=12, day=24, tzinfo=None),  # 7
            base_timezone.replace(month=12, day=29, tzinfo=None),  # 9
            base_timezone.replace(month=12, day=4, tzinfo=None),  # 1
            base_timezone.replace(month=12, day=6, tzinfo=None),  # 2
            base_timezone.replace(month=12, day=16, tzinfo=None),  # 4
            base_timezone.replace(month=12, day=22, tzinfo=None),  # 6
            base_timezone.replace(month=12, day=27, tzinfo=None),  # 8
            base_timezone.replace(month=12, day=28, tzinfo=None),  # 10
            base_timezone.replace(month=12, day=30, tzinfo=None),  # 11
            base_timezone.replace(month=12, day=31, tzinfo=None),  # 12
        ]
        phone_numbers = [
            "081234000001",
            "081234000002",
            "081234000003",
            "081234000002",
            "081234000001",
            "081234000011",
            "081234000012",
            "081234000013",
            "081234000012",
            "081234000011",
            "091234000013",
            "091234000012",
            "091234000011",
        ]

        loans = LoanFactory.create_batch(
            13,
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=Iterator([1000000, 8000000, 3000000, 1000000, 600000]),
            loan_status=StatusLookupFactory(status_code=220),
        )
        ayc_products = AYCProductFactory.create_batch(
            5, type=SepulsaProductType.EWALLET, product_name='ayc'
        )
        ayc_ewallet_transactions = AYCEWalletTransactionFactory.create_batch(
            5,
            customer=self.customer,
            phone_number=Iterator(phone_numbers[:5]),
            ayc_product=Iterator([
                ayc_products[0],
                ayc_products[2],
                ayc_products[2],
                ayc_products[2],
                ayc_products[3],
            ]),
            loan=Iterator([loans[0], loans[3], loans[5], loans[7], loans[12]])
        )
        i = 0
        for transaction in ayc_ewallet_transactions:
            transaction.cdate = cdate_times[i]
            transaction.save()
            i += 1

        xfers_products = XfersProductFactory.create_batch(
            5, type=SepulsaProductType.EWALLET, product_name='xfers'
        )
        xfers_ewallet_transactions = XfersEWalletTransactionFactory.create_batch(
            5,
            customer=self.customer,
            phone_number=Iterator(phone_numbers[5:]),
            xfers_product=Iterator([
                xfers_products[0],
                xfers_products[2],
                xfers_products[2],
                xfers_products[2],
                xfers_products[3],
            ]),
            loan=Iterator([loans[1], loans[2], loans[4], loans[6], loans[8]])
        )
        for transaction in xfers_ewallet_transactions:
            transaction.cdate = cdate_times[i]
            transaction.save()
            i += 1

        sepulsa_products = SepulsaProductFactory.create_batch(
            3, type=SepulsaProductType.EWALLET, product_name='sepulsa'
        )
        sepulsa_ewallet_transactions = SepulsaTransactionFactory.create_batch(
            3,
            customer=self.customer,
            phone_number=Iterator(phone_numbers[5:]),
            transaction_status="success",
            product=Iterator([
                sepulsa_products[0],
                sepulsa_products[1],
                sepulsa_products[2]
            ]),
            loan=Iterator([loans[9], loans[10], loans[11]])
        )
        for transaction in sepulsa_ewallet_transactions:
            transaction.cdate = cdate_times[i]
            transaction.save()
            i += 1

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.DOMPET_DIGITAL.code], self.application
        )

        self.assertEqual(len(transaction_info), 5)
        self.assertEqual(transaction_info[0]['loan_id'], loans[12].id)
        self.assertEqual(transaction_info[1]['loan_id'], loans[11].id)
        self.assertEqual(transaction_info[2]['loan_id'], loans[10].id)
        self.assertEqual(transaction_info[3]['loan_id'], loans[9].id)
        self.assertEqual(transaction_info[4]['loan_id'], loans[8].id)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_duplicated_dompet_digital(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        loans = LoanFactory.create_batch(
            3,
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=Iterator([1000000, 1000000, 600000]),
            loan_status=StatusLookupFactory(status_code=210),
        )
        sepulsa_products = SepulsaProductFactory.create_batch(
            2,
            type=SepulsaProductType.EWALLET
        )
        SepulsaTransactionFactory.create_batch(
            3,
            customer=self.customer,
            phone_number="081234000001",
            transaction_status="success",
            product=Iterator([
                sepulsa_products[0],
                sepulsa_products[0],
                sepulsa_products[1]
            ]),
            loan=Iterator(loans)
        )
        for loan in loans:
            loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.DOMPET_DIGITAL.code], self.application
        )
        assert len(transaction_info) == 2

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_dompet_digital_responded_data(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=100000,
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=210),
        )
        xfers_product = XfersProductFactory(
            product_name="GoPay 10.000",
            type=SepulsaProductType.EWALLET,
            category=SepulsaProductCategory.GOPAY
        )
        XfersEWalletTransactionFactory(
            customer=self.customer,
            phone_number="081234000001",
            xfers_product=xfers_product,
            loan=loan
        )
        loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.DOMPET_DIGITAL.code], self.application
        )

        expected_result = [{
            'loan_id': loan.id,
            'title': "GoPay 10.000",
            'body': "081234000001",
            'icon': mock.ANY,
            'transaction_method_id': 5,
            'product_data': {
                "transaction_method_name": mock.ANY,
                "phone_number": "081234000001",
                "loan_duration": 4,
                "loan_amount": 100000,
                "sepulsa_product_id": xfers_product.sepulsa_id,
                "sepulsa_product_category": SepulsaProductCategory.GOPAY
            }
        }]
        self.assertEqual(transaction_info, expected_result)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_latest_transactions(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        # Tarik dana loans
        tarik_dana_loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=Iterator([1000000, 50000, 600000, 1200000]),
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )
        # Dompet digital loans
        dompet_digital_loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=Iterator([130000, 75000, 10000, 12000]),
            loan_status=StatusLookupFactory(status_code=210)
        )
        AYCEWalletTransactionFactory.create_batch(
            4,
            customer=self.customer,
            phone_number="081234000001",
            ayc_product=Iterator(
                AYCProductFactory.create_batch(4, type=SepulsaProductType.EWALLET)
            ),
            loan=Iterator(dompet_digital_loans)
        )
        for dompet_digital_loan in dompet_digital_loans:
            dompet_digital_loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info(
            self.customer, "v2", True, self.application
        )
        loans = tarik_dana_loans + dompet_digital_loans
        expected_loans = loans[-OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN:][::-1]
        expected_loan_ids = list(map(operator.attrgetter('id'), expected_loans))
        result_loan_ids = list(map(operator.itemgetter('loan_id'), transaction_info))
        self.assertEqual(result_loan_ids, expected_loan_ids)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_bpjs_cdate(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        base_timezone = timezone.localtime(timezone.now())
        cdate_times = [
            base_timezone.replace(month=12, day=1, tzinfo=None),  # 0
            base_timezone.replace(month=12, day=15, tzinfo=None),  # 3
            base_timezone.replace(month=12, day=18, tzinfo=None),  # 5
            base_timezone.replace(month=12, day=24, tzinfo=None),  # 7
            base_timezone.replace(month=12, day=29, tzinfo=None),  # 9
            base_timezone.replace(month=12, day=4, tzinfo=None),  # 1
            base_timezone.replace(month=12, day=6, tzinfo=None),  # 2
            base_timezone.replace(month=12, day=16, tzinfo=None),  # 4
            base_timezone.replace(month=12, day=22, tzinfo=None),  # 6
            base_timezone.replace(month=12, day=27, tzinfo=None),  # 8
        ]
        customer_numbers = [
            "081234000001",
            "081234000002",
            "081234000003",
            "081234000002",
            "081234000001",
            "081234000011",
            "081234000012",
            "081234000013",
            "081234000012",
            "081234000011"
        ]

        loans = LoanFactory.create_batch(
            10,
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=Iterator([1000000, 8000000, 3000000, 1000000, 600000]),
            loan_status=StatusLookupFactory(status_code=220),
        )
        sepulsa_transactions = SepulsaTransactionFactory.create_batch(
            10,
            customer=self.customer,
            customer_number=Iterator(customer_numbers[5:]),
            transaction_status="success",
            product=Iterator(
                SepulsaProductFactory.create_batch(5, type=SepulsaProductType.BPJS)
            ),
            loan=Iterator(loans)
        )
        i = 0
        for transaction in sepulsa_transactions:
            transaction.cdate = cdate_times[i]
            transaction.save()
            i += 1

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.BPJS_KESEHATAN.code], self.application
        )

        self.assertEqual(len(transaction_info), 5)
        self.assertEqual(transaction_info[0]['loan_id'], loans[9].id)
        self.assertEqual(transaction_info[1]['loan_id'], loans[8].id)
        self.assertEqual(transaction_info[2]['loan_id'], loans[7].id)
        self.assertEqual(transaction_info[3]['loan_id'], loans[6].id)
        self.assertEqual(transaction_info[4]['loan_id'], loans[5].id)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_utilities_bpjs(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        loans = LoanFactory.create_batch(
            3,
            customer=self.customer,
            transaction_method_id=7,
            loan_amount=Iterator([1000001, 1000001, 600001]),
            loan_status=StatusLookupFactory(status_code=210),
        )
        SepulsaTransactionFactory.create_batch(
            3,
            customer=self.customer,
            customer_number="081234000002",
            transaction_status="success",
            product=Iterator(
                SepulsaProductFactory.create_batch(5, type=SepulsaProductType.BPJS)
            ),
            loan=Iterator(loans)
        )
        for loan in loans:
            loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.BPJS_KESEHATAN.code], self.application
        )
        assert len(transaction_info) == 3

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_utilities_pln(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        loans = LoanFactory.create_batch(
            3,
            customer=self.customer,
            transaction_method_id=6,
            loan_amount=Iterator([1000004, 1000004, 600004]),
            loan_status=StatusLookupFactory(status_code=210),
        )
        SepulsaTransactionFactory.create_batch(
            3,
            customer=self.customer,
            customer_number="081234000005",
            transaction_status="success",
            product=Iterator(
                SepulsaProductFactory.create_batch(
                    3,
                    type=SepulsaProductType.ELECTRICITY,
                    category=SepulsaProductCategory.ELECTRICITY_PREPAID
                )
            ),
            loan=Iterator(loans)
        )
        for loan in loans:
            loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.LISTRIK_PLN.code], self.application
        )
        assert len(transaction_info) == 3

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_duplicated__utilities_bpjs(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        loans = LoanFactory.create_batch(
            3,
            customer=self.customer,
            transaction_method_id=7,
            loan_amount=Iterator([1000001, 1000001, 600001]),
            loan_status=StatusLookupFactory(status_code=210),
        )
        sepulsa_products = SepulsaProductFactory.create_batch(
            4,
            type=SepulsaProductType.BPJS
        )
        SepulsaTransactionFactory.create_batch(
            3,
            customer=self.customer,
            customer_number="081234000002",
            transaction_status="success",
            product=Iterator([
                sepulsa_products[0],
                sepulsa_products[0],
                sepulsa_products[1]
            ]),
            loan=Iterator(loans)
        )
        for loan in loans:
            loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.BPJS_KESEHATAN.code], self.application
        )
        assert len(transaction_info) == 2

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_duplicated__utilities_pln(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        loans = LoanFactory.create_batch(
            3,
            customer=self.customer,
            transaction_method_id=6,
            loan_amount=Iterator([1000004, 1000004, 600004]),
            loan_status=StatusLookupFactory(status_code=210),
        )
        sepulsa_products = SepulsaProductFactory.create_batch(
            4,
            type=SepulsaProductType.ELECTRICITY,
            category=SepulsaProductCategory.ELECTRICITY_PREPAID
        )
        SepulsaTransactionFactory.create_batch(
            3,
            customer=self.customer,
            customer_number="081234000005",
            transaction_status="success",
            product=Iterator([sepulsa_products[0], sepulsa_products[0], sepulsa_products[1]]),
            loan=Iterator(loans)
        )
        for loan in loans:
            loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.LISTRIK_PLN.code], self.application
        )
        assert len(transaction_info) == 2

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_utilities_bpjs_responded_data(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=7,
            loan_amount=10000,
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=210),
        )
        sepulsa_product = SepulsaProductFactory(
            product_name="BPJS Kesehatan",
            type=SepulsaProductType.BPJS,
            category=SepulsaProductCategory.BPJS_KESEHATAN
        )
        transaction = SepulsaTransactionFactory(
            customer=self.customer,
            customer_number="081234000002",
            transaction_status="success",
            product=sepulsa_product,
            loan=loan,
            paid_period=2
        )
        loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info_from_db(
            self.customer,
            [TransactionMethodCode.BPJS_KESEHATAN.code],
            self.application
        )
        expected_result = [{
            'loan_id': loan.id,
            'title': str(transaction.paid_period) + " Bulan",
            'body': "081234000002",
            'icon': mock.ANY,
            'transaction_method_id': 7,
            'product_data': {
                "transaction_method_name": mock.ANY,
                "customer_number": "081234000002",
                "loan_duration": 4,
                "loan_amount": 10000,
                "sepulsa_product_id": sepulsa_product.id,
                "sepulsa_product_category": str(SepulsaProductCategory.BPJS_KESEHATAN),
                "paid_period": transaction.paid_period
            }
        }]
        self.assertEqual(transaction_info, expected_result)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_utilities_pln_responded_data(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=6,
            loan_amount=10000,
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=210),
        )
        sepulsa_product = SepulsaProductFactory(
            product_name="PLN prepaid",
            type=SepulsaProductType.ELECTRICITY,
            category=SepulsaProductCategory.ELECTRICITY_PREPAID
        )
        SepulsaTransactionFactory(
            customer=self.customer,
            customer_number="081234000005",
            transaction_status="success",
            product=sepulsa_product,
            loan=loan
        )
        loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info_from_db(
            self.customer, [TransactionMethodCode.LISTRIK_PLN.code], self.application
        )

        expected_result = [{
            'loan_id': loan.id,
            'title': "PLN prepaid",
            'body': "081234000005",
            'icon': mock.ANY,
            'transaction_method_id': 6,
            'product_data': {
                "transaction_method_name": mock.ANY,
                "customer_number": "081234000005",
                "loan_duration": 4,
                "loan_amount": 10000,
                "sepulsa_product_id": sepulsa_product.id,
                "sepulsa_product_category": str(SepulsaProductCategory.ELECTRICITY_PREPAID)
            }
        }]
        self.assertEqual(transaction_info, expected_result)

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_no_loan_transaction(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        transaction_method_ids = [
            TransactionMethodCode.DOMPET_DIGITAL.code,
            TransactionMethodCode.LISTRIK_PLN.code,
            TransactionMethodCode.BPJS_KESEHATAN.code
        ]
        loans = LoanFactory.create_batch(
            3,
            customer=self.customer,
            transaction_method_id=Iterator(transaction_method_ids),
            loan_amount=Iterator([1000000, 1000000, 600000]),
            loan_status=StatusLookupFactory(status_code=220),
        )
        sepulsa_products = SepulsaProductFactory.create_batch(
            3,
            type=Iterator([
                SepulsaProductType.EWALLET,
                SepulsaProductType.ELECTRICITY,
                SepulsaProductType.BPJS
            ]),
            category=Iterator([
                None,
                SepulsaProductCategory.ELECTRICITY_PREPAID,
                None
            ])
        )
        sepulsa_transactions = SepulsaTransactionFactory.create_batch(
            3,
            customer=self.customer,
            phone_number="081234000001",
            transaction_status="success",
            product=Iterator(sepulsa_products)
        )
        transaction_info = get_latest_transactions_info_from_db(
            customer=self.customer,
            transaction_method_ids=transaction_method_ids,
            application=self.application
        )
        assert len(transaction_info) == 0

        for sepulsa_transaction, loan in zip(sepulsa_transactions, loans):
            sepulsa_transaction.update_safely(loan=loan)

        transaction_info = get_latest_transactions_info_from_db(
            customer=self.customer,
            transaction_method_ids=transaction_method_ids,
            application=self.application
        )
        assert len(transaction_info) == 3

        loans[1].update_safely(loan_status_id=210)
        transaction_info = get_latest_transactions_info_from_db(
            customer=self.customer,
            transaction_method_ids=transaction_method_ids,
            application=self.application
        )
        assert len(transaction_info) == 2

    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_latest_transactions_v3(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        # Tarik dana loans
        tarik_dana_loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=Iterator([1000000, 50000, 600000, 1200000]),
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )
        # Dompet digital loans
        dompet_digital_loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=Iterator([130000, 75000, 10000, 12000]),
            loan_status=StatusLookupFactory(status_code=210)
        )

        bpjs_loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=7,
            loan_amount=Iterator([50001, 60001, 70001, 80001]),
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=210)
        )

        electricity_loans = LoanFactory.create_batch(
            4,
            customer=self.customer,
            transaction_method_id=6,
            loan_amount=Iterator([50002, 60002, 70002, 80002]),
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=210)
        )
        SepulsaTransactionFactory.create_batch(
            4,
            customer=self.customer,
            phone_number="081234000001",
            transaction_status="success",
            product=Iterator(
                SepulsaProductFactory.create_batch(4, type=SepulsaProductType.EWALLET)
            ),
            loan=Iterator(dompet_digital_loans)
        )
        SepulsaTransactionFactory.create_batch(
            4,
            customer=self.customer,
            transaction_status="success",
            product=Iterator(
                SepulsaProductFactory.create_batch(4, type=SepulsaProductType.BPJS)
            ),
            loan=Iterator(bpjs_loans)
        )
        SepulsaTransactionFactory.create_batch(
            4,
            customer=self.customer,
            transaction_status="success",
            product=Iterator(
                SepulsaProductFactory.create_batch(
                    4,
                    type=SepulsaProductType.ELECTRICITY,
                    category=SepulsaProductCategory.ELECTRICITY_PREPAID
                )
            ),
            loan=Iterator(electricity_loans)
        )
        for dompet_digital_loan in dompet_digital_loans:
            dompet_digital_loan.update_safely(loan_status_id=220)
        for bpjs_loan in bpjs_loans:
            bpjs_loan.update_safely(loan_status_id=220)
        for electricity_loan in electricity_loans:
            electricity_loan.update_safely(loan_status_id=220)

        transaction_info = get_latest_transactions_info(
            self.customer, "v3", True, self.application
        )
        loans = tarik_dana_loans + dompet_digital_loans + bpjs_loans + electricity_loans
        expected_loans = loans[-OneClickRepeatConst.ONE_CLICK_REPEAT_DISPLAYED_LOAN:][::-1]
        expected_loan_ids = list(map(operator.attrgetter('id'), expected_loans))
        result_loan_ids = list(map(operator.itemgetter('loan_id'), transaction_info))
        self.assertEqual(result_loan_ids, expected_loan_ids)


    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_passed_interval_day(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        # Tarik Dana loan
        tarik_dana_loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )
        # Dompet Digital loan
        dompet_digital_loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=50000,
            loan_status=StatusLookupFactory(status_code=220)
        )
        # BPJS loan
        bpjs_loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=7,
            loan_amount=70000,
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=220)
        )
        # PLN loan
        electricity_loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=6,
            loan_amount=50000,
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=220)
        )
        dompet_digital_trx = SepulsaTransactionFactory(
            customer=self.customer,
            phone_number="081234000001",
            transaction_status="success",
            product=SepulsaProductFactory(type=SepulsaProductType.EWALLET),
            loan=dompet_digital_loan
        )
        bpjs_trx = SepulsaTransactionFactory(
            customer=self.customer,
            transaction_status="success",
            product=SepulsaProductFactory(type=SepulsaProductType.BPJS),
            loan=bpjs_loan
        )
        electricity_trx = SepulsaTransactionFactory(
            customer=self.customer,
            transaction_status="success",
            product=SepulsaProductFactory(
                type=SepulsaProductType.ELECTRICITY,
                category=SepulsaProductCategory.ELECTRICITY_PREPAID
            ),
            loan=electricity_loan
        )
        sepulsa_transactions = [dompet_digital_trx, bpjs_trx, electricity_trx]
        loans = [tarik_dana_loan, dompet_digital_loan, bpjs_loan, electricity_loan]

        now = timezone.localtime(timezone.now())
        for loan in loans:
            loan.update_safely(cdate=now - datetime.timedelta(days=120))
        for transaction in sepulsa_transactions:
            transaction.update_safely(cdate=now - datetime.timedelta(days=120))

        transaction_info = get_latest_transactions_info_from_db(
            customer=self.customer,
            transaction_method_ids=[
                TransactionMethodCode.SELF.code,
                TransactionMethodCode.DOMPET_DIGITAL.code,
                TransactionMethodCode.LISTRIK_PLN.code,
                TransactionMethodCode.BPJS_KESEHATAN.code
            ],
            application=self.application
        )
        self.assertEqual(len(transaction_info), 0)


    @mock.patch(f'{PACKAGE_NAME}.FeatureSetting')
    @mock.patch(f'{PACKAGE_NAME}.get_redis_client')
    def test_get_one_click_repeat_in_interval_day(self, mock_get_client, mock_fs):
        mock_get_client.return_value = self.fake_redis
        mock_fs.objects.filter().last.return_value = mock.Mock(
            parameters={"interval_day": 90}
        )

        # Tarik Dana loan
        tarik_dana_loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=1,
            loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=220),
            bank_account_destination=self.bank_account_destination_1
        )
        # Dompet Digital loan
        dompet_digital_loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=5,
            loan_amount=50000,
            loan_status=StatusLookupFactory(status_code=220)
        )
        # BPJS loan
        bpjs_loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=7,
            loan_amount=70000,
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=220)
        )
        # PLN loan
        electricity_loan = LoanFactory(
            customer=self.customer,
            transaction_method_id=6,
            loan_amount=50000,
            loan_duration=4,
            loan_status=StatusLookupFactory(status_code=220)
        )
        dompet_digital_trx = SepulsaTransactionFactory(
            customer=self.customer,
            phone_number="081234000001",
            transaction_status="success",
            product=SepulsaProductFactory(type=SepulsaProductType.EWALLET),
            loan=dompet_digital_loan
        )
        bpjs_trx = SepulsaTransactionFactory(
            customer=self.customer,
            transaction_status="success",
            product=SepulsaProductFactory(type=SepulsaProductType.BPJS),
            loan=bpjs_loan
        )
        electricity_trx = SepulsaTransactionFactory(
            customer=self.customer,
            transaction_status="success",
            product=SepulsaProductFactory(
                type=SepulsaProductType.ELECTRICITY,
                category=SepulsaProductCategory.ELECTRICITY_PREPAID
            ),
            loan=electricity_loan
        )
        loans = [tarik_dana_loan, dompet_digital_loan, bpjs_loan, electricity_loan]

        sepulsa_transactions = [dompet_digital_trx, bpjs_trx, electricity_trx]
        loans = [tarik_dana_loan, dompet_digital_loan, bpjs_loan, electricity_loan]

        now = timezone.localtime(timezone.now())
        for loan in loans:
            loan.update_safely(cdate=now - datetime.timedelta(days=60))
        for transaction in sepulsa_transactions:
            transaction.update_safely(cdate=now - datetime.timedelta(days=60))

        transaction_info = get_latest_transactions_info_from_db(
            customer=self.customer,
            transaction_method_ids=[
                TransactionMethodCode.SELF.code,
                TransactionMethodCode.DOMPET_DIGITAL.code,
                TransactionMethodCode.LISTRIK_PLN.code,
                TransactionMethodCode.BPJS_KESEHATAN.code
            ],
            application=self.application
        )
        self.assertEqual(len(transaction_info), 4)
