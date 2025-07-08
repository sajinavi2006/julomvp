import random
from unittest import TestCase as UnitTestCase

from mock import patch
import mock
from time import sleep
from juloserver.julo.exceptions import DuplicateProcessing
import pytest
from datetime import datetime, timedelta
from django.test.testcases import TestCase
from juloserver.followthemoney.services import (
    get_max_limit,
    lock_on_redis_with_ex_time,
    reassign_lender,
    get_summary_value,
    get_outstanding_loans_by_lender,
    get_bypass_lender_matchmaking,
    get_list_product_line_code_need_to_hide,
    reassign_lender_julo_one, GrabLoanAgreementBorrowerSignature,
    GrabLenderAgreementLenderSignature, LoanAgreementLenderSignature,
    LoanAgreementBorrowerSignature,
    get_signature_key_config,
    generate_lender_signature,
    get_total_outstanding_for_lender,
    JuloverLoanAgreementBorrowerSignature,
    JuloverLoanAgreementLenderSignature,
)
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.tests.factories import (
    PartnerFactory,
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    ProductLineFactory,
    OfferFactory,
    StatusLookupFactory,
    ProductLookupFactory,
    LoanFactory,
    LenderFactory,
    PaymentFactory,
    CreditScoreFactory,
    ApplicationJ1Factory,
    FeatureSettingFactory,
    LenderProductCriteriaFactory,
    LenderDisburseCounterFactory,
    WorkflowFactory,
    DocumentFactory,
)
from juloserver.julo.models import StatusLookup
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.followthemoney.constants import LoanWriteOffPeriodConst, RedisLockWithExTimeType
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
    ApplicationLenderHistoryFactory,
    FeatureSettingHistoryFactory,
    LenderBalanceCurrentFactory,
    SbDailyOspProductLenderFactory,
)
from juloserver.julovers.tests.factories import JuloverFactory
from juloserver.followthemoney.models import LenderApproval, LoanWriteOff
from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan.services.agreement_related import get_julo_loan_agreement_template
from juloserver.loan.services.lender_related import julo_one_lender_auto_matchmaking


class TestFlollowTheMoneyServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username='test')
        self.partner = PartnerFactory(user=self.user)
        self.product_line = ProductLineFactory(product_line_code=12345)
        self.product_look_up = ProductLookupFactory(product_line=self.product_line)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer, partner=self.partner,
                                              product_line=self.product_line,
                                              application_xid=123456789)
        self.application_lender_history = ApplicationLenderHistoryFactory(application=self.application)
        self.feature_setting_history = FeatureSettingHistoryFactory(parameters={'reassign_count': 6})
        self.offer = OfferFactory(application=self.application, product=self.product_look_up)
        self.loan_status = StatusLookupFactory()
        self.lender = LenderCurrentFactory(user=self.user)
        self.loan = LoanFactory(customer=self.customer, application=self.application, offer=self.offer,
                                loan_status=self.loan_status,
                                product=self.product_look_up, lender=self.lender)
        self.payment = PaymentFactory(loan=self.loan, payment_status=self.loan_status, paid_principal=0)
        self.credit_score = CreditScoreFactory()
        self.lender_balance = LenderBalanceCurrentFactory(lender=self.lender)
        LoanWriteOff.objects.create(loan=self.loan, wo_period=LoanWriteOffPeriodConst.WO_90)
        self.signature_config_setting = FeatureSettingHistoryFactory(
            feature_name=FeatureNameConst.SIGNATURE_KEY_CONFIGURATION,
            is_active=False,
        )

    @patch('juloserver.followthemoney.tasks.auto_expired_application_tasks')
    @patch('juloserver.julo.services.assign_lender_to_disburse')
    def test_reassign_lender(self, mock_assign_lender_to_disburse, mock_auto_expired_application_tasks):
        self.assertIsNone(reassign_lender(1))
        mock_assign_lender_to_disburse.return_value = self.lender
        result = reassign_lender(self.application.id)
        self.assertIsNone(result)
        LenderApproval.objects.create(partner=self.lender.user.partner, expired_in=datetime.now())
        result = reassign_lender(self.application.id)
        self.assertIsNone(result)

    def test_get_summary_value(self):
        self.assertEqual(get_summary_value(self.loan.id, 'paid_principal'), self.payment.paid_principal)

    def test_get_outstanding_loans_by_lender(self):
        result = get_outstanding_loans_by_lender(lender_id=self.lender.id + 1)
        self.assertIsNone(result)
        result = get_outstanding_loans_by_lender(lender_id=self.lender.id, include_paid_off=True, limit=20)
        self.assertEqual(result, {})

    def test_generate_lender_signature(self):
        self.assertEqual(generate_lender_signature(None), False)
        self.assertEqual(generate_lender_signature(LenderCurrentFactory(user=None)), False)

    def test_get_signature_key_config(self):
        users_key, default_key = get_signature_key_config()
        self.assertEqual(users_key, [])
        self.assertEqual(default_key, '1')

        self.signature_config_setting.is_active = True
        self.signature_config_setting.parameters = None
        self.signature_config_setting.save()
        users_key, default_key = get_signature_key_config()
        self.assertEqual(users_key, [])
        self.assertEqual(default_key, '1')

        default_parameters = {'users': {'1': 'lender'}, 'default': '2'}
        self.signature_config_setting.parameters = default_parameters
        self.signature_config_setting.save()
        users_key, default_key = get_signature_key_config()
        self.assertEqual(len(users_key), 1)
        self.assertEqual(default_key, '2')


