import datetime
import json
from datetime import date
from unittest.mock import patch

import mock
from django.test.testcases import TestCase, override_settings
from django.utils import timezone
from factory import Iterator

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountPropertyFactory, \
    AccountLimitFactory, CreditLimitGenerationFactory
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    AddressGeolocation,
    PaymentEvent,
    Application,
    ApplicationFieldChange,
    Payment,
    StatusLookup,
    DjangoAdminLogChanges,
    FeatureSetting,
    MobileFeatureSetting,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.signals import (
    document_data_change_after_model_update,
    update_skiptrace,
    update_app_version_to_moengage,
)
from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes, PaymentStatusCodes
from juloserver.julo.tests.factories import (
    AddressGeolocationFactory,
    ApplicationJ1Factory,
    ApplicationFieldChangeFactory,
    PaymentFactory,
    ApplicationFactory,
    ProductLineFactory,
    PartnerFactory,
    StatusLookupFactory,
    CustomerFactory,
    FeatureSettingFactory,
    MobileFeatureSettingFactory,
    ApplicationHistoryFactory,
    CleanLoanFactory,
)
from juloserver.julo.tests.factories import PaymentMethodFactory
from juloserver.julo.tests.factories import LoanFactory
from juloserver.julo.tests.factories import AccountingCutOffDateFactory
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.payment_methods import PaymentMethodCodes

PACKAGE_NAME = 'juloserver.julo.signals'


@override_settings(SUSPEND_SIGNALS=True)
class TestPaymentEventSignal(TestCase):

    def setUp(self):
        loan = LoanFactory()
        self.payment_method = PaymentMethodFactory(
            loan=loan,
            payment_method_name='INDOMARET',
            customer=loan.customer)
        self.payment = PaymentFactory(
            installment_principal=2000,
            installment_interest=200,
            late_fee_amount=20,
            paid_interest=200,
            paid_principal=2000,
            payment_number=1,
            due_amount=0)
        self.accounting_date_cut_off = AccountingCutOffDateFactory()

    @mock.patch('django.utils.timezone.localtime')
    def test_add_accounting_date_on_creation_logic(self, mock_localtime):

        test_cases = [
            (date(2020, 10, 29), date(2020, 10, 30), date(2020, 10, 30)),
            (date(2020, 10, 2), date(2020, 10, 10), date(2020, 10, 10)),
            (date(2019, 7, 29), date(2020, 10, 2), date(2020, 9, 30)),
            (date(2020, 7, 29), date(2020, 10, 19), date(2020, 10, 19)),
            (date(2019, 12, 29), date(2020, 1, 8), date(2019, 12, 31)),
            (date(2020, 6, 30), date(2020, 7, 8), date(2020, 6, 30)),
            (date(2020, 6, 8), date(2020, 7, 8), date(2020, 6, 30)),
            (date(2020, 5, 29), date(2020, 7, 8), date(2020, 6, 30)),
            (date(2020, 7, 1), date(2020, 7, 8), date(2020, 7, 8)),
            (date(2020, 7, 1), date(2020, 7, 9), date(2020, 7, 9)),
            (date(2020, 7, 8), date(2020, 7, 8), date(2020, 7, 8)),
            (datetime.datetime(2020, 7, 9), date(2020, 7, 9), date(2020, 7, 9)),
            ("2020-07-09", date(2020, 7, 8), date(2020, 7, 8))
        ]
        for event_date, today, expected_accounting_date in test_cases:

            mock_localtime.reset_mock()
            mock_localtime.return_value.date.return_value = today


            payment_event = PaymentEvent.objects.create(
                event_type='payment',
                payment_method=self.payment_method,
                event_payment=10000,
                event_due_amount=100000,
                event_date=event_date,
                payment=self.payment)
            assert payment_event.accounting_date == expected_accounting_date

    @mock.patch('juloserver.julo.signals.FeatureSetting.objects.get_or_none')
    @mock.patch('django.utils.timezone.localtime')
    def test_not_to_update_accounting_date(self, mock_localtime, mocked_feature):

        today = date(2020, 10, 16)

        mock_localtime.reset_mock()
        mock_localtime.return_value.date.return_value = today
        event_date = date(2020, 6, 29)
        payment_event = PaymentEvent.objects.create(
            event_type='payment',
            payment_method=self.payment_method,
            event_payment=10000,
            event_due_amount=100000,
            event_date=event_date,
            payment=self.payment)

        expected_accounting_date = date(2020, 10, 16)
        not_allowed_accounting_date = date(2018, 10, 9)
        payment_event.accounting_date = not_allowed_accounting_date
        payment_event.save()
        assert payment_event.accounting_date == expected_accounting_date

        payment_event.update_safely(accounting_date=not_allowed_accounting_date)
        assert payment_event.accounting_date == expected_accounting_date


