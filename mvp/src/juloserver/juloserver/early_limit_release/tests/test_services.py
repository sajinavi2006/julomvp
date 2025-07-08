import datetime
from unittest import mock
from unittest.mock import call

import pytz
import pytest
from django.test import TestCase
from django.utils import timezone
from django.db.models import Sum

from juloserver.early_limit_release.constants import (
    FeatureNameConst,
    LoanDurationsCheckReasons,
    PreRequisiteCheckReasons,
    ReleaseTrackingType
)
from juloserver.early_limit_release.exceptions import LoanPaidOffException
from juloserver.early_limit_release.services import (
    EarlyLimitReleaseService,
    check_early_limit_fs, update_or_create_release_tracking,
)
from juloserver.account.tests.factories import AccountFactory, AccountPropertyFactory, \
    AccountLimitFactory
from juloserver.early_limit_release.tests.factories import (
    EarlyReleaseLoanMappingFactory,
    EarlyReleaseExperimentFactory,
    ReleaseTrackingFactory,
    OdinConsolidatedFactory,
)
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
    LoanFactory,
    StatusLookupFactory,
    ProductLineFactory,
    FeatureSettingFactory,
    FDCInquiryFactory,
    FDCInquiryCheckFactory,
    FDCInquiryLoanFactory,
)
from juloserver.julo.models import Payment
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.early_limit_release.constants import (
    ExperimentOption,
    EarlyLimitReleaseMoengageStatus,
)
from juloserver.early_limit_release.models import (
    EarlyReleaseCheckingV2,
    ReleaseTracking,
    ReleaseTrackingHistory, EarlyReleaseCheckingHistoryV2,
)
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.models import MoengageUpload
from juloserver.moengage.services.use_cases import \
    send_user_attributes_to_moengage_for_early_limit_release
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.loan_refinancing.constants import CovidRefinancingConst


