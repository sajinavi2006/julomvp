import datetime
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from factory import Iterator

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountLimitFactory,
    AccountPropertyFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.collection_vendor.tests.factories import SkiptraceHistoryFactory
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.models import StatusLookup, Application
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    ProductLineFactory,
    WorkflowFactory,
    ApplicationFactory,
    PartnerFactory,
    SkiptraceResultChoiceFactory,
    AuthUserFactory,
    SkiptraceFactory,
    CustomerFactory,
    LoanFactory,
    VoiceCallRecordFactory,
    CootekRobocallFactory,
    PaymentFactory,
    StatusLookupFactory,
)
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.sales_ops.constants import SalesOpsSettingConst
from juloserver.sales_ops.services import julo_services

PACKAGE_NAME = 'juloserver.sales_ops.services.julo_services'


class TestJulo(TestCase):
    def test_get_sales_ops_setting(self):
        parameters = {
            SalesOpsSettingConst.MONETARY_PERCENTAGES: '20,20,20,20,20'
        }
        FeatureSettingFactory(feature_name=FeatureNameConst.SALES_OPS, parameters=parameters
        )

        value = julo_services.get_sales_ops_setting(SalesOpsSettingConst.MONETARY_PERCENTAGES)
        self.assertEqual(value, '20,20,20,20,20')

    def test_get_sales_ops_setting_not_found(self):
        parameters = {}
        FeatureSettingFactory(feature_name=FeatureNameConst.SALES_OPS, parameters=parameters)

        value = julo_services.get_sales_ops_setting(
            SalesOpsSettingConst.MONETARY_PERCENTAGES, '20,20,20,20,20'
        )
        self.assertEqual(value, '20,20,20,20,20')


class TestIsJulo1Account(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.julo1_product_line = ProductLineFactory(product_line_code=ProductLineCodes().J1)
        cls.julo1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)

    def test_valid(self):
        account = AccountFactory(account_lookup=AccountLookupFactory(name='JULO1'))
        ApplicationFactory(account=account, product_line=self.julo1_product_line,
                                         workflow=self.julo1_workflow, partner=None)

        with self.assertNumQueries(1):
            ret_val = julo_services.is_julo1_account(account)
        self.assertTrue(ret_val)

    def test_invalid_product_line(self):
        account = AccountFactory(account_lookup=AccountLookupFactory(name='JULO1'))
        ApplicationFactory(account=account, product_line=ProductLineFactory(),
                                         workflow=self.julo1_workflow, partner=None)

        ret_val = julo_services.is_julo1_account(account)
        self.assertFalse(ret_val)

    def test_invalid_workflow(self):
        account = AccountFactory(account_lookup=AccountLookupFactory(name='JULO1'))
        ApplicationFactory(account=account, product_line=self.julo1_product_line,
                                         workflow=WorkflowFactory(), partner=None)

        ret_val = julo_services.is_julo1_account(account)
        self.assertFalse(ret_val)

    def test_invalid_partner(self):
        account = AccountFactory(account_lookup=AccountLookupFactory(name='JULO1'))
        ApplicationFactory(account=account, product_line=self.julo1_product_line,
                                         workflow=self.julo1_workflow, partner=PartnerFactory())

        ret_val = julo_services.is_julo1_account(account)
        self.assertFalse(ret_val)

    def test_get_sales_ops_setting_name_is_none(self):
        parameters = {'param-1': 1, 'param-2': 2}
        FeatureSettingFactory(feature_name=FeatureNameConst.SALES_OPS, parameters=parameters)

        ret_val = julo_services.get_sales_ops_setting()
        self.assertEqual(parameters, ret_val)


class TestGetAgent(TestCase):
    def test_success(self):
        user = AuthUserFactory()
        agent = AgentFactory(user=user)

        ret_val = julo_services.get_agent(user.id)

        self.assertEqual(agent, ret_val)