class TestApplicationUpdation(TestCase):
    """
    Testing these signals:
    - get_data_before_application_updation
    - get_data_after_application_updation
    """
    def setUp(self):
        self.product_line = ProductLineFactory()
        self.partner = PartnerFactory()
        self.application = ApplicationFactory(
            bank_name='test bank',
            bank_account_number='123456789',
            product_line=self.product_line,
            is_fdc_risky=True,
            monthly_income=100000,
            loan_purpose='test purpose',
            job_type='test job',
            job_industry='test industry',
            mobile_phone_1='123456789',
            dob='2000-01-01',
            address_kabupaten='test kabupaten',
            address_provinsi='test provinsi',
            partner=self.partner
        )

    def test_post_init(self):
        with self.assertNumQueries(1):
            application = Application.objects.get(id=self.application.id)

        self.assertEqual('test bank', getattr(application, '__stored_bank_name'))
        self.assertEqual('123456789', getattr(application, '__stored_bank_account_number'))
        self.assertEqual(self.product_line.product_line_code, getattr(application, '__stored_product_line_id'))
        self.assertEqual(True, getattr(application, '__stored_is_fdc_risky'))
        self.assertEqual(100000, getattr(application, '__stored_monthly_income'))
        self.assertEqual('test purpose', getattr(application, '__stored_loan_purpose'))
        self.assertEqual('test job', getattr(application, '__stored_job_type'))
        self.assertEqual('test industry', getattr(application, '__stored_job_industry'))
        self.assertEqual('123456789', getattr(application, '__stored_mobile_phone_1'))
        self.assertEqual('2000-01-01', str(getattr(application, '__stored_dob')))
        self.assertEqual('test kabupaten', getattr(application, '__stored_address_kabupaten'))
        self.assertEqual('test provinsi', getattr(application, '__stored_address_provinsi'))
        self.assertEqual(self.partner.id, getattr(application, '__stored_partner_id'))

    @override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=False)
    @patch(f'{PACKAGE_NAME}.execute_after_transaction_safely')
    def test_post_save_product_line(self, mock_execute_after_transaction_safely):
        application = Application.objects.get(id=self.application.id)
        new_product_line = ProductLineFactory()
        application.product_line = new_product_line

        # 1x for pre_save (no idea how to ignore this)
        # 1x for saving
        # Two queries for transaction commit
        with self.assertNumQueries(7):
            application.save()

        self.assertEqual(1, mock_execute_after_transaction_safely.call_count)