class TestEarlyLimitReleaseService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_property = AccountPropertyFactory(account=self.account)
        self.account_property.save()
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=5000000)
        self.odin_consolidated = OdinConsolidatedFactory(customer_id=self.customer.id)

        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=220),
        )
        self.loan.save()
        self.payments = Payment.objects.filter(loan=self.loan)

        self.experiment = EarlyReleaseExperimentFactory(
            option=ExperimentOption.OPTION_2,
            criteria={
                'last_cust_digit': {'from': '00', 'to': '19'},
                'loan_duration_payment_rules': {'5': 3, '6': 3, '9': 2},
            }
        )

        self.customer1 = CustomerFactory()
        self.account1 = AccountFactory(customer=self.customer1)
        self.account1.id = int(str(self.account1.id) + '00')
        self.customer2 = CustomerFactory()
        self.account2 = AccountFactory(customer=self.customer2)
        self.account2.id = int(str(self.account2.id) + '22')
        self.customer3 = CustomerFactory()
        self.account3 = AccountFactory(customer=self.customer3)
        self.account3.id = int(str(self.account3.id) + '90')

        self.fdc_inquiry = FDCInquiryFactory()
        self.fdc_inquiry_check = FDCInquiryCheckFactory()
        self.fdc_inquiry_loan = FDCInquiryLoanFactory()
        self.feature_setting = FeatureSettingFactory(
            feature_name='fdc_inquiry_check', is_active=True
        )
        self.fdc_inquiry.application_id = self.application.id
        self.fdc_inquiry.inquiry_status = 'success'
        self.fdc_inquiry.inquiry_date = datetime.date(2020, 1, 1)
        self.fdc_inquiry.save()

        self.fdc_inquiry_check.min_threshold = 0.8
        self.fdc_inquiry_check.max_threshold = 1.1
        self.fdc_inquiry_check.is_active = True

        self.feature_setting_early = FeatureSettingFactory(
            feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE, is_active=True,
            parameters={
                'minimum_used_limit': 100
            }
        )

    def test_pre_requisite_check(self):
        self.payments[0].update_safely(due_amount=0)
        self.account_property.is_entry_level = False
        self.account_property.save()
        loan_refinancing_request = LoanRefinancingRequestFactory()
        loan_refinancing_request.update_safely(
            account=self.account,
            status=CovidRefinancingConst.STATUSES.approved,
            offer_activated_ts=datetime.date.today() + datetime.timedelta(days=1)
        )

        # FAILED: has loan refinancing request
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )
        result = service.check_pre_requisite()
        self.assertFalse(result['status'])
        self.assertEqual(
            result['reason'],
            PreRequisiteCheckReasons.FAILED_CUSTOMER_HAS_LOAN_REFINANCING
        )

        # PASSED
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )
        loan_refinancing_request.update_safely(
            offer_activated_ts=datetime.date.today()
        )
        result = service.check_pre_requisite()
        self.assertTrue(result['status'])

    def test_payment_paid_on_time_success(self):
        self.account_property.is_entry_level = False
        self.account_property.save()
        payment = self.payments[0]
        payment.update_safely(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        )

        service = EarlyLimitReleaseService(
            payment=payment,
            loan=self.loan,
            account=self.account
        )
        result = service.check_paid_on_time()
        self.assertTrue(result.get('status'))

    def test_payment_paid_on_time_fail(self):
        self.account_property.is_entry_level = False
        self.account_property.save()
        payment = self.payments[0]
        payment.update_safely(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_LATE)
        )

        service = EarlyLimitReleaseService(
            payment=payment,
            loan=self.loan,
            account=self.account
        )
        result = service.check_paid_on_time()
        self.assertFalse(result.get('status'))

        # not fully paid
        payment.update_safely(
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        )

        service = EarlyLimitReleaseService(
            payment=payment,
            loan=self.loan,
            account=self.account
        )
        result = service.check_paid_on_time()
        self.assertFalse(result.get('status'))

    def test_check_regular_customer_success(self):
        self.account_property.is_entry_level = False
        self.account_property.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )

        result = service.check_regular_customer()
        self.assertTrue(result.get('status'))

    def test_check_regular_customer_fail(self):
        self.account_property.is_entry_level = True
        self.account_property.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )

        result = service.check_regular_customer()
        self.assertFalse(result.get('status'))

    def test_check_customer_pgood_success(self):
        self.experiment.criteria['pgood'] = "0.7"
        self.experiment.save()

        self.account_property.pgood = 0.8
        self.account_property.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )

        service.experiment = self.experiment

        result = service.check_customer_pgood()
        self.assertTrue(result.get('status'))

    def test_check_customer_pgood_failed(self):
        self.experiment.criteria['pgood'] = "0.7"
        self.experiment.save()

        self.account_property.pgood = 0.2
        self.account_property.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )

        service.experiment = self.experiment

        result = service.check_customer_pgood()
        self.assertFalse(result.get('status'))

    def test_check_customer_odin_success(self):
        self.experiment.criteria['odin'] = "0.7"
        self.experiment.save()

        self.odin_consolidated.odin_consolidated = 0.8
        self.odin_consolidated.save()


        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )

        service.experiment = self.experiment

        result = service.check_customer_odin()
        self.assertTrue(result.get('status'))

    def test_check_customer_odin_failed(self):
        self.experiment.criteria['odin'] = "0.7"
        self.experiment.save()

        self.odin_consolidated.odin_consolidated = 0.35
        self.odin_consolidated.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )

        service.experiment = self.experiment

        result = service.check_customer_odin()
        self.assertFalse(result.get('status'))

    def test_check_repeat_customer_success(self):
        # pass due to fund_transfer_ts > paid_date or valid product line
        init_payment = Payment.objects.filter(loan=self.loan).first()
        init_payment.update_safely(paid_date=datetime.datetime(2023, 3, 4).date())
        loan = LoanFactory(
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            fund_transfer_ts=datetime.datetime.now(),
        )
        compared_payment = Payment.objects.filter(loan=loan).first()
        service = EarlyLimitReleaseService(compared_payment, loan, self.account)
        result = service.check_repeat_customer()
        self.assertTrue(result['status'])

        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER)
        )
        service = EarlyLimitReleaseService(compared_payment, loan, self.account)
        result = service.check_repeat_customer()
        self.assertTrue(result['status'])

    def test_check_repeat_customer_fail(self):
        # Fail due to different product line
        init_payment = Payment.objects.filter(loan=self.loan).first()
        init_payment.update_safely(paid_date=datetime.datetime.now() + datetime.timedelta(days=3))
        loan = LoanFactory(
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            fund_transfer_ts=datetime.datetime.now(),
        )
        compared_payment = Payment.objects.filter(loan=loan).first()

        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        service = EarlyLimitReleaseService(compared_payment, loan, self.account)
        result = service.check_repeat_customer()
        self.assertFalse(result['status'])

    def test_check_repeat_customer_paid_date_none(self):
        init_payment = Payment.objects.filter(loan=self.loan).first()
        service = EarlyLimitReleaseService(init_payment, self.loan, self.account)
        result = service.check_repeat_customer()
        self.assertFalse(result['status'])

    def test_check_repeat_customer_timezone_utc(self):
        init_payment = Payment.objects.filter(loan=self.loan).first()
        init_payment.update_safely(paid_date=timezone.localtime(timezone.now()).date())
        loan = LoanFactory(
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            fund_transfer_ts=timezone.now(),
        )
        compared_payment = Payment.objects.filter(loan=loan).first()
        service = EarlyLimitReleaseService(compared_payment, loan, self.account)
        result = service.check_repeat_customer()
        self.assertFalse(result['status'])

        loan.update_safely(
            fund_transfer_ts=timezone.localtime(timezone.now()) + datetime.timedelta(days=1)
        )
        compared_payment = Payment.objects.filter(loan=loan).first()
        service = EarlyLimitReleaseService(compared_payment, loan, self.account)
        result = service.check_repeat_customer()
        self.assertTrue(result['status'])

    def test_check_repeat_customer_loan_status_not_current(self):
        self.loan.update_safely(
            loan_status=StatusLookupFactory(
                status_code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING
            )
        )
        loan = LoanFactory(
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            fund_transfer_ts=timezone.now(),
        )
        init_payment = Payment.objects.filter(loan=loan).first()
        init_payment.update_safely(paid_date=datetime.datetime.now() - datetime.timedelta(days=10))
        loan_2 = LoanFactory(
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            fund_transfer_ts=timezone.now(),
        )
        compared_payment = Payment.objects.filter(loan=loan).first()
        service = EarlyLimitReleaseService(compared_payment, loan_2, self.account)
        result = service.check_repeat_customer()
        self.assertTrue(result['status'])

    @pytest.mark.skip(reason="flaky")
    def test_check_loan_durations(self):
        # failed missing config
        service = EarlyLimitReleaseService(
            payment=self.payments[0], loan=self.loan, account=self.account
        )
        result = service.check_loan_durations()
        self.assertFalse(result['status'])
        self.assertEqual(result['reason'], LoanDurationsCheckReasons.MISSING_EXPERIMENT_CONFIG)

        criteria = {'loan_duration_payment_rules': {'5': 3, '6': 3, '9': 2}}
        early_release_loan = EarlyReleaseLoanMappingFactory(
            loan=self.loan, experiment=EarlyReleaseExperimentFactory(criteria=criteria)
        )
        # failed loan duration
        self.loan.update_safely(loan_duration=4)
        service = EarlyLimitReleaseService(
            payment=self.payments[0], loan=self.loan, account=self.account
        )
        service.experiment = early_release_loan.experiment
        result = service.check_loan_durations()
        self.assertFalse(result['status'])
        self.assertEqual(result['reason'], LoanDurationsCheckReasons.LOAN_DURATION_FAILED)

        # failed min payment
        self.loan.update_safely(loan_duration=5)
        self.payments[0].update_safely(payment_number=1)
        service = EarlyLimitReleaseService(
            payment=self.payments[0], loan=self.loan, account=self.account
        )
        service.experiment = early_release_loan.experiment
        result = service.check_loan_durations()
        self.assertFalse(result['status'])
        self.assertEqual(result['reason'], LoanDurationsCheckReasons.MIN_PAYMENT_FAILED)

        # success
        self.payments[0].update_safely(payment_number=3)
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account,
        )
        service.experiment = early_release_loan.experiment
        result = service.check_loan_durations()
        self.assertTrue(result['status'])
        self.assertEqual(
            result['reason'], LoanDurationsCheckReasons.PASSED_LOAN_DURATION_PAYMENT_RULE
        )

    def test_check_used_limit_customer_success(self):
        # Pass because loan amount is >= set limit * Used limit
        self.loan.update_safely(loan_amount=self.account_limit.set_limit)
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )
        result = service.check_used_limit_customer()
        self.assertTrue(result['status'])

        self.feature_setting_early.update_safely(parameters={'minimum_used_limit': 80})
        result = service.check_used_limit_customer()
        self.assertTrue(result['status'])

        self.feature_setting_early.update_safely(parameters={})
        result = service.check_used_limit_customer()
        self.assertTrue(result['status'])

    def test_check_used_limit_customer_failed(self):
        # Fail because loan amount is < set limit * Used limit
        lower_loan_amount = self.account_limit.set_limit * 0.8
        self.loan.update_safely(loan_amount=lower_loan_amount)
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )
        result = service.check_used_limit_customer()
        self.assertFalse(result['status'])

        self.feature_setting_early.update_safely(parameters={'minimum_used_limit': 90})
        result = service.check_used_limit_customer()
        self.assertFalse(result['status'])

    def test_check_all(self):
        self.account_property.is_entry_level = False
        self.account_property.save()
        criteria = {
            'last_cust_digit': {'from': '00', 'to': '99'},
            'loan_duration_payment_rules': {'5': 3, '6': 3, '9': 2},
        }
        init_payment = Payment.objects.filter(loan=self.loan).first()
        init_payment.update_safely(paid_date=datetime.datetime(2023, 3, 4).date())
        loan = LoanFactory(
            loan_amount=self.account_limit.set_limit,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            fund_transfer_ts=datetime.datetime.now(),
            loan_duration=6,
        )
        compared_payment = Payment.objects.filter(loan=loan).first()
        compared_payment.update_safely(
            payment_number=3,
            due_amount=0,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        )
        service = EarlyLimitReleaseService(
            payment=compared_payment, loan=loan, account=self.account
        )
        experiment = EarlyReleaseExperimentFactory(
            criteria=criteria,
            option=ExperimentOption.OPTION_2,
            is_active=True,
            is_delete=False
        )
        service.experiment = experiment
        self.experiment.is_active = False
        self.experiment.save()
        _ = service.check_all_rules()
        checkings = EarlyReleaseCheckingV2.objects.filter(payment_id=compared_payment.id)

        self.assertEqual(1, len(checkings))
        early_release_checking = EarlyReleaseCheckingV2.objects.filter(
            payment_id=compared_payment.id
        ).last()
        expected_result = {
            'fdc': {'status': True},
            'repeat': {'status': True},
            'regular': {'status': True},
            'used_limit': {'status': True},
            'paid_on_time': {'status': True},
            'loan_duration': {'status': True},
            'pre_requisite': {'status': True},
            'experimentation': {'status': True}
        }
        checking_result = early_release_checking.checking_result
        self.assertEqual(checking_result, expected_result)

        compared_payment.update_safely(payment_status_id=332)
        _ = service.check_all_rules()
        history = EarlyReleaseCheckingHistoryV2.objects.filter(checking=early_release_checking).last()
        self.assertIsNotNone(history)
        self.assertEqual(
            history.value_old,
            {
                'fdc': {'status': True},
                'repeat': {'status': True},
                'regular': {'status': True},
                'used_limit': {'status': True},
                'paid_on_time': {'status': True},
                'loan_duration': {'status': True},
                'pre_requisite': {'status': True},
                'experimentation': {'status': True}
            }
        )
        self.assertEqual(
            history.value_new, {
                'paid_on_time': {'reason': 'Payment not paid on time', 'status': False},
                'pre_requisite': {'status': True}
            }
        )

    def test_check_all_with_pgood_and_odin(self):
        self.account_property.update_safely(is_entry_level=False, pgood=0.85)
        self.odin_consolidated.update_safely(odin_consolidated=0.8)
        criteria = {
            'last_cust_digit': {'from': '00', 'to': '99'},
            'loan_duration_payment_rules': {'5': 3, '6': 3, '9': 2},
            'pgood': 0.7,
            'odin': 0.75
        }
        init_payment = Payment.objects.filter(loan=self.loan).first()
        init_payment.update_safely(paid_date=datetime.datetime(2023, 3, 4).date())
        loan = LoanFactory(
            loan_amount=self.account_limit.set_limit,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            fund_transfer_ts=datetime.datetime.now(),
            loan_duration=6,
        )
        compared_payment = Payment.objects.filter(loan=loan).first()
        compared_payment.update_safely(
            payment_number=3,
            due_amount=0,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        )
        service = EarlyLimitReleaseService(
            payment=compared_payment, loan=loan, account=self.account
        )
        experiment = EarlyReleaseExperimentFactory(
            criteria=criteria,
            option=ExperimentOption.OPTION_2,
            is_active = True,
            is_delete = False
        )
        service.experiment = experiment
        self.experiment.is_active = False
        self.experiment.save()
        _ = service.check_all_rules()
        checkings = EarlyReleaseCheckingV2.objects.filter(payment_id=compared_payment.id)

        self.assertEqual(1, len(checkings))
        early_release_checking = EarlyReleaseCheckingV2.objects.filter(
            payment_id=compared_payment.id
        ).last()
        expected_result = {
            'fdc': {'status': True},
            'pgood': {'status': True},
            'odin': {'status': True},
            'repeat': {'status': True},
            'regular': {'status': True},
            'used_limit': {'status': True},
            'paid_on_time': {'status': True},
            'loan_duration': {'status': True},
            'pre_requisite': {'status': True},
            'experimentation': {'status': True}
        }
        checking_result = early_release_checking.checking_result
        self.assertEqual(checking_result, expected_result)

    def test_check_all_with_loan_paid_off(self):
        self.account_property.is_entry_level = False
        self.account_property.save()
        criteria = {
            'last_cust_digit': {'from': '00', 'to': '19'},
            'loan_duration_payment_rules': {'5': 3, '6': 3, '9': 2},
        }
        init_payment = Payment.objects.filter(loan=self.loan).first()
        init_payment.update_safely(paid_date=datetime.datetime(2023, 3, 4).date())
        loan = LoanFactory(
            loan_amount=self.account_limit.set_limit,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            fund_transfer_ts=datetime.datetime.now(),
            loan_duration=6,
        )
        compared_payment = Payment.objects.filter(loan=loan).first()
        compared_payment.update_safely(
            payment_number=3,
            due_amount=0,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        )
        service = EarlyLimitReleaseService(
            payment=compared_payment, loan=loan, account=self.account
        )
        early_release_loan = EarlyReleaseLoanMappingFactory(
            loan=loan,
            experiment=EarlyReleaseExperimentFactory(
                criteria=criteria,
                option=ExperimentOption.OPTION_2
            )
        )
        service.experiment = early_release_loan.experiment
        loan.update_safely(loan_status_id=LoanStatusCodes.PAID_OFF)
        with self.assertRaises(LoanPaidOffException):
            service.release()

    def test_experiment_option_1_success(self):
        loan = LoanFactory(
            account=self.account1,
            customer=self.customer1,
            loan_status=StatusLookupFactory(status_code=220),
        )

        self.experiment.option = ExperimentOption.OPTION_2
        self.experiment.criteria = {
            'last_cust_digit': {'from': '00', 'to': '19'},
            'loan_duration_payment_rules': {5: 3, 6: 3, 9: 2},
        }
        self.experiment.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=loan,
            account=self.account1,
        )
        result = service.check_experimentation()
        self.assertTrue(result.get('status'))

    def test_experiment_option_2_success(self):
        loan = LoanFactory(
            account=self.account2,
            customer=self.customer2,
            loan_status=StatusLookupFactory(status_code=220),
        )

        self.experiment.option = ExperimentOption.OPTION_2
        self.experiment.criteria = {
            'last_cust_digit': {'from': '20', 'to': '89'},
            'loan_duration_payment_rules': {5: 3, 6: 3, 9: 2},
        }
        self.experiment.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=loan,
            account=self.account2,
        )
        result = service.check_experimentation()
        self.assertTrue(result.get('status'))

    def test_exist_experiment_is_delete(self):
        loan = LoanFactory(
            account=self.account1,
            customer=self.customer1,
            loan_status=StatusLookupFactory(status_code=220),
        )
        self.experiment.is_delete = True
        self.experiment.save()
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=loan,
            account=self.account1,
        )
        result = service.check_experimentation()
        self.assertFalse(result.get('status'))

    def test_exist_experiment_not_is_active_1(self):
        loan = LoanFactory(
            account=self.account1,
            customer=self.customer1,
            loan_status=StatusLookupFactory(status_code=220),
        )
        self.experiment.is_active = True
        self.experiment.is_delete = False
        self.experiment.save()
        EarlyReleaseLoanMappingFactory(loan=loan, experiment=self.experiment)
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=loan,
            account=self.account1,
        )
        result = service.check_experimentation()
        self.assertTrue(result.get('status'))

    def test_exist_experiment_not_is_active_2(self):
        loan = LoanFactory(
            account=self.account1,
            customer=self.customer1,
            loan_status=StatusLookupFactory(status_code=220),
        )
        self.experiment.is_active = True
        self.experiment.is_delete = True
        self.experiment.save()
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=loan,
            account=self.account1,
        )
        result = service.check_experimentation()
        self.assertFalse(result.get('status'))

    def test_fdc_binary_check_with_threshold(self):
        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )
        result = service.check_fdc_customer()
        self.assertTrue(result.get('status'))

    def test_fdc_binary_check_with_tidak_lancar_failed(self):
        # check tidak_lancar / macet count
        # failed by min_macet_pct
        self.fdc_inquiry_check.min_macet_pct = -1
        self.fdc_inquiry_check.save()

        self.fdc_inquiry_loan.fdc_inquiry_id = self.fdc_inquiry.id
        self.fdc_inquiry_loan.tgl_pelaporan_data = datetime.date(2020, 8, 1)
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Macet (>90)'
        self.fdc_inquiry_loan.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account)
        result = service.check_fdc_customer()
        self.assertFalse(result.get('status'))

    def test_fdc_binary_check_with_paid_pct_failed(self):
        # failed by max_paid_pct = 3
        self.fdc_inquiry_check.inquiry_date = datetime.date(2020, 1, 1)
        self.fdc_inquiry_check.min_macet_pct = 2
        self.fdc_inquiry_check.min_tidak_lancar = 2
        self.fdc_inquiry_check.max_paid_pct = 3
        self.fdc_inquiry_check.save()

        self.fdc_inquiry_loan.fdc_inquiry = self.fdc_inquiry
        self.fdc_inquiry_loan.tgl_pelaporan_data = datetime.date(2020, 1, 2)
        self.fdc_inquiry_loan.tgl_jatuh_tempo_pinjaman = datetime.date(2020, 7, 1)
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Tidak Lancar (30 sd 90 hari)'
        self.fdc_inquiry_loan.total = 1
        self.fdc_inquiry_loan.nilai_pendanaan = 100
        self.fdc_inquiry_loan.sisa_pinjaman_berjalan = 50
        self.fdc_inquiry_loan.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )
        result_fdc_check = service.check_fdc_customer()
        self.assertFalse(result_fdc_check.get('status'))

    def test_fdc_binary_check_with_paid_pct_passed(self):
        # passed by max_paid_pct = 0.1
        self.fdc_inquiry_check.inquiry_date = datetime.date(2020, 1, 1)
        self.fdc_inquiry_check.min_macet_pct = 2
        self.fdc_inquiry_check.min_tidak_lancar = 2
        self.fdc_inquiry_check.max_paid_pct = 0.1
        self.fdc_inquiry_check.save()

        self.fdc_inquiry_loan.fdc_inquiry = self.fdc_inquiry
        self.fdc_inquiry_loan.tgl_pelaporan_data = datetime.date(2020, 1, 2)
        self.fdc_inquiry_loan.tgl_jatuh_tempo_pinjaman = datetime.date(2020, 7, 1)
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Tidak Lancar (30 sd 90 hari)'
        self.fdc_inquiry_loan.total = 1
        self.fdc_inquiry_loan.nilai_pendanaan = 100
        self.fdc_inquiry_loan.sisa_pinjaman_berjalan = 50
        self.fdc_inquiry_loan.save()

        service = EarlyLimitReleaseService(
            payment=self.payments[0],
            loan=self.loan,
            account=self.account
        )
        result = service.check_fdc_customer()
        self.assertTrue(result.get('status'))

    @mock.patch('juloserver.moengage.services.use_cases.send_to_moengage')
    @mock.patch('juloserver.moengage.services.data_constructors.timezone')
    def test_send_user_attributes_to_moengage_for_early_limit_release(self, mock_timezone,
                                                                      mock_send_to_moengage):
        mock_now = timezone.localtime(timezone.now())
        mock_now = mock_now.replace(
            year=2020, month=12, day=1, hour=23, minute=59, second=59, microsecond=0, tzinfo=
            pytz.utc
        )
        mock_timezone.localtime.return_value = mock_now
        ReleaseTrackingFactory(
            limit_release_amount=1000000,
            account=self.loan.account,
            loan=self.loan,
            payment=self.payments[0],
            cdate=datetime.datetime(2023, 5, 18)
        )
        send_user_attributes_to_moengage_for_early_limit_release(
            self.customer.id, 1000000, EarlyLimitReleaseMoengageStatus.SUCCESS
        )
        data_to_send = [
            {
                "type": "customer",
                "customer_id": self.customer.id,
                "attributes": {
                    "customer_id": self.customer.id,
                    "platforms": [
                        {
                            "platform": "ANDROID",
                            "active": "true"
                        }
                    ]
                }
            },
            {
                'type': 'event',
                'customer_id': self.customer.id,
                'device_id': self.application.device.gcm_reg_id,
                'actions': [
                    {
                        'action': MoengageEventType.EARLY_LIMIT_RELEASE,
                        'attributes': {
                            "status": "success",
                            "limit_release_amount": 'Rp 1.000.000',
                        },
                        'platform': 'ANDROID',
                        'current_time': mock_now.timestamp(),
                        'user_timezone_offset': mock_now.utcoffset().seconds,
                    }
                ]
            }
        ]
        moengage_upload = MoengageUpload.objects.filter(
            type=MoengageEventType.EARLY_LIMIT_RELEASE,
            customer_id=self.customer.id,
        ).last()
        calls = [
            call([moengage_upload.id], data_to_send),
        ]
        mock_send_to_moengage.delay.assert_has_calls(calls)