class TestGetBypassLenderMatchmaking(TestCase):
    def setUp(self):
        self.j1_product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.account = AccountFactory()
        self.application = ApplicationJ1Factory(account=self.account)
        self.loan = LoanFactory(account=self.account)

        self.random_lenders = LenderCurrentFactory.create_batch(2)

    def test_get_bypass_lender_matchmaking_no_setting(self):
        ret_lender, is_bypass = get_bypass_lender_matchmaking(self.loan)

        self.assertFalse(is_bypass)
        self.assertIsNone(ret_lender)

    def test_get_bypass_lender_matchmaking_application_bypass(self):
        lender = LenderCurrentFactory(lender_name='test-lender')
        FeatureSettingFactory(
            feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS,
            category='followthemoney',
            is_active=True,
            parameters={
                'application_ids': [self.application.id],
                'lender_name': 'test-lender'
            }
        )

        ret_lender, is_bypass = get_bypass_lender_matchmaking(self.loan)

        self.assertTrue(is_bypass)
        self.assertEqual(lender, ret_lender)

    def test_get_bypass_lender_matchmaking_application_bypass_not_included(self):
        other_app = ApplicationJ1Factory()
        lender = LenderCurrentFactory(lender_name='test-lender')
        FeatureSettingFactory(
            feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS,
            category='followthemoney',
            is_active=True,
            parameters={
                'application_ids': [other_app.id],
                'lender_name': 'test-lender'
            }
        )

        ret_lender, is_bypass = get_bypass_lender_matchmaking(self.loan)

        self.assertFalse(is_bypass)
        self.assertIsNone(ret_lender)

    def test_get_bypass_lender_matchmaking_product_line_bypass(self):
        lender = LenderCurrentFactory(lender_name='test-lender')
        FeatureSettingFactory(
            feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE,
            category='followthemoney',
            is_active=True,
            parameters={
                str(self.j1_product_line.pk): lender.id
            }
        )

        ret_lender, is_bypass = get_bypass_lender_matchmaking(self.loan)

        self.assertTrue(is_bypass)
        self.assertEqual(lender, ret_lender)

    def test_get_bypass_lender_matchmaking_product_line_bypass_different(self):
        lender = LenderCurrentFactory(lender_name='test-lender')
        other_product_line = ProductLineFactory(product_line_code=self.j1_product_line.pk+1)
        FeatureSettingFactory(
            feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE,
            category='followthemoney',
            is_active=True,
            parameters={
                str(other_product_line.pk): lender.id
            }
        )

        ret_lender, is_bypass = get_bypass_lender_matchmaking(self.loan)

        self.assertFalse(is_bypass)
        self.assertIsNone(ret_lender)