class TestPaymentUpdation(TestCase):
    """
    Testing these signals:
    - get_data_before_payment_updation
    - get_data_after_payment_updation
    """
    def setUp(self):
        self.customer = CustomerFactory()
        self.loan = LoanFactory(customer=self.customer)
        self.status = StatusLookupFactory(status_code=310)
        self.payment = PaymentFactory(
            loan=self.loan,
            payment_status=self.status,
            due_amount=10000,
            cashback_earned=1000
        )

    def test_post_init(self):
        with self.assertNumQueries(1):
            payment = Payment.objects.get(id=self.payment.id)

        self.assertEqual(310, getattr(payment, '__stored_payment_status_id'))
        self.assertEqual(10000, getattr(payment, '__stored_due_amount'))
        self.assertEqual(1000, getattr(payment, '__stored_cashback_earned'))

    @override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=False)
    @patch(f'{PACKAGE_NAME}.send_user_attributes_to_moengage_for_realtime_basis')
    def test_post_save_payment(self, mock_moengage_logic):
        new_status = StatusLookupFactory(status_code=320)
        payment = Payment.objects.get(id=self.payment.id)
        payment.payment_status = new_status
        payment.due_amount = 200000
        payment.cashback_earned = 2000

        # 1x for saving
        # 2x for get customer via loan
        with self.assertNumQueries(3):
            payment.save()

        self.assertEqual(1, mock_moengage_logic.apply_async.call_count)


class TestPaymentAndLoanSignalsUpdateGraduation(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_property = AccountPropertyFactory(account=self.account, is_entry_level=True)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.loan_status_212 = StatusLookup.objects.get(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING
        )
        self.loan = LoanFactory(
            application=self.application, account=self.account, loan_status=self.loan_status_212
        )

        self.payment = PaymentFactory(payment_status=StatusLookupFactory(status_code=310))
        self.payment.loan = self.loan
        self.payment.save()
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name='cfs',
            parameters={
                "graduation_rules": [],
                "is_active_graduation": True,
            }
        )

    @mock.patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_signals_loan(self, mock_execute_after_transaction_safely):
        old_loan_status_id = self.loan.loan_status_id
        self.loan.update_safely(loan_status_id=220)
        self.loan.refresh_from_db()
        self.assertNotEqual(old_loan_status_id, self.loan.loan_status_id)
        mock_execute_after_transaction_safely.assert_called_once()

    @mock.patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_signals_loan_with_graduation_not_call(self, mock_execute_after_transaction_safely):
        self.loan.update_safely(julo_bank_name='abcde')
        mock_execute_after_transaction_safely.assert_not_called()

    @mock.patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_signals_payment(self, mock_execute_after_transaction_safely):
        old_paid_amount = self.payment.paid_amount
        old_payment_status_id = self.payment.payment_status_id
        self.payment.update_safely(paid_amount=10000, payment_status_id=330)
        self.payment.refresh_from_db()
        self.assertNotEqual(old_paid_amount, self.payment.paid_amount)
        self.assertNotEqual(old_payment_status_id, self.payment.payment_status_id)
        mock_execute_after_transaction_safely.assert_called_once()

    @mock.patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_signals_payment_with_graduation_not_call(self, mock_execute_after_transaction_safely):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.payment.update_safely(payment_number=5)
        mock_execute_after_transaction_safely.assert_not_called()