class TestFeatureSettingEarlyLimitRelease(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE, is_active=True
        )

    def test_feature_setting(self):
        check = check_early_limit_fs()
        self.assertTrue(check)

        self.feature_setting.update_safely(is_active=False)
        check = check_early_limit_fs()
        self.assertFalse(check)


class TestReleaseLimitOptions(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_property = AccountPropertyFactory(account=self.account)
        self.account_property.save()
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
            set_limit=9000000,
            used_limit=9000000,
            available_limit=0
        )

        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=220),
            loan_duration=5
        )
        criteria = {
            'loan_duration_payment_rules': {
                5: 3, 6: 3, 9: 2
            }
        }

        self.experiment_option_2 = EarlyReleaseExperimentFactory(
            criteria=criteria, option=ExperimentOption.OPTION_2
        )

    def test_release_limit_option_2(self):
        # first time
        early_limit_amount = 100000
        payment = Payment.objects.filter(loan_id=self.loan.pk, payment_number=3).first()
        payment.installment_principal = early_limit_amount
        payment.save()
        service = EarlyLimitReleaseService(
            payment=payment,
            loan=self.loan,
            account=self.account
        )
        service.experiment = self.experiment_option_2
        service.release()
        tracking = ReleaseTracking.objects.filter(payment_id=payment.pk).first()
        self.account_limit.refresh_from_db()

        assert self.account_limit.available_limit == early_limit_amount
        assert tracking.limit_release_amount == early_limit_amount

        # second time
        payment = Payment.objects.filter(loan_id=self.loan.pk, payment_number=4).first()
        payment.installment_principal = early_limit_amount
        payment.save()
        service = EarlyLimitReleaseService(
            payment=payment,
            loan=self.loan,
            account=self.account
        )
        service.experiment = self.experiment_option_2
        service.release()
        tracking = ReleaseTracking.objects.filter(payment_id=payment.pk).first()

        self.account_limit.refresh_from_db()
        assert self.account_limit.available_limit == early_limit_amount * 2
        assert tracking.limit_release_amount == early_limit_amount
        assert self.account_limit.available_limit