class TestGetApplicationSkiptracePhone(TestCase):
    def test_success(self):
        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        contact_sources = [
            'mobile_phone_number_1',
            'mobile_phone',
            'mobile_phone_1',
            'sales_ops_1',
            'sales_ops_2',
            'sales_ops_3',
            'sales_ops_4',
            'mobile_phone_2',
            'mobile_phone_3',
            'mobile phone',
            'mobile phone 1',
            'mobile phone 2',
            'mobile_phone_lain',
            'mobile_phone1',
            'mobile_phone2',
            'mobile',
            'mobile 1',
            'mobile 2',
            'mobile2',
            'mobile 3',
            'mobile aktif',
            'App mobile phone',
            'App_mobile_phone',
            'kin_mobile_phone',
            'spouse_mobile_phone',
        ]
        initial_skiptrace = SkiptraceFactory(
                customer=customer, contact_source='random-stuff', phone_number="+62123456789",
                contact_name='contact name', effectiveness=0
        )
        skiptrace_list = [initial_skiptrace]
        for idx, contact_source in enumerate(contact_sources):
            skiptrace_list.append(
                SkiptraceFactory(
                    customer=customer, contact_source=contact_source,
                    phone_number="+62123456789" + str(idx),
                    contact_name='contact name', effectiveness=idx
                ))
        skiptrace_list[3].update_safely(effectiveness=1000)
        skiptrace_list[4].update_safely(effectiveness=1002)
        skiptrace_list[5].update_safely(effectiveness=1001)
        skiptrace_list[6].update_safely(effectiveness=1005)
        skiptrace_list[7].update_safely(effectiveness=1004)
        ret_val = julo_services.get_application_skiptrace_phone(application)
        contact_sources = [skiptrace['contact_source'] for skiptrace in ret_val]
        self.assertIn('sales_ops_1', contact_sources)
        self.assertIn('sales_ops_2', contact_sources)
        self.assertIn('sales_ops_3', contact_sources)
        self.assertIn('sales_ops_4', contact_sources)
        self.assertIn('mobile_phone_1', contact_sources)
        self.assertIn('mobile_phone_2', contact_sources)
        self.assertEqual(len(ret_val), 6)
        self.assertEqual(ret_val[0]['contact_source'], 'sales_ops_3')
        self.assertEqual(ret_val[0]['effectiveness'], 1005)
        self.assertEqual(ret_val[1]['contact_source'], 'sales_ops_4')
        self.assertEqual(ret_val[1]['effectiveness'], 1004)
        self.assertEqual(ret_val[2]['contact_source'], 'sales_ops_1')
        self.assertEqual(ret_val[2]['effectiveness'], 1002)
        self.assertEqual(ret_val[3]['contact_source'], 'sales_ops_2')
        self.assertEqual(ret_val[3]['effectiveness'], 1001)


class TestGetSkiptraceResultChoice(TestCase):
    def test_success(self):
        skiptrace_list = SkiptraceResultChoiceFactory.create_batch(5)
        ret_val = julo_services.get_skiptrace_result_choice(skiptrace_list[1].id)

        self.assertEqual(skiptrace_list[1], ret_val)


class TestGetBulkLatestApplicationIdDict(TestCase):
    def test_equal_with_get_latest_application(self):
        account = AccountFactory()
        ApplicationFactory.create_batch(3, is_deleted=Iterator([False, False, True]),
                                                           account=account)
        application = Application.objects.filter(account=account).last()
        application.application_status_id = 190
        application.save()

        ret_val = julo_services.get_bulk_latest_application_id_dict([account.id])
        application = julo_services.get_latest_application(account.id)

        self.assertEqual(application.id, ret_val[account.id])


class TestGetBulkLatestDisbursedLoanIdDict(TestCase):
    def setUp(self):
        self.now = timezone.localtime(timezone.now())

    def test_equal_with_get_latest_disbursed_loan(self):
        account = AccountFactory()
        loan_list = LoanFactory.create_batch(3, fund_transfer_ts=self.now, account=account,
                                             loan_disbursement_amount=Iterator([1000, 1000, 0]))
        LoanFactory.create_batch(5)

        ret_val = julo_services.get_bulk_latest_disbursed_loan_id_dict([account.id])
        loan = julo_services.get_latest_disbursed_loan(account.id)

        self.assertEqual(loan.id, ret_val[account.id])

    def test_with_single_account_id(self):
        account = AccountFactory()
        loan_list = LoanFactory.create_batch(3, fund_transfer_ts=self.now, account=account,
                                             loan_disbursement_amount=Iterator([1000, 1000, 0]))
        LoanFactory.create_batch(5)

        ret_val = julo_services.get_bulk_latest_disbursed_loan_id_dict([account.id])

        self.assertEqual(loan_list[1].id, ret_val[account.id])

    def test_with_multiple_account_id(self):
        account_list = AccountFactory.create_batch(3)
        loan_list = []
        for account in account_list:
            loan_list.append(LoanFactory.create_batch(3, fund_transfer_ts=self.now, account=account,
                                                      loan_disbursement_amount=Iterator([1000, 1000, 0])))
        LoanFactory.create_batch(5)

        ret_val = julo_services.get_bulk_latest_disbursed_loan_id_dict([account.id for account in account_list])

        self.assertEqual(3, len(ret_val))
        for idx, account in enumerate(account_list):
            self.assertEqual(loan_list[idx][1].id, ret_val[account.id])