@pytest.mark.django_db
class TestJuloOneAutoMatchmaking(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username='test')
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.application = ApplicationFactory(
            customer=self.customer,
            partner=self.partner,
            product_line=self.product_line,
            application_xid=123456789,
            account=self.account
        )
        self.account2 = AccountFactory(last_application=self.application)
        self.application2 = ApplicationJ1Factory(account=self.account2)
        self.loan = LoanFactory(
            id=1,
            account=self.account2,
            loan_amount=1000000,
            lender=LenderFactory(id=99,lender_name='test'),
            partner=self.partner,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            loan_duration=4,
        )
        self.lender = LenderFactory(id=100, lender_name='ska', lender_status='active')
        self.lender2 = LenderFactory(id=101, lender_name='ska2', lender_status='active')
        self.lender3 = LenderFactory(id=102, lender_name='ska3', lender_status='active')
        self.lender_balance = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=999999999
        )
        self.lender_balance2 = LenderBalanceCurrentFactory(
            lender=self.lender2, available_balance=999999999
        )
        self.lender_balance3 = LenderBalanceCurrentFactory(
            lender=self.lender3, available_balance=999999999
        )
        self.lender_product_criteria = LenderProductCriteriaFactory(
            lender=self.lender,
            partner=self.partner,
            product_profile_list=[1, self.product_line.product_line_code],
            min_duration=1,
            max_duration=12,
        )
        self.lender_product_criteria2 = LenderProductCriteriaFactory(
            lender=self.lender2,
            product_profile_list=[1, self.product_line.product_line_code],
            min_duration=1,
            max_duration=12,
        )
        self.lender_product_criteria3 = LenderProductCriteriaFactory(
            lender=self.lender3,
            product_profile_list=[1, self.product_line.product_line_code],
            min_duration=1,
            max_duration=12,
        )
        self.lender_counter = LenderDisburseCounterFactory(
            lender=self.lender, actual_count=1, rounded_count=2
        )
        self.lender_counter2 = LenderDisburseCounterFactory(
            lender=self.lender2, actual_count=1, rounded_count=2
        )
        self.lender_counter3 = LenderDisburseCounterFactory(
            lender=self.lender3, actual_count=1, rounded_count=2
        )
        self.feature_setting_history = FeatureSettingHistoryFactory(parameters={'reassign_count': 6})

    def test_reassign_all_lender(self):
        lender_ids = [self.loan.lender.id]
        lender = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender.id)
        lender2 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender2.id)
        lender3 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender3.id)
        lender4 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        self.assertEqual(lender_ids, [99,100,101,102])
        self.assertEqual(lender4, None)

    def test_one_min_max_duration_not_qualified(self):
        lender_ids = [self.loan.lender.id]

        self.lender4 = LenderFactory(id=103, lender_name='ska4', lender_status='active')
        self.lender_balance4 = LenderBalanceCurrentFactory(
            lender=self.lender4, available_balance=999999999
        )
        self.lender_product_criteria4 = LenderProductCriteriaFactory(
            lender=self.lender4,
            product_profile_list=[1, self.product_line.product_line_code],
            min_duration=1,
            max_duration=2,
        )
        self.lender_counter4 = LenderDisburseCounterFactory(
            lender=self.lender4, actual_count=1, rounded_count=2
        )

        lender = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender.id)
        lender2 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender2.id)
        lender3 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender3.id)
        lender4 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        self.assertEqual(lender_ids, [99, 100, 101, 102])
        self.assertEqual(lender4, None)

    def test_one_balance_not_enough(self):
        lender_ids = [self.loan.lender.id]
        self.lender_balance2.available_balance = 0
        self.lender_balance2.save()
        lender = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender.id)
        lender2 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender2.id)
        lender3 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)

        self.assertEqual(lender_ids, [99,100,102])
        self.assertEqual(lender3, None)

    def test_all_balance_not_enough(self):
        lender_ids = [self.loan.lender.id]
        self.lender_balance.available_balance = 0
        self.lender_balance.save()
        self.lender_balance2.available_balance = 0
        self.lender_balance2.save()
        self.lender_balance3.available_balance = 0
        self.lender_balance3.save()

        lender = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        self.assertEqual(lender, None)

    def test_default_lender_not_reused(self):
        self.loan.lender = self.lender
        lender_ids = [self.loan.lender.id]
        lender = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender.id)
        lender2 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender2.id)
        lender3 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)

        self.assertEqual(lender_ids, [100,101,102])
        self.assertEqual(lender3, None)

    def test_default_lender_not_reused_and_balance_not_enough(self):
        self.loan.lender = self.lender
        self.lender_balance2.available_balance = 0
        self.lender_balance2.save()
        lender_ids = [self.loan.lender.id]
        lender = julo_one_lender_auto_matchmaking(self.loan, lender_ids)
        lender_ids.append(lender.id)
        lender2 = julo_one_lender_auto_matchmaking(self.loan, lender_ids)

        self.assertEqual(lender_ids, [100,102])
        self.assertEqual(lender2, None)

    @mock.patch('juloserver.loan.services.loan_related.update_loan_status_and_loan_history')
    def test_reassign_lender_julo_one_product_line(self, mock_update_219):
        self.loan.product.product_line = self.product_line
        self.loan.product.save()
        reassign_lender_julo_one(self.loan.id)
        mock_update_219.assert_called()

    @mock.patch('juloserver.loan.services.lender_related.update_loan_status_and_loan_history')
    def test_reassign_lender_julo_one_product_line_failed(self, mock_update_219):
        self.loan.product.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.loan.product.save()
        reassign_lender_julo_one(self.loan.id)
        mock_update_219.assert_not_called()