class TestDocumentDataChangeAfterModelUpdate(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(feature_name='cfs',
                                                     is_active=True,
                                                     parameters={'test': 1},
                                                     description='test',
                                                     cdate='2022-08-12 05:08:48.459493+00:00')
        self.feature_setting.parameters = {'test': 2}
        self.feature_setting.save()

        self.mobile_feature_setting = MobileFeatureSettingFactory(
            feature_name='test',
            is_active=True,
            parameters={'test': 1},
            udate='2022-08-12 05:08:48.459493+00:00')
        self.mobile_feature_setting.parameters = {'test': 2}
        self.mobile_feature_setting.save()

    def test_update_one_value_once_success(self):
        """
        Expected Result: Retrieve successfully the record created after changing data once and saving
            App: Feature Setting and Mobile Feature Setting
        """
        result_feature_setting = DjangoAdminLogChanges.objects.get(
            model_name='FeatureSetting',
            item_changed='parameters',
            old_value={'test': 1},
            new_value={'test': 2})
        result_mobile_feature_setting = DjangoAdminLogChanges.objects.get(
            model_name='MobileFeatureSetting',
            item_changed='parameters',
            old_value={'test': 1},
            new_value={'test': 2})

        self.assertTrue(result_feature_setting)
        self.assertTrue(result_mobile_feature_setting)

    def test_update_one_value_multiple_success(self):
        """
        Expected Result: Retrieve successfully the record created after changing data and saving
        multiple times to see if the correct values were documented
            App: Feature Setting and Mobile Feature Setting
        """
        self.feature_setting.parameters = {'test': 3}
        self.feature_setting.parameters = {'test': 4}
        self.feature_setting.save()

        self.mobile_feature_setting.parameters = {'test': 3}
        self.mobile_feature_setting.parameters = {'test': 4}
        self.mobile_feature_setting.save()

        result_feature_setting = DjangoAdminLogChanges.objects.get(
            model_name='FeatureSetting',
            item_changed='parameters',
            old_value={'test': 2},
            new_value={'test': 4})
        result_mobile_feature_setting = DjangoAdminLogChanges.objects.get(
            model_name='MobileFeatureSetting',
            item_changed='parameters',
            old_value={'test': 2},
            new_value={'test': 4})

        self.assertTrue(result_feature_setting)
        self.assertTrue(result_mobile_feature_setting)

    def test_update_multiple_values_success(self):
        """
        Expected Result: Retrieve successfully the record created after updating multiple fields
        to see if the correct values were documented
            App: Feature Setting
        """
        old_value_dict = {'is_active': True, 'parameters': {'test': 2}, 'description': 'test'}
        new_value_dict = {'is_active': False, 'parameters': {'test': 3},
                          'description': 'changed_test'}
        self.feature_setting.update_safely(is_active=False, parameters={'test': 3},
                                           description='changed_test')

        for field in old_value_dict.keys():
            result = DjangoAdminLogChanges.objects.get_or_none(model_name='FeatureSetting',
                                                               item_changed=field,
                                                               old_value=old_value_dict[field],
                                                               new_value=new_value_dict[field])
            self.assertTrue(result)

    def test_update_different_model_failure(self):
        """
        Expected Result: Retrieve a None variable. Test might fail (successfully retrieve a record
        from the DjangoAdminLogChanges table) depending on which app gets registered as Sender in
        the future
            App: Customer
        """
        customer = CustomerFactory(email='test@test.com')
        customer.email = 'test_changed@test.com'
        customer.save()

        result_customer = DjangoAdminLogChanges.objects.get_or_none(
            model_name='Customer',
            item_changed='email',
            old_value='test@test.com',
            new_value='test_changed@test.com')
        self.assertFalse(result_customer)

    def test_update_nothing_failure(self):
        """
        Expected Result: Return None because there weren't any differences comparing to the original
        created object
            App: Feature Setting and Mobile Feature Setting
        """
        self.feature_setting.parameters = {'test': 2}
        self.feature_setting.save()
        self.mobile_feature_setting.parameters = {'test': 2}
        self.mobile_feature_setting.save()

        result_feature_setting = DjangoAdminLogChanges.objects.get_or_none(
            model_name='FeatureSetting',
            item_changed='parameters',
            old_value={'test': 2},
            new_value={'test': 2})
        result_mobile_feature_setting = DjangoAdminLogChanges.objects.get_or_none(
            model_name='MobileFeatureSetting',
            item_changed='parameters',
            old_value={'test': 2},
            new_value={'test': 2})

        self.assertFalse(result_feature_setting)
        self.assertFalse(result_mobile_feature_setting)

    def test_update_cdate_udate_failure(self):
        """
        Expected Result: Return None because table does not document differences in field 'cdate'
        and 'udate'
            App: Feature Setting and Mobile Feature Setting
        """
        self.feature_setting.update_safely(cdate='2022-08-12 05:08:50.459493+00:00')
        self.mobile_feature_setting.update_safely(udate='2022-08-12 05:09:48.459493+00:00')

        result_feature_setting = DjangoAdminLogChanges.objects.get_or_none(
            model_name='FeatureSetting',
            item_changed='cdate',
            old_value='2022-08-12 05:08:48.459493+00:00',
            new_value='2022-08-12 05:08:50.459493+00:00')
        result_mobile_feature_setting = DjangoAdminLogChanges.objects.get_or_none(
            model_name='MobileFeatureSetting',
            item_changed='udate',
            old_value='2022-08-12 05:08:48.459493+00:00',
            new_value='2022-08-12 05:09:48.459493+00:00')

        self.assertFalse(result_feature_setting)
        self.assertFalse(result_mobile_feature_setting)


class TestPaymentAndLoanSignalsUpdateEntryGraduation(TestCase):
    @patch('django.utils.timezone.now')
    def setUp(self, mock_timezone):
        mock_timezone.return_value = datetime.datetime(2022, 9, 30, 0, 0, 0)
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            cdate=datetime.datetime(2022, 9, 30).strftime('%Y-%m-%d')
        )
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id, status_new=ApplicationStatusCodes.LOC_APPROVED
        )
        mock_timezone.return_value = timezone.localtime(timezone.now())

        self.loan = CleanLoanFactory.create_batch(
            3, customer=self.customer, account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_duration=2,
            loan_amount=Iterator([500000, 500000, 500000])
        )
        self.payment = PaymentFactory.create_batch(
            6, loan=Iterator([
                self.loan[0], self.loan[0], self.loan[1], self.loan[1], self.loan[2], self.loan[2]
            ]),
            due_amount=Iterator([250000, 250000, 250000, 250000, 250000, 250000]),
            paid_amount=0,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )
        self.account_property = AccountPropertyFactory(
            account=self.account, is_entry_level=True
        )
        self.account_limit = AccountLimitFactory(
            account=self.account, max_limit=500000, set_limit=500000,
            available_limit=100000, used_limit=400000
        )
        self.credit_limit_generation = CreditLimitGenerationFactory(
            account=self.account, application=self.application,
            log='{"simple_limit": 17532468, "reduced_limit": 15779221, '
                '"limit_adjustment_factor": 0.9, "max_limit (pre-matrix)": 17000000, '
                '"set_limit (pre-matrix)": 15000000}',
            max_limit=5000000,
            set_limit=500000
        )
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'faqs': {
                    'header': 'header',
                    'topics': [{
                        'question': 'question test 1',
                        'answer': 'answer test 1'
                    }]
                },
                "graduation_rules": [
                    {
                        "max_account_limit": 300000,
                        "min_account_limit": 100000,
                        "max_grace_payment": 1,
                        "max_late_payment": 0,
                        "min_percentage_limit_usage": 300,
                        "min_percentage_paid_amount": 100,
                        "new_account_limit": 500000
                    },
                    {
                        "max_account_limit": 500000,
                        "min_account_limit": 500000,
                        "max_grace_payment": 1,
                        "max_late_payment": 0,
                        "min_percentage_limit_usage": 200,
                        "min_percentage_paid_amount": 100,
                        "new_account_limit": 1000000
                    }
                ],
                "is_active_graduation": True,
            }
        )

    @mock.patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_signals_payment(self, mock_execute_after_transaction_safely):
        for payment in self.payment:
            payment.update_safely(
                paid_amount=250000,
                payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
            )

        self.assertEquals(6, mock_execute_after_transaction_safely.call_count)

    @mock.patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_signals_loan(self, mock_execute_after_transaction_safely):
        for loan in self.loan:
            loan.update_safely(
                loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF)
            )

        self.assertEquals(3, mock_execute_after_transaction_safely.call_count)

    @mock.patch('juloserver.julo.signals.execute_after_transaction_safely')
    def test_signals_payment_loan_finish(self, mock_execute_after_transaction_safely):
        for payment in self.payment:
            payment.update_safely(
                paid_amount=250000,
                payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
            )

        for loan in self.loan:
            loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF)
            loan.save()

        self.assertEquals(9, mock_execute_after_transaction_safely.call_count)