class TestGetBulkLatestAccountLimitIdDict(TestCase):
    def test_equal_with_get_latest_account_limit(self):
        account = AccountFactory()
        account_limit_list = AccountLimitFactory.create_batch(2, account=account)
        AccountLimitFactory.create_batch(2)

        ret_val = julo_services.get_bulk_latest_account_limit_id_dict([account.id])
        account_limit = julo_services.get_latest_account_limit(account.id)

        self.assertEqual(account_limit.id, ret_val[account.id])

    def test_with_single_account_id(self):
        account = AccountFactory()
        account_limit_list = AccountLimitFactory.create_batch(2, account=account)
        AccountLimitFactory.create_batch(2)

        ret_val = julo_services.get_bulk_latest_account_limit_id_dict([account.id])

        self.assertEqual(account_limit_list[1].id, ret_val[account.id])

    def test_with_multiple_account_id(self):
        account_list = AccountFactory.create_batch(3)
        account_limit_list = []
        for account in account_list:
            account_limit_list.append(AccountLimitFactory.create_batch(2, account=account))
        AccountLimitFactory.create_batch(2)

        ret_val = julo_services.get_bulk_latest_account_limit_id_dict([account.id for account in account_list])

        self.assertEqual(3, len(ret_val))
        for idx, account in enumerate(account_list):
            self.assertEqual(account_limit_list[idx][1].id, ret_val[account.id])


class TestGetBulkLatestAccountPropertyIdDict(TestCase):
    def test_equal_with_get_latest_account_property(self):
        account = AccountFactory()
        account_property = AccountPropertyFactory.create_batch(2, account=account)
        AccountPropertyFactory.create_batch(2)

        ret_val = julo_services.get_bulk_latest_account_property_id_dict([account.id])
        account_property = julo_services.get_latest_account_property(account.id)

        self.assertEqual(account_property.id, ret_val[account.id])

    def test_with_single_account_id(self):
        account = AccountFactory()
        account_property_list = AccountPropertyFactory.create_batch(2, account=account)
        AccountPropertyFactory.create_batch(2)

        ret_val = julo_services.get_bulk_latest_account_property_id_dict([account.id])

        self.assertEqual(account_property_list[1].id, ret_val[account.id])

    def test_with_multiple_account_id(self):
        account_list = AccountFactory.create_batch(3)
        account_property_list = []
        for account in account_list:
            account_property_list.append(AccountPropertyFactory.create_batch(2, account=account))
        AccountPropertyFactory.create_batch(2)

        ret_val = julo_services.get_bulk_latest_account_property_id_dict([account.id for account in account_list])

        self.assertEqual(3, len(ret_val))
        for idx, account in enumerate(account_list):
            self.assertEqual(account_property_list[idx][1].id, ret_val[account.id])