class TestGetListProductLineCodeNeedToHide(TestCase):
    def test_returns_empty_list_when_hide_partner_loan_fs_not_active(self):
        self.assertEqual(get_list_product_line_code_need_to_hide(), [])

        FeatureSettingFactory(
            feature_name=FeatureNameConst.HIDE_PARTNER_LOAN,
            category='followthemoney',
            is_active=False,
            parameters={
                'hidden_product_line_codes': [123]
            }
        )
        self.assertEqual(get_list_product_line_code_need_to_hide(), [])

    def test_returns_hidden_product_line_codes_when_hide_partner_loan_fs_active(self):
        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.HIDE_PARTNER_LOAN,
            category='followthemoney',
            is_active=True,
            parameters={
                'hidden_product_line_codes': []
            }
        )
        self.assertEqual(get_list_product_line_code_need_to_hide(), [])

        fs.parameters = {'hidden_product_line_codes': [123, 456]}
        fs.save()
        self.assertEqual(get_list_product_line_code_need_to_hide(), [123, 456])


class TestGetJuloAgreementTemplate(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB'
        )
        self.account = AccountFactory(
            account_lookup=self.account_lookup,
            customer=self.customer
        )

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.product_line_julover = ProductLineFactory(
            product_line_code=ProductLineCodes.JULOVER)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.product_lookup_julover = ProductLookupFactory(
            product_line=self.product_line_julover, admin_fee=40000)
        self.application_status_code = StatusLookupFactory(code=190)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            bank_name='bank_test',
            name_in_bank='name_in_bank',
            workflow=self.workflow
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_xid=random.randint(3000000000, 3100000000),
            product=self.product_lookup
        )
        self.customer_j1 = CustomerFactory()
        self.account_j1 = AccountFactory(customer=self.customer)
        self.application_j1 = ApplicationJ1Factory(
            account=self.account_j1,
            customer=self.customer_j1,
            email='test@gmail.com',
        )
        self.loan_j1 = LoanFactory(account=self.account_j1)
        self.julover = JuloverFactory(application_id=self.application_j1.id, email='abcxyz@gmail.com')

    def test_get_julo_loan_agreement_template_grab(self):
        return_value = get_julo_loan_agreement_template(loan_id=self.loan.id)
        self.assertEqual(len(return_value), 4)
        self.assertEqual(return_value, (
            mock.ANY, 'sphp', GrabLenderAgreementLenderSignature,
            GrabLoanAgreementBorrowerSignature
        ))

    def test_get_julo_loan_agreement_template_julo_one_sphp(self):
        return_value = get_julo_loan_agreement_template(loan_id=self.loan_j1.id)
        self.assertEqual(len(return_value), 4)
        self.assertEqual(return_value, (
            mock.ANY, 'skrtp', LoanAgreementLenderSignature,
            LoanAgreementBorrowerSignature
        ))

    def test_get_julo_loan_agreement_template_julo_one_skrtp(self):
        document = DocumentFactory(
            document_type="master_agreement",
            document_source=self.application_j1.id
        )
        document.save()
        return_value = get_julo_loan_agreement_template(loan_id=self.loan_j1.id)
        self.assertEqual(len(return_value), 4)
        self.assertEqual(return_value, (
            mock.ANY, 'skrtp', LoanAgreementLenderSignature,
            LoanAgreementBorrowerSignature
        ))

    def test_get_julo_loan_agreement_template_julover_sphp(self):
        application = self.account_j1.application_set.last()
        application.product_line = self.product_line_julover
        application.save()
        return_value = get_julo_loan_agreement_template(loan_id=self.loan_j1.id)
        self.assertEqual(len(return_value), 4)
        self.assertEqual(return_value, (
            mock.ANY, 'sphp', JuloverLoanAgreementLenderSignature,
            JuloverLoanAgreementBorrowerSignature
        ))