@mock.patch('juloserver.julo.signals.save_address_geolocation_geohash')
class TestFillAddressGeolocationGeohash(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()

    def test_create(self, mock_save_address_geolocation_geohash):
        address_geolocation = (
            AddressGeolocation.objects.create(latitude=0, longitude=0, application=self.application)
        )

        mock_save_address_geolocation_geohash.assert_called_once_with(address_geolocation)

    def test_update(self, mock_save_address_geolocation_geohash):
        address_geolocation = AddressGeolocationFactory()
        address_geolocation.update_safely(latitude=1, longitude=2)

        mock_save_address_geolocation_geohash.assert_not_called()


class TestOneClickRepeatTransactionSignals(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.application.application_status_id = 190
        self.application.save()

        self.bank_account_destination = BankAccountDestinationFactory(customer=self.customer)
        self.loans = LoanFactory.create_batch(
            5, customer=self.customer, transaction_method_id=1, loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            bank_account_destination=self.bank_account_destination
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name='one_click_repeat', parameters={'transaction_method_ids': [1]},
            is_active=True
        )
        self.loan = LoanFactory(
            customer=self.customer, transaction_method_id=1, loan_amount=1000000,
            loan_status=StatusLookupFactory(status_code=StatusLookup.FUND_DISBURSAL_ONGOING),
            bank_account_destination=self.bank_account_destination
        )
        self.account_limit = AccountLimitFactory(
            account=self.account, set_limit=10000000, available_limit=1000000, used_limit=9000000
        )
        self.key = 'click_rep:{}'.format(self.customer.id)
        self.key_v2 = 'click_rep_v2:{}'.format(self.customer.id)

    def set_cache_value(self, expected_results, fake_redis):
        for loan in self.loans:
            loan_info = dict()
            loan_info['loan_id'] = loan.id
            loan_info['title'] = 'Rp {:,}'.format(loan.loan_amount).replace(",", "."),
            loan_info['body'] = '{} - {}'.format(
                loan.bank_account_destination.bank.bank_name_frontend,
                loan.bank_account_destination.account_number
            )
            loan_info['icon'] = loan.transaction_method.foreground_icon_url
            loan_info['product_data'] = {
                "transaction_method_name": loan.transaction_method.fe_display_name,
                "bank_account_destination_id": loan.bank_account_destination_id,
                "bank_account_number": loan.bank_account_destination.account_number,
                "loan_duration": loan.loan_duration,
                "loan_purpose": loan.loan_purpose,
            }

            expected_results.append(loan_info)
        fake_redis.set(self.key, json.dumps(expected_results))
        fake_redis.set(self.key_v2, json.dumps(expected_results))

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_delete_cache_success(self, mock_get_client):
        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis
        expected_results = []
        self.set_cache_value(expected_results, fake_redis)
        self.loan.update_safely(loan_status=StatusLookupFactory(
            status_code=LoanStatusCodes.CURRENT)
        )
        self.assertIsNone(fake_redis.get(self.key))
        self.assertIsNone(fake_redis.get(self.key_v2))

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_feature_setting_off(self, mock_get_client):
        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        self.feature_setting.update_safely(is_active=False)
        expected_results = []
        self.set_cache_value(expected_results, fake_redis)
        pre_cache_update = fake_redis.get(self.key)
        pre_cache_update_v2 = fake_redis.get(self.key_v2)

        self.loan.update_safely(loan_status=StatusLookupFactory(
            status_code=LoanStatusCodes.CURRENT)
        )

        prior_cache_update = fake_redis.get(self.key)
        self.assertEquals(pre_cache_update, prior_cache_update)

        prior_cache_update_v2 = fake_redis.get(self.key_v2)
        self.assertEquals(pre_cache_update_v2, prior_cache_update_v2)

    @mock.patch('juloserver.loan.services.loan_one_click_repeat.get_redis_client')
    def test_delete_cache_key_not_found(self, mock_get_client):
        fake_redis = MockRedisHelper()
        mock_get_client.return_value = fake_redis

        self.loan.update_safely(loan_status=StatusLookupFactory(
            status_code=LoanStatusCodes.CURRENT)
        )
        self.assertIsNone(fake_redis.get(self.key))
        self.assertIsNone(fake_redis.get(self.key_v2))


class UpdateSkiptraceTest(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            customer = self.customer,
            mobile_phone_1 = '1234567891',
            mobile_phone_2 = '1231232421'
        )
        self.application_field_change = ApplicationFieldChangeFactory(
            application=self.application,
        )

    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    @patch('juloserver.julo.signals.logger')
    def test_update_fields_not_present(self, mock_logger, mock_update_skiptrace_number):
        update_skiptrace(ApplicationFieldChange, created=False, instance=self.application_field_change)
        mock_update_skiptrace_number.assert_not_called()
        mock_logger.info.assert_called_once_with({
            'action': 'julo.signals.update_skiptrace',
            'application_field_change_id': self.application_field_change.id
            })

    @patch('juloserver.julo.signals.execute_after_transaction_safely')
    @patch('juloserver.julo.signals.logger')
    def test_update_fields_present(self, mock_logger, mock_update_skiptrace_number):
        update_skiptrace(ApplicationFieldChange,  created=True, instance=self.application_field_change)
        mock_update_skiptrace_number.assert_called_once()
        mock_logger.info.assert_called_once_with({
            'action': 'julo.signals.update_skiptrace',
            'application_field_change_id': self.application_field_change.id
            })

@patch('juloserver.julo.signals.execute_after_transaction_safely')
class TestApplicationSignals(TestCase):
    def test_update_app_version_to_moengage_app_version_change_triggers_function(self, mock_transaction_wrapper):
        application = ApplicationFactory(app_version='3.0.0')
        application.update_safely(app_version='4.0.0')

        mock_transaction_wrapper.assert_called_once()

    def test_update_app_version_to_moengage_new_application_does_not_trigger_function(self, mock_transaction_wrapper):
        ApplicationFactory(app_version='3.0.0')

        mock_transaction_wrapper.assert_not_called()

    def test_update_app_version_to_moengage_same_app_version_not_triggers_function(self, mock_transaction_wrapper):
        application = ApplicationFactory(app_version='3.0.0')
        application.update_safely(app_version='3.0.0')

        mock_transaction_wrapper.assert_not_called()


class TestUpdateDanaWalletVirtualAccount(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(
            mobile_phone_1='081234567890',
            customer=self.customer,
        )
        self.payment_method = PaymentMethodFactory(
            payment_method_code=PaymentMethodCodes.DANA_BILLER,
            customer=self.customer,
            loan=None,
        )

    def test_update_va(self):
        change_phone_number = '081234567891'
        self.application.update_safely(mobile_phone_1=change_phone_number)
        self.payment_method.refresh_from_db()
        self.assertEqual(
            self.payment_method.virtual_account,
            (PaymentMethodCodes.DANA_BILLER + change_phone_number)
        )

    def test_not_update_va_when_when_no_update_on_mobile_phone_1(self):
        change_kin_phone = '081234567800'
        self.application.update_safely(kin_mobile_phone=change_kin_phone)
        self.payment_method.refresh_from_db()
        self.assertNotEqual(
            self.payment_method.virtual_account,
            (PaymentMethodCodes.DANA_BILLER + change_kin_phone)
        )