class TestGetLastCollectionNexmoCalls(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.application = ApplicationFactory(account=self.account)
        self.loan = LoanFactory()

    def test_multiple_event_types(self):
        voice_calls = VoiceCallRecordFactory.create_batch(
            4,
            application=self.application,
            event_type=Iterator(['event 1', 'event 1', 'event 2', 'event 2']),
        )

        ret_val = julo_services.get_last_collection_nexmo_calls(self.account.id)

        self.assertEqual(2, len(ret_val))
        self.assertEqual(voice_calls[1], ret_val[0])
        self.assertEqual(voice_calls[3], ret_val[1])

    def test_with_multiple_application(self):
        applications = ApplicationFactory.create_batch(2, account=self.account)
        voice_calls = VoiceCallRecordFactory.create_batch(
            2,
            application=Iterator(applications),
            event_type='event 1',
        )

        ret_val = julo_services.get_last_collection_nexmo_calls(self.account.id)

        self.assertEqual(1, len(ret_val))
        self.assertEqual(voice_calls[1], ret_val[0])

    def test_no_calls(self):
        VoiceCallRecordFactory(application=ApplicationFactory())

        ret_val = julo_services.get_last_collection_nexmo_calls(self.account.id)

        self.assertEqual(0, len(ret_val))


class TestGetLastCollectionCootekCalls(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.loan = LoanFactory()

    def test_multiple_account_payments(self):
        account_payments = AccountPaymentFactory.create_batch(
            4,
            account=self.account,
        )
        calls = CootekRobocallFactory.create_batch(
            4,
            account_payment=Iterator(account_payments),
            call_status='completed',
            task_status=Iterator(['calling', 'calling', 'finished', 'finished']),
        )

        ret_val = julo_services.get_last_collection_cootek_calls(self.account.id)

        self.assertEqual(1, len(ret_val))
        self.assertEqual(calls[3], ret_val[0])

    def test_with_various_status(self):
        account_payments = AccountPaymentFactory.create_batch(
            3,
            account=self.account,
        )

        calls = CootekRobocallFactory.create_batch(
            3,
            account_payment=Iterator(account_payments),
            call_status='completed',
            task_status=Iterator(['calling', 'finished', 'random']),
        )

        ret_val = julo_services.get_last_collection_cootek_calls(self.account.id)

        self.assertEqual(1, len(ret_val))
        self.assertEqual(calls[1], ret_val[0])

    def test_no_calls(self):
        account_payment = AccountPaymentFactory(account=self.account)
        CootekRobocallFactory(account_payment=AccountPaymentFactory())
        CootekRobocallFactory(account_payment=account_payment, call_status=None)

        ret_val = julo_services.get_last_collection_nexmo_calls(self.account.id)

        self.assertEqual(0, len(ret_val))


class TestGetLastCollectionSkiptraceCalls(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory()

    def test_multiple_payments_non_intelix(self):
        applications = ApplicationFactory.create_batch(2, account=self.account)
        skiptraces = SkiptraceHistoryFactory.create_batch(
            2,
            application=Iterator(applications),
            payment=PaymentFactory(),
            source=Iterator(['CRM', None])
        )

        ret_val = julo_services.get_last_collection_skiptrace_calls(self.account.id)

        self.assertEqual(1, len(ret_val))
        self.assertEqual(skiptraces[1], ret_val[0])

    def test_no_result_non_intelix(self):
        application = ApplicationFactory(account=self.account)
        payment = PaymentFactory(account_payment=AccountPaymentFactory(account=self.account))
        SkiptraceHistoryFactory(application=ApplicationFactory(), payment=PaymentFactory(),
                                source='CRM')
        SkiptraceHistoryFactory(application=application, payment=payment, source='Intelix')

        ret_val = julo_services.get_last_collection_skiptrace_calls(self.account.id)

        self.assertEqual(0, len(ret_val))

    def test_multiple_application_intelix(self):
        applications = ApplicationFactory.create_batch(2, account=self.account)
        skiptraces = SkiptraceHistoryFactory.create_batch(
            2,
            application=Iterator(applications),
            payment=PaymentFactory(),
            source='Intelix'
        )

        ret_val = julo_services.get_last_collection_skiptrace_calls(self.account.id, True)

        self.assertEqual(1, len(ret_val))
        self.assertEqual(skiptraces[1], ret_val[0])

    def test_no_result_intelix(self):
        application = ApplicationFactory(account=self.account)
        payment = PaymentFactory(account_payment=self.account_payment)
        SkiptraceHistoryFactory(application=ApplicationFactory(),
                                payment=PaymentFactory(),
                                source='Intelix')
        SkiptraceHistoryFactory(application=application, payment=payment, source='CRM')

        ret_val = julo_services.get_last_collection_skiptrace_calls(self.account.id, True)

        self.assertEqual(0, len(ret_val), ret_val)


class TestFilterInvalidAccountIdsCollectionRestriction(TestCase):
    def test_filter_due_date(self):
        mock_today = datetime.datetime(2020, 1, 10)
        accounts = AccountFactory.create_batch(3)
        AccountPaymentFactory.create_batch(3, account=Iterator(accounts), due_date=Iterator(['2020-01-10', '2020-01-11', '2020-01-12']), status_id=310)

        dpd_time_delta = timedelta(days=1)
        with patch.object(timezone, 'now', return_value=mock_today):
            ret_val = julo_services.filter_invalid_account_ids_collection_restriction(accounts, dpd_time_delta)

        expected_account_ids = [accounts[0].id, accounts[1].id]
        self.assertEqual(expected_account_ids, sorted(ret_val))


class TestFilterInvalidAccountIdsLoanRestriction(TestCase):
    def test_filter_invalid_account_loan_restriction(self):
        mock_today = datetime.datetime(2021, 2, 10)
        accounts = list(AccountFactory.create_batch(4))
        #  can show on lineup because last paid date < today - 7
        loan_1 = LoanFactory(
            account=accounts[0], loan_status=StatusLookupFactory(status_code=250), loan_duration=2
        )
        loan_1.payment_set.first().update_safely(
            paid_date='2020-01-02', payment_status=StatusLookupFactory(status_code=330)
        )
        loan_1.payment_set.last().update_safely(
            paid_date='2020-02-02', payment_status=StatusLookupFactory(status_code=331)
        )

        #  can not show on lineup because last paid date > today - 7
        loan_2 = LoanFactory(
            account=accounts[1], loan_status=StatusLookupFactory(status_code=250), loan_duration=2
        )
        loan_2.payment_set.first().update_safely(
            paid_date='2021-02-09', payment_status=StatusLookupFactory(status_code=330)
        )
        loan_2.payment_set.last().update_safely(
            paid_date='2021-01-09', payment_status=StatusLookupFactory(status_code=331)
        )

        #  account 4 can show on lineup because don't have loan
        min_available_days = 7  # fake from sales_ops setting
        with patch.object(timezone, 'now', return_value=mock_today):
            invalid_account_ids = julo_services.filter_invalid_account_ids_loan_restriction(
                [accounts[0].id, accounts[1].id, accounts[2].id], min_available_days
            )
        expected_invalid_account_ids = {accounts[1].id}
        self.assertEqual(expected_invalid_account_ids, invalid_account_ids)


class TestFilterInvalidAccountIdsDisbursementDateRestriction(TestCase):
    def test_filter_invalid_account_disbursement_date_restriction(self):
        mock_today = datetime.datetime(2021, 2, 10)
        accounts = list(AccountFactory.create_batch(4))
        #  can show on lineup because last paid date < today - 7
        LoanFactory(
            account=accounts[0], loan_status=StatusLookupFactory(status_code=220), loan_duration=2,
            fund_transfer_ts=mock_today
        )
        LoanFactory(
            account=accounts[1], loan_status=StatusLookupFactory(status_code=220), loan_duration=2,
            fund_transfer_ts=datetime.datetime(2021, 1, 20)
        )

        #  account 4 can show on lineup because don't have loan
        min_available_days = 14  # fake from sales_ops setting
        with patch.object(timezone, 'now', return_value=mock_today):
            invalid_account_ids = \
                julo_services.filter_invalid_account_ids_disbursement_date_restriction(
                    [accounts[0].id, accounts[1].id, accounts[2].id], min_available_days
                )
        expected_invalid_account_ids = {accounts[0].id}
        self.assertEqual(expected_invalid_account_ids, invalid_account_ids)


@patch.object(timezone, 'now')
class TestFilterInvalidAccountIdsPaidCollectionRestriction(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.last_paid_account_payment = AccountPaymentFactory(
            account=self.account, status_id=330,
            due_date='2020-01-20', paid_date='2020-02-11'
        )
        self.other_account_payments = AccountPaymentFactory.create_batch(
            2,
            account=self.account,
            status_id=310,
            due_date=Iterator(['2020-01-20', '2020-03-20']),
        )

    @classmethod
    def setUpTestData(cls):
        cls.status_not_due = StatusLookupFactory(status_code=310)
        cls.status_paid_on_time = StatusLookupFactory(status_code=330)

    def test_no_collection_call(self, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 11)
        ret_val = julo_services.filter_invalid_account_ids_paid_collection_restriction(
            [self.account.id], timedelta(days=1)
        )
        self.assertEquals(0, len(ret_val))

    def test_collection_call_and_pass_date(self, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 12)
        ret_val = julo_services.filter_invalid_account_ids_paid_collection_restriction(
            [self.account.id], timedelta(days=1)
        )
        VoiceCallRecordFactory(
            account_payment=self.last_paid_account_payment,
            application=ApplicationFactory(account=self.account)
        )
        self.assertEquals(0, len(ret_val))

    def test_collection_call_nexmo(self, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 11)
        VoiceCallRecordFactory(
            account_payment=self.last_paid_account_payment,
            application=ApplicationFactory(account=self.account)
        )
        ret_val = julo_services.filter_invalid_account_ids_paid_collection_restriction(
            [self.account.id], timedelta(days=1)
        )
        self.assertEqual({self.account.id}, ret_val)

    def test_collection_call_cootek(self, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 11)
        CootekRobocallFactory(
            account_payment=self.last_paid_account_payment,
            task_status='finished',
            call_status='completed',
        )
        ret_val = julo_services.filter_invalid_account_ids_paid_collection_restriction(
            [self.account.id], timedelta(days=1)
        )
        self.assertEqual({self.account.id}, ret_val)

    def test_collection_call_skiptrace(self, mock_now):
        mock_now.return_value = datetime.datetime(2020, 2, 11)
        SkiptraceHistoryFactory(
            account_payment=self.last_paid_account_payment,
            source='Intelix',
            payment=PaymentFactory(loan=LoanFactory()),
            application=ApplicationFactory(account=self.account),
        )
        ret_val = julo_services.filter_invalid_account_ids_paid_collection_restriction(
            [self.account.id], timedelta(days=1)
        )
        self.assertEqual({self.account.id}, ret_val)