class TestGetTotalOutstandingForLender(TestCase):
    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_get_total_outstanding_for_lender(self, mock_get_redis_client):
        mock_redis_helper = MockRedisHelper()
        mock_get_redis_client.return_value = mock_redis_helper

        lender_name = 'jh'
        day_filter = datetime(year=2023, month=5, day=25).date()
        cache_key = 'total_outstanding:{}:{}'.format(lender_name, day_filter.strftime("%Y-%m-%d"))

        # TEST NOT EXIST SUITABLE DATA IN sb.daily_osp_product_lender
        # no record on sb.daily_osp_product_lender
        mock_redis_helper.delete_key(key=cache_key)
        self.assertEqual(
            get_total_outstanding_for_lender(lender_name=lender_name, day_filter=day_filter),
            0
        )

        # have records on sb.daily_osp_product_lender but not match lender_name
        SbDailyOspProductLenderFactory(
            day=day_filter,
            lender='other_lender',
            current=1000001,
        )
        mock_redis_helper.delete_key(key=cache_key)
        self.assertEqual(
            get_total_outstanding_for_lender(lender_name=lender_name, day_filter=day_filter),
            0
        )

        # have records on sb.daily_osp_product_lender but not match day
        SbDailyOspProductLenderFactory(
            day=day_filter - timedelta(days=3),
            lender=lender_name,
            current=1000002
        )
        mock_redis_helper.delete_key(key=cache_key)
        self.assertEqual(
            get_total_outstanding_for_lender(lender_name=lender_name, day_filter=day_filter),
            0
        )

        # have records is previous day of day_filter on sb.daily_osp_product_lender
        SbDailyOspProductLenderFactory(
            day=day_filter - timedelta(days=1),
            lender=lender_name,
            current=100000212
        )
        mock_redis_helper.delete_key(key=cache_key)
        self.assertEqual(
            get_total_outstanding_for_lender(lender_name=lender_name, day_filter=day_filter),
            100000212
        )

        # TEST HAVE SUITABLE DATA
        SbDailyOspProductLenderFactory(
            day=day_filter,
            lender=lender_name,
            product='J1',
            current=1000001,
            dpd1=1000002,
            dpd30=1000003,
            dpd60=1000004,
            dpd90=1000005,
            dpd120=1000006,
            dpd150=1000007,
            dpd180=1000008,
        )
        SbDailyOspProductLenderFactory(
            day=day_filter,
            lender=lender_name,
            product='GRAB',
            current=1,
            dpd1=2,
            dpd30=3,
            dpd60=4,
            dpd90=5,
            dpd120=6,
            dpd150=7,
            dpd180=8,
        )
        mock_redis_helper.delete_key(key=cache_key)
        self.assertEqual(
            get_total_outstanding_for_lender(lender_name=lender_name, day_filter=day_filter),
            7000056
        )

        # TEST GET DATA FROM CACHE
        mock_redis_helper.set(key=cache_key, value=123)
        self.assertEqual(
            get_total_outstanding_for_lender(lender_name=lender_name, day_filter=day_filter),
            123
        )


class TestGetMaxLimitFunction(UnitTestCase):
    def test_max_limit(self):
        max_limit = 5

        # ok
        limit = '3'
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, 3)

        limit = 4
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, limit)

        # empty string or None
        limit = ''
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, max_limit)

        limit = None
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, max_limit)

        # chars
        limit = 'a'
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, max_limit)

        limit = '0'
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, max_limit)

        # less than minimum value
        limit = 0
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, max_limit)

        limit = -5
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, max_limit)

        # case exceeding max
        limit = 30
        result = get_max_limit(limit, max_limit=max_limit)
        self.assertEqual(result, max_limit)


class TestLockRedisWithExTime(TestCase):
    def setUp(self) -> None:
        pass

    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_lock_on_redis_with_ex_time(self, mock_redis_client):
        mock_redis_client.return_value = MockRedisHelper()
        lock_on_redis_with_ex_time(
            key_name=RedisLockWithExTimeType.APPROVED_LOAN_ON_LENDER_DASHBOARD, unique_value=1
        )
        with self.assertRaises(DuplicateProcessing):
            lock_on_redis_with_ex_time(
                key_name=RedisLockWithExTimeType.APPROVED_LOAN_ON_LENDER_DASHBOARD, unique_value=1
            )

    @patch('juloserver.followthemoney.services.get_redis_client')
    def test_lock_on_redis_with_ex_time_already_expried(self, mock_redis_client):
        mock_redis_client.return_value = MockRedisHelper()
        lock_on_redis_with_ex_time(
            key_name=RedisLockWithExTimeType.APPROVED_LOAN_ON_LENDER_DASHBOARD, unique_value=1, ex=1
        )
        sleep(2)
        # no raise exception
        lock_on_redis_with_ex_time(
            key_name=RedisLockWithExTimeType.APPROVED_LOAN_ON_LENDER_DASHBOARD, unique_value=1
        )