class TestUpdateOrCreateReleaseTracking(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_property = AccountPropertyFactory(account=self.account)
        self.account_property.save()
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application_id2=self.application.id,
            loan_status=StatusLookupFactory(status_code=220),
            loan_duration=5
        )

    def test_update_or_create_release_tracking_history(self):
        update_or_create_release_tracking(
            self.loan.id, self.account.id, 100000, tracking_type=ReleaseTrackingType.LAST_RELEASE
        )
        release_tracking = ReleaseTracking.objects.get(
            loan_id=self.loan.id, account_id=self.account.id, limit_release_amount=100000,
            type=ReleaseTrackingType.LAST_RELEASE
        )
        tracking_histories = list(ReleaseTrackingHistory.objects.filter(
            release_tracking=release_tracking
        ))
        self.assertEqual(tracking_histories, [])

        # update 2nd will create history
        update_or_create_release_tracking(
            self.loan.id, self.account.id, 100000, tracking_type=ReleaseTrackingType.LAST_RELEASE
        )
        release_tracking = ReleaseTracking.objects.get(
            loan_id=self.loan.id, account_id=self.account.id, limit_release_amount=100000,
            type=ReleaseTrackingType.LAST_RELEASE
        )
        tracking_history = ReleaseTrackingHistory.objects.get(
            release_tracking=release_tracking,
            field_name='limit_release_amount'
        )
        self.assertGreater(tracking_history.id, 0)
