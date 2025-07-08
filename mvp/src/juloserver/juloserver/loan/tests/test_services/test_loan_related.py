from collections import namedtuple
import math
from unittest.mock import patch
from datetime import date
from freezegun import freeze_time
from django.db.models import Q

import pytz
from django.utils import timezone
from django.test.testcases import TestCase
import mock
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from django.db.models import Sum, signals
from mock import call, patch
from pytest import mark
from rest_framework.status import HTTP_400_BAD_REQUEST

from juloserver.julocore.python2.utils import py2round
from juloserver.account.models import (
    AccountTransaction,
    CreditLimitGeneration,
    CurrentCreditMatrix,
    AccountGTL,
    AccountGTLHistory,
)
from juloserver.account_payment.services.account_payment_related import void_ppob_transaction
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.ana_api.tests.factories import FDCPlatformCheckBypassFactory, \
    PdApplicationFraudModelResultFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.early_limit_release.constants import ReleaseTrackingType
from juloserver.early_limit_release.models import ReleaseTracking
from juloserver.early_limit_release.tests.factories import ReleaseTrackingFactory
from juloserver.followthemoney.factories import LenderCurrentFactory, ApplicationHistoryFactory
from juloserver.followthemoney.models import LenderTransactionMapping
from juloserver.julo.formulas import round_rupiah
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julocore.constants import RedisWhiteList
from juloserver.loan.exceptions import CreditMatrixNotFound
from juloserver.loan.models import TransactionRiskyCheck, LoanTransactionDetail
from juloserver.loan.services.lender_related import (
    return_lender_balance_amount,
    julo_one_loan_disbursement_success,
)
from juloserver.moengage.constants import MoengageEventType
from juloserver.portal.object.product_profile.tests.test_product_profile_services import ProductProfileFactory
from juloserver.referral.constants import ReferralBenefitConst, ReferralLevelConst, \
    ReferralPersonTypeConst
from juloserver.referral.models import ReferralBenefitHistory
from juloserver.referral.signals import invalidate_cache_referee_count
from juloserver.referral.tests.factories import (
    ReferralBenefitFactory,
    ReferralLevelFactory,
    ReferralBenefitFeatureSettingFactory
)
from juloserver.streamlined_communication.models import InAppNotificationHistory
from juloserver.loan.tasks.campaign import trigger_reward_cashback_for_limit_usage
from juloserver.loan.services.loan_related import (
    calculate_max_duration_from_additional_month_param,
    get_credit_matrix_field_param,
    get_loan_credit_matrix_params,
    get_loan_duration,
    calculate_installment_amount,
    generate_loan_payment_julo_one,
    is_product_locked,
    notify_transaction_status_to_user,
    transaction_method_limit_check,
    trigger_reward_cashback_for_campaign_190,
    update_loan_status_and_loan_history,
    refiltering_cash_loan_duration,
    check_promo_code_julo_one,
    compute_payment_installment_julo_one,
    compute_first_payment_installment_julo_one,
    determine_transaction_method_by_transaction_type,
    suspicious_ip_loan_fraud_check,
    suspicious_hotspot_loan_fraud_check,
    calculate_loan_amount,
    transaction_web_location_blocked_check,
    get_range_loan_duration_and_amount_apply_zero_interest,
    is_eligible_apply_zero_interest,
    is_customer_segments_zero_interest,
    transaction_hardtoreach_check,
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
    is_eligible_other_active_platforms,
    check_eligible_and_out_date_other_platforms,
    get_fdc_loan_active_checking_for_daily_checker,
    get_parameters_fs_check_gtl,
    is_apply_gtl_inside,
    is_eligible_gtl_inside,
    check_lock_by_gtl_inside,
    get_credit_matrix_and_credit_matrix_product_line,
    create_or_update_is_maybe_gtl_inside,
    is_eligible_gtl_outside,
    is_b_score_satisfy_gtl_outside,
    is_repeat_user_gtl_outside,
    calculate_date_diff_m_and_m_minus_1_gtl_outside,
    is_fdc_loan_satisfy_gtl_outside,
    process_block_by_gtl_outside,
    process_block_by_gtl_inside,
    check_lock_by_gtl_outside,
    is_experiment_gtl_outside,
    is_apply_gtl_outside,
    process_check_gtl_outside,
    fill_dynamic_param_in_error_message_gtl_outside,
    process_check_gtl_inside,
    get_loan_amount_by_transaction_type,
    is_eligible_application_status,
    is_name_in_bank_mismatch,
    is_julo_one_product_locked_and_reason,
    is_qris_1_blocked,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    ProductLookupFactory,
    AuthUserFactory,
    CustomerFactory,
    BankFactory,
    CreditMatrixFactory,
    LoanFactory,
    WorkflowFactory,
    ReferralSystemFactory,
    ProductLineFactory,
    CreditScoreFactory,
    PaymentFactory,
    SepulsaTransactionFactory,
    AccountingCutOffDateFactory,
    LoanHistoryFactory,
    CustomerWalletHistoryFactory,
    ExperimentSettingFactory,
    CreditMatrixProductLineFactory,
    RefereeMappingFactory,
    ZeroInterestExcludeFactory,
    FDCInquiryFactory,
    FDCActiveLoanCheckingFactory,
    FDCInquiryLoanFactory,
    CreditMatrixRepeatFactory,
    PartnerFactory,
    MobileFeatureSettingFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountPropertyFactory,
    AccountLimitFactory,
    CreditLimitGenerationFactory,
    AccountGTLFactory,
)
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory
)
from juloserver.customer_module.models import CashbackBalance
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.models import (
    LoanHistory, StatusLookup, LoanStatusChange, FeatureSetting,
    Payment, CustomerWalletHistory, RefereeMapping, Application,
    FDCActiveLoanChecking,
    FDCInquiry, FDCRejectLoanTracking,
    CreditMatrixRepeatLoan,
)
from juloserver.payment_point.models import TransactionMethod, Vendor, SpendTransaction
from juloserver.account.constants import (
    AccountConstant,
    TransactionType,
    VoidTransactionType,
    CreditMatrixType,
    AccountLockReason,
)
from juloserver.loan.tests.factories import (
    TransactionRiskyDecisionFactory,
    TransactionMethodFactory,
)
from juloserver.loan.constants import (
    LoanFeatureNameConst,
    FDCUpdateTypes,
    ErrorCode,
    IS_NAME_IN_BANK_MISMATCH_TAG,
    LoanJuloOneConstant,
)
from juloserver.cfs.tests.factories import (
    CfsTierFactory,
    PdClcsPrimeResultFactory,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.promo.tests.factories import (
    PromoCodeBenefitConst,
    PromoCodeBenefitFactory,
    PromoCodeFactory,
    PromoCodeLoanFactory,
    PromoCodeUsageFactory,
)
from juloserver.promo.models import PromoHistory, WaivePromo
from juloserver.promo.services_v3 import get_apply_promo_code_benefit_handler_v2
from juloserver.streamlined_communication.models import InAppNotificationHistory
from juloserver.referral.services import process_referral_code_v2
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
)
from juloserver.balance_consolidation.constants import BalanceConsolidationStatus
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.referral.services import check_referral_cashback_v2
from juloserver.loan.tasks.lender_related import (
    process_loan_fdc_other_active_loan_from_platforms_task,
    fdc_inquiry_other_active_loans_from_platforms_task,
    fdc_inquiry_for_active_loan_from_platform_daily_checker_task,
    fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask,
)
from juloserver.loan.services.views_related import get_crossed_interest_and_installment_amount
from juloserver.loan.services.sphp import accept_julo_sphp
from juloserver.fdc.constants import FDCLoanStatus
from rest_framework.test import APIClient
from juloserver.application_flow.factories import (
    ApplicationPathTagStatusFactory,
    ApplicationTagFactory,
)
from juloserver.new_crm.tests.factories import ApplicationPathTagFactory
from juloserver.dana.tests.factories import DanaCustomerDataFactory
from juloserver.referral.constants import FeatureNameConst as ReferralFeatureNameConst
from juloserver.loan.constants import LoanTaxConst, LoanDigisignFeeConst
from juloserver.loan.models import (
    LoanAdditionalFee,
    LoanAdditionalFeeType,
)
from juloserver.digisign.tests.factories import DigisignRegistrationFeeFactory
from juloserver.digisign.constants import DigisignFeeTypeConst


http_request = namedtuple('http_request', ['META', 'user'])
event_response = namedtuple('Response', ['status_code'])


class TestLoanCalculation(TestCase):

    def setUp(self) -> None:
        three_days_ago = timezone.localtime(timezone.now()) - relativedelta(days=3)
        three_days_later = timezone.localtime(timezone.now()) + relativedelta(days=3)
        self.experiment = ExperimentSettingFactory(
            code='LoanDurationDetermination',
            start_date=three_days_ago,
            end_date=three_days_later
        )

    def test_get_loan_duration(self):
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000)
        self.assertEqual(len(loan_duration), 4)

    def test_get_loan_duration_feature_setting(self):
        parameters = {'number_of_loan_tenures': 5}
        FeatureSettingFactory(
            feature_name=FeatureNameConst.NUMBER_TENURE_OPTION,
            is_active=True,
            category='loan',
            parameters=parameters,
        )
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000)
        self.assertEqual(len(loan_duration), 5)

    def test_get_loan_duration_with_larger_number_tenure(self):
        parameters = {'number_of_loan_tenures': 10}
        FeatureSettingFactory(
            feature_name=FeatureNameConst.NUMBER_TENURE_OPTION,
            is_active=True,
            category='loan',
            parameters=parameters,
        )
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000)
        self.assertEqual(len(loan_duration), 5)

    def test_get_loan_duration__customer__with_experiment_customer_in_one_test_group(self):
        self.experiment.criteria = {"customer_id": ['#last:3:3']}
        self.experiment.save()
        customer = CustomerFactory(id='1000000003')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 3)

    def test_get_loan_duration__customer__with_experiment_customer_take_the_least_of_two_test_groups(self):
        self.experiment.criteria = {"customer_id": ['#last:3:3', '#last:2:3']}
        self.experiment.save()
        customer = CustomerFactory(id='1000000003')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 2)

    def test_get_loan_duration__customer__with_experiment__test_group_greater_than_calculation(self):
        self.experiment.criteria = {"customer_id": ['#last:8:3']}
        self.experiment.save()
        customer = CustomerFactory(id='1000000003')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 4)

    def test_get_loan_duration__customer__with_experiment_customer_not_filtered_in_test_group(self):
        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.save()
        customer = CustomerFactory(id='1000000004')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 4)

    def test_get_loan_duration__customer__with_experiment_incorrect_marker(self):
        self.experiment.criteria = {"customer_id": ['#nth:3:3', '#first:2:3']}
        self.experiment.save()
        customer = CustomerFactory(id='1000000003')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 4)

    def test_get_loan_duration_start_date_1_minute_before(self):
        """
        Test the precise timing loan duration activation.
        It should filtered when start time 1 minutes before
        """
        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.start_date = timezone.localtime(timezone.now()) - relativedelta(hours=1)
        self.experiment.save()

        customer = CustomerFactory(id='1000000003')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 2)

    def test_get_loan_duration_start_date_1_minute_after(self):
        """
        Test the precise timing loan duration activation.
        It should NOT filtered when start time 1 minutes after
        """
        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.start_date = timezone.localtime(timezone.now()) + relativedelta(hours=1)
        self.experiment.save()

        customer = CustomerFactory(id='1000000003')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 4)

    def test_get_loan_duration_end_date_1_minute_before(self):
        """
        Test the precise timing loan duration activation.
        It should NOT filtered when end time 1 minutes before
        """
        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.end_date = timezone.localtime(timezone.now()) - relativedelta(hours=1)
        self.experiment.save()

        customer = CustomerFactory(id='1000000003')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 4)

    def test_get_loan_duration_end_date_1_minute_after(self):
        """
        Test the precise timing loan duration activation.
        It should filtered when start time 1 minutes after
        """
        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.end_date = timezone.localtime(timezone.now()) + relativedelta(hours=1)
        self.experiment.save()

        customer = CustomerFactory(id='1000000003')
        loan_duration = get_loan_duration(3000000, 8, 1, 8000000, customer=customer)
        self.assertEqual(len(loan_duration), 2)

    # installment amount
    def test_calculate_installment_amount(self):
        installment_amount = calculate_installment_amount(3000000, 2, 0.2)
        self.assertEqual(installment_amount, 2100000)

    def test_get_loan_duration_with_credit_limit_generation(self):
        # loan_amount_request, max_duration, min_duration, set_limit, customer=None, application=None
        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.end_date = timezone.localtime(timezone.now()) - relativedelta(hours=1)
        self.experiment.save()

        customer = CustomerFactory(id='1000000003')
        application = ApplicationFactory(id='123123123', customer=customer)
        credit_limit_generation = CreditLimitGenerationFactory(
            application=application,
            log='{"simple_limit": 17532468, "reduced_limit": 15779221, '
            '"limit_adjustment_factor": 0.9, "max_limit (pre-matrix)": 8000000, '
            '"set_limit (pre-matrix)": 8000000}',
            max_limit=5000000,
            set_limit=5000000,
        )
        credit_limit_generation.save()
        loan_duration = get_loan_duration(
            3000000, 8, 1, 5000000, customer=customer, application=application
        )
        self.assertEqual(len(loan_duration), 4)

    def test_get_loan_duration_with_credit_limit_generation_1(self):
        user_loan_request = 10000000
        set_limit = 10000000
        min_request = 3
        max_request = 9
        result_formula_old = 9
        result_formula_new = 7

        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.end_date = timezone.localtime(timezone.now()) - relativedelta(hours=1)
        self.experiment.save()

        customer = CustomerFactory(id='1000000003')
        application = ApplicationFactory(id='123123123', customer=customer)
        credit_limit_generation = CreditLimitGenerationFactory(
            application=application,
            log='{"simple_limit": 17532468, "reduced_limit": 15779221, '
            '"limit_adjustment_factor": 0.9, "max_limit (pre-matrix)": 15000000, '
            '"set_limit (pre-matrix)": 15000000}',
            max_limit=5000000,
            set_limit=5000000,
        )
        credit_limit_generation.save()
        loan_duration_old = get_loan_duration(
            user_loan_request, max_request, min_request, set_limit, customer=customer
        )
        loan_duration_new = get_loan_duration(
            user_loan_request,
            max_request,
            min_request,
            set_limit,
            customer=customer,
            application=application,
        )
        self.assertEqual(min(loan_duration_old), result_formula_old)
        self.assertEqual(min(loan_duration_new), result_formula_new)

    def test_get_loan_duration_with_credit_limit_generation_2(self):
        user_loan_request = 10000000
        set_limit = 10000000
        min_request = 3
        max_request = 9
        result_formula_old = 9
        result_formula_new = 5

        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.end_date = timezone.localtime(timezone.now()) - relativedelta(hours=1)
        self.experiment.save()

        customer = CustomerFactory(id='1000000003')
        application = ApplicationFactory(id='123123123', customer=customer)
        credit_limit_generation = CreditLimitGenerationFactory(
            application=application,
            log='{"simple_limit": 17532468, "reduced_limit": 15779221, '
            '"limit_adjustment_factor": 0.9, "max_limit (pre-matrix)": 35000000, '
            '"set_limit (pre-matrix)": 35000000}',
            max_limit=5000000,
            set_limit=5000000,
        )
        credit_limit_generation.save()
        loan_duration_old = get_loan_duration(
            user_loan_request, max_request, min_request, set_limit, customer=customer
        )
        loan_duration_new = get_loan_duration(
            user_loan_request,
            max_request,
            min_request,
            set_limit,
            customer=customer,
            application=application,
        )
        self.assertEqual(min(loan_duration_old), result_formula_old)
        self.assertEqual(min(loan_duration_new), result_formula_new)

    def test_get_loan_duration_with_credit_limit_generation_3(self):
        user_loan_request = 10000000
        set_limit = 15000000
        min_request = 3
        max_request = 9
        result_formula_old = 7
        result_formula_new = 7

        self.experiment.criteria = {"customer_id": ['#last:2:3']}
        self.experiment.end_date = timezone.localtime(timezone.now()) - relativedelta(hours=1)
        self.experiment.save()

        customer = CustomerFactory(id='1000000003')
        application = ApplicationFactory(id='123123123', customer=customer)
        credit_limit_generation = CreditLimitGenerationFactory(
            application=application,
            log='{"simple_limit": 17532468, "reduced_limit": 15779221, '
            '"limit_adjustment_factor": 0.9, "max_limit (pre-matrix)": 10000000, '
            '"set_limit (pre-matrix)": 10000000}',
            max_limit=5000000,
            set_limit=5000000,
        )
        credit_limit_generation.save()
        loan_duration_old = get_loan_duration(
            user_loan_request, max_request, min_request, set_limit, customer=customer
        )
        loan_duration_new = get_loan_duration(
            user_loan_request,
            max_request,
            min_request,
            set_limit,
            customer=customer,
            application=application,
        )
        self.assertEqual(min(loan_duration_old), result_formula_old)
        self.assertEqual(min(loan_duration_new), result_formula_new)


class TestGenerateLoan(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.status_lookup = StatusLookupFactory()
        self.product_lookup = ProductLookupFactory()
        StatusLookupFactory(
            status_code=210
        )
        self.bank = BankFactory(
            bank_code='012',
            bank_name='BCA',
            xendit_bank_code='BCA',
            swift_bank_code='01'
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='self',
            display_label='Pribadi',
            parent_category_id=1
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='initiated',
            mobile_phone='08674734',
            attempt=0,
        )
        self.bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=self.bank_account_category,
            customer=self.customer,
            bank=self.bank,
            name_bank_validation=self.name_bank_validation,
            account_number='12345',
            is_deleted=False
        )
        self.credit_matrix = CreditMatrixFactory()
        self.timezone = pytz.timezone('Asia/Jakarta')
        self.method_self = TransactionMethod.objects.get(pk=1)
        self.method_other = TransactionMethod.objects.get(pk=2)
        FeatureSettingFactory(
            is_active=True,
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            parameters={
                'daily_max_fee': 0.9
            },
        )

    def test_generate_loan_and_payment(self):
        loan_requested = {'loan_amount': 3000000,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.02,
                          'product': self.product_lookup,
                          'provision_fee': 0.07
                          }
        loan_purpose = 'modal usaha'
        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination)
        self.assertIsNotNone(result)

    def test_generate_loan_and_payment_with_daily_fee(self):
        fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            is_active=True,
            parameters={'daily_max_fee': '0.001'}
        )
        loan_requested = {
            'loan_amount': 3000000,
            'loan_duration_request': 4,
            'interest_rate_monthly': 0.2,
            'product': self.product_lookup,
            'provision_fee': 0.7,
            'insurance_premium': 11000,
            'is_loan_amount_adjusted': False,
            'is_withdraw_funds': False,
            'device_brand': 'Xiaomi',
            'device_model': 'Redmi',
            'os_version': 32,
        }
        loan_purpose = 'modal usaha'
        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination)
        fs.is_active = False
        fs.save()
        self.assertIsNotNone(result)

    def test_generate_loan_and_payment_with_digisign_fee_self(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )
        loan_additional_fee_type = \
            LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        loan_requested = {'loan_amount': 1_000_000,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.07,
                          'product': self.product_lookup,
                          'provision_fee': 0.05,
                          'digisign_fee': 4000,
                          'transaction_method_id': TransactionMethodCode.SELF.code,
                          }
        loan_purpose = 'modal usaha'
        original_loan_amount = loan_requested['loan_amount']
        digisign_fee = loan_requested['digisign_fee']
        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination)
        self.assertIsNotNone(result)

        provision_amount = original_loan_amount * loan_requested['provision_fee']
        tax = int(py2round(0.1 * (provision_amount + digisign_fee)))
        origination_fee = int(py2round(original_loan_amount * self.product_lookup.origination_fee_pct))
        self.assertEqual(result.loan_amount, original_loan_amount)
        self.assertEqual(
            result.loan_disbursement_amount,
            original_loan_amount - origination_fee - tax - digisign_fee
        )

        loan_additional_fee = LoanAdditionalFee.objects.filter(
            loan=result,
            fee_type=loan_additional_fee_type,
        ).last()
        self.assertIsNotNone(loan_additional_fee)

    def test_generate_loan_and_payment_with_digisign_fee_non_self(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )
        loan_additional_fee_type = \
            LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE)
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)

        provision_fee = 0.05
        original_loan_amount = 1_000_000
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        original_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_fee, False
        )
        loan_requested = {'loan_amount': original_loan_amount,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.07,
                          'product': self.product_lookup,
                          'provision_fee': provision_fee,
                          'digisign_fee': 4000,
                          'transaction_method_id': TransactionMethodCode.OTHER.code,
                          }
        loan_purpose = 'modal usaha'
        digisign_fee = loan_requested['digisign_fee']

        provision_amount = original_loan_amount * loan_requested['provision_fee']
        tax = int(py2round(0.1 * (provision_amount + digisign_fee)))
        original_loan_amount += (tax + digisign_fee)
        origination_fee = int(
            py2round(
                (original_loan_amount - (tax + digisign_fee))
                * self.product_lookup.origination_fee_pct
            )
        )

        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination)
        self.assertIsNotNone(result)
        self.assertEqual(result.loan_amount, original_loan_amount)
        self.assertEqual(
            result.loan_disbursement_amount,
            original_loan_amount - origination_fee - tax - digisign_fee
        )

        loan_additional_fee = LoanAdditionalFee.objects.filter(
            loan=result,
            fee_type=loan_additional_fee_type,
        ).last()
        self.assertIsNotNone(loan_additional_fee)

    def test_generate_loan_and_payment_with_registration_fee_self(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )
        loan_dukcapil_fee_type = \
            LoanAdditionalFeeType.objects.create(
                name=LoanDigisignFeeConst.REGISTRATION_DUKCAPIL_FEE_TYPE
            )
        loan_fr_fee_type = \
            LoanAdditionalFeeType.objects.create(
                name=LoanDigisignFeeConst.REGISTRATION_FR_FEE_TYPE
            )
        loan_liveness_fee_type = \
            LoanAdditionalFeeType.objects.create(
                name=LoanDigisignFeeConst.REGISTRATION_LIVENESS_FEE_TYPE
            )

        registration_fees = {
            'REGISTRATION_DUKCAPIL_FEE': 1000,
            'REGISTRATION_FR_FEE': 2000,
            'REGISTRATION_LIVENESS_FEE': 5000,
        }
        total_registration_fee = sum(list(registration_fees.values()))
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        loan_requested = {'loan_amount': 1_000_000,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.07,
                          'product': self.product_lookup,
                          'provision_fee': 0.05,
                          'registration_fees_dict': registration_fees,
                          'transaction_method_id': TransactionMethodCode.SELF.code,
                          }
        loan_purpose = 'modal usaha'
        original_loan_amount = loan_requested['loan_amount']
        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination)
        self.assertIsNotNone(result)

        provision_amount = original_loan_amount * loan_requested['provision_fee']
        tax = int(py2round(0.1 * (provision_amount + total_registration_fee)))
        origination_fee = int(py2round(original_loan_amount * self.product_lookup.origination_fee_pct))
        self.assertEqual(result.loan_amount, original_loan_amount)
        self.assertEqual(
            result.loan_disbursement_amount,
            original_loan_amount - origination_fee - tax - total_registration_fee
        )

        loan_dukcapil_fee = LoanAdditionalFee.objects.filter(
            loan=result,
            fee_type=loan_dukcapil_fee_type,
        ).last()
        self.assertIsNotNone(loan_dukcapil_fee)

        loan_fr_fee = LoanAdditionalFee.objects.filter(
            loan=result,
            fee_type=loan_fr_fee_type,
        ).last()
        self.assertIsNotNone(loan_fr_fee)

        loan_liveness_fee = LoanAdditionalFee.objects.filter(
            loan=result,
            fee_type=loan_liveness_fee_type,
        ).last()
        self.assertIsNotNone(loan_liveness_fee)

    def test_generate_loan_and_payment_with_registration_fee_non_self(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )
        loan_dukcapil_fee_type = \
            LoanAdditionalFeeType.objects.create(
                name=LoanDigisignFeeConst.REGISTRATION_DUKCAPIL_FEE_TYPE
            )
        loan_fr_fee_type = \
            LoanAdditionalFeeType.objects.create(
                name=LoanDigisignFeeConst.REGISTRATION_FR_FEE_TYPE
            )
        loan_liveness_fee_type = \
            LoanAdditionalFeeType.objects.create(
                name=LoanDigisignFeeConst.REGISTRATION_LIVENESS_FEE_TYPE
            )

        registration_fees = {
            'REGISTRATION_DUKCAPIL_FEE': 1000,
            'REGISTRATION_FR_FEE': 2000,
            'REGISTRATION_LIVENESS_FEE': 5000,
        }
        total_registration_fee = sum(list(registration_fees.values()))
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)

        provision_fee = 0.05
        original_loan_amount = 1_000_000
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        original_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_fee, False
        )
        loan_requested = {'loan_amount': original_loan_amount,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.07,
                          'product': self.product_lookup,
                          'provision_fee': provision_fee,
                          'registration_fees_dict': registration_fees,
                          'transaction_method_id': TransactionMethodCode.OTHER.code,
                          }
        loan_purpose = 'modal usaha'

        provision_amount = original_loan_amount * loan_requested['provision_fee']
        tax = int(py2round(0.1 * (provision_amount + total_registration_fee)))
        original_loan_amount += (tax + total_registration_fee)
        origination_fee = int(
            py2round(
                (original_loan_amount - (tax + total_registration_fee))
                * self.product_lookup.origination_fee_pct
            )
        )

        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination)
        self.assertIsNotNone(result)
        self.assertEqual(result.loan_amount, original_loan_amount)
        self.assertEqual(
            result.loan_disbursement_amount,
            original_loan_amount - origination_fee - tax - total_registration_fee
        )

        loan_dukcapil_fee = LoanAdditionalFee.objects.filter(
            loan=result,
            fee_type=loan_dukcapil_fee_type,
        ).last()
        self.assertIsNotNone(loan_dukcapil_fee)

        loan_fr_fee = LoanAdditionalFee.objects.filter(
            loan=result,
            fee_type=loan_fr_fee_type,
        ).last()
        self.assertIsNotNone(loan_fr_fee)

        loan_liveness_fee = LoanAdditionalFee.objects.filter(
            loan=result,
            fee_type=loan_liveness_fee_type,
        ).last()
        self.assertIsNotNone(loan_liveness_fee)

    def test_create_loan_transaction_detail_in_generate_loan_and_payment(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )

        registration_fees = {
            'REGISTRATION_DUKCAPIL_FEE': 1000,
            'REGISTRATION_FR_FEE': 2000,
            'REGISTRATION_LIVENESS_FEE': 5000,
        }
        total_registration_fee = sum(list(registration_fees.values()))
        digisign_fee = 4000
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        loan_requested = {'loan_amount': 1_000_000,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.07,
                          'product': self.product_lookup,
                          'provision_fee': 0.05,
                          'digisign_fee': digisign_fee,
                          'registration_fees_dict': registration_fees,
                          'transaction_method_id': TransactionMethodCode.SELF.code,
                          }
        loan_purpose = 'modal usaha'
        original_loan_amount = loan_requested['loan_amount']
        loan = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination)
        self.assertIsNotNone(loan)

        provision_fee = original_loan_amount * loan_requested['provision_fee']
        additional_fee = total_registration_fee + digisign_fee
        tax = int(py2round(0.1 * (provision_fee + additional_fee)))

        loan_transaction_detail = LoanTransactionDetail.objects.filter(loan_id=loan.id).last()
        self.assertIsNotNone(loan_transaction_detail)
        self.assertIsNotNone(loan_transaction_detail.detail)

        detail = loan_transaction_detail.detail
        self.assertEqual(detail['tax_fee'], tax)
        self.assertEqual(detail['provision_fee_rate'], loan_requested['provision_fee'])
        self.assertEqual(
            detail['monthly_interest_rate'],
            loan_requested['interest_rate_monthly']
        )

    def test_generate_loan_and_payment_with_provision_discount_fixed_amount_non_self(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        # Setup promo code
        promo_code_benefit = PromoCodeBenefitFactory(
            type = PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT,
            value = {"amount": 10000}
        )
        promo_code = PromoCodeFactory(
            type=PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT,
            promo_code_benefit=promo_code_benefit,
        )

        provision_fee = 0.05
        original_loan_amount = 1_000_000
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        original_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_fee, False
        )
        loan_requested = {'loan_amount': original_loan_amount,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.07,
                          'product': self.product_lookup,
                          'provision_fee': provision_fee,
                          'transaction_method_id': TransactionMethodCode.OTHER.code,
                          }
        loan_purpose = 'modal usaha'
        provision_amount = (original_loan_amount * loan_requested['provision_fee']) - 10000
        tax = int(py2round(0.1 * provision_amount))
        original_loan_amount += tax
        origination_fee = int(
            py2round(
                (original_loan_amount - tax)
                * self.product_lookup.origination_fee_pct
            )
        )
        apply_benefit_service_handler = get_apply_promo_code_benefit_handler_v2(
            promo_code=promo_code
        )
        promo_code_data = {
            'promo_code': promo_code,
            'handler': apply_benefit_service_handler,
            'type': promo_code_benefit.type
        }

        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination,
                                                promo_code_data=promo_code_data)
        self.assertIsNotNone(result)
        self.assertEqual(result.loan_amount, original_loan_amount)
        self.assertEqual(
            result.loan_disbursement_amount,
            original_loan_amount - origination_fee - tax + 10000
        )

    def test_generate_loan_and_payment_with_provision_discount_fixed_amount_self(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.11
            },
        )
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        # Setup promo code
        promo_code_benefit = PromoCodeBenefitFactory(
            type = PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT,
            value = {"amount": 25_000}
        )
        promo_code = PromoCodeFactory(
            type=PromoCodeBenefitConst.FIXED_PROVISION_DISCOUNT,
            promo_code_benefit=promo_code_benefit,
        )

        provision_fee = 0.08
        original_loan_amount = 1_000_007
        self.product_lookup.update_safely(origination_fee_pct=0.08)
        loan_requested = {'loan_amount': original_loan_amount,
                          'loan_duration_request': 3,
                          'interest_rate_monthly': 0.052,
                          'product': self.product_lookup,
                          'provision_fee': provision_fee,
                          'transaction_method_id': TransactionMethodCode.SELF.code,
                          }
        loan_purpose = 'modal usaha'
        provision_amount = (original_loan_amount * loan_requested['provision_fee']) - 25_000
        tax = int(py2round(0.11 * provision_amount))
        origination_fee = int(py2round(
            original_loan_amount * self.product_lookup.origination_fee_pct
            )
        )
        apply_benefit_service_handler = get_apply_promo_code_benefit_handler_v2(
            promo_code=promo_code
        )
        promo_code_data = {
            'promo_code': promo_code,
            'handler': apply_benefit_service_handler,
            'type': promo_code_benefit.type
        }

        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination,
                                                promo_code_data=promo_code_data)
        self.assertIsNotNone(result)
        self.assertEqual(result.loan_amount, original_loan_amount)
        self.assertEqual(
            result.loan_disbursement_amount,
            original_loan_amount - origination_fee - tax + 25_000
        )

    def test_generate_loan_and_payment_with_provision_discount_percentage_non_self(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        # Setup promo code
        promo_code_benefit = PromoCodeBenefitFactory(
            type = PromoCodeBenefitConst.PERCENT_PROVISION_DISCOUNT,
            value = {"percentage_provision_rate_discount": 0.02,
                     "max_amount": 50000}
        )
        promo_code = PromoCodeFactory(
            promo_code_benefit=promo_code_benefit,
        )
        apply_benefit_service_handler = get_apply_promo_code_benefit_handler_v2(
            promo_code=promo_code
        )
        promo_code_data = {
            'promo_code': promo_code,
            'handler': apply_benefit_service_handler,
            'type': promo_code_benefit.type
        }

        provision_fee = 0.05
        original_loan_amount = 1_000_000
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        original_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_fee, False
        )
        loan_requested = {'loan_amount': original_loan_amount,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.07,
                          'product': self.product_lookup,
                          'provision_fee': provision_fee,
                          'transaction_method_id': TransactionMethodCode.OTHER.code,
                          }
        loan_purpose = 'modal usaha'
        provision_fee_rate = loan_requested['provision_fee'] - 0.02
        provision_amount = min((int(py2round(original_loan_amount * provision_fee_rate))), 50000)
        tax = int(py2round(0.1 * provision_amount))
        original_loan_amount += tax
        origination_fee = int(
            py2round(
                (original_loan_amount - tax)
                * self.product_lookup.origination_fee_pct
            )
        )

        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination,
                                                promo_code_data=promo_code_data)
        self.assertIsNotNone(result)
        self.assertEqual(result.loan_amount, original_loan_amount)
        self.assertEqual(
            result.loan_disbursement_amount,
            original_loan_amount - origination_fee - tax + 21053
        )
    
    def test_generate_loan_and_payment_with_provision_discount_percentage_self(self):
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            parameters={
                'tax_percentage': 0.1
            },
        )
        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        # Setup promo code
        promo_code_benefit = PromoCodeBenefitFactory(
            type = PromoCodeBenefitConst.PERCENT_PROVISION_DISCOUNT,
            value = {"percentage_provision_rate_discount": 0.02,
                     "max_amount": 10000}
        )
        promo_code = PromoCodeFactory(
            promo_code_benefit=promo_code_benefit,
        )
        apply_benefit_service_handler = get_apply_promo_code_benefit_handler_v2(
            promo_code=promo_code
        )
        promo_code_data = {
            'promo_code': promo_code,
            'handler': apply_benefit_service_handler,
            'type': promo_code_benefit.type
        }

        provision_fee = 0.05
        original_loan_amount = 1_000_000
        self.product_lookup.update_safely(origination_fee_pct=0.05)
        loan_requested = {'loan_amount': original_loan_amount,
                          'loan_duration_request': 4,
                          'interest_rate_monthly': 0.07,
                          'product': self.product_lookup,
                          'provision_fee': provision_fee,
                          'transaction_method_id': TransactionMethodCode.SELF.code,
                          }
        loan_purpose = 'modal usaha'
        provision_fee_rate = loan_requested['provision_fee'] - 0.02
        discount_applied = min(original_loan_amount * provision_fee_rate, 10_000)
        provision_amount = original_loan_amount * provision_fee - discount_applied
        tax = int(py2round(0.1 * provision_amount))
        origination_fee = int(py2round(
            original_loan_amount * self.product_lookup.origination_fee_pct
            )
        )

        result = generate_loan_payment_julo_one(self.application,
                                                loan_requested,
                                                loan_purpose,
                                                self.credit_matrix,
                                                self.bank_account_destination,
                                                promo_code_data=promo_code_data)
        self.assertIsNotNone(result)
        self.assertEqual(result.loan_amount, original_loan_amount)
        self.assertEqual(
            result.loan_disbursement_amount,
            original_loan_amount - origination_fee - tax + 10000
        )


    @mock.patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @mock.patch('juloserver.loan.services.loan_related.timezone.now')
    def test_refiltering_cash_loan_duration_removed(self, mocked_now, mocked_func):
        mocked_now.return_value = self.timezone.localize(datetime.strptime('01012021', "%d%m%Y"))
        mocked_func.return_value = datetime.strptime('01022021', "%d%m%Y").date()
        available_duration = [2, 3, 4, 5, 6]
        result = refiltering_cash_loan_duration(available_duration, self.application)
        self.assertNotIn(2, result)

    @mock.patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @mock.patch('juloserver.loan.services.loan_related.timezone.now')
    def test_refiltering_cash_loan_duration_not_only_two(self, mocked_now, mocked_func):
        mocked_now.return_value = self.timezone.localize(datetime.strptime('01012021', "%d%m%Y"))
        mocked_func.return_value = datetime.strptime('01022021', "%d%m%Y").date()
        available_duration = [2]
        result = refiltering_cash_loan_duration(available_duration, self.application)
        self.assertIn(3, result)

    @mock.patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @mock.patch('juloserver.loan.services.loan_related.timezone.now')
    def test_refiltering_cash_loan_duration_not_removed(self, mocked_now, mocked_func):
        mocked_now.return_value = self.timezone.localize(datetime.strptime('01032021', "%d%m%Y"))
        mocked_func.return_value = datetime.strptime('01042021', "%d%m%Y").date()
        available_duration = [2, 3, 4, 5, 6]
        result = refiltering_cash_loan_duration(available_duration, self.application)
        mocked_func.assert_called_once()
        self.assertIn(2, result)

    @mock.patch('juloserver.loan.services.loan_related.get_first_payment_date_by_application')
    @mock.patch('juloserver.loan.services.loan_related.timezone.now')
    def test_refiltering_cash_loan_duration_without_two_in_availabel(self, mocked_now, mocked_func):
        mocked_now.return_value = self.timezone.localize(datetime.strptime('01032021', "%d%m%Y"))
        mocked_func.return_value = datetime.strptime('01042021', "%d%m%Y").date()
        available_duration = [3, 4, 5, 6]
        result = refiltering_cash_loan_duration(available_duration, self.application)
        self.assertEqual(available_duration, result)

    def test_compute_payment_installment_julo_one(self):
        loan_amount = 1000000
        loan_duration = 3
        interest_rate = 0.4
        principal, interest, installment = compute_payment_installment_julo_one(
            loan_amount, loan_duration, interest_rate)

        principal_ref = int(math.floor(float(loan_amount) / float(loan_duration)))
        interest_ref = int(math.floor(float(loan_amount) * interest_rate))
        installment_amount = round_rupiah(principal + interest_ref)
        derived_interest_ref = installment_amount - principal

        self.assertEqual(principal, principal_ref)
        self.assertEqual(interest, derived_interest_ref)
        self.assertEqual(installment_amount, installment)

    def test_compute_first_payment_installment_julo_one(self):
        loan_amount = 1000000
        loan_duration = 3
        interest_rate = 0.4
        today_date = timezone.localtime(timezone.now()).date()
        first_due_date = today_date + timedelta(days=20)
        principal_res, interest_res, installment_res = compute_first_payment_installment_julo_one(
            loan_amount, loan_duration, interest_rate, today_date, first_due_date)

        days_in_month = 30.0
        delta_days = (first_due_date - today_date).days
        principal = int(math.floor(float(loan_amount) / float(loan_duration)))
        basic_interest = float(loan_amount) * interest_rate
        adjusted_interest = int(math.floor((float(delta_days) / days_in_month) * basic_interest))

        installment_amount = round_rupiah(
            principal + adjusted_interest) if loan_duration > 1 else principal + adjusted_interest
        derived_adjusted_interest = installment_amount - principal

        self.assertEqual(principal_res, principal)
        self.assertEqual(interest_res, derived_adjusted_interest)
        self.assertEqual(installment_amount, installment_res)

    def test_compute_first_payment_installment_julo_one_with_zero_interest(self):
        loan_amount = 104_000
        loan_duration = 3
        interest_rate = 0
        today_date = timezone.localtime(timezone.now()).date()
        first_due_date = today_date + timedelta(days=20)
        principal_res, interest_res, installment_res = compute_first_payment_installment_julo_one(
            loan_amount, loan_duration, interest_rate, today_date, first_due_date)

        assert principal_res == installment_res
        assert int(math.floor(float(loan_amount) / float(loan_duration))) == principal_res
        assert interest_res == 0

    def test_compute_payment_installment_julo_one_case_rounding(self):
        """
        Testing case rounding due amount
        """
        # Due amount NOT ROUNDED, DUE TO LOW LOAN AMOUNT
        loan_amount = 15_300
        loan_duration = 3
        interest_rate = 0.02
        principal, interest, due_amount = compute_payment_installment_julo_one(
            loan_amount, loan_duration, interest_rate
        )

        expected_principal = int(math.floor(float(loan_amount) / float(loan_duration)))

        original_interest = int(math.floor(float(loan_amount) * interest_rate))

        expected_due_amount = expected_principal + original_interest
        expected_interest = expected_due_amount - expected_principal

        self.assertEqual(principal, expected_principal)
        self.assertEqual(interest, expected_interest)
        self.assertEqual(due_amount, expected_due_amount)

        # STILL UNROUNDED, amount is large but it's one tenure
        loan_amount = 100_000
        loan_duration = 1
        interest_rate = 0.02
        principal, interest, due_amount = compute_payment_installment_julo_one(
            loan_amount, loan_duration, interest_rate
        )

        expected_principal = int(math.floor(float(loan_amount) / float(loan_duration)))

        original_interest = int(math.floor(float(loan_amount) * interest_rate))

        expected_due_amount = expected_principal + original_interest
        expected_interest = expected_due_amount - expected_principal

        self.assertEqual(principal, expected_principal)
        self.assertEqual(interest, expected_interest)
        self.assertEqual(due_amount, expected_due_amount)

        # STILL UNROUNDED, amount is not large enough; one tenure
        loan_amount = 50_000
        loan_duration = 1
        interest_rate = 0.02
        principal, interest, due_amount = compute_payment_installment_julo_one(
            loan_amount, loan_duration, interest_rate
        )

        expected_principal = int(math.floor(float(loan_amount) / float(loan_duration)))

        original_interest = int(math.floor(float(loan_amount) * interest_rate))

        expected_due_amount = expected_principal + original_interest
        expected_interest = expected_due_amount - expected_principal

        self.assertEqual(principal, expected_principal)
        self.assertEqual(interest, expected_interest)
        self.assertEqual(due_amount, expected_due_amount)
        # Due amount ROUNDED, amount is larger
        loan_amount = 50_000
        loan_duration = 3
        interest_rate = 0.02
        principal, interest, due_amount = compute_payment_installment_julo_one(
            loan_amount, loan_duration, interest_rate
        )

        expected_principal = int(math.floor(float(loan_amount) / float(loan_duration)))

        original_interest = int(math.floor(float(loan_amount) * interest_rate))

        expected_due_amount = round_rupiah(expected_principal + original_interest)
        expected_interest = expected_due_amount - expected_principal

        self.assertEqual(principal, expected_principal)
        self.assertEqual(interest, expected_interest)
        self.assertEqual(due_amount, expected_due_amount)

    def test_compute_first_payment_installment_julo_one_case_rounding(self):
        """
        Testing case rounding due amount
        """
        # due amount NOT ROUNDED, DUE TO LOW LOAN AMOUNT
        loan_amount = 15_300
        loan_duration = 1
        thirty_day_interest_rate = 0.02
        today_date = timezone.localtime(timezone.now()).date()
        days_in_first_month = 20
        first_due_date = today_date + timedelta(days=days_in_first_month)
        principal, interest, due_amount = compute_first_payment_installment_julo_one(
            loan_amount,
            loan_duration,
            monthly_interest_rate=thirty_day_interest_rate,
            start_date=today_date,
            end_date=first_due_date,
        )

        expected_principal = int(math.floor(float(loan_amount) / float(loan_duration)))

        original_interest = int(
            math.floor(float(loan_amount) * (thirty_day_interest_rate / 30 * days_in_first_month))
        )

        expected_due_amount = expected_principal + original_interest
        expected_interest = expected_due_amount - expected_principal

        self.assertEqual(principal, expected_principal)
        self.assertEqual(interest, expected_interest)
        self.assertEqual(due_amount, expected_due_amount)

        # Due amount not ROUNDED; because duration is only 1
        loan_amount = 100_000
        loan_duration = 1
        thirty_day_interest_rate = 0.02
        today_date = timezone.localtime(timezone.now()).date()
        first_due_date = today_date + timedelta(days=days_in_first_month)
        principal, interest, due_amount = compute_first_payment_installment_julo_one(
            loan_amount,
            loan_duration,
            thirty_day_interest_rate,
            start_date=today_date,
            end_date=first_due_date,
        )

        expected_principal = int(math.floor(float(loan_amount) / float(loan_duration)))

        original_interest = int(
            math.floor(float(loan_amount) * (thirty_day_interest_rate / 30 * days_in_first_month))
        )

        expected_due_amount = expected_principal + original_interest
        expected_interest = expected_due_amount - expected_principal

        self.assertEqual(principal, expected_principal)
        self.assertEqual(interest, expected_interest)
        self.assertEqual(due_amount, expected_due_amount)

        # Due amount ROUNDED
        loan_amount = 100_000
        loan_duration = 2
        thirty_day_interest_rate = 0.02
        today_date = timezone.localtime(timezone.now()).date()
        first_due_date = today_date + timedelta(days=days_in_first_month)
        principal, interest, due_amount = compute_first_payment_installment_julo_one(
            loan_amount,
            loan_duration,
            thirty_day_interest_rate,
            start_date=today_date,
            end_date=first_due_date,
        )

        expected_principal = int(math.floor(float(loan_amount) / float(loan_duration)))

        original_interest = int(
            math.floor(float(loan_amount) * (thirty_day_interest_rate / 30 * days_in_first_month))
        )

        expected_due_amount = round_rupiah(expected_principal + original_interest)
        expected_interest = expected_due_amount - expected_principal

        self.assertEqual(principal, expected_principal)
        self.assertEqual(interest, expected_interest)
        self.assertEqual(due_amount, expected_due_amount)

    def test_determine_transaction_method_by_transaction_type(self):
        self_method = determine_transaction_method_by_transaction_type(TransactionType.SELF)
        self.assertEqual(self_method, self.method_self)
        other_method = determine_transaction_method_by_transaction_type(TransactionType.OTHER)
        self.assertEqual(other_method, self.method_other)
        invalid_method = determine_transaction_method_by_transaction_type('any_other_method')
        self.assertEqual(invalid_method, self.method_other)


class TestUpdateLoanHistory(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.status_lookup = StatusLookupFactory(status_code=210)
        StatusLookupFactory(status_code=211)
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        self.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow,
            name='julo1',
            payment_frequency='1'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.loan = LoanFactory(customer=self.customer, account=self.account, application=None)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=210, status_next=211, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=211, status_next=212, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=220, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=220, status_next=250, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=230, status_next=250, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=237, status_next=250, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=218, status_next=215, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=216, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=218, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=214, workflow=self.workflow)
        FeatureSettingFactory(
            is_active=True,
            feature_name=LoanFeatureNameConst.AFPI_DAILY_MAX_FEE,
            parameters={
                'daily_max_fee': 0.4
            },
        )

    @mock.patch('juloserver.loan.services.lender_related.return_lender_balance_amount')
    @mock.patch('juloserver.loan.services.loan_related.update_available_limit')
    @mock.patch.object(LoanHistory.objects, 'create')
    def test_loan_history(self, mocked_loan_history, mock_update_available_limit,
                          mock_return_lender_balance_amount):
        loan_history_data = {
            'loan': self.loan,
            'status_old': self.loan.status,
            'status_new': 218,
            'change_reason': "system triggered",
            'change_by_id': None
        }
        mock_update_available_limit.return_value = None
        mocked_loan_history.return_value = None
        update_loan_status_and_loan_history(self.loan.id, 250)
        mocked_loan_history.called_with(loan_history_data)

        # change loan status to 215
        self.loan.loan_status_id = 218
        self.loan.save()
        mock_update_available_limit.return_value = None
        mocked_loan_history.return_value = None
        update_loan_status_and_loan_history(self.loan.id, 215)
        mock_return_lender_balance_amount.assert_called_once()
        self.assertIsNotNone(LoanStatusChange.objects.filter(loan_id=self.loan.id).last())

    @mock.patch('juloserver.ecommerce.services.update_iprice_transaction_by_loan')
    @mock.patch('juloserver.loan.services.lender_related.return_lender_balance_amount')
    @mock.patch('juloserver.loan.services.loan_related.update_available_limit')
    @mock.patch.object(LoanHistory.objects, 'create')
    def test_update_iprice_transaction_by_loan_called(self, mocked_loan_history, mock_update_available_limit,
                                                      mock_return_lender_balance_amount,
                                                      mock_update_iprice_transaction_by_loan):
        mock_update_available_limit.return_value = None
        mocked_loan_history.return_value = None
        update_loan_status_and_loan_history(self.loan.id, 250, change_reason='test reason')
        mock_update_iprice_transaction_by_loan.assert_called_once_with(
            self.loan, 250, 'test reason'
        )

    @mark.parametrize("test_date, expected_due_dates", )
    def test_payment_due_date_end_of_month_for_julovers(self):
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        product_profile = ProductProfileFactory(
            code=ProductLineCodes.JULOVER,
            name='JULOVER',
            min_amount=300000,
            max_amount=20000000,
            min_duration=1,
            max_duration=4,
            min_interest_rate=0,
            max_interest_rate=0,
            interest_rate_increment=0,
            payment_frequency='Monthly',
            min_origination_fee=0,
            max_origination_fee=0,
            origination_fee_increment=0,
            late_fee=0,
            cashback_initial=0,
            cashback_payment=0,
            is_active=True,
            debt_income_ratio=0,
            is_product_exclusive=True,
            is_initial=True,
        )
        product_lookup = ProductLookupFactory(
            product_name='I.000-O.000-L.000-C1.000-C2.000-M',
            interest_rate=0,
            origination_fee_pct=0,
            late_fee_pct=0,
            cashback_initial_pct=0,
            cashback_payment_pct=0,
            product_line=product_line,
            product_profile=product_profile,
            is_active=True,
            admin_fee=0,
        )
        credit_matrix = CreditMatrixFactory(product=product_lookup, transaction_type=1)

        account = AccountFactory(cycle_day=31)
        AccountLimitFactory(account=account, available_limit=10000000000)
        application = ApplicationFactory(product_line=product_line, payday=31, account=account,)
        application.update_safely(application_status=StatusLookupFactory(status_code=190))

        default_loan_requested = dict(
            is_loan_amount_adjusted=False,
            original_loan_amount_requested=10000,
            loan_amount=10000,
            loan_duration_request=3,
            interest_rate_monthly=credit_matrix.product.monthly_interest_rate,
            product=credit_matrix.product,
            provision_fee=0,
            is_withdraw_funds=False
        )

        test_data = [
            (datetime(2020, 1, 1), ['2020-01-31', '2020-02-29', '2020-03-31']),
            (datetime(2020, 1, 16), ['2020-01-31', '2020-02-29', '2020-03-31']),
            (datetime(2020, 1, 17), ['2020-02-29', '2020-03-31', '2020-04-30']),
            (datetime(2020, 2, 1), ['2020-02-29', '2020-03-31', '2020-04-30']),
            (datetime(2020, 4, 15), ['2020-04-30', '2020-05-31', '2020-06-30']),
        ]
        for (test_date, expected_due_dates) in test_data:
            with patch.object(timezone, 'now') as mock_now:
                mock_now.return_value = test_date
                loan_requested = default_loan_requested.copy()

                loan = generate_loan_payment_julo_one(application, loan_requested, "test", credit_matrix)
                payments = loan.payment_set.order_by('payment_number')

                for key, expected_due_date in enumerate(expected_due_dates):
                    self.assertEqual(
                        expected_due_date,
                        payments[key].due_date.strftime('%Y-%m-%d'),
                        (key, test_date)
                    )


class TestUpdateLoanStatusAndLoanHistory(TestCase):

    def setUp(self):
        signals.post_save.disconnect(invalidate_cache_referee_count, sender=Application)
        self.fake_redis = MockRedisHelper()
        self.tier = CfsTierFactory(id=2, name='Advanced', point=300, referral_bonus=75000)
        self_referral_code = 'TEST_REFERRAL_CODE'
        self.referrer = CustomerFactory(self_referral_code=self_referral_code)
        self.referrer.save()
        self.referrer_account = AccountFactory(customer=self.referrer)
        self.product_line_code = ProductLineFactory(product_line_code=1)
        self.referrer_application = ApplicationFactory(
            customer=self.referrer,
            account=self.referrer_account,
            product_line=self.product_line_code,
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            referral_code=self_referral_code,
            product_line=self.product_line_code,
        )
        self.today = timezone.localtime(timezone.now()).date()
        self.referral_system = ReferralSystemFactory(
            name='PromoReferral', minimum_transaction_amount=100000
        )
        self.referral_benefit_fs = ReferralBenefitFeatureSettingFactory()
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        AccountingCutOffDateFactory()
        WorkflowStatusPathFactory(status_previous=210, status_next=211, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=211, status_next=212, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=220, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=214, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=220, status_next=250, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=218, status_next=215, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=215, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=216, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=217, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=219, workflow=self.workflow)
        AccountLimitFactory(account=self.account, available_limit=10000000)
        self.referral_fs = FeatureSettingFactory(
            feature_name=ReferralFeatureNameConst.REFERRAL_BENEFIT_LOGIC
        )

    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.loan.services.loan_related.update_is_proven_julo_one')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_update_loan_status_and_loan_history_paid_off(
            self, mock_get_tier_info, mock_update_is_proven_julo_one,
             mock_get_appsflyer_service):
        mock_get_tier_info.return_value = (0, self.tier)
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer
        )
        AccountLimitFactory(account=account, available_limit=500000)
        julo_product = ProductLineFactory(product_line_code=1)
        application = ApplicationFactory(
            customer=customer,
            product_line=julo_product,
            application_xid=919,
            account=account)
        application.application_status_id = 190
        application.save()
        ReferralSystemFactory()
        CreditScoreFactory(
            application_id=application.id,
            score=u'A-'
        )
        loan = LoanFactory(customer=customer, application=application, account=account)
        loan.loan_status_id = 220
        loan.save()
        update_loan_status_and_loan_history(loan.id, 250)

        customer.refresh_from_db()
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 250)
        last_release = ReleaseTracking.objects.get(
            loan_id=loan.id, type=ReleaseTrackingType.LAST_RELEASE
        )
        # because no payment paid, then assert loan amount
        self.assertEqual(last_release.limit_release_amount, loan.loan_amount)

    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.loan.services.loan_related.update_is_proven_julo_one')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_last_release_loan_paid_off(
        self,
        mock_get_tier_info,
        mock_update_is_proven_julo_one,
        mock_get_appsflyer_service,
    ):
        mock_get_tier_info.return_value = (0, self.tier)
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        AccountLimitFactory(account=account, available_limit=500000)
        julo_product = ProductLineFactory(product_line_code=1)
        application = ApplicationFactory(
            customer=customer, product_line=julo_product, application_xid=919, account=account
        )
        application.application_status_id = 190
        application.save()
        ReferralSystemFactory()
        CreditScoreFactory(application_id=application.id, score=u'A-')
        loan = LoanFactory(customer=customer, application=application, account=account)
        loan.loan_status_id = 210
        loan.save()
        payments = Payment.objects.filter(loan=loan, payment_number=4).update(payment_status=330)
        payment4 = loan.payment_set.get(payment_number=4)
        ReleaseTrackingFactory(
            loan=loan,
            payment=payment4,
            account=account,
            limit_release_amount=payment4.installment_principal
        )
        update_loan_status_and_loan_history(loan.id, 250)

        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 250)
        last_release = ReleaseTracking.objects.get(
            loan_id=loan.id, type=ReleaseTrackingType.LAST_RELEASE
        )
        remaining_amount = (
            Payment.objects.filter(loan=loan, payment_number__lte=4)
                .annotate(total_amount=Sum('installment_principal'))
                .values_list('total_amount', flat=True)[0]
        )
        self.assertEqual(last_release.limit_release_amount, loan.loan_amount - remaining_amount)

    @patch('juloserver.referral.services.get_redis_client')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @mock.patch('juloserver.moengage.services.use_cases.update_moengage_referral_event')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.loan.services.loan_related.update_is_proven_julo_one')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_process_referral_code_logic_v2_at_220_status(
        self,
        mock_get_julo_pn_client,
        mock_update_is_proven_julo_one,
        mock_update_available_limit,
        mock_update_moengage_referral_event,
        mock_get_appsflyer_service,
        mock_redis_client
    ):
        mock_redis_client.return_value = self.fake_redis
        FeatureSettingFactory(feature_name='referral_benefit_logic')
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, self_referral_code='TEST_REFERRAL_CODE'
        )
        self.account = AccountFactory(customer=self.customer)
        self.account.status_id = 420
        self.account.save()
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.application.application_status_id = 150
        self.application.save()
        referral_system = ReferralSystemFactory()
        # benefit for referee
        self.user_auth2 = AuthUserFactory()
        self.customer2 = CustomerFactory(user=self.user_auth2)
        self.account2 = AccountFactory(customer=self.customer2)
        self.application2 = ApplicationFactory(
            customer=self.customer2, account=self.account2,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        app2_190_history = ApplicationHistoryFactory(
            application=self.application2, status_old=110, status_new=190
        )
        app2_190_history.update_safely(cdate=self.today - timedelta(days=5))
        self.application2.referral_code = 'TEST_REFERRAL_CODE'
        self.application2.application_status_id = 190
        self.application2.save()
        loan = LoanFactory(
            customer=self.customer2, application=self.application2, account=self.account2
        )

        ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=50000,
            referee_benefit=20000, min_disburse_amount=loan.loan_amount, is_active=True
        )
        ReferralLevelFactory(
            benefit_type=ReferralLevelConst.CASHBACK, min_referees=5, referrer_level_benefit=50000,
            is_active=True
        )
        RefereeMappingFactory.create_batch(5, referrer=self.customer2)
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan.loan_status = self.status_lookup
        loan.account = self.account2
        loan.set_fund_transfer_time()
        loan.save()
        self.customer_wallet_history = CustomerWalletHistoryFactory(customer=self.customer2)
        self.application.refresh_from_db()
        update_loan_status_and_loan_history(loan.id, 220)
        mock_update_moengage_referral_event.delay.assert_has_calls([
            call(
                self.customer, MoengageEventType.BEx220_GET_REFERRER,
                50000
            ),
            call(
                self.customer2, MoengageEventType.BEX220_GET_REFEREE,
                20000
            ),
        ])
        customer_wallet_history = CustomerWalletHistory.objects.filter(
            customer=self.customer2).last()
        self.assertEqual(
            customer_wallet_history.wallet_balance_available,
            20000
        )
        referee_mapping = RefereeMapping.objects.filter(
            referrer=self.customer, referee=self.customer2
        ).last()
        referrer_history = ReferralBenefitHistory.objects.filter(
            customer=self.customer, referee_mapping=referee_mapping,
            referral_person_type=ReferralPersonTypeConst.REFERRER,
            benefit_unit=ReferralBenefitConst.CASHBACK, amount=50000
        ).exists()
        self.assertTrue(referrer_history)
        referee_history = ReferralBenefitHistory.objects.filter(
            customer=self.customer2, referee_mapping=referee_mapping,
            referral_person_type=ReferralPersonTypeConst.REFEREE,
            benefit_unit=ReferralBenefitConst.CASHBACK, amount=20000
        ).exists()
        self.assertTrue(referee_history)

    @patch('juloserver.referral.services.get_redis_client')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.loan.services.loan_related.update_is_proven_julo_one')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_process_referral_code_logic_v2_at_220_status_min_disburse_failed(
            self,
            mock_get_julo_pn_client,
            mock_update_is_proven_julo_one,
            mock_update_available_limit,
            mock_get_appsflyer_service,
            mock_redis_client
    ):
        mock_redis_client.return_value = self.fake_redis
        FeatureSettingFactory(feature_name='referral_benefit_logic')
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, self_referral_code='TEST_REFERRAL_CODE'
        )
        self.account = AccountFactory(customer=self.customer)
        self.account.status_id = 420
        self.account.save()
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.application_status_id = 150
        self.application.save()
        referral_system = ReferralSystemFactory()
        # benefit for referee
        self.user_auth2 = AuthUserFactory()
        self.customer2 = CustomerFactory(user=self.user_auth2)
        self.account2 = AccountFactory(customer=self.customer2)
        self.application2 = ApplicationFactory(
            customer=self.customer2,
            account=self.account2,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application2.referral_code = 'TEST_REFERRAL_CODE'
        self.application2.application_status_id = 190
        self.application2.save()
        app2_190_history = ApplicationHistoryFactory(
            application=self.application2, status_old=110, status_new=190
        )
        app2_190_history.update_safely(cdate=self.today - timedelta(days=5))
        loan = LoanFactory(
            customer=self.customer2, application=self.application2, account=self.account2,
            loan_amount=1000000
        )

        ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=50000,
            referee_benefit=20000, min_disburse_amount=2000000, is_active=True
        )
        ReferralLevelFactory(
            benefit_type=ReferralLevelConst.CASHBACK, min_referees=5, referrer_level_benefit=50000,
            is_active=True
        )
        RefereeMappingFactory.create_batch(5, referrer=self.customer2)
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan.loan_status = self.status_lookup
        loan.account = self.account2
        loan.save()
        self.customer_wallet_history = CustomerWalletHistoryFactory(customer=self.customer2)
        self.application.refresh_from_db()
        update_loan_status_and_loan_history(loan.id, 220)

        referee_mapping = RefereeMapping.objects.filter(
            referrer=self.customer, referee=self.customer2
        ).exists()
        self.assertFalse(referee_mapping)
        referee_cashback = CashbackBalance.objects.get(customer=self.customer2)
        self.assertEquals(referee_cashback.cashback_balance, 0)
        referrer_cashback = CashbackBalance.objects.get(customer=self.customer)
        self.assertEquals(referrer_cashback.cashback_balance, 0)

    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_process_referral_code_at_220_status_exception(self, mock_get_tier_info,
            mock_get_julo_pn_client, mock_update_available_limit, mock_get_appsflyer_service):
        mock_get_tier_info.return_value = (0, self.tier)
        referrer = CustomerFactory(self_referral_code='TEST_REFERRAL_CODE')
        referrer.save()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.application_status_id = 150
        self.application.referral_code = 'test_referral_code'
        self.application.save()
        account = AccountFactory(
            customer=self.application.customer)
        account.status_id = 410
        account.save()
        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account
        )
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan.loan_status = self.status_lookup
        loan.account = self.account
        loan.save()
        update_loan_status_and_loan_history(loan.id, 220)
        self.assertEqual(self.customer.self_referral_code, '')

    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    def test_process_referral_code_at_220_status_exception(self, mock_get_julo_pn_client,
            mock_update_available_limit):
        referrer = CustomerFactory(self_referral_code='TEST_REFERRAL_CODE')
        referrer.save()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.application_status_id = 150
        self.application.referral_code = 'test_referral_code'
        self.application.save()
        account = AccountFactory(
            customer=self.application.customer)
        account.status_id = 410
        account.save()
        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account
        )
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan.loan_status = self.status_lookup
        loan.account = self.account
        loan.save()
        update_loan_status_and_loan_history(loan.id, 250)
        self.assertEqual(self.customer.self_referral_code, '')

    @patch.object(LenderTransactionMapping.objects, 'filter')
    def test_return_lender_balance_amount(self, lender_objects_filter):
        pulsa_method = TransactionMethod.objects.get(pk=3)
        loan = LoanFactory(
            transaction_method=pulsa_method,
            lender=LenderCurrentFactory(),
        )
        sepulsa_transaction = SepulsaTransactionFactory(
            loan=loan
        )
        # case sepulsa
        return_lender_balance_amount(loan)
        lender_objects_filter.assert_called_once_with(**{
            'sepulsa_transaction_id': sepulsa_transaction.id,
        })


    @patch('juloserver.loan.services.loan_related.handle_loan_prize_chance_on_loan_status_change')
    @patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.send_event_to_ga')
    @patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    @patch('juloserver.loan.services.loan_related.execute_after_transaction_safely')
    def test_update_220_status_events(self, mock_execute_after_transaction_safely, mock_get_tier_info,
        mock_get_julo_pn_client, mock_update_available_limit, mock_get_appsflyer_service,
        mock_send_event_to_ga, mock_handle_loan_prize_chance,
    ):
        mock_get_appsflyer_service.return_value = event_response(
            status_code=200
        )
        mock_get_tier_info.return_value = (0, self.tier)
        referrer = CustomerFactory(self_referral_code='TEST_REFERRAL_CODE')
        referrer.save()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.customer.appsflyer_device_id = "new_appsflyer_id"
        self.customer.app_instance_id = "appinstanceid"
        self.customer.save()

        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.customer.appsflyer_device_id = "new_appsflyer_id"
        self.application.application_status_id = 190
        self.application.save()
        account = AccountFactory(
            customer=self.application.customer)
        account.status_id = 410
        account.save()
        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account
        )
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan.loan_status = self.status_lookup
        loan.account = self.account
        loan.set_fund_transfer_time()
        loan.save()
        update_loan_status_and_loan_history(loan.id, 220)
        self.assertEqual(mock_get_appsflyer_service.call_count, 1)
        self.assertEqual(mock_send_event_to_ga.call_count, 1)
        self.assertEqual(
            mock_execute_after_transaction_safely.call_count, 1
        )  #  call trigger pn loan 220
        mock_handle_loan_prize_chance.assert_called_once_with(loan)

    @patch('juloserver.loan.services.loan_related.handle_loan_prize_chance_on_loan_status_change')
    @patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.send_event_to_ga')
    @patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    @patch('juloserver.loan.services.loan_related.execute_after_transaction_safely')
    def test_update_220_status_ftc_pct_events(self, mock_execute_after_transaction_safely, mock_get_tier_info,
        mock_get_julo_pn_client, mock_update_available_limit, mock_get_appsflyer_service,
        mock_send_event_to_ga, mock_handle_loan_prize_chance,
    ):
        mock_get_appsflyer_service.return_value = event_response(
            status_code=200
        )
        mock_get_tier_info.return_value = (0, self.tier)
        referrer = CustomerFactory(self_referral_code='TEST_REFERRAL_CODE')
        referrer.save()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.customer.appsflyer_device_id = "new_appsflyer_id"
        self.customer.app_instance_id = "appinstanceid"
        self.customer.save()

        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        PdApplicationFraudModelResultFactory(customer_id=self.customer.id, pgood=0.92)
        self.application.customer.appsflyer_device_id = "new_appsflyer_id"
        self.application.application_status_id = 190
        self.application.save()
        account = AccountFactory(
            customer=self.application.customer)
        account.status_id = 410
        account.save()
        account_property = AccountPropertyFactory(
            pgood=0.80, p0=0.80, account=self.account, is_proven=True,
            is_salaried=True, is_premium_area=True
        )
        account_property.save()

        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account
        )
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan.loan_status = self.status_lookup
        loan.account = self.account
        loan.set_fund_transfer_time()
        loan.save()
        update_loan_status_and_loan_history(loan.id, 220)
        self.assertEqual(mock_get_appsflyer_service.call_count, 6)
        self.assertEqual(mock_send_event_to_ga.call_count, 6)

    @patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.send_event_to_ga')
    @patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_update_250_status_events(self, mock_get_tier_info,
            mock_get_julo_pn_client, mock_update_available_limit, mock_get_appsflyer_service, mock_send_event_to_ga):
        mock_get_appsflyer_service.return_value = event_response(
            status_code=200
        )
        mock_get_tier_info.return_value = (0, self.tier)
        referrer = CustomerFactory(self_referral_code='TEST_REFERRAL_CODE')
        referrer.save()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.customer.appsflyer_device_id = "new_appsflyer_id"
        self.customer.app_instance_id = "appinstanceid"
        self.customer.save()

        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.customer.appsflyer_device_id = "new_appsflyer_id"
        self.application.application_status_id = 190
        self.application.save()
        account = AccountFactory(
            customer=self.application.customer)
        account.status_id = 410
        account.save()
        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account
        )
        self.status_lookup = StatusLookupFactory(status_code=220)
        loan.loan_status = self.status_lookup
        loan.account = self.account
        loan.save()
        # test 250
        update_loan_status_and_loan_history(loan.id, 250)
        mock_get_appsflyer_service.assert_called()
        mock_send_event_to_ga.assert_called()

    @patch('juloserver.referral.services.check_referral_cashback_v2')
    def test_process_referral_code_with_more_loans(self, mock_check_referral_cashback):
        # the customer already has more than one loan => referral code can't get bonus
        account = AccountFactory(customer=self.referrer)
        self.status_lookup = StatusLookupFactory(status_code=220)
        account.status_id = 420
        account.save()
        LoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_amount=54000,
            loan_status=self.status_lookup
        )
        loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_amount=54000
        )
        self.referral_system.minimum_transaction_amount = 100000
        self.referral_system.save()
        process_referral_code_v2(self.application, loan, self.referral_fs)
        mock_check_referral_cashback.assert_not_called()

    @patch('juloserver.referral.services.check_referral_cashback_v2')
    def test_referral_system_off_benefit_logic_v2(self, check_referral_cashback):
        account = AccountFactory(customer=self.referrer)
        account.status_id = 420
        account.save()
        loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_amount=54000,
        )
        self.referral_system.update_safely(is_active=False)

        process_referral_code_v2(self.application, loan, self.referral_fs)
        self.assertEquals(check_referral_cashback.call_count, 0)

    @patch('juloserver.referral.services.check_referral_cashback_v2')
    def test_referral_benefit_logic_v2(self, check_referral_cashback):
        account = AccountFactory(customer=self.referrer)
        account.status_id = 420
        account.save()
        loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_amount=54000,
        )
        self.application.update_safely(application_status_id=190)
        app_190_history = ApplicationHistoryFactory(
            application=self.application, status_old=110, status_new=190
        )
        app_190_history.update_safely(cdate=self.today - timedelta(days=5))
        process_referral_code_v2(self.application, loan, self.referral_fs)
        self.assertEquals(check_referral_cashback.call_count, 1)

    @patch('juloserver.referral.services.check_referral_cashback_v2')
    def test_referral_benefit_logic_v2_case_invalid_cut_off_date(self, check_referral_cashback):
        account = AccountFactory(customer=self.referrer)
        account.status_id = 420
        account.save()
        loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_amount=54000,
        )

        self.application.update_safely(application_status_id=190)
        app_190_history = ApplicationHistoryFactory(
            application=self.application, status_old=110, status_new=190
        )
        app_190_history.update_safely(cdate=self.today - timedelta(days=100))
        process_referral_code_v2(self.application, loan, self.referral_fs)
        self.assertEquals(check_referral_cashback.call_count, 0)

    @patch('juloserver.referral.services.check_referral_cashback_v2')
    def test_referral_benefit_logic_v2_case_valid_cut_off_date(self, check_referral_cashback):
        account = AccountFactory(customer=self.referrer)
        account.status_id = 420
        account.save()
        loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_amount=54000,
        )

        self.application.update_safely(application_status_id=190)
        app_190_history = ApplicationHistoryFactory(
            application=self.application, status_old=110, status_new=190
        )
        app_190_history.update_safely(cdate=self.today - timedelta(days=5))
        referral_fs = FeatureSettingFactory(feature_name='referral_benefit_logic')
        process_referral_code_v2(self.application, loan, referral_fs)
        self.assertEquals(check_referral_cashback.call_count, 1)

    def test_promo_code_return_count_loan_fail_same_day_tc(self):
        disbursement = DisbursementFactory()
        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            disbursement_id=disbursement.id,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.FIXED_CASHBACK, value={'amount': 10000}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit,
            promo_code_daily_usage_count=5,
            promo_code_usage_count=10,
        )
        promo_code_usage = PromoCodeUsageFactory(
            loan_id=loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=promo_code,
        )
        for current_status in LoanStatusCodes.fail_status():
            loan.loan_status = StatusLookupFactory(
                status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING
            )
            loan.save()

            update_loan_status_and_loan_history(loan.id, current_status)

            loan.refresh_from_db()
            promo_code_usage.refresh_from_db()
            promo_code.refresh_from_db()
            self.assertEqual(loan.loan_status_id, current_status)
            self.assertEqual(9, promo_code.promo_code_usage_count)
            self.assertEqual(4, promo_code.promo_code_daily_usage_count)
            self.assertIsNotNone(promo_code_usage.cancelled_at)

    @mock.patch('django.utils.timezone.now')
    def test_promo_code_return_count_loan_fail_diff_day_tc(self, mock_now):
        mock_now.return_value = datetime(2024, 4, 10, 12, 23, 34)
        disbursement = DisbursementFactory()
        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            disbursement_id=disbursement.id,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.FIXED_CASHBACK, value={'amount': 10000}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit,
            promo_code_daily_usage_count=5,
            promo_code_usage_count=10,
        )
        promo_code_usage = PromoCodeUsageFactory(
            loan_id=loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=promo_code,
        )

        mock_now.return_value = datetime(2024, 4, 11, 12, 23, 34)
        for current_status in LoanStatusCodes.fail_status():
            loan.loan_status = StatusLookupFactory(
                status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING
            )
            loan.save()

            update_loan_status_and_loan_history(loan.id, current_status)

            loan.refresh_from_db()
            promo_code_usage.refresh_from_db()
            promo_code.refresh_from_db()
            self.assertEqual(loan.loan_status_id, current_status)
            self.assertEqual(9, promo_code.promo_code_usage_count)
            self.assertEqual(5, promo_code.promo_code_daily_usage_count)
            self.assertIsNotNone(promo_code_usage.cancelled_at)

    @patch('juloserver.julo.models.WorkflowStatusPath.objects')
    def test_promo_code_no_return_count_loan_fail_tc(self, mock_workflow_status_path):
        disbursement = DisbursementFactory()
        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            disbursement_id=disbursement.id,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.FIXED_CASHBACK, value={'amount': 10000}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit,
            promo_code_daily_usage_count=5,
            promo_code_usage_count=10,
        )
        PromoCodeUsageFactory(
            loan_id=loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=promo_code,
        )
        for old_status in LoanStatusCodes.fail_status():
            for current_status in LoanStatusCodes.fail_status():
                if old_status == current_status:
                    continue
                loan.loan_status = StatusLookupFactory(status_code=old_status)
                loan.save()
                mock_workflow_status_path.get_or_none.return_value = WorkflowStatusPathFactory(
                    status_previous=old_status, status_next=current_status, workflow=self.workflow
                )
                update_loan_status_and_loan_history(loan.id, current_status)
                loan.refresh_from_db()
                self.assertEqual(loan.loan_status_id, current_status)
                promo_code.refresh_from_db()
                self.assertEqual(10, promo_code.promo_code_usage_count)
                self.assertEqual(5, promo_code.promo_code_daily_usage_count)

    @patch('juloserver.referral.services.is_valid_referral_date')
    @patch('juloserver.referral.services.get_redis_client')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.moengage.services.use_cases.update_moengage_referral_event')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.loan.services.loan_related.update_is_proven_julo_one')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_duplicate_cashback_reactivate_loan_status(self, mock_get_tier_info,
                                                       mock_get_julo_pn_client,
                                                       mock_update_is_proven_julo_one,
                                                       mock_update_available_limit,
                                                       mock_update_moengage_referral_event,
                                                       mock_get_appsflyer_service,
                                                       mock_redis_client,
                                                       mock_is_valid_referral_date
                                                       ):
        mock_redis_client.return_value = self.fake_redis
        mock_is_valid_referral_date.return_value = True
        mock_get_tier_info.return_value = (0, self.tier)
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user_auth, self_referral_code='TEST_REFERRAL_CODE'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.application.application_status_id = 150
        self.application.save()

        ReferralSystemFactory()

        # benefit for referee
        self.user_auth2 = AuthUserFactory()
        self.customer2 = CustomerFactory(user=self.user_auth2)
        self.account2 = AccountFactory(customer=self.customer2)
        self.application2 = ApplicationFactory(
            customer=self.customer2, account=self.account2,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.application2.referral_code = 'TEST_REFERRAL_CODE'
        self.application2.application_status_id = 190
        self.application2.save()

        loan = LoanFactory(
            customer=self.customer2, application=self.application2, account=self.account2,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
        )

        ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=75000,
            referee_benefit=20000, min_disburse_amount=loan.loan_amount, is_active=True
        )

        update_loan_status_and_loan_history(loan.id, 220)
        loan.refresh_from_db()
        update_loan_status_and_loan_history(loan.id, 230)
        loan.refresh_from_db()
        update_loan_status_and_loan_history(loan.id, 220)

        loan.refresh_from_db()
        self.assertEquals(loan.loan_status_id, 220)

        referee_history = CustomerWalletHistory.objects.filter(customer=self.customer2).count()
        self.assertEquals(referee_history, 1)
        referrer_history = CustomerWalletHistory.objects.filter(customer=self.customer).count()
        self.assertEquals(referrer_history, 1)

        referee_cashback = CashbackBalance.objects.get(customer=self.customer2)
        self.assertEquals(referee_cashback.cashback_balance, 20000)
        referrer_cashback = CashbackBalance.objects.get(customer=self.customer)
        self.assertEquals(referrer_cashback.cashback_balance, 75000)

    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    @patch('juloserver.loan.services.loan_related.process_referral_code_v2')
    def test_zero_interest_in_loan_balance_consolidation(
        self,
        mock_process_referral_code,
        mock_get_tier_info,
        mock_get_julo_pn_client,
        mock_update_available_limit,
        mock_get_appsflyer_service,
    ):
        mock_get_tier_info.return_value = (0, self.tier)
        account_property = AccountPropertyFactory(account=self.account)
        account_property.save()
        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account
        )
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan.loan_status = self.status_lookup
        loan.account = self.account
        balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
        )
        consolidation_verification.account_limit_histories = {
            "upgrade": {"max_limit": 385918, "set_limit": 385919, "available_limit": 385920}
        }
        consolidation_verification.loan = loan
        loan.set_fund_transfer_time()
        loan.save()
        consolidation_verification.save()
        update_loan_status_and_loan_history(loan.id, 220)

        payments = Payment.objects.filter(loan_id=loan.id)
        for payment in payments:
            self.assertEqual(payment.installment_interest, payment.paid_interest)
            self.assertEqual(payment.installment_interest, payment.paid_amount)

    @patch('django.db.transaction.atomic')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_update_loan_x220_and_account_payment(
        self,
        mock_get_tier_info,
        mock_get_julo_pn_client,
        mock_update_available_limit,
        mock_get_appsflyer_service,
        mock_atomic
    ):
        mock_get_tier_info.return_value = (0, self.tier)
        referrer = CustomerFactory(self_referral_code='TEST_REFERRAL_CODE')
        referrer.save()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.application_status_id = 150
        self.application.referral_code = 'test_referral_code'
        self.application.save()
        account = AccountFactory(
            customer=self.application.customer)
        account.status_id = 410
        account.save()
        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account
        )
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan.loan_status = self.status_lookup
        loan.account = self.account
        loan.fund_transfer_ts = None
        loan.save()
        mock_atomic.side_effect = ConnectionError("Mocked ConnectionError")
        with self.assertRaises(ConnectionError):
            julo_one_loan_disbursement_success(loan)
        loan.refresh_from_db()
        assert loan.loan_status == self.status_lookup
        assert loan.fund_transfer_ts == None

    @patch('juloserver.moengage.services.use_cases.update_moengage_referral_event')
    def test_referral_benefit_logic_v2_referrer_is_deleted(self, update_moengage_referral_event):
        account = AccountFactory(customer=self.referrer)
        account.status_id = 420
        account.save()
        self.referrer_application.is_deleted = True
        self.referrer_application.save()
        loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_amount=2_100_000,
        )
        ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=50000,
            referee_benefit=20000, min_disburse_amount=2_000_000, is_active=True
        )
        self.application.update_safely(application_status_id=190)
        app_190_history = ApplicationHistoryFactory(
            application=self.application, status_old=110, status_new=190
        )
        app_190_history.update_safely(cdate=self.today - timedelta(days=5))
        referral_fs = FeatureSettingFactory(feature_name='referral_benefit_logic')
        referee = self.customer
        self.referral_system.activate_referee_benefit = True
        self.referral_system.save()
        check_referral_cashback_v2(
            referee,
            self.referrer,
            True,
            loan.loan_amount,
            referral_fs
        )
        self.assertEquals(update_moengage_referral_event.delay.call_count, 1)

    @patch('juloserver.moengage.services.use_cases.update_moengage_referral_event')
    def test_referral_benefit_logic_v2_referrer_success(self, update_moengage_referral_event):
        account = AccountFactory(customer=self.referrer)
        account.status_id = 420
        account.save()
        loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_amount=2_100_000,
        )
        ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=50000,
            referee_benefit=20000, min_disburse_amount=2_000_000, is_active=True
        )
        self.application.update_safely(application_status_id=190)
        app_190_history = ApplicationHistoryFactory(
            application=self.application, status_old=110, status_new=190
        )
        app_190_history.update_safely(cdate=self.today - timedelta(days=5))
        referral_fs = FeatureSettingFactory(feature_name='referral_benefit_logic')
        referee = self.customer
        self.referral_system.activate_referee_benefit = True
        self.referral_system.save()
        check_referral_cashback_v2(
            referee,
            self.referrer,
            True,
            loan.loan_amount,
            referral_fs
        )
        self.assertEquals(update_moengage_referral_event.delay.call_count, 2)

    @patch('juloserver.loan.services.loan_related.handle_loan_prize_chance_on_loan_status_change')
    @patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.send_event_to_ga')
    @patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    @patch('juloserver.loan.services.loan_related.execute_after_transaction_safely')
    def test_update_220_registration_fee_status(
        self, mock_execute_after_transaction_safely, mock_get_tier_info,
        mock_get_julo_pn_client, mock_update_available_limit, mock_get_appsflyer_service,
        mock_send_event_to_ga, mock_handle_loan_prize_chance,
    ):
        mock_get_appsflyer_service.return_value = event_response(
            status_code=200
        )
        mock_get_tier_info.return_value = (0, self.tier)
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.customer.appsflyer_device_id = "new_appsflyer_id"
        self.customer.app_instance_id = "appinstanceid"
        self.customer.save()

        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.customer.appsflyer_device_id = "new_appsflyer_id"
        self.application.application_status_id = 190
        self.application.save()
        account = AccountFactory(
            customer=self.application.customer)
        account.status_id = 410
        account.save()
        self.status_lookup = StatusLookupFactory(status_code=212)
        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account,
            loan_status=self.status_lookup
        )

        registration_fee = DigisignRegistrationFeeFactory(
            customer_id=self.customer.id,
            fee_type=DigisignFeeTypeConst.REGISTRATION_DUKCAPIL_FEE_TYPE,
            fee_amount=10_000,
            status=DigisignFeeTypeConst.REGISTRATION_FEE_CREATED_STATUS,
            extra_data={'loan_id': loan.id}
        )
        registration_fee.save()

        update_loan_status_and_loan_history(loan.id, 220)
        registration_fee.refresh_from_db()
        self.assertEqual(registration_fee.status, DigisignFeeTypeConst.REGISTRATION_FEE_CHARGED_STATUS)

    @patch('juloserver.loan.services.loan_related.handle_loan_prize_chance_on_loan_status_change')
    @patch('juloserver.google_analytics.clients.GoogleAnalyticsClient.send_event_to_ga')
    @patch('juloserver.julo.clients.appsflyer.JuloAppsFlyer.post_event')
    @patch('juloserver.loan.services.loan_related.update_available_limit')
    @patch('juloserver.julo.clients.get_julo_pn_client')
    @patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    @patch('juloserver.loan.services.loan_related.execute_after_transaction_safely')
    def test_update_fail_status_registration_fee_status(
        self, mock_execute_after_transaction_safely, mock_get_tier_info,
        mock_get_julo_pn_client, mock_update_available_limit, mock_get_appsflyer_service,
        mock_send_event_to_ga, mock_handle_loan_prize_chance,
    ):
        mock_get_appsflyer_service.return_value = event_response(
            status_code=200
        )
        mock_get_tier_info.return_value = (0, self.tier)
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.customer.appsflyer_device_id = "new_appsflyer_id"
        self.customer.app_instance_id = "appinstanceid"
        self.customer.save()

        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.customer.appsflyer_device_id = "new_appsflyer_id"
        self.application.application_status_id = 190
        self.application.save()
        account = AccountFactory(
            customer=self.application.customer)
        account.status_id = 410
        account.save()
        self.status_lookup = StatusLookupFactory(status_code=212)
        disbursement = DisbursementFactory()
        loan = LoanFactory(
            customer=self.customer, application=self.application, account=self.account,
            loan_status=self.status_lookup, disbursement_id=disbursement.id
        )

        for current_status in LoanStatusCodes.fail_status():
            loan.update_safely(loan_status=self.status_lookup)
            registration_fee = DigisignRegistrationFeeFactory(
                customer_id=self.customer.id,
                fee_type=DigisignFeeTypeConst.REGISTRATION_DUKCAPIL_FEE_TYPE,
                fee_amount=20_000,
                status=DigisignFeeTypeConst.REGISTRATION_FEE_CREATED_STATUS,
                extra_data={'loan_id': loan.id}
            )
            registration_fee.save()

            update_loan_status_and_loan_history(loan.id, current_status)
            registration_fee.refresh_from_db()
            self.assertEqual(
                registration_fee.status, DigisignFeeTypeConst.REGISTRATION_FEE_CANCELLED_STATUS
            )


class TestCheckPromoCode(TestCase):

    def setUp(self):
        self.customer = CustomerFactory()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.promo_code = PromoCodeFactory()
        self.application = ApplicationFactory(customer=self.customer,
                                              account=self.account,
                                              referral_code=self.promo_code.promo_code)
        self.loan = LoanFactory(customer=self.customer, account=self.account)
        self.payment = PaymentFactory(loan=self.loan)
        self.credit_score = CreditScoreFactory()

    def test_check_promo_code_cashback(self):
        check_promo_code_julo_one(self.loan)
        self.assertEqual(len(PromoHistory.objects.all()), 1)

    def test_check_promo_code_interest(self):
        self.promo_code.promo_benefit = '0% INTEREST'
        self.promo_code.save()
        self.promo_code.refresh_from_db()
        check_promo_code_julo_one(self.loan)
        self.assertEqual(len(WaivePromo.objects.all()), 1)

    def test_loan_not_eligible_promo(self):
        self.promo_code.partner = ['test_fail_partner']
        self.promo_code.save()
        self.promo_code.refresh_from_db()
        check_promo_code_julo_one(self.loan)
        self.assertEqual(len(PromoHistory.objects.all()), 0)

        self.promo_code.product_line = ['test_fail_product_line']
        self.promo_code.save()
        self.promo_code.refresh_from_db()
        check_promo_code_julo_one(self.loan)
        self.assertEqual(len(PromoHistory.objects.all()), 0)

        self.credit_score.application = self.application
        self.credit_score.save()
        self.promo_code.credit_score = ['test_fail_credit_score']
        self.promo_code.save()
        self.promo_code.refresh_from_db()
        check_promo_code_julo_one(self.loan)
        self.assertEqual(len(PromoHistory.objects.all()), 0)


class TestVoidUnexpectedPathPPOB(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.loan = LoanFactory(
            account=self.account,
            disbursement_id=888
        )
        LoanHistory.objects.create(
            loan=self.loan,
            status_old=StatusLookup.CURRENT_CODE,
            status_new=StatusLookup.FUND_DISBURSAL_FAILED
        )
        self.account_payment = AccountPaymentFactory(
            account=self.loan.account,
            due_amount=self.loan.loan_amount
        )
        PaymentFactory(
            loan=self.loan,
            account_payment=self.account_payment
        )
        self.payment = self.loan.payment_set.first()
        self.loan.payment_set.all().exclude(id=self.payment.id).delete()
        self.payment.account_payment = self.account_payment
        self.payment.save()
        self.sepulsa_transaction = SepulsaTransactionFactory(
            transaction_status='failed',
            loan=self.loan
        )
        Vendor.objects.get_or_create(
            vendor_name=PartnerConstant.SEPULSA_PARTNER)
        self.vendor = Vendor.objects.filter(vendor_name=PartnerConstant.SEPULSA_PARTNER).last()
        self.spend_transaction = SpendTransaction.objects.create(
            spend_product=self.sepulsa_transaction,
            vendor=self.vendor
        )
        self.accounting_cutoff_date = AccountingCutOffDateFactory()

    def test_void_unexpected_ppob_path(self):
        void_ppob_transaction(self.loan)
        assert AccountTransaction.objects.filter(
            account=self.loan.account,
            transaction_type=VoidTransactionType.PPOB_VOID,
            can_reverse=False
        ).exists()


class TestFraudService(TestCase):

    def setUp(self):
        self.application = ApplicationFactory()
        self.user = AuthUserFactory()
        self.request = http_request({'HTTP_X_FORWARDED_FOR': '192.168.20.111'}, self.user)
        self.loan = LoanFactory()
        self.decision = TransactionRiskyDecisionFactory()

    @patch('juloserver.loan.services.loan_related.check_suspicious_ip')
    def test_suspicious_ip_loan_fraud_check(self, mock_check_suspicious_ip):
        mock_check_suspicious_ip.return_value = False
        result = suspicious_ip_loan_fraud_check(self.loan, self.request)
        self.assertFalse(result.is_vpn_detected)

        mock_check_suspicious_ip.return_value = True
        result = suspicious_ip_loan_fraud_check(self.loan, self.request)
        loan_risky_check = result
        self.assertIsNotNone(result)

        # TransactionRiskyCheck is already existed
        result = suspicious_ip_loan_fraud_check(self.loan, self.request)
        self.assertIsNone(result)

        # ip address not found
        request = http_request({}, self.user)
        result = suspicious_ip_loan_fraud_check(self.loan, request)
        self.assertIsNone(result)

        # is_suspicious_ip param is true
        loan_risky_check.update_safely(is_vpn_detected=False)
        result = suspicious_ip_loan_fraud_check(self.loan, request, True)
        self.assertIsNotNone(result)

    @patch('juloserver.loan.services.loan_related.check_fraud_hotspot_gps')
    def test_suspicious_hotspot_loan_fraud_check(self, mock_check_fraud_hotspot_gps):
        data = {
            'loan': self.loan,
            'gcm_reg_id': 'test_gcm_reg_id_id',
            'android_id': 'test_android_id',
            'latitude': '3.0',
            'longitude': '100.0',
            'imei': 'dAuisyey3812heui7821y3h',
            'manufacturer': '11111111111111111111111111',
            'model': 'ip 13 promax'
        }
        mock_check_fraud_hotspot_gps.return_value = False
        result = suspicious_hotspot_loan_fraud_check(self.loan, data)
        self.assertFalse(result.is_fh_detected)

        mock_check_fraud_hotspot_gps.return_value = True
        result = suspicious_hotspot_loan_fraud_check(self.loan, data)
        loan_risky_check = result
        self.assertIsNotNone(result)

        # TransactionRiskyCheck is already existed
        result = suspicious_hotspot_loan_fraud_check(self.loan, data)
        self.assertIsNone(result)


class TestTransactionMethodLimit(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.tm = TransactionMethod.objects.get(pk=1)
        self.loans = []
        self.loan_histories = []
        for i in range(10):
            loan = LoanFactory(
                account=self.account, transaction_method=self.tm)
            loan.loan_status_id = 211
            loan.save()
            self.loans.append(loan)
            loan_history = LoanHistoryFactory(
                loan=loan,
                status_old=0,
                status_new=211)
            self.loan_histories.append(loan_history)
        method_names = TransactionMethod.objects.all().values_list('method', flat=True)
        initial_data = {}
        for name in method_names:
            initial_data[name] = {
                '24 hr': 10,
                '1 hr': 5,
                '5 min': 1,
                'is_active': True
                }
        self.errors = {
            '24 hr': "Maaf Anda telah mencapai batas maksimal transaksi harian. Silakan coba lagi besok",
            'other': "Mohon tunggu sebentar untuk melakukan transaksi ini"
        }
        initial_data['errors'] = self.errors
        feature = FeatureSetting.objects.create(
            is_active=True,
            feature_name=LoanFeatureNameConst.TRANSACTION_METHOD_LIMIT,
            parameters=initial_data)

    def test_transaction_method_limit_check_24hr(self):
        success, msg = transaction_method_limit_check(self.account, self.tm)
        assert success == False

    def test_transaction_method_limit_check_5min(self):
        LoanHistory.objects.all().delete()
        LoanHistoryFactory(loan=self.loans[0], status_old=0, status_new=211)
        success, msg = transaction_method_limit_check(self.account, self.tm)
        assert success == False
        for loan in self.loans[:5]:
            LoanHistoryFactory(loan=loan, status_old=0, status_new=211)
        success, msg = transaction_method_limit_check(self.account, self.tm)
        assert success == False


class TestTransactionHardToReach(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.tm = TransactionMethod.objects.get(pk=1)
        self.loan = LoanFactory(
            account=self.account, transaction_method=self.tm)
        self.loan.save()

        self.decision = TransactionRiskyDecisionFactory()

    @mock.patch('juloserver.loan.services.loan_related.is_account_hardtoreach')
    def test_transaction_is_hardtoreach_true(self, mock_is_account_hardtoreach):
        mock_is_account_hardtoreach.return_value = True
        transaction_hardtoreach_check(self.loan, self.account.id)
        loan_risk_check = TransactionRiskyCheck.objects.get(loan=self.loan)
        self.assertTrue(loan_risk_check.is_hardtoreach)

    @mock.patch('juloserver.loan.services.loan_related.is_account_hardtoreach')
    def test_transaction_is_hardtoreach_false(self, mock_is_account_hardtoreach):
        mock_is_account_hardtoreach.return_value = False
        transaction_hardtoreach_check(self.loan, self.account.id)
        loan_risk_check = TransactionRiskyCheck.objects.get(loan=self.loan)
        self.assertFalse(loan_risk_check.is_hardtoreach)


class TestCampaignCashback(TestCase):
    def setUp(self):
        pass

    @patch('juloserver.loan.tasks.campaign.timezone')
    @patch('juloserver.loan.tasks.campaign.trigger_reward_cashback_for_campaign_190')
    def test_campaign_190_not_date_in_range(self, m_trigger_reward, m_timezone):
        today = datetime.strptime("2000-12-01", "%Y-%m-%d")
        end_date = "1900-12-01"
        start_date = "1800-12-01"
        FeatureSettingFactory(is_active=True, feature_name=FeatureNameConst.CAMPAIGN_190_SETTINGS,
            parameters={
                'start_date': start_date,
                'end_date': end_date,
            }
        )
        m_timezone.localtime.return_value = today
        trigger_reward_cashback_for_limit_usage()
        self.assertEqual(m_trigger_reward.call_count, 0)


    @patch('juloserver.loan.tasks.campaign.FeatureSetting.objects')
    @patch('juloserver.loan.tasks.campaign.trigger_reward_cashback_for_campaign_190')
    def test_campaign_190_no_feature_settings(self, m_trigger_reward, m_FeatureSetting):
        m_FeatureSetting.filter.return_value = m_FeatureSetting
        m_FeatureSetting.last.return_value = False
        trigger_reward_cashback_for_limit_usage()
        self.assertEqual(m_trigger_reward.call_count, 0)


    def test_trigger_function_campaign_190(self):
        promo_loan_amount = 1000
        promo_cashback_amount = 2000
        campaign_code = "campaign_unit_test"
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        LoanFactory(customer=customer, loan_amount=promo_loan_amount+10000, account=account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT))

        InAppNotificationHistory.objects.create(customer_id=str(customer.id), status="clicked",
            template_code=campaign_code
        )
        three_days_ago = timedelta(days=3)
        trigger_reward_cashback_for_campaign_190(
            promo_cashback_amount=promo_cashback_amount,
            promo_loan_amount=promo_loan_amount,
            money_change_reason="unit_test",
            time_ago=three_days_ago,
            campaign_code=campaign_code
        )
        wallet_history = CustomerWalletHistory.objects.filter(customer=customer).first()
        self.assertEqual(wallet_history.wallet_balance_available, promo_cashback_amount)


    def test_function_campaign_190_case_same_money_change_reason(self):
        promo_loan_amount = 1000
        promo_cashback_amount = 2000
        campaign_code = "campaign_unit_test"
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        LoanFactory(customer=customer, loan_amount=promo_loan_amount+10000, account=account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT))

        InAppNotificationHistory.objects.create(customer_id=str(customer.id), status="clicked",
            template_code=campaign_code
        )

        three_days_ago = timedelta(days=3)
        money_change_reason = "unit test"
        CustomerWalletHistoryFactory(
            customer=customer,
            change_reason=money_change_reason,
            wallet_balance_available = 1000
        )
        trigger_reward_cashback_for_campaign_190(
            promo_cashback_amount=promo_cashback_amount,
            promo_loan_amount=promo_loan_amount,
            money_change_reason=money_change_reason,
            time_ago=three_days_ago,
            campaign_code=campaign_code
        )
        wallet_history = CustomerWalletHistory.objects.filter(customer=customer).last()
        self.assertEqual(wallet_history.wallet_balance_available, 1000)

    @patch('juloserver.loan.tasks.campaign.timezone')
    @patch('juloserver.loan.tasks.campaign.trigger_reward_cashback_for_campaign_190')
    def test_campaign_190_with_feature_settings(self, m_trigger_reward, m_timezone):
        today = datetime.strptime("2000-12-01", "%Y-%m-%d")
        m_timezone.localtime.return_value = today
        end_date = "2100-12-01"
        start_date = "1800-12-01"
        segments = {
            "seg1": {
                "campaign_code": "Campaign190_segment1",
                "cashback_amount": 10000,
                "min_loan": 100000
            },
            "seg2": {
                "campaign_code": "Campaign190_segment2",
                "cashback_amount": 10000,
                "min_loan": 500000
            },
            "seg3": {
                "campaign_code": "Campaign190_segment3",
                "cashback_amount": 10000,
                "min_loan": 750000
            },
            "seg4": {
                "campaign_code": "Campaign190_segment4",
                "cashback_amount": 10000,
                "min_loan": 1000000
            },
        }
        FeatureSettingFactory(is_active=True, feature_name=FeatureNameConst.CAMPAIGN_190_SETTINGS,
            parameters={
                'start_date': start_date,
                'end_date': end_date,
                'money_change_reason': "unittest",
                'segments': segments,
            }
        )
        trigger_reward_cashback_for_limit_usage()
        time_ago = relativedelta(days=3)
        expected_calls = [
            call(promo_cashback_amount=10000, promo_loan_amount=100000, time_ago=time_ago,
                    money_change_reason='unittest', campaign_code='Campaign190_segment1'),
            call(promo_cashback_amount=10000, promo_loan_amount=500000, time_ago=time_ago,
                    money_change_reason='unittest', campaign_code='Campaign190_segment2'),
            call(promo_cashback_amount=10000, promo_loan_amount=750000, time_ago=time_ago,
                    money_change_reason='unittest', campaign_code='Campaign190_segment3'),
            call(promo_cashback_amount=10000, promo_loan_amount=1000000, time_ago=time_ago,
                    money_change_reason='unittest', campaign_code='Campaign190_segment4'),
        ]
        m_trigger_reward.assert_has_calls(expected_calls)


class TestProductsLocked(TestCase):
    def setUp(self):
        status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.customer = CustomerFactory()
        self.account = AccountFactory(status=status, customer=self.customer)
        self.app = ApplicationFactory(account=self.account)
        self.tier_one = CfsTierFactory(id=1, name='Starter', point=100)
        self.tier_two = CfsTierFactory(id=2, name='Advanced', point=300)
        self.tier_three = CfsTierFactory(id=3, name='Pro', point=600)
        self.tier_four = CfsTierFactory(id=4, name='Champion', point=1000)
        self.method_other_code = TransactionMethodCode.OTHER.code

    @patch('juloserver.loan.services.loan_related.is_julo_one_product_locked_and_reason')
    @patch('juloserver.loan.services.loan_related.get_julo_one_is_proven')
    @patch('juloserver.loan.services.loan_related.is_graduate_of')
    def test_locked_tier_pro_and_above_method_other(self, mock_proven_graduate, mock_is_proven, mock_islocked):
        # is proven graduate
        mock_proven_graduate.return_value = True
        mock_is_proven.return_value = False
        mock_islocked.return_value = False, None

        is_product_locked(self.account, self.method_other_code)
        mock_islocked.assert_called_once()
        mock_is_proven.assert_not_called()


    @patch('juloserver.loan.services.loan_related.get_julo_one_is_proven')
    @patch('juloserver.loan.services.loan_related.is_graduate_of')
    def test_locked_tier_regular_and_below_method_other(self, mock_proven_graduate, mock_is_proven):
        # is not proven graduate
        mock_proven_graduate.return_value = False
        mock_is_proven.return_value = False

        is_product_locked(self.account, self.method_other_code)

        mock_is_proven.assert_called_once()

    def test_product_locked_balance_consolidation(self):
        balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        BalanceConsolidationVerificationFactory(
            balance_consolidation=balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
        )
        # is not proven graduate
        assert is_product_locked(self.account, self.method_other_code) == True


class TestCalculateLoanAmount(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.product_line = ProductLineFactory(product_line_code=1)
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
        )

        self.product = ProductLookupFactory(origination_fee_pct=0.20)
        self.credit_matrix = CreditMatrixFactory(
            min_threshold=0.95, max_threshold=1,
            product=self.product,
            version='1',
            transaction_type=TransactionType.SELF,
            is_salaried=True,
            is_premium_area=True,
            credit_matrix_type=CreditMatrixType.JULO1_PROVEN,
            parameter=None,
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            product=self.product_line
        )
        CurrentCreditMatrix.objects.create(
            credit_matrix=self.credit_matrix, transaction_type=TransactionType.SELF
        )
        self.account_property = AccountPropertyFactory(
            pgood=0.99, p0=0.99, account=self.account, is_proven=True,
            is_salaried=True, is_premium_area=True
        )

    def test_calculate_loan_amount(self):
        ret_val = calculate_loan_amount(
            loan_amount_requested=200000,
            application=self.application,
            transaction_type=TransactionType.SELF,
        )
        self.assertEqual(250000, ret_val[0])
        self.assertEqual(self.credit_matrix, ret_val[1])
        self.assertEqual(self.credit_matrix_product_line, ret_val[2])


class TestCalculateFirstInterest(TestCase):
    def setUp(self):
        pass

    def test_compute_first_payment_installment_julo_one(self):
        loan_amount = 20217
        duration = 5
        today_date = datetime(2022, 11, 11)
        first_due_date = datetime(2022, 11, 21)
        monthly_interest_rate = 0.08

        # greater than 0
        first_due_date = datetime(2022, 11, 30)
        _, interest, _ = compute_first_payment_installment_julo_one(
            loan_amount, duration, monthly_interest_rate, today_date, first_due_date
        )
        self.assertGreater(interest, 0)


class TestTransactionWebLocationBlockedCheck(TestCase):
    def setUp(self):
        self.decision = TransactionRiskyDecisionFactory()

    def test_location_blocked_with_coordinates(self):
        loan = LoanFactory()
        transaction_web_location_blocked_check(loan=loan, latitude=14.0583, longitude=108.2772)

        loan_risk_check = TransactionRiskyCheck.objects.get(loan=loan)
        self.assertIsNone(loan_risk_check.is_web_location_blocked)
        self.assertIsNone(loan_risk_check.decision)

    def test_location_blocked_without_coordinates(self):
        loan = LoanFactory()
        transaction_web_location_blocked_check(loan=loan, latitude=None, longitude=None)

        loan_risk_check = TransactionRiskyCheck.objects.get(loan=loan)
        self.assertTrue(loan_risk_check.is_web_location_blocked)
        self.assertEqual(loan_risk_check.decision, self.decision)


class TestZeroInterestFunction(TestCase):
    def setUp(self):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
            parameters={
                "condition": {
                    "min_loan_amount": 30_000,
                    "max_loan_amount": 1_000_000,
                    "min_duration": 2,
                    "max_duration": 5,
                    "list_transaction_method_code": ["1"],
                },
                "whitelist": {
                    "is_active": False,
                    "list_customer_id": [],
                },
                "is_experiment_for_last_digit_customer_id_is_even": False,
                "customer_segments": {"is_ftc": True, "is_repeat": True},
            },
            is_active=False,
        )

    def test_get_range_loan_duration_and_amount_apply_zero_interest(self):
        # INACTIVE FS
        # => False
        self.fs.is_active = False
        self.fs.save()
        result = get_range_loan_duration_and_amount_apply_zero_interest(1, 123)
        self.assertEqual(result, (False, None, None, None, None))

        # ACTIVE FS
        self.fs.is_active = True
        self.fs.save()

        # enable whitelist, but the customer is not in the whitelist
        # => False
        self.fs.parameters['whitelist']['is_active'] = True
        self.fs.parameters['whitelist']['list_customer_id'] = []
        self.fs.save()
        result = get_range_loan_duration_and_amount_apply_zero_interest(1, 123)
        self.assertEqual(result, (False, None, None, None, None))

        # enable whitelist, and the customer is in the whitelist
        # => True
        self.fs.parameters['whitelist']['list_customer_id'] = [123]
        self.fs.save()
        result = get_range_loan_duration_and_amount_apply_zero_interest(1, 123)
        self.assertEqual(
            result,
            (
                True,
                self.fs.parameters['condition']['min_duration'],
                self.fs.parameters['condition']['max_duration'],
                self.fs.parameters['condition']['min_loan_amount'],
                self.fs.parameters['condition']['max_loan_amount'],
            )
        )

        # enable whitelist, and the customer is in the whitelist,
        # but transaction method is not applicable
        # => False
        result = get_range_loan_duration_and_amount_apply_zero_interest(2, 123)
        self.assertEqual(result, (False, None, None, None, None))

        # enable whitelist, and the customer not is in the whitelist,
        # enable experiment, and the customer is in the experiment
        # => False because we prioritize whitelist
        self.fs.parameters['whitelist']['is_experiment_for_last_digit_customer_id_is_even'] = True
        self.fs.save()
        result = get_range_loan_duration_and_amount_apply_zero_interest(1, 1234)
        self.assertEqual(result, (False, None, None, None, None))

        # disable whitelist, enable experiment, and the customer is in the experiment
        # => True
        self.fs.parameters['whitelist']['is_active'] = False
        self.fs.save()
        result = get_range_loan_duration_and_amount_apply_zero_interest(1, 1234)
        self.assertEqual(
            result,
            (
                True,
                self.fs.parameters['condition']['min_duration'],
                self.fs.parameters['condition']['max_duration'],
                self.fs.parameters['condition']['min_loan_amount'],
                self.fs.parameters['condition']['max_loan_amount'],
            )
        )

        # disable whitelist, enable experiment, and the customer is in the experiment
        # but transaction method is not applicable
        # => False
        result = get_range_loan_duration_and_amount_apply_zero_interest(2, 1234)
        self.assertEqual(result, (False, None, None, None, None))

        # disable whitelist, disable experiment
        # => True
        self.fs.parameters['whitelist']['is_active'] = False
        self.fs.parameters['whitelist']['is_experiment_for_last_digit_customer_id_is_even'] = False
        self.fs.save()
        result = get_range_loan_duration_and_amount_apply_zero_interest(1, 12345)
        self.assertEqual(
            result,
            (
                True,
                self.fs.parameters['condition']['min_duration'],
                self.fs.parameters['condition']['max_duration'],
                self.fs.parameters['condition']['min_loan_amount'],
                self.fs.parameters['condition']['max_loan_amount'],
            )
        )

        # disable whitelist, disable experiment
        # but transaction method is not applicable
        # => False
        result = get_range_loan_duration_and_amount_apply_zero_interest(2, 12345)
        self.assertEqual(result, (False, None, None, None, None))

    def test_is_eligible_apply_zero_interest(self):
        # ACTIVE FS, DISABLE WHITELIST, DISABLE EXPERIMENT
        self.fs.is_active = True
        self.fs.parameters['whitelist']['is_active'] = False
        self.fs.parameters['whitelist']['is_experiment_for_last_digit_customer_id_is_even'] = False
        self.fs.save()

        # loan amount < min_loan_amount
        result = is_eligible_apply_zero_interest(1, 123, 1, 500)
        self.assertFalse(result)

        # loan amount > max_loan_amount
        result = is_eligible_apply_zero_interest(1, 123, 1, 5_000_000)
        self.assertFalse(result)

        # loan duration < min_duration
        result = is_eligible_apply_zero_interest(1, 123, 1, 500_000)
        self.assertFalse(result)

        # loan duration > max_duration
        result = is_eligible_apply_zero_interest(1, 123, 6, 500_000)
        self.assertFalse(result)

        # loan amount and duration is in range
        result = is_eligible_apply_zero_interest(1, 123, 2, 30_000)
        self.assertTrue(result)
        result = is_eligible_apply_zero_interest(1, 123, 3, 500_000)
        self.assertTrue(result)
        result = is_eligible_apply_zero_interest(1, 123, 5, 1_000_000)
        self.assertTrue(result)

        # loan amount and duration is in range, but transaction method is not applicable
        result = is_eligible_apply_zero_interest(3, 123, 3, 500_000)
        self.assertFalse(result)


class TestEligibleUserTypeFunction(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE),
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
            parameters={
                "condition": {
                    "min_loan_amount": 30_000,
                    "max_loan_amount": 1_000_000,
                    "min_duration": 2,
                    "max_duration": 5,
                    "list_transaction_method_code": ["1"],
                },
                "whitelist": {
                    "is_active": False,
                    "list_customer_id": [],
                },
                "is_experiment_for_last_digit_customer_id_is_even": False,
            },
            is_active=False,
        )

    def test_is_customer_segments_zero_interest_ftc(self):
        customer_segments = {"is_ftc": True, "is_repeat": True}
        is_customer_segment, segment = is_customer_segments_zero_interest(customer_segments,
                                                                          self.customer.id)
        self.assertEqual(segment, 'ftc')

    def test_is_customer_segments_zero_interest_repeat(self):
        customer_segments = {"is_ftc": True, "is_repeat": True}
        LoanFactory(
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            account=self.account,
            application=self.application,
        )
        is_customer_segment, segment = is_customer_segments_zero_interest(customer_segments,
                                                                          self.customer.id)
        self.assertEqual(segment, 'repeat')

    def test_is_customer_segments_zero_interest_blacklist(self):
        customer_segments = {"is_ftc": True, "is_repeat": True}
        ZeroInterestExcludeFactory(customer_id=self.customer.id)
        is_customer_segment, segment = is_customer_segments_zero_interest(customer_segments,
                                                                          self.customer.id)
        self.assertEqual(is_customer_segment, False)

    def test_is_customer_segments_zero_interest_account_not_exist(self):
        customer = CustomerFactory()
        customer_segments = {"is_ftc": True, "is_repeat": True}
        ZeroInterestExcludeFactory(customer_id=customer.id)
        is_customer_segment, segment = is_customer_segments_zero_interest(customer_segments,
                                                                          customer.id)
        self.assertEqual(is_customer_segment, False)


class TestCheckActiveLoansUsingFdcFunction(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.nik = '041100'
        self.customer = CustomerFactory(user=self.user_auth, nik=self.nik)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line,
            ktp=self.nik,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.deleted_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.CUSTOMER_ON_DELETION
        )
        self.application.save()
        self.credit_score = CreditScoreFactory(application_id=self.application.pk, score='C')
        # Dana
        partner = PartnerFactory(user=self.user_auth, is_active=True)
        self.dana_product_line = ProductLineFactory(product_line_code=ProductLineCodes.DANA)
        self.dana_user_auth = AuthUserFactory()
        self.dana_customer = CustomerFactory(user=self.dana_user_auth)
        self.dana_application = ApplicationFactory(
            customer=self.dana_customer, product_line=self.dana_product_line, ktp=self.nik
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679776',
            customer=self.dana_customer,
            nik=self.nik,
            application=self.dana_application,
            partner_id=partner.pk,
            full_name='test',
            proposed_credit_limit=1_000_000,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_property = AccountPropertyFactory(account=self.account, pgood=0.75)
        self.customer_segment = 'activeus_a'
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
            parameters={
                "number_of_allowed_active_loans": 3,
                "number_of_allowed_platforms": 3,
                "whitelist": {
                    "is_active": False,
                    "list_application_id": [],
                },
                "bypass": {
                    "is_active": False,
                    "list_application_id": [],
                },
                "ineligible_message_for_old_application": "ineligible_message_for_old_application",
                "popup": {},
                "ineligible_alert_after_fdc_checking": {},
                "transaction_methods_bypass": {
                    "is_active": False,
                    "whitelist": []
                }
            },
            is_active=False,
        )

    def test_get_parameters_fs_check_other_active_platforms_using_fdc(self):
        # INACTIVE FS
        # => False
        self.fs.is_active = False
        self.fs.save()
        result = get_parameters_fs_check_other_active_platforms_using_fdc()
        self.assertEqual(result, None)

        # ACTIVE FS
        self.fs.is_active = True
        self.fs.save()
        result = get_parameters_fs_check_other_active_platforms_using_fdc()
        self.assertIsNotNone(result)

    def test_is_apply_check_other_active_platforms_using_fdc(self):
        # INACTIVE FS
        # => False
        self.fs.is_active = False
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, False)

        # ACTIVE FS
        self.fs.is_active = True

        # enable whitelist, but the application is not in the whitelist
        # => False
        self.fs.parameters['whitelist']['is_active'] = True
        self.fs.parameters['whitelist']['list_application_id'] = []
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, False)

        # enable whitelist, and the application is in the whitelist
        # => True
        self.fs.parameters['whitelist']['list_application_id'] = [self.application.id]
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, True)

        # disable whitelist, enable bypass, but the application is not in the bypass list
        # => True
        self.fs.parameters['whitelist']['is_active'] = False
        self.fs.parameters['bypass']['is_active'] = True
        self.fs.parameters['bypass']['list_application_id'] = []
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, True)

        # disable whitelist, enable bypass, but the application is in the bypass list
        # => False
        self.fs.parameters['bypass']['list_application_id'] = [self.application.id]
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, False)

        # disable whitelist, enable bypass, the application is not in the bypass list,
        # but the application id is not in the FDCPlatformCheckBypass
        # => True
        self.fs.parameters['bypass']['list_application_id'] = []
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, True)

        # disable whitelist, enable bypass, the application is not in the bypass list,
        # but the application id is in the FDCPlatformCheckBypass
        # => False
        FDCPlatformCheckBypassFactory(
            application_id=self.application.id,
        )
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, False)

        # disable whitelist, disable bypass
        # => True
        self.fs.parameters['bypass']['is_active'] = False
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, True)

        # turn off c_score_bypass => True
        self.fs.parameters.update(
            c_score_bypass=dict(is_active=False, pgood_gte=0.75),
        )
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, True)

        # pgood = 0.75 => bypass
        self.fs.parameters['c_score_bypass']['is_active'] = True
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, False)

        # pgood < 0.75 => checking fdc
        self.fs.parameters['c_score_bypass']['is_active'] = True
        self.fs.save()
        self.account_property.pgood = 0.74
        self.account_property.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, True)

        # pgood = 0.8 > 0.75 => bypass
        self.fs.parameters['c_score_bypass']['is_active'] = True
        self.fs.save()
        self.account_property.pgood = 0.8
        self.account_property.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id)
        self.assertEqual(result, False)

        # test bypass balance consolidation
        self.fs.parameters['transaction_methods_bypass']['is_active'] = True
        self.fs.parameters['transaction_methods_bypass']['whitelist'] = [
            TransactionMethodCode.BALANCE_CONSOLIDATION.code
        ]
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(
            self.application.id,
            transaction_method_id=TransactionMethodCode.BALANCE_CONSOLIDATION.code)
        self.assertEqual(result, False)

        # inactive bypass
        self.fs.parameters['transaction_methods_bypass']['is_active'] = False
        self.fs.save()
        self.account_property.pgood = 0.7
        self.account_property.save()
        result = is_apply_check_other_active_platforms_using_fdc(
            self.application.id,
            transaction_method_id=TransactionMethodCode.BALANCE_CONSOLIDATION.code)
        self.assertEqual(result, True)

        # bypass active but not exist in the list
        self.fs.parameters['transaction_methods_bypass']['is_active'] = True
        self.fs.parameters['transaction_methods_bypass']['whitelist'] = []
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(
            self.application.id,
            transaction_method_id=TransactionMethodCode.BALANCE_CONSOLIDATION.code)
        self.assertEqual(result, True)

    def test_not_show_pop_with_3pr(self):
        self.fs.parameters['transaction_methods_bypass']['is_active'] = True
        self.fs.parameters['transaction_methods_bypass']['whitelist'] = [
            TransactionMethodCode.SELF.code]
        self.fs.is_active = True
        self.fs.save()
        url = '/api/loan/v1/active-platform-rule-check?transaction_type_code=1'
        response = self.client.get(url)
        data = response.json()['data']
        assert data['is_button_enable'] == True

        # not found application
        self.application.application_status = self.deleted_status
        self.application.save()
        url_no_params = '/api/loan/v1/active-platform-rule-check'
        response = self.client.get(url_no_params)
        assert response.json()['errors'] == [
            "Terdapat kesalahan silahkan hubungi customer service JULO."
        ]

    @patch('juloserver.loan.services.loan_related.get_or_non_fdc_inquiry_not_out_date')
    @patch('juloserver.loan.services.loan_related.get_info_active_loan_from_platforms')
    def test_is_eligible_other_active_platforms(
        self, mock_get_info_active_loan_from_platforms, mock_get_or_non_fdc_inquiry_not_out_date
    ):
        # have active loans on Julo -> True
        loan = LoanFactory(customer=self.customer, loan_status=StatusLookupFactory(status_code=220))
        is_eligible = is_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible, True)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )

        # Dana product check 3PR when the customer has active loan in J1 => bypass
        is_eligible = is_eligible_other_active_platforms(
            application_id=self.dana_application.pk,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible, True)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )

        fdc_active_loan_checking = FDCActiveLoanChecking.objects.get(
            customer_id=self.application.customer_id
        )
        self.assertEqual(
            fdc_active_loan_checking.last_access_date, timezone.localtime(timezone.now()).date()
        )
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, None)
        fdc_active_loan_checking.last_access_date = (
            timezone.localtime(timezone.now()).date() - timedelta(days=2)
        )
        fdc_active_loan_checking.save()
        loan.loan_status = StatusLookupFactory(status_code=216)
        loan.save()

        # not exists FDCInquiry not outdated data -> True
        mock_get_or_non_fdc_inquiry_not_out_date.return_value = None
        is_eligible = is_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible, True)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )
        fdc_active_loan_checking.refresh_from_db()
        # already exist, but last_access_date is not today -> update last_access_date to today
        self.assertEqual(
            fdc_active_loan_checking.last_access_date, timezone.localtime(timezone.now()).date()
        )
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, None)

        # exists FDCInquiry not outdated data
        mock_get_or_non_fdc_inquiry_not_out_date.return_value = FDCInquiry(pk=1)
        # number current other platforms = 2 -> True
        mock_get_info_active_loan_from_platforms.return_value = (None, 2, 2)
        is_eligible = is_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible, True)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )
        fdc_active_loan_checking.refresh_from_db()
        # number_of_other_platforms already updated
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, 2)

        # 3 other platforms + Julo = 4 platforms > 3 allowed platforms
        mock_get_info_active_loan_from_platforms.return_value = (None, 3, 1)
        is_eligible = is_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        active_loan_checking = FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).last()

        self.assertEqual(self.application.product_line_id, active_loan_checking.product_line_id)
        self.assertEqual(is_eligible, False)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )
        fdc_active_loan_checking.refresh_from_db()
        # number_of_other_platforms already updated
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, 3)
        self.assertEqual(FDCRejectLoanTracking.objects.filter(
            customer_id=self.application.customer_id).exists(), True)

    @patch('juloserver.loan.services.loan_related.timezone.now')
    @patch('juloserver.loan.services.loan_related.get_or_non_fdc_inquiry_not_out_date')
    @patch('juloserver.loan.services.loan_related.get_info_active_loan_from_platforms')
    def test_is_eligible_other_active_platforms_create_tracking_record(
        self, mock_get_info_active_loan_from_platforms, mock_get_or_non_fdc_inquiry_not_out_date, mock_time_zone_now
    ):
        mock_time_zone_now.return_value = datetime(2024, 3, 4)
        fdc_inquiry = FDCInquiry.objects.create()
        fdc_active_loan_checking, _ = FDCActiveLoanChecking.objects.get_or_create(
            customer_id=self.application.customer_id
        )
        mock_get_or_non_fdc_inquiry_not_out_date.return_value = fdc_inquiry
        # 3 other platforms + Julo = 4 platforms > 3 allowed platforms
        mock_get_info_active_loan_from_platforms.return_value = (None, 3, 1)
        is_eligible = is_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible, False)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )
        fdc_active_loan_checking.refresh_from_db()
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, 3)
        self.assertEqual(FDCRejectLoanTracking.objects.filter(
            customer_id=self.application.customer_id).count(), 1)

        # number_of_other_platforms already updated
        number_other_platforms = 5
        mock_time_zone_now.return_value = datetime(2024, 3, 4) + relativedelta(days=1)
        mock_get_info_active_loan_from_platforms.return_value = (None, number_other_platforms, 1)
        is_eligible = is_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        tracking = FDCRejectLoanTracking.objects.filter(
            customer_id=self.application.customer_id).last()

        self.assertEqual(FDCRejectLoanTracking.objects.filter(
            customer_id=self.application.customer_id).count(), 2)
        self.assertEqual(tracking.number_of_other_platforms, number_other_platforms)
        self.assertEqual(fdc_inquiry.pk, tracking.fdc_inquiry_id)

        fdc_inquiry_2 = FDCInquiry.objects.create()
        mock_get_or_non_fdc_inquiry_not_out_date.return_value = fdc_inquiry_2
        is_eligible = is_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        count_tracking = FDCRejectLoanTracking.objects.filter(
            customer_id=self.application.customer_id).count()
        self.assertEqual(count_tracking, 3)


class TestLoanCreationWithFDCChecking(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.nik = '041100'
        self.customer = CustomerFactory(user=self.user_auth, nik=self.nik)
        self.customer_segment = 'activeus_a'
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        WorkflowFactory(name=WorkflowConst.LEGACY)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            workflow=self.workflow,
            product_line=self.product_line,
            ktp=self.nik,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        AccountLimitFactory(account=self.account, available_limit=1000000)
        self.application.save()
        self.inactive_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        self.lender_approve_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LENDER_APPROVAL)
        self.lender_reject_status = StatusLookupFactory(
            status_code=LoanStatusCodes.LENDER_REJECT)
        self.current_status = StatusLookupFactory(
            status_code=LoanStatusCodes.CURRENT)
        self.fund_disbursal_status = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
            loan_status=self.lender_approve_status,
            product=ProductLookupFactory(product_line=self.product_line, cashback_payment_pct=0.05),
            transaction_method=TransactionMethod.objects.get(pk=1)
        )
        # Dana
        partner = PartnerFactory(user=self.user_auth, is_active=True)
        self.dana_product_line = ProductLineFactory(product_line_code=ProductLineCodes.DANA)
        self.dana_user_auth = AuthUserFactory()
        self.dana_customer = CustomerFactory(user=self.dana_user_auth)
        self.dana_application = ApplicationFactory(
            customer=self.dana_customer, product_line=self.dana_product_line, ktp=self.nik
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679776',
            customer=self.dana_customer,
            nik=self.nik,
            application=self.dana_application,
            partner_id=partner.pk,
            full_name='test',
            proposed_credit_limit=1_000_000,
            registration_time=timezone.localtime(timezone.now()),
        )

        self.fdc_inquiry = FDCInquiryFactory(
            application_id=self.application.id, inquiry_status='success'
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_platforms": 3,
                "ineligible_alert_after_fdc_checking": {},
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 30
                },
                "whitelist": {
                    "is_active": True,
                    "list_application_id": [self.application.pk],
                }
            },
            is_active=True,
        )

    @patch('juloserver.loan.tasks.lender_related.loan_lender_approval_process_task')
    def test_fs_turn_off_process_loan_x212_success(self, mock_loan_lender_approval_process_task):
        self.fs.is_active = False
        self.fs.save()
        process_loan_fdc_other_active_loan_from_platforms_task(self.loan.pk)
        mock_loan_lender_approval_process_task.delay.assert_called_once()

    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    @patch(
        'juloserver.loan.services.loan_related.check_eligible_and_out_date_other_platforms')
    def test_fs_turn_on_process_loan_out_date_data_fdc_data_but_eligible(
        self, mock_check_active_platforms_after_x211, mock_fdc_inquiry_task):
        # if FDC data is out date => force call checking FDC api
        mock_check_active_platforms_after_x211.return_value = True, True
        process_loan_fdc_other_active_loan_from_platforms_task(self.loan.pk)
        mock_fdc_inquiry_task.delay.assert_called_once()
        assert FDCInquiry.objects.filter(application_id=self.application.pk).exists() == True

    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    @patch(
        'juloserver.loan.services.loan_related.check_eligible_and_out_date_other_platforms')
    def test_fs_turn_on_process_loan_out_date_data_fdc_data_but_ineligible(
        self, mock_check_active_platforms_after_x211, mock_fdc_inquiry_task):
        # if FDC data is out date => force call checking FDC api
        mock_check_active_platforms_after_x211.return_value = False, True
        process_loan_fdc_other_active_loan_from_platforms_task(self.loan.pk)
        mock_fdc_inquiry_task.delay.assert_called_once()
        assert FDCInquiry.objects.filter(application_id=self.application.pk).exists() == True

    @patch(
        'juloserver.loan.services.loan_related'
        '.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.services.loan_related.check_eligible_and_out_date_other_platforms')
    def test_fs_turn_on_process_loan_data_fdc_data_but_ineligible(
        self, mock_check_active_platforms_after_x211,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule
    ):
        # if FDC data is out date => force call checking FDC api
        mock_check_active_platforms_after_x211.return_value = False, False
        process_loan_fdc_other_active_loan_from_platforms_task(self.loan.pk)
        self.loan.refresh_from_db()
        self.loan.loan_status == self.lender_reject_status
        mock_send_user_attributes_to_moengage_for_active_platforms_rule.assert_called_once_with(
            customer_id=self.customer.id, is_eligible=False
        )


    @patch('juloserver.loan.tasks.lender_related.loan_lender_approval_process_task')
    @patch('juloserver.loan.services.loan_related.check_eligible_and_out_date_other_platforms')
    def test_fs_turn_on_process_loan_data_fdc_data_but_eligible(
        self, mock_check_active_platforms_after_x211, mock_loan_lender_approval_process_task):
        # if FDC data is out date => force call checking FDC api
        mock_check_active_platforms_after_x211.return_value = True, False
        process_loan_fdc_other_active_loan_from_platforms_task(self.loan.pk)
        self.loan.refresh_from_db()
        self.loan.loan_status == self.lender_reject_status
        mock_loan_lender_approval_process_task.delay.assert_called_once()

    @patch('juloserver.loan.services.loan_related.get_info_active_loan_from_platforms')
    @patch('juloserver.loan.services.loan_related.get_or_non_fdc_inquiry_not_out_date')
    def test_check_eligible_and_out_date_fdc_after_x211(self, mock_fdc_inquiry, mock_get_info_fdc):
        # has active loan => True, False
        self.loan.loan_status = self.current_status
        self.loan.save()
        fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days']
        number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms']
        is_eligible, is_out_date = check_eligible_and_out_date_other_platforms(
            self.customer.pk, self.application.pk, fdc_data_outdated_threshold_days,number_of_allowed_platforms
        )
        assert is_eligible == True
        assert is_out_date == False

        # Dana loan
        is_eligible, is_out_date = check_eligible_and_out_date_other_platforms(
            self.dana_customer_data.pk,
            self.dana_application.pk,
            fdc_data_outdated_threshold_days,
            number_of_allowed_platforms,
        )
        assert is_eligible == True
        assert is_out_date == False

        # has  loan => True, False
        self.loan.loan_status = self.fund_disbursal_status
        self.loan.save()
        fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days']
        number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms']
        is_eligible, is_out_date = check_eligible_and_out_date_other_platforms(
            self.customer.pk, self.application.pk, fdc_data_outdated_threshold_days,number_of_allowed_platforms
        )
        assert is_eligible == True
        assert is_out_date == False

        # no active loans, data is not out date and no active loans from platforms => True, False
        self.loan.loan_status = self.lender_approve_status
        self.loan.save()
        fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days']
        number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms']
        mock_get_info_fdc.return_value = None, 2, None
        mock_fdc_inquiry.return_value = self.fdc_inquiry
        is_eligible, is_out_date = check_eligible_and_out_date_other_platforms(
            self.customer.pk, self.application.pk, fdc_data_outdated_threshold_days,number_of_allowed_platforms
        )
        assert is_eligible == True
        assert is_out_date == False

        # no active loans, data is not out date and has active loans from platforms => True, False
        fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days']
        number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms']
        mock_get_info_fdc.return_value = None, 2, None
        is_eligible, is_out_date = check_eligible_and_out_date_other_platforms(
            self.customer.pk, self.application.pk, fdc_data_outdated_threshold_days - 1,number_of_allowed_platforms
        )
        assert is_eligible == True
        assert is_out_date == False

        # no active loans, data is out date => True, True
        fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days']
        number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms']
        mock_fdc_inquiry.return_value = None
        is_eligible, is_out_date = check_eligible_and_out_date_other_platforms(
            self.customer.pk, self.application.pk, fdc_data_outdated_threshold_days,number_of_allowed_platforms
        )
        assert is_eligible == True
        assert is_out_date == True

        self.loan.loan_status = self.lender_approve_status
        self.loan.save()
        fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days']
        number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms']
        mock_get_info_fdc.return_value = None, 5, None
        mock_fdc_inquiry.return_value = self.fdc_inquiry
        is_eligible, is_out_date = check_eligible_and_out_date_other_platforms(
            self.customer.pk, self.application.pk, fdc_data_outdated_threshold_days,number_of_allowed_platforms
        )
        assert is_eligible == False
        assert is_out_date == False
        assert FDCRejectLoanTracking.objects.filter(
            customer_id=self.loan.customer_id).exists() == True


    @patch('juloserver.loan.services.loan_related.get_info_active_loan_from_platforms')
    @patch('juloserver.loan.tasks.lender_related.get_and_save_fdc_data')
    @patch('juloserver.loan.tasks.lender_related.loan_lender_approval_process_task')
    def test_fdc_inquiry_other_active_loans_from_platforms_task_success_and_eligible(
        self, mock_loan_lender_approval_process_task, mock_get_and_save_fdc_data, mock_get_info_fdc_data):
        number_active_platforms = 2
        fdc_active_loan = FDCActiveLoanChecking.objects.create(customer=self.customer)
        fdc_inquiry = FDCInquiryFactory(customer_id=self.customer.id, nik=self.customer.pk)
        fdc_data = {"id": fdc_inquiry.pk, "nik": self.customer.nik}

        mock_get_info_fdc_data.return_value = None, number_active_platforms, None
        params = dict(
            loan_id=self.loan.pk,
            fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days'],
            number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms'],
            application_id=self.application.pk,
            fdc_inquiry_id=fdc_inquiry.pk,
        )
        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_data, self.customer.pk, FDCUpdateTypes.AFTER_LOAN_STATUS_x211, params
        )
        fdc_active_loan.refresh_from_db()
        fdc_active_loan.number_of_other_platforms = number_active_platforms
        mock_loan_lender_approval_process_task.delay.assert_called_once()

    @patch(
        'juloserver.loan.services.loan_related'
        '.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.services.loan_related.get_info_active_loan_from_platforms')
    @patch('juloserver.loan.tasks.lender_related.get_and_save_fdc_data')
    def test_fdc_inquiry_other_active_loans_from_platforms_task_success_and_ineligible(
        self, mock_get_and_save_fdc_data, mock_get_info_fdc_data,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule
    ):
        number_active_platforms = 4
        fdc_active_loan = FDCActiveLoanChecking.objects.create(customer=self.customer)
        fdc_inquiry = FDCInquiryFactory(
            customer_id=self.customer.id, nik=self.customer.pk, application_id=self.application.pk
        )
        fdc_data = {"id": fdc_inquiry.pk, "nik": self.customer.nik}

        mock_get_info_fdc_data.return_value = None, number_active_platforms, None
        params = dict(
            loan_id=self.loan.pk,
            fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days'],
            number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms'],
            application_id=self.application.pk,
            fdc_inquiry_id=fdc_inquiry.pk,
        )
        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_data, self.customer.pk, FDCUpdateTypes.AFTER_LOAN_STATUS_x211, params
        )
        fdc_active_loan.refresh_from_db()
        fdc_active_loan.number_of_other_platforms = number_active_platforms
        self.loan.refresh_from_db()
        self.loan.loan_status == self.lender_reject_status
        mock_send_user_attributes_to_moengage_for_active_platforms_rule.assert_called_once_with(
            customer_id=self.customer.id, is_eligible=False
        )

    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    @patch('juloserver.fdc.clients.requests.get')
    def test_fdc_inquiry_other_active_loans_from_platforms_task_failed_and_retry(
        self, mock_get_info_fdc_data_request, mock_fdc_inquiry_task):
        FDCActiveLoanChecking.objects.create(customer=self.customer)
        fdc_inquiry = FDCInquiryFactory(
            customer_id=self.customer.id, nik=self.customer.pk, application_id=self.application.pk
        )
        fdc_data = {"id": fdc_inquiry.pk, "nik": self.customer.nik}

        mock_get_info_fdc_data_request.return_value.status_code = 503
        params = dict(
            loan_id=self.loan.pk,
            fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days'],
            number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms'],
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config']
        )
        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_data, self.customer.pk, FDCUpdateTypes.AFTER_LOAN_STATUS_x211, params
        )
        mock_fdc_inquiry_task.apply_async.assert_called_once()

    @patch('juloserver.loan.services.loan_related.get_info_active_loan_from_platforms')
    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    @patch('juloserver.fdc.clients.requests.get')
    def test_fdc_inquiry_other_from_platforms_task_failed_and_retry_max_times_and_ineligible(
        self, mock_get_info_fdc_data_request, mock_fdc_inquiry_task, mock_get_info_fdc):
        # will reject when the cusomter is still ineligible
        number_active_platforms = 4
        FDCActiveLoanChecking.objects.create(customer=self.customer)
        fdc_inquiry = FDCInquiryFactory(
            customer_id=self.customer.id, nik=self.customer.pk, application_id=self.application.pk
        )
        fdc_data = {"id": fdc_inquiry.pk, "nik": self.customer.nik}

        mock_get_info_fdc_data_request.return_value.status_code = 503
        mock_get_info_fdc.return_value = None, number_active_platforms, None
        params = dict(
            loan_id=self.loan.pk,
            fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days'],
            number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms'],
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config']
        )
        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_data, self.customer.pk, FDCUpdateTypes.AFTER_LOAN_STATUS_x211, params, self.fs.parameters['fdc_inquiry_api_config']['max_retries']
        )

        mock_fdc_inquiry_task.apply_async.assert_not_called()
        self.loan.refresh_from_db()
        self.loan.loan_status == self.lender_reject_status

    @patch('juloserver.loan.tasks.lender_related.loan_lender_approval_process_task')
    @patch('juloserver.loan.services.loan_related.get_info_active_loan_from_platforms')
    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    @patch('juloserver.fdc.clients.requests.get')
    def test_fdc_inquiry_other_from_platforms_task_failed_and_retry_max_times_and_eligible(
        self, mock_get_info_fdc_data_request, mock_fdc_inquiry_task, mock_get_info_fdc, mock_lender_approval_task):
        # will reject when the cusomter is still ineligible
        number_active_platforms = 2
        FDCActiveLoanChecking.objects.create(customer=self.customer)
        fdc_inquiry = FDCInquiryFactory(
            customer_id=self.customer.id, nik=self.customer.pk, application_id=self.application.pk
        )
        fdc_data = {"id": fdc_inquiry.pk, "nik": self.customer.nik}

        mock_get_info_fdc_data_request.return_value.status_code = 503
        mock_get_info_fdc.return_value = None, number_active_platforms, None
        params = dict(
            loan_id=self.loan.pk,
            fdc_data_outdated_threshold_days = self.fs.parameters['fdc_data_outdated_threshold_days'],
            number_of_allowed_platforms = self.fs.parameters['number_of_allowed_platforms'],
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config']
        )
        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_data, self.customer.pk, FDCUpdateTypes.AFTER_LOAN_STATUS_x211, params, self.fs.parameters['fdc_inquiry_api_config']['max_retries']
        )
        mock_fdc_inquiry_task.apply_async.assert_not_called()
        mock_lender_approval_task.delay.assert_called_once()

    @patch('juloserver.loan.services.sphp.process_loan_fdc_other_active_loan_from_platforms_task')
    def test_accept_julo_sphp(self, mock_process_loan_fdc_task, *args):
        self.loan.loan_status = self.inactive_status
        self.loan.save()
        accept_julo_sphp(self.loan, "JULO")
        mock_process_loan_fdc_task.delay.assert_called_once()


class TestFDCActiveLoanDailyChecker(TestCase):
    def setUp(self):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_platforms": 3,
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 30
                },
                "whitelist": {
                    "is_active": True,
                    "list_application_id": [],
                },
                "daily_checker_config": {
                    "rps_throttling": 3,
                    "nearest_due_date_from_days": 5,
                    "batch_size": 1000,
                    "last_access_days": 7,
                    "retry_per_days": 1
                },
                "c_score_bypass": {
                    "is_active": False,
                }
            },
            is_active=True,
        )

        self.grab_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_platforms": 3,
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 30
                },
                "whitelist": {
                    "is_active": True,
                    "list_application_id": [],
                },
                "daily_checker_config": {
                    "rps_throttling": 3,
                    "nearest_due_date_from_days": 5,
                    "batch_size": 1000,
                    "last_access_days": 7,
                    "retry_per_days": 1
                }
            },
            is_active=True,
        )

        FDCActiveLoanCheckingFactory.create_batch(
            5, number_of_other_platforms=4
        )
        self.customer = CustomerFactory(nik='123321123321')
        self.customer_segment = 'activeus_a'
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.account_property = AccountPropertyFactory(account=self.account, pgood=0.75)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        AccountLimitFactory(account=self.account, available_limit=1000000)
        self.application.save()
        self.fdc_inquiry = FDCInquiryFactory(
            application_id=self.application.id, inquiry_status='success'
        )
        self.nearest_due_date = datetime(2024, 1, 15).date()
        self.fdc_inquiry = FDCInquiry.objects.create(
            nik=self.customer.nik, customer_id=self.customer.pk, application_id=self.application.pk
        )
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=2,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.nearest_due_date,
        )
        self.list_fdc_3 = FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=3,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=datetime(2024, 2, 1),
        )

    def test_get_fdc_loan_active_checking_for_daily_checker(self):
        current_time = datetime(2024, 1, 10, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_customer_ids = FDCActiveLoanChecking.objects.all().values_list('customer_id', flat=True)

        # 1 last_access_days
        # 1.1 Get all match condition from config
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) == len(customer_ids)

        # 1.2 Two records > the config
        time_last_access_days = current_time - relativedelta(days=self.fs.parameters['daily_checker_config']['last_access_days'] + 1)
        total_exclude = 2

        # 2. last_updated_time
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(
                days=self.fs.parameters['daily_checker_config']['retry_per_days']),
            nearest_due_date=current_time
        )
        # 2.1 Get all match condition from config
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) == len(customer_ids)

        # 2.2 exclude last_updated_time of Two records < the config (1) or null
        total_exclude = 2
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(last_updated_time=current_time)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        # 2.2.2 None case
        assert len(total_customer_ids) - total_exclude == len(customer_ids)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_exclude = 2
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(last_updated_time=None)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) - total_exclude == len(customer_ids)

        # 3. number_of_other_platforms
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_exclude = 2
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(number_of_other_platforms=2)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) - total_exclude == len(customer_ids)

        # 4. Nearest due date, nearest_due_date is far from config
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time,
            number_of_other_platforms=4
        )
        nearest_due_date = current_time.date() + relativedelta(
            days=self.fs.parameters['daily_checker_config']['nearest_due_date_from_days'] + 1
        )
        total_exclude = 2
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(nearest_due_date=nearest_due_date)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) - total_exclude == len(customer_ids)

        # 4.1 nearest_due_date is null
        FDCActiveLoanChecking.objects.all().update(
            number_of_other_platforms=4,
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time,
        )
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(nearest_due_date=None)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) - total_exclude == len(customer_ids)

        # 5 FDCActiveLoanChecking don't have data.
        FDCActiveLoanChecking.objects.all().update(
            number_of_other_platforms=None,
            last_access_date=current_time.date(),
            last_updated_time=None,
            nearest_due_date=None,
        )
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) == len(customer_ids)

    @freeze_time("2024-01-01 15:00:00")
    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask')
    def test_fdc_inquiry_for_active_loan_from_platform_daily_checker_task(self, _mock_sub_task):
        current_time = datetime(2024, 1, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_customer_ids = FDCActiveLoanChecking.objects.all().values_list('customer_id', flat=True)

        fdc_inquiry_for_active_loan_from_platform_daily_checker_task()
        call_count = _mock_sub_task.apply_async.call_count
        self.assertEqual(call_count, len(total_customer_ids))
        self.assertNotEqual(call_count, 0)

    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask')
    def test_fdc_inquiry_for_active_loan_from_platform_daily_checker_with_j1(self, _mock_sub_task):
        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time,
            product_line_id=ProductLineCodes.J1
        )
        total_customer_ids = FDCActiveLoanChecking.objects.all().values_list('customer_id', flat=True)
        self.fs.parameters['daily_checker_config'].update(
            applied_product_lines=[ProductLineCodes.J1, ProductLineCodes.JTURBO]
        )
        self.fs.save()

        fdc_inquiry_for_active_loan_from_platform_daily_checker_task()
        _mock_sub_task.call_count == len(total_customer_ids)

    @patch('juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    def test_fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask(
        self, _mock_fdc_inquiry_active_loans_task):
        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()

        fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask(
            fdc_checking.customer_id, self.fs.parameters)
        _mock_fdc_inquiry_active_loans_task.assert_called()

    @patch('juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    def test_fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask_bypass_c_score(
        self, _mock_fdc_inquiry_active_loans_task):
        self.fs.parameters['c_score_bypass']['is_active'] = True
        self.fs.parameters['c_score_bypass']['pgood_gte'] = 0.75
        self.fs.save()
        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()

        fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask(
            fdc_checking.customer_id, self.fs.parameters)
        _mock_fdc_inquiry_active_loans_task.assert_not_called()

        self.account_property.pgood = 0.6
        self.account_property.save()
        fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask(
            fdc_checking.customer_id, self.fs.parameters)
        _mock_fdc_inquiry_active_loans_task.assert_called()

    @patch('juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    def test_fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask_deleted_application(
        self, _mock_fdc_inquiry_active_loans_task):
        self.fs.parameters['c_score_bypass']['is_active'] = False
        self.fs.save()
        self.application.is_deleted = True
        self.application.save()
        CreditScoreFactory(
            application_id=self.application.pk,
            score="A-"
        )
        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()

        fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask(
            fdc_checking.customer_id, self.fs.parameters)
        _mock_fdc_inquiry_active_loans_task.assert_not_called()

    @patch(
        'juloserver.loan.services.loan_related'
        '.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.tasks.lender_related.get_and_save_fdc_data')
    def test_fdc_inquiry_other_active_loans_from_platforms_task_success(
        self, _mock_get_and_save_fdc_data,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule
    ):
        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()
        params = dict(
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config'],
            number_of_allowed_platforms=self.fs.parameters['number_of_allowed_platforms'],
            fdc_inquiry_id=self.fdc_inquiry.pk
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.pk, 'nik': self.fdc_inquiry.nik}

        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_inquiry_data, self.customer.pk, FDCUpdateTypes.DAILY_CHECKER, params
        )
        fdc_checking.refresh_from_db()
        fdc_checking.nearest_due_date == self.nearest_due_date
        fdc_checking.number_of_other_platforms == 2
        mock_send_user_attributes_to_moengage_for_active_platforms_rule.assert_called_once_with(
            customer_id=self.customer.id, is_eligible=True
        )

    @patch("juloserver.loan.services.loan_related.move_grab_app_to_190")
    @patch(
        'juloserver.loan.services.loan_related'
        '.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.tasks.lender_related.get_and_save_fdc_data')
    def test_grab_fdc_inquiry_other_active_loans_from_platforms_task_success(
        self, _mock_get_and_save_fdc_data,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule,
        mock_move_grab_app_to_190
    ):
        self.application.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )
        self.application.save()

        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()
        params = dict(
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config'],
            number_of_allowed_platforms=self.fs.parameters['number_of_allowed_platforms'],
            fdc_inquiry_id=self.fdc_inquiry.pk
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.pk, 'nik': self.fdc_inquiry.nik}

        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_inquiry_data, self.customer.pk, FDCUpdateTypes.GRAB_DAILY_CHECKER, params
        )
        fdc_checking.refresh_from_db()
        fdc_checking.nearest_due_date == self.nearest_due_date
        fdc_checking.number_of_other_platforms == 2

        mock_move_grab_app_to_190.assert_called()

    @patch("juloserver.loan.services.loan_related.move_grab_app_to_190")
    @patch(
        'juloserver.loan.services.loan_related'
        '.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.tasks.lender_related.get_and_save_fdc_data')
    def test_grab_fdc_inquiry_other_active_loans_from_platforms_task_success_above_limit(
        self, _mock_get_and_save_fdc_data,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule,
        mock_move_grab_app_to_190
    ):
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=4,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=datetime(2024, 2, 1),
        )

        self.application.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )
        self.application.save()

        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()
        params = dict(
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config'],
            number_of_allowed_platforms=self.fs.parameters['number_of_allowed_platforms'],
            fdc_inquiry_id=self.fdc_inquiry.pk
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.pk, 'nik': self.fdc_inquiry.nik}

        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_inquiry_data, self.customer.pk, FDCUpdateTypes.GRAB_DAILY_CHECKER, params
        )
        fdc_checking.refresh_from_db()
        fdc_checking.nearest_due_date == self.nearest_due_date
        fdc_checking.number_of_other_platforms == 2

        mock_move_grab_app_to_190.assert_not_called()


class TestCheckGTL(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account, used_limit=0)
        self.application = ApplicationFactory(customer=self.customer)
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.CHECK_GTL,
            parameters={
                "threshold_set_limit_percent": 90,
                "threshold_loan_within_hours": 12,
                "list_transaction_method_code": [1],
                "whitelist": {
                    "is_active": False,
                    "list_application_id": [],
                },
                "ineligible_message_for_old_application": "ineligible_message_for_old_application",
                "ineligible_popup": {
                    "is_active": True,
                    "title": "ineligible_popup title",
                    "banner": {
                        "is_active": True,
                        "url": "banner url",
                    },
                    "content": "ineligible_popup content",
                },
            },
            is_active=False,
        )

    def test_get_parameters_fs_check_gtl(self):
        # INACTIVE FS
        # => False
        self.fs.is_active = False
        self.fs.save()
        result = get_parameters_fs_check_gtl()
        self.assertEqual(result, None)

        # ACTIVE FS
        self.fs.is_active = True
        self.fs.save()
        result = get_parameters_fs_check_gtl()
        self.assertIsNotNone(result)

    def test_is_apply_check_gtl(self):
        # application is not J1 or Jturbo
        result = is_apply_gtl_inside(TransactionMethodCode.SELF.code, self.application)
        self.assertEqual(result, False)

        # application is J1
        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )

        # INACTIVE FS
        # => False
        self.fs.is_active = False
        self.fs.save()
        result = is_apply_gtl_inside(TransactionMethodCode.SELF.code, self.application)
        self.assertEqual(result, False)

        # ACTIVE FS
        self.fs.is_active = True

        # transaction method is in the list_transaction_method_code, disable whitelist
        # => True
        self.fs.parameters['whitelist']['is_active'] = False
        self.fs.parameters['list_transaction_method_code'] = [TransactionMethodCode.SELF.code]
        self.fs.save()
        result = is_apply_gtl_inside(TransactionMethodCode.SELF.code, self.application)
        self.assertEqual(result, True)

        # transaction method is in the list_transaction_method_code,
        # enable whitelist, but the application is not in the whitelist
        # => False
        self.fs.parameters['whitelist']['is_active'] = True
        self.fs.parameters['whitelist']['list_application_id'] = []
        self.fs.save()
        result = is_apply_gtl_inside(TransactionMethodCode.SELF.code, self.application)
        self.assertEqual(result, False)

        # transaction method is in the list_transaction_method_code,
        # enable whitelist, and the application is in the whitelist
        # => True
        self.fs.parameters['whitelist']['list_application_id'] = [self.application.id]
        self.fs.save()
        result = is_apply_gtl_inside(TransactionMethodCode.SELF.code, self.application)
        self.assertEqual(result, True)

        # transaction method is in the list_transaction_method_code,
        # disable whitelist
        # => True
        self.fs.parameters['whitelist']['is_active'] = False
        self.fs.save()
        result = is_apply_gtl_inside(TransactionMethodCode.SELF.code, self.application)
        self.assertEqual(result, True)

        # transaction method is in not the list_transaction_method_code
        # => False
        self.fs.parameters['list_transaction_method_code'] = []
        self.fs.save()
        result = is_apply_gtl_inside(TransactionMethodCode.SELF.code, self.application)
        self.assertEqual(result, False)

    def test_process_block_by_gtl_inside(self):
        account_gtl = AccountGTLFactory(account=self.account)
        process_block_by_gtl_inside(account_id=self.account.id)
        account_gtl.refresh_from_db()
        self.assertEqual(account_gtl.is_gtl_inside, True)
        account_gtl_histories = AccountGTLHistory.objects.filter(account_gtl=account_gtl).all()
        self.assertEqual(account_gtl_histories.count(), 1)
        self.assertEqual(account_gtl_histories[0].field_name, 'is_gtl_inside')
        self.assertEqual(account_gtl_histories[0].value_old, 'False')
        self.assertEqual(account_gtl_histories[0].value_new, 'True')

        account_gtl.delete()
        process_block_by_gtl_inside(account_id=self.account.id)
        new_account_gtl = AccountGTL.objects.get_or_none(account=self.account)
        self.assertEqual(new_account_gtl.is_gtl_inside, True)
        # no new AccountGTL and history created
        self.assertEqual(AccountGTLHistory.objects.all().count(), 1)

    def test_is_eligible_gtl_inside(self):
        # already blocked before => False
        account_gtl = AccountGTLFactory(account=self.account, is_gtl_inside=True)
        self.assertFalse(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 90 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        account_gtl.is_gtl_inside = False
        account_gtl.save()

        loan = LoanFactory(account=self.account, customer=self.account.customer)
        Payment.objects.filter(loan=loan).update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)
        last_payment = Payment.objects.filter(loan=loan).last()
        last_payment.payment_status_id = PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
        last_payment.save()
        loan_history = LoanHistoryFactory(
            loan=loan,
            status_old=220,
            status_new=250,
            cdate=timezone.localtime(timezone.now()) - timedelta(hours=3)
        )
        # unblock & create loan with 90% of user's set limit and within 12 hours after paid off
        # and last payment is paid DPD+1
        # => False
        self.assertFalse(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 90 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        # didn't check gtl before
        # create loan with 90% of user's set limit and within 12 hours after paid off
        # and last payment is paid DPD+1
        # => False
        account_gtl.delete()
        self.assertFalse(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 90 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        # didn't check gtl before
        # create loan with 90% of user's set limit (used limit <> 0) within 12 hours after paid off
        # and last payment is paid DPD+1
        # => False
        self.account_limit.set_limit = 1_000_000
        self.account_limit.used_limit = 500_000
        self.account_limit.save()
        self.assertFalse(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=400_000,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        self.account_limit.used_limit = 0
        self.account_limit.save()

        # create loan with 90% of user's set limit and within 12 hours after paid off
        # and last payment is paid on time
        # => True
        last_payment.payment_status_id = PaymentStatusCodes.PAID_ON_TIME
        last_payment.save()
        self.assertTrue(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 90 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        # create loan with 90% of user's set limit and within 12 hours after paid off
        # last payment is paid on time and other payment is paid DPD+1
        # => True
        first_payment = Payment.objects.filter(loan=loan).first()
        first_payment.payment_status_id = PaymentStatusCodes.PAID_LATE
        first_payment.save()
        self.assertTrue(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 90 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        loan2 = LoanFactory(account=self.account, customer=self.account.customer)
        Payment.objects.filter(loan=loan2).update(payment_status_id=PaymentStatusCodes.PAID_ON_TIME)
        last_payment2 = Payment.objects.filter(loan=loan2).last()
        last_payment2.payment_status_id = PaymentStatusCodes.PAID_LATE
        last_payment2.save()
        loan_history2 = LoanHistoryFactory(
            loan=loan2,
            status_old=220,
            status_new=250,
            cdate=timezone.localtime(timezone.now()) - timedelta(hours=3)
        )
        # create loan with 90% of user's set limit and within 12 hours after paid off
        # and last payment of second loan is paid DPD+1
        # => False
        self.assertFalse(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 90 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        loan_history2.delete()
        AccountGTL.objects.filter(account=self.account).delete()

        # create loan with 80% of user's set limit and within 12 hours after paid off
        # => True
        self.assertTrue(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 80 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        # create loan with 90% of user's set limit and no paid off loan within 12 hours
        # => True
        loan_history.delete()
        self.assertTrue(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 90 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

        # create loan with 89% of user's set limit and no paid off loan within 12 hours
        # => True
        self.assertTrue(
            is_eligible_gtl_inside(
                account_limit=self.account_limit,
                loan_amount_request=self.account_limit.set_limit * 89 / 100,
                threshold_set_limit_percent=90,
                threshold_loan_within_hours=12,
            )
        )

    @patch('juloserver.loan.services.loan_related.get_parameters_fs_check_gtl')
    def test_check_lock_by_gtl_inside(self, mock_get_parameters_fs_check_gtl):
        # fs disable => False
        mock_get_parameters_fs_check_gtl.return_value = None
        self.assertFalse(check_lock_by_gtl_inside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, but transaction method is not in the list_transaction_method_code => False
        mock_get_parameters_fs_check_gtl.return_value = {'list_transaction_method_code': []}
        self.assertFalse(check_lock_by_gtl_inside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, transaction method is in the list_transaction_method_code,
        # but user doesn't have any AccountGTL => False
        mock_get_parameters_fs_check_gtl.return_value = {
            'list_transaction_method_code': [TransactionMethodCode.SELF.code],
        }
        self.assertFalse(check_lock_by_gtl_inside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, transaction method is in the list_transaction_method_code,
        # user has AccountGTL, but is_gtl_inside=False => False
        account_gtl = AccountGTLFactory(account=self.account, is_gtl_inside=False)
        self.assertFalse(check_lock_by_gtl_inside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, transaction method is in the list_transaction_method_code,
        # user has AccountGTL, but is_gtl_inside=True => True
        account_gtl.is_gtl_inside = True
        account_gtl.save()
        self.assertTrue(check_lock_by_gtl_inside(self.account, TransactionMethodCode.SELF.code))

    def test_create_or_update_is_maybe_gtl_inside(self):
        # test update
        account_gtl = AccountGTLFactory(account=self.account, is_maybe_gtl_inside=False)
        create_or_update_is_maybe_gtl_inside(account_id=self.account.id, new_value=True)
        account_gtl.refresh_from_db()
        self.assertEqual(account_gtl.is_maybe_gtl_inside, True)
        self.assertEqual(AccountGTLHistory.objects.filter(account_gtl=account_gtl).count(), 1)
        account_gtl_history = AccountGTLHistory.objects.filter(account_gtl=account_gtl).last()
        self.assertEqual(account_gtl_history.field_name, 'is_maybe_gtl_inside')
        self.assertEqual(account_gtl_history.value_old, 'False')
        self.assertEqual(account_gtl_history.value_new, 'True')

        # test update: no update because new_value is the same as the old value
        create_or_update_is_maybe_gtl_inside(account_id=self.account.id, new_value=True)
        self.assertEqual(AccountGTLHistory.objects.filter(account_gtl=account_gtl).count(), 1)

        account_gtl.delete()
        # test create
        create_or_update_is_maybe_gtl_inside(account_id=self.account.id, new_value=True)
        new_account_gtl = AccountGTL.objects.get(account=self.account)
        self.assertEqual(new_account_gtl.is_maybe_gtl_inside, True)
        self.assertEqual(AccountGTLHistory.objects.filter(account_gtl=new_account_gtl).count(), 0)

    @patch('juloserver.loan.services.loan_related.get_parameters_fs_check_gtl')
    @patch('juloserver.loan.services.loan_related.is_apply_gtl_inside')
    @patch('juloserver.loan.services.loan_related.is_eligible_gtl_inside')
    @patch('juloserver.loan.services.loan_related.'
           'create_or_update_is_maybe_gtl_inside_and_send_to_moengage')
    @patch('juloserver.loan.services.loan_related.create_loan_rejected_by_gtl')
    @patch('juloserver.loan.services.loan_related.process_block_by_gtl_inside')
    def test_process_check_gtl_inside(
        self,
        mock_process_block_by_gtl_inside,
        mock_create_loan_rejected_by_gtl,
        mock_create_or_update_is_maybe_gtl_inside_and_send_to_moengage,
        mock_is_eligible_gtl_inside,
        mock_is_apply_check_gtl,
        mock_get_parameters_fs_check_gtl,
    ):
        transaction_method_id = 1
        loan_amount = 123
        error_message = 'error message'

        def call_process_check_gtl_inside():
            return process_check_gtl_inside(
                transaction_method_id=transaction_method_id,
                loan_amount=loan_amount,
                application=self.application,
                customer_id=self.customer.id,
                account_limit=self.account_limit,
            )

        fs_parameters = {
            "threshold_set_limit_percent": 90,
            "threshold_loan_within_hours": 12,
            "list_transaction_method_code": [1],
            "whitelist": {
                "is_active": False,
                "list_application_id": [],
            },
            "ineligible_message_for_old_application": error_message,
            "ineligible_popup": {
                "is_active": True,
                "title": "Kamu Belum Bisa Transaksi",
                "banner": {
                    "is_active": True,
                    "url": "123",
                },
                "content": error_message,
            },
        }

        mock_get_parameters_fs_check_gtl.return_value = fs_parameters

        # Case 1: is_apply_gtl_inside=True, but ineligible
        mock_is_apply_check_gtl.return_value = True
        mock_is_eligible_gtl_inside.return_value = False
        result = call_process_check_gtl_inside()
        self.assertEqual(result.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(error_message, result.data['errors'][0])
        self.assertEqual(
            result.data['data']['error_popup']['error_code'], ErrorCode.INELIGIBLE_GTL_INSIDE
        )
        self.assertEqual(result.data['data']['error_popup'], fs_parameters['ineligible_popup'])
        mock_create_loan_rejected_by_gtl.assert_called()
        mock_process_block_by_gtl_inside.assert_called()
        mock_create_or_update_is_maybe_gtl_inside_and_send_to_moengage.assert_called_with(
            customer_id=self.customer.id,
            account_id=self.account.id,
            new_value_is_maybe_gtl_inside=False,
        )

        mock_create_or_update_is_maybe_gtl_inside_and_send_to_moengage.reset_mock()

        # Case 2: is_apply_gtl_inside=True, but eligible
        mock_is_apply_check_gtl.return_value = True
        mock_is_eligible_gtl_inside.return_value = True
        # didn't mark is_maybe_gtl_inside=True before
        self.assertIsNone(call_process_check_gtl_inside())
        mock_create_or_update_is_maybe_gtl_inside_and_send_to_moengage.assert_not_called()

        # mark is_maybe_gtl_inside=True before
        AccountGTLFactory(account=self.account, is_maybe_gtl_inside=True)
        self.assertIsNone(call_process_check_gtl_inside())
        mock_create_or_update_is_maybe_gtl_inside_and_send_to_moengage.assert_called_with(
            customer_id=self.customer.id,
            account_id=self.account.id,
            new_value_is_maybe_gtl_inside=False,
        )

        # Case 3: is_apply_gtl_inside=False
        mock_is_apply_check_gtl.return_value = False
        self.assertIsNone(call_process_check_gtl_inside())



class TestGTLOutside(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account, used_limit=0)
        self.application = ApplicationFactory(customer=self.customer)
        self.today = timezone.localtime(timezone.now()).date()

    def test_is_b_score_satisfy_gtl_outside(self):
        # no bscore -> False: bypass GTL outside
        self.assertFalse(
            is_b_score_satisfy_gtl_outside(customer_id=self.customer.id, threshold_lte_b_score=0.75)
        )

        pd_clcs_prime_result = PdClcsPrimeResultFactory(
            customer_id=self.customer.id,
            partition_date=self.today,
            b_score=0.76,
            clcs_prime_score=1,
        )
        self.assertFalse(
            is_b_score_satisfy_gtl_outside(customer_id=self.customer.id, threshold_lte_b_score=0.75)
        )

        # bscore is null -> False: bypass GTL outside
        pd_clcs_prime_result.b_score = None
        pd_clcs_prime_result.save()
        self.assertFalse(
            is_b_score_satisfy_gtl_outside(customer_id=self.customer.id, threshold_lte_b_score=0.75)
        )

        # bscore = 0.75 -> True: check GTL outside
        pd_clcs_prime_result.b_score = 0.75
        pd_clcs_prime_result.save()
        self.assertTrue(
            is_b_score_satisfy_gtl_outside(customer_id=self.customer.id, threshold_lte_b_score=0.75)
        )

        # bscore < 0.75 -> True: check GTL outside
        pd_clcs_prime_result.b_score = 0.70
        pd_clcs_prime_result.save()
        self.assertTrue(
            is_b_score_satisfy_gtl_outside(customer_id=self.customer.id, threshold_lte_b_score=0.75)
        )

        # bscore > 0.75 -> False: bypass GTL outside
        pd_clcs_prime_result.b_score = 0.81
        pd_clcs_prime_result.save()
        self.assertFalse(
            is_b_score_satisfy_gtl_outside(customer_id=self.customer.id, threshold_lte_b_score=0.75)
        )

    def test_is_repeat_user_gtl_outside(self):
        # do not have any loan -> FTC => True
        self.assertFalse(is_repeat_user_gtl_outside(customer_id=self.customer.id))

        # have loan, but min paid date > current date
        loan = LoanFactory(account=self.account, customer=self.account.customer)
        last_payment = Payment.objects.filter(loan=loan).last()
        last_payment.paid_date = self.today + timedelta(days=1)
        last_payment.save()
        self.assertFalse(is_repeat_user_gtl_outside(customer_id=self.customer.id))

        last_payment.paid_date = self.today
        last_payment.save()
        self.assertTrue(is_repeat_user_gtl_outside(customer_id=self.customer.id))

    @patch('juloserver.loan.services.loan_related.timezone.now')
    @patch('juloserver.loan.services.loan_related.replace_day')
    def test_calculate_date_diff_m_and_m_minus_1_gtl_outside(self, mock_replace_day, mock_now):
        last_due_date = date(year=2024, month=3, day=26)
        mock_now.return_value = datetime(year=2024, month=3, day=26)

        date_diff_m, date_diff_m_minus_1 = calculate_date_diff_m_and_m_minus_1_gtl_outside(
            last_due_date=last_due_date,
        )
        mock_replace_day.assert_not_called()
        self.assertEqual(date_diff_m, 0)
        self.assertIsNotNone(date_diff_m_minus_1)

        date_diff_m, date_diff_m_minus_1 = calculate_date_diff_m_and_m_minus_1_gtl_outside(
            last_due_date=last_due_date - timedelta(days=1),
        )
        mock_replace_day.assert_not_called()
        self.assertEqual(date_diff_m, 1)
        self.assertIsNotNone(date_diff_m_minus_1)

        tomorrow_of_last_due_date = last_due_date + timedelta(days=1)
        mock_replace_day.return_value = tomorrow_of_last_due_date
        date_diff_m, date_diff_m_minus_1 = calculate_date_diff_m_and_m_minus_1_gtl_outside(
            last_due_date=tomorrow_of_last_due_date,
        )
        self.assertEqual(date_diff_m, -1)
        self.assertIsNotNone(date_diff_m_minus_1)

    def test_is_fdc_loan_satisfy_gtl_outside(self):
        # do not have any FDCInquiry
        self.assertFalse(
            is_fdc_loan_satisfy_gtl_outside(
                application_id=self.application.id, threshold_gt_last_dpd_fdc=0
            )
        )

        # have FDCInquiry, but do not have any FDCInquiryLoan
        fdc_inquiry = FDCInquiryFactory(
            application_id=self.application.id, inquiry_status='success'
        )
        self.assertFalse(
            is_fdc_loan_satisfy_gtl_outside(
                application_id=self.application.id, threshold_gt_last_dpd_fdc=0
            )
        )

        fdc_inquiry_loan1 = FDCInquiryLoanFactory(
            fdc_inquiry_id=fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.today - timedelta(days=10),
            dpd_terakhir=0,
            fdc_id='1',
        )
        fdc_inquiry_loan2 = FDCInquiryLoanFactory(
            fdc_inquiry_id=fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.today - timedelta(days=10),
            dpd_terakhir=0,
            fdc_id='2',
        )
        fdc_inquiry_loan3 = FDCInquiryLoanFactory(
            fdc_inquiry_id=fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.today - timedelta(days=10),
            dpd_terakhir=0,
            fdc_id='1',
        )
        self.assertFalse(
            is_fdc_loan_satisfy_gtl_outside(
                application_id=self.application.id, threshold_gt_last_dpd_fdc=0
            )
        )

        fdc_inquiry_loan1.tgl_jatuh_tempo_pinjaman = self.today - timedelta(days=5)
        fdc_inquiry_loan1.save()
        self.assertFalse(
            is_fdc_loan_satisfy_gtl_outside(
                application_id=self.application.id, threshold_gt_last_dpd_fdc=0
            )
        )

        fdc_inquiry_loan2.tgl_jatuh_tempo_pinjaman = self.today - timedelta(days=4)
        fdc_inquiry_loan2.save()
        self.assertFalse(
            is_fdc_loan_satisfy_gtl_outside(
                application_id=self.application.id, threshold_gt_last_dpd_fdc=0
            )
        )

        # fdc_id='1' has dpd_terakhir > 0
        fdc_inquiry_loan3.dpd_terakhir = 10
        fdc_inquiry_loan3.save()
        self.assertTrue(
            is_fdc_loan_satisfy_gtl_outside(
                application_id=self.application.id, threshold_gt_last_dpd_fdc=0
            )
        )

        fdc_inquiry_loan3.is_julo_loan = True
        fdc_inquiry_loan3.save()
        self.assertFalse(
            is_fdc_loan_satisfy_gtl_outside(
                application_id=self.application.id, threshold_gt_last_dpd_fdc=0
            )
        )

    def test_process_block_by_gtl_outside(self):
        account_gtl = AccountGTLFactory(account=self.account)

        process_block_by_gtl_outside(
            account_id=self.account.id,
            is_experiment=False,
            block_time_in_hours=1,
        )
        account_gtl.refresh_from_db()
        self.assertEqual(account_gtl.is_gtl_outside, True)
        account_gtl_histories = AccountGTLHistory.objects.filter(account_gtl=account_gtl).all()
        # 1 for is_gtl_outside, 1 for last_gtl_outside_blocked
        self.assertEqual(account_gtl_histories.count(), 2)
        is_gtl_outside_history = account_gtl_histories.filter(field_name='is_gtl_outside').first()
        self.assertEqual(is_gtl_outside_history.value_old, 'False')
        self.assertEqual(is_gtl_outside_history.value_new, 'True')
        last_gtl_outside_blocked_history = account_gtl_histories.filter(
            field_name='last_gtl_outside_blocked'
        ).first()
        self.assertTrue(
            str(self.today + timedelta(hours=1)) in last_gtl_outside_blocked_history.value_new
        )

        account_gtl.delete()
        process_block_by_gtl_outside(
            account_id=self.account.id, is_experiment=False, block_time_in_hours=1
        )
        new_account_gtl = AccountGTL.objects.get_or_none(account=self.account)
        self.assertEqual(new_account_gtl.is_gtl_outside, True)
        # no new AccountGTL and history created
        self.assertEqual(AccountGTLHistory.objects.all().count(), 2)

        # test bypass by experiment with exist AccountGTL
        new_account_gtl.is_gtl_outside = False
        new_account_gtl.save()
        old_last_gtl_outside_blocked = new_account_gtl.last_gtl_outside_blocked
        process_block_by_gtl_outside(
            account_id=self.account.id,
            is_experiment=True,
            block_time_in_hours=1,
        )
        new_account_gtl.refresh_from_db()
        self.assertEqual(new_account_gtl.is_gtl_outside_bypass, True)
        self.assertEqual(new_account_gtl.is_gtl_outside, False)
        # do not update last_gtl_outside_blocked
        self.assertEqual(new_account_gtl.last_gtl_outside_blocked, old_last_gtl_outside_blocked)
        self.assertEqual(AccountGTLHistory.objects.all().count(), 3)

        # test bypass by experiment with no exist AccountGTL
        new_account_gtl.delete()
        process_block_by_gtl_outside(
            account_id=self.account.id,
            is_experiment=True,
            block_time_in_hours=1,
        )
        account_gtl = AccountGTL.objects.get_or_none(account=self.account)
        self.assertEqual(account_gtl.is_gtl_outside_bypass, True)
        self.assertEqual(account_gtl.is_gtl_outside, False)
        self.assertEqual(account_gtl.last_gtl_outside_blocked, None)
        # no new AccountGTL and history created
        self.assertEqual(AccountGTLHistory.objects.filter(account_gtl=account_gtl).count(), 0)

        # test block when disable bypass by experiment
        process_block_by_gtl_outside(
            account_id=self.account.id,
            is_experiment=False,
            block_time_in_hours=1,
        )
        account_gtl.refresh_from_db()
        self.assertEqual(account_gtl.is_gtl_outside_bypass, False)
        self.assertEqual(account_gtl.is_gtl_outside, True)
        self.assertIsNotNone(account_gtl.last_gtl_outside_blocked)
        # 3 records for is_gtl_outside_bypass, is_gtl_outside, and last_gtl_outside_blocked
        self.assertEqual(AccountGTLHistory.objects.filter(account_gtl=account_gtl).count(), 3)

    @patch('juloserver.loan.services.loan_related.process_block_by_gtl_outside')
    @patch('juloserver.loan.services.loan_related.is_fdc_loan_satisfy_gtl_outside')
    @patch('juloserver.loan.services.loan_related.is_repeat_user_gtl_outside')
    @patch('juloserver.loan.services.loan_related.is_b_score_satisfy_gtl_outside')
    def test_check_eligible_gtl_outside(
        self,
        mock_is_b_score_satisfy_gtl_outside,
        mock_is_repeat_user_gtl_outside,
        mock_is_fdc_loan_satisfy_gtl_outside,
        mock_process_block_by_gtl_outside,
    ):
        def call_check_eligible_gtl_outside(
            application_id=None,
            customer_id=None,
            account_limit=None,
            loan_amount_request=None,
        ):
            return is_eligible_gtl_outside(
                application_id=application_id
                if application_id is not None
                else self.application.id,
                customer_id=customer_id if customer_id is not None else self.customer.id,
                account_limit=account_limit if account_limit is not None else self.account_limit,
                loan_amount_request=loan_amount_request
                if loan_amount_request is not None
                else self.account_limit.available_limit * 95 / 100,
            )

        # Case: already blocked before, not bypass by experiment => False
        account_gtl = AccountGTLFactory(account=self.account, is_gtl_outside=True)
        self.assertFalse(call_check_eligible_gtl_outside())

        # Case: already blocked before, bypass by experiment => True
        account_gtl.is_gtl_outside_bypass = True
        account_gtl.save()
        self.assertTrue(call_check_eligible_gtl_outside())

        # unblock
        account_gtl.is_gtl_outside = False
        account_gtl.is_gtl_outside_bypass = False
        account_gtl.save()

        # Case: loan amount request is not more than 90% of available limit => True
        self.assertTrue(
            call_check_eligible_gtl_outside(
                loan_amount_request=self.account_limit.available_limit * 50 / 100
            )
        )

        # Case: B Score > 0.75 => True
        mock_is_b_score_satisfy_gtl_outside.return_value = False
        self.assertTrue(call_check_eligible_gtl_outside())

        mock_is_b_score_satisfy_gtl_outside.return_value = True

        # Case: is not repeat user
        mock_is_repeat_user_gtl_outside.return_value = False
        self.assertTrue(call_check_eligible_gtl_outside())

        mock_is_repeat_user_gtl_outside.return_value = True

        # Case: check FDC outstanding loans
        mock_is_fdc_loan_satisfy_gtl_outside.return_value = False
        self.assertTrue(call_check_eligible_gtl_outside())

        mock_is_fdc_loan_satisfy_gtl_outside.return_value = True
        mock_process_block_by_gtl_outside.return_value = None
        self.assertFalse(call_check_eligible_gtl_outside())

    @patch('juloserver.loan.services.loan_related.get_params_fs_gtl_cross_platform')
    def test_check_lock_by_gtl_outside(self, mock_get_params_fs_gtl_cross_platform):
        # fs disable => False
        mock_get_params_fs_gtl_cross_platform.return_value = None
        self.assertFalse(check_lock_by_gtl_outside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, but transaction method is not in the list_transaction_method_code => False
        mock_get_params_fs_gtl_cross_platform.return_value = {'block_trx_method_ids': []}
        self.assertFalse(check_lock_by_gtl_outside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, transaction method is in the list_transaction_method_code,
        # but user doesn't have any AccountGTL => False
        mock_get_params_fs_gtl_cross_platform.return_value = {
            'block_trx_method_ids': [TransactionMethodCode.SELF.code],
        }
        self.assertFalse(check_lock_by_gtl_outside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, transaction method is in the list_transaction_method_code,
        # user has AccountGTL, but is_gtl_outside=False => False
        account_gtl = AccountGTLFactory(account=self.account, is_gtl_outside=False)
        self.assertFalse(check_lock_by_gtl_outside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, transaction method is in the list_transaction_method_code,
        # user has AccountGTL, but is_gtl_outside=True => True
        account_gtl.is_gtl_outside = True
        account_gtl.save()
        self.assertTrue(check_lock_by_gtl_outside(self.account, TransactionMethodCode.SELF.code))

        # fs enable, transaction method is in the list_transaction_method_code,
        # user has AccountGTL, is_gtl_outside=True, but is_gtl_outside_bypass=True => False
        account_gtl.is_gtl_outside_bypass = True
        account_gtl.save()
        self.assertFalse(check_lock_by_gtl_outside(self.account, TransactionMethodCode.SELF.code))

    def test_is_experiment_gtl_outside(self):
        # experiment_last_digits is empty
        self.assertFalse(is_experiment_gtl_outside([], 12345))

        # experiment_last_digits is not empty and application_id is in experiment_last_digits
        self.assertTrue(is_experiment_gtl_outside([5, 6, 7], 25))

        # experiment_last_digits is not empty but application_id is not in experiment_last_digits
        self.assertFalse(is_experiment_gtl_outside([5, 6, 7], 123))

    def test_is_apply_gtl_outside(self):
        # application is not J1 or Jturbo
        self.assertFalse(
            is_apply_gtl_outside(
                transaction_method_code=TransactionMethodCode.SELF.code,
                application=self.application,
                fs_parameters={'block_trx_method_ids': [TransactionMethodCode.SELF.code]},
            )
        )

        # application is J1
        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )

        # INACTIVE FS
        # => False
        self.assertFalse(
            is_apply_gtl_outside(
                transaction_method_code=TransactionMethodCode.SELF.code,
                application=self.application,
                fs_parameters=None,
            )
        )

        # ACTIVE FS
        # transaction method is not in the list_transaction_method_code
        # => False
        self.assertFalse(
            is_apply_gtl_outside(
                transaction_method_code=TransactionMethodCode.SELF.code,
                application=self.application,
                fs_parameters={'block_trx_method_ids': []},
            )
        )

        # ACTIVE FS
        # transaction method is not in the list_transaction_method_code
        # => True
        self.assertTrue(
            is_apply_gtl_outside(
                transaction_method_code=TransactionMethodCode.SELF.code,
                application=self.application,
                fs_parameters={'block_trx_method_ids': [TransactionMethodCode.SELF.code]},
            )
        )

    def test_fill_dynamic_param_in_error_message_gtl_outside(self):
        self.assertEqual(
            fill_dynamic_param_in_error_message_gtl_outside(
                block_time_in_hours=72,  # 3 days
                message="Your account is blocked for {{waiting_days}} days.",
            ),
            "Your account is blocked for 3 days."
        )

        # no replacement
        self.assertEqual(
            fill_dynamic_param_in_error_message_gtl_outside(
                block_time_in_hours=72,
                message="Your account is blocked.",
            ),
            "Your account is blocked."
        )

    @patch('juloserver.loan.services.loan_related.get_params_fs_gtl_cross_platform')
    @patch('juloserver.loan.services.loan_related.is_apply_gtl_outside')
    @patch('juloserver.loan.services.loan_related.is_eligible_gtl_outside')
    @patch('juloserver.loan.services.loan_related.create_loan_rejected_by_gtl')
    @patch('juloserver.loan.services.loan_related.process_block_by_gtl_outside')
    @patch('juloserver.loan.services.loan_related.is_experiment_gtl_outside')
    @patch('juloserver.loan.services.loan_related.fill_dynamic_param_in_error_message_gtl_outside')
    def test_process_check_gtl_outside(self, mock_fill_dynamic_param_in_error_message_gtl_outside, mock_is_experiment_gtl_outside, mock_process_block_by_gtl_outside, mock_create_loan_rejected_by_gtl, mock_is_eligible_gtl_outside, mock_is_apply_gtl_outside, mock_get_params_fs_gtl_cross_platform):
        transaction_method_id = 1
        loan_amount = 123
        error_message = 'error message'

        def call_process_check_gtl_outside():
            return process_check_gtl_outside(
                transaction_method_id=transaction_method_id,
                loan_amount=loan_amount,
                application=self.application,
                customer_id=self.customer.id,
                account_limit=self.account_limit,
            )

        fs_parameters = {
            "threshold_gte_available_limit_percent": 90,
            "threshold_lte_b_score": 0.75,
            "threshold_gt_last_dpd_fdc": 0,
            "exclude_app_id_last_digit": [],
            "block_time_in_hours": 24 * 14,
            "ineligible_message_for_old_application": "",
            "ineligible_popup": {
                "is_active": True,
                "title": "Kamu Belum Bisa Transaksi",
                "banner": {
                    "is_active": True,
                    "url": "123",
                },
                "content": "",
            },
        }

        mock_get_params_fs_gtl_cross_platform.return_value = fs_parameters
        mock_fill_dynamic_param_in_error_message_gtl_outside.return_value = error_message

        # Case 1: is_apply_gtl_outside=True, but ineligible
        mock_is_apply_gtl_outside.return_value = True
        mock_is_eligible_gtl_outside.return_value = False

        # experiment
        mock_is_experiment_gtl_outside.return_value = True
        self.assertIsNone(call_process_check_gtl_outside())

        # don't experiment
        mock_is_experiment_gtl_outside.return_value = False
        result = call_process_check_gtl_outside()
        self.assertEqual(result.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(error_message, result.data['errors'][0])
        self.assertEqual(
            result.data['data']['error_popup']['error_code'], ErrorCode.INELIGIBLE_GTL_OUTSIDE
        )
        fs_parameters['ineligible_popup']['content'] = error_message
        self.assertEqual(result.data['data']['error_popup'], fs_parameters['ineligible_popup'])
        mock_create_loan_rejected_by_gtl.assert_called()
        mock_process_block_by_gtl_outside.assert_called_with(
            account_id=self.account.id,
            is_experiment=False,
            block_time_in_hours=fs_parameters['block_time_in_hours'],
        )

        # Case 2: is_apply_gtl_outside=True, but eligible
        mock_is_apply_gtl_outside.return_value = True
        mock_is_eligible_gtl_outside.return_value = True
        self.assertIsNone(call_process_check_gtl_outside())

        # Case 3: is_apply_gtl_outside=False
        mock_is_apply_gtl_outside.return_value = False
        self.assertIsNone(call_process_check_gtl_outside())


class TestCreditMatrix(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_property = AccountPropertyFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

        self.goldfish_credit_matrix = CreditMatrixFactory.goldfish(app=self.application)
        self.semi_good_credit_matrix = CreditMatrixFactory.semi_good(app=self.application)

        self.credit_matrix = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                min_threshold=0,
                max_threshold=1,
                transaction_type='self',
            ),
        )

        self.new_logic_fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.NEW_CREDIT_MATRIX_PRODUCT_LINE_RETRIEVAL_LOGIC,
            is_active=False,
        )

    @patch("juloserver.loan.services.loan_related.check_is_success_goldfish")
    def test_get_goldfish_credit_matrix(self, mock_define_goldfish_application):
        mock_define_goldfish_application.return_value = True

        credit_matrix, _ = get_credit_matrix_and_credit_matrix_product_line(
            self.application, True, None, 'self'
        )
        self.assertEqual(credit_matrix, self.goldfish_credit_matrix)

    @patch("juloserver.loan.services.loan_related.get_revive_semi_good_customer_score")
    def test_get_semi_good_credit_matrix(self, mock_define_semi_good_application):
        mock_define_semi_good_application.return_value = 'C+'
        credit_matrix, _ = get_credit_matrix_and_credit_matrix_product_line(
            self.application, True, None, 'self'
        )
        self.assertEqual(credit_matrix, self.semi_good_credit_matrix)

    def test_get_semi_good_credit_matrix_new_logic(self):
        # activate FS for new logic
        self.new_logic_fs.is_active = True
        self.new_logic_fs.save()

        CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=self.semi_good_credit_matrix,
        )
        credit_matrix, _ = get_credit_matrix_and_credit_matrix_product_line(
            self.application, True, None, 'self'
        )
        self.assertEqual(credit_matrix, self.semi_good_credit_matrix)

    def test_not_found_credit_matrix_by_account_property(self):
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        application = ApplicationFactory(customer=customer, account=account)

        credit_matrix, _ = get_credit_matrix_and_credit_matrix_product_line(
            application, True, None, None
        )
        self.assertEqual(credit_matrix, None)

    @patch(
        "juloserver.loan.services.loan_related.get_credit_matrix_parameters_from_account_property"
    )
    def test_not_found_credit_matrix_by_parameters(self, mock_get_parameters):
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        AccountPropertyFactory(account=account)
        application = ApplicationFactory(customer=customer, account=account)
        mock_get_parameters.return_value = None
        credit_matrix, _ = get_credit_matrix_and_credit_matrix_product_line(
            application, True, None, None
        )
        self.assertEqual(credit_matrix, None)

    def test_get_matrix_from_credit_limit_generation(self):
        """
        new get cm & cm product line logic
        """
        # activate FS for new logic
        self.new_logic_fs.is_active = True
        self.new_logic_fs.save()

        field_param = 'feature:any_feature_really'
        type = CreditMatrixType.JULO1

        test_credit_matrix = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter=field_param,
                credit_matrix_type=type,
                transaction_type='self',
            ),
        )
        CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=test_credit_matrix,
        )

        credit_matrix, _ = get_credit_matrix_and_credit_matrix_product_line(
            self.application, True, None, 'self'
        )
        self.assertEqual(credit_matrix, test_credit_matrix)

    @patch("juloserver.loan.services.loan_related.get_credit_matrix_field_param")
    def test_new_logic_credit_matrix_not_found(self, mock_get_cm_field_param):
        mock_get_cm_field_param.return_value = Q(parameter='feature:non_existing_field')

        # activate FS for new logic
        self.new_logic_fs.is_active = True
        self.new_logic_fs.save()

        field_param = 'feature:any_feature_really'
        type = CreditMatrixType.JULO1

        test_credit_matrix = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter=field_param,
                credit_matrix_type=type,
                transaction_type='self',
            ),
        )
        CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=test_credit_matrix,
        )

        with self.assertRaises(CreditMatrixNotFound):
            get_credit_matrix_and_credit_matrix_product_line(self.application, True, None, 'self')

    @patch("juloserver.loan.services.loan_related.get_revive_semi_good_customer_score")
    def test_ok_credit_matrix_field_param(self, mock_semi_good):
        # activate FS for new logic
        self.new_logic_fs.is_active = True
        self.new_logic_fs.save()

        mock_semi_good.return_value = None

        field_param = 'feature:abc'
        type = CreditMatrixType.JULO1

        test_credit_matrix = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter=field_param,
                credit_matrix_type=type,
                transaction_type='self',
            ),
        )
        CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=test_credit_matrix,
        )

        param_query_filter = get_credit_matrix_field_param(app=self.application)

        expected_filter = {'parameter': field_param}
        self.assertEqual(
            param_query_filter.__dict__, Q(**expected_filter).__dict__
        )

    @patch("juloserver.loan.services.loan_related.get_revive_semi_good_customer_score")
    def test_multi_cmgeneration_credit_matrix_field_param(self, mock_semi_good):
        """
        Case app has multiple CM Generation records, expect to get lastest
        """
        mock_semi_good.return_value = None

        field_param = 'feature:first'
        field_param2 = 'feature:second'
        type = CreditMatrixType.JULO1

        credit_matrix1 = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter=field_param,
                credit_matrix_type=type,
                transaction_type='self',
            ),
        )
        CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=credit_matrix1,
        )

        credit_matrix2 = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter=field_param2,
                credit_matrix_type=type,
                transaction_type='self',
            ),
        )
        CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=credit_matrix2,
        )

        param_query_filter = get_credit_matrix_field_param(app=self.application)

        expected_filter = {'parameter': field_param2}
        self.assertEqual(
            param_query_filter.__dict__, Q(**expected_filter).__dict__
        )

    def test_semi_good_credit_matrix_field_param(self):

        expeted_field_param = 'feature:is_semi_good'
        CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=self.semi_good_credit_matrix,
        )

        param_query_filter = get_credit_matrix_field_param(app=self.application)

        expected_filter = {'parameter': expeted_field_param}
        self.assertEqual(
            param_query_filter.__dict__, Q(**expected_filter).__dict__
        )

    @patch("juloserver.loan.services.loan_related.get_revive_semi_good_customer_score")
    def test_julostarter_loan_credit_matrix_params(self, mock_semi_good):
        mock_semi_good.return_value = None

        # at this status, users don't have CM generation yet
        self.application.application_status_id = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        self.application.save()

        # make sure we don't have CM Generation (cmg) before test
        cmg_exists = CreditLimitGeneration.objects.filter(application=self.application).exists()
        self.assertEqual(cmg_exists, False)

        type = CreditMatrixType.JULO_STARTER
        CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                credit_matrix_type=type,
                transaction_type='self',
            ),
        )
        param_query_filter = get_credit_matrix_field_param(app=self.application)

        # expect filter None
        self.assertEqual(param_query_filter, None)

    @patch(
        "juloserver.loan.services.loan_related.get_account_property_by_account"
    )
    def test_get_loan_credit_matrix_params_no_account_property(self, mock_get_acc_property):

        mock_get_acc_property.return_value = None

        return_value = get_loan_credit_matrix_params(app=self.application)
        self.assertEqual(return_value, {})

    @patch(
        "juloserver.loan.services.loan_related.get_credit_matrix_parameters_from_account_property"
    )
    def test_ok_get_loan_credit_matrix_params(self, mock_get_cmparams_from_property):
        expected_pgood = 0.5
        expected_type = CreditMatrixType.JULO1
        expected_return = dict(
            min_threshold__lte=expected_pgood,
            max_threshold__gte=expected_pgood,
            credit_matrix_type=expected_type,
            is_fdc=False,
        )
        mock_get_cmparams_from_property.return_value = expected_return

        return_value = get_loan_credit_matrix_params(app=self.application)
        self.assertEqual(return_value['min_threshold__lte'], expected_return['min_threshold__lte'])
        self.assertEqual(return_value['max_threshold__gte'], expected_return['max_threshold__gte'])
        self.assertEqual(return_value['credit_matrix_type'], expected_return['credit_matrix_type'])
        self.assertEqual(return_value['is_fdc'], expected_return['is_fdc'])

    @patch('juloserver.loan.services.loan_related.get_fdc_status')
    def test_get_credit_matrix_and_credit_matrix_product_line_v1_fdc(self, mock_get_fdc_status):
        type = CreditMatrixType.JULO1

        fdc_credit_matrix = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter='',
                credit_matrix_type=type,
                transaction_type='self',
                is_fdc=True,
            ),
        )

        non_fdc_credit_matrix = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter='',
                credit_matrix_type=type,
                transaction_type='self',
                is_fdc=False,
            ),
        )

        mock_get_fdc_status.return_value = True
        cm, cm_product_line = get_credit_matrix_and_credit_matrix_product_line(
            application=self.application,
            transaction_type='self',
        )

        self.assertEqual(cm, fdc_credit_matrix)
        self.assertIsNotNone(cm_product_line)

        mock_get_fdc_status.return_value = False
        cm, cm_product_line = get_credit_matrix_and_credit_matrix_product_line(
            application=self.application,
            transaction_type='self',
        )

        self.assertEqual(cm, non_fdc_credit_matrix)
        self.assertIsNotNone(cm_product_line)

    @patch('juloserver.loan.services.loan_related.get_fdc_status')
    def test_get_credit_matrix_and_credit_matrix_product_line_v2_fdc(self, mock_get_fdc_status):
        # activate v2 fs
        self.new_logic_fs.is_active = True
        self.new_logic_fs.save()
        type = CreditMatrixType.JULO1

        fdc_credit_matrix = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter='',
                credit_matrix_type=type,
                transaction_type='self',
                is_fdc=True,
            ),
        )

        non_fdc_credit_matrix = CreditMatrixFactory.new(
            app=self.application,
            data=dict(
                parameter='',
                credit_matrix_type=type,
                transaction_type='self',
                is_fdc=False,
            ),
        )

        mock_get_fdc_status.return_value = True
        cm, cm_product_line = get_credit_matrix_and_credit_matrix_product_line(
            application=self.application,
            transaction_type='self',
        )

        self.assertEqual(cm, fdc_credit_matrix)
        self.assertIsNotNone(cm_product_line)

        mock_get_fdc_status.return_value = False
        cm, cm_product_line = get_credit_matrix_and_credit_matrix_product_line(
            application=self.application,
            transaction_type='self',
        )

        self.assertEqual(cm, non_fdc_credit_matrix)
        self.assertIsNotNone(cm_product_line)


class TestEligibleApplicationStatus(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        AccountPropertyFactory(account=self.account)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.status_submit = StatusLookupFactory(
            status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED
        )
        self.status_verified = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            application_status=self.status_submit,
        )

    def test_eligible_application_status_code(self):
        assert is_eligible_application_status(self.account, None) == False

        self.application.application_status = self.status_verified
        self.application.save()
        assert is_eligible_application_status(self.account, None) == True

        self.application.application_status = self.status_verified
        self.application.workflow = self.workflow_j1
        self.application.save()
        assert is_eligible_application_status(self.account, None) == True


class TestNotifyTransactionStatusToUser(TestCase):
    def setUp(self):
        self.app_version = '8.25.0'

        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            app_version=self.app_version,
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)

        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, workflow=self.workflow
        )
        self.loan = LoanFactory(
            application=self.application,
            loan_status=StatusLookupFactory(status_code=212),
            customer=self.customer,
            account=self.account,
            transaction_method_id=TransactionMethodCode.SELF.code,
        )
        WorkflowStatusPathFactory(status_previous=212, status_next=220, workflow=self.workflow)

        params = {
            'minimum_app_version': self.app_version,
            'allowed_methods': [
                TransactionMethodCode.SELF.code,
                TransactionMethodCode.OTHER.code,
                TransactionMethodCode.PULSA_N_PAKET_DATA.code,
                TransactionMethodCode.PASCA_BAYAR.code,
                TransactionMethodCode.DOMPET_DIGITAL.code,
                TransactionMethodCode.LISTRIK_PLN.code,
                TransactionMethodCode.BPJS_KESEHATAN.code,
                TransactionMethodCode.E_COMMERCE.code,
                TransactionMethodCode.TRAIN_TICKET.code,
                TransactionMethodCode.PDAM.code,
                TransactionMethodCode.EDUCATION.code,
                TransactionMethodCode.HEALTHCARE.code,
            ],
        }

        # case unactive
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.TRANSACTION_RESULT_NOTIFICATION,
            is_active=True,
            parameters=params,
        )

    @patch("juloserver.loan.services.loan_related.send_transaction_status_event_to_moengage.delay")
    @patch("juloserver.loan.services.loan_related.execute_after_transaction_safely")
    def test_notify_transaction_status_to_j1_user(self, mock_execute, mock_send):
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        self.loan.loan_status = StatusLookupFactory(status_code=220)
        self.loan.save()

        notify_transaction_status_to_user(
            loan=self.loan,
            app=self.application,
        )

        # make sure execute_transaction_safely was called
        mock_execute.assert_called_once()
        self.assertTrue(callable(mock_execute.call_args[0][0]))  # Ensure it's a callable (lambda)

        # manually call what we passed in e
        execute_func_param = mock_execute.call_args[0][0]
        execute_func_param()

        mock_send.assert_called_once_with(
            customer_id=self.customer.id,
            loan_xid=self.loan.loan_xid,
            loan_status_code=self.loan.loan_status_id,
        )

    @patch("juloserver.loan.services.loan_related.send_transaction_status_event_to_moengage.delay")
    @patch("juloserver.loan.services.loan_related.execute_after_transaction_safely")
    def test_notify_transaction_status_to_starter_user(self, mock_execute, mock_send):
        # starter
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER)
        self.application.product_line = product_line
        self.application.save()

        self.workflow.name = WorkflowConst.JULO_STARTER
        self.workflow.save()

        # set loan to right status
        self.loan.loan_status = StatusLookupFactory(status_code=220)
        self.loan.save()

        notify_transaction_status_to_user(
            loan=self.loan,
            app=self.application,
        )

        # make sure execute_transaction_safely was called
        mock_execute.assert_called_once()
        self.assertTrue(callable(mock_execute.call_args[0][0]))  # Ensure it's a callable (lambda)

        # manually call what we passed in e
        execute_func_param = mock_execute.call_args[0][0]
        execute_func_param()

        mock_send.assert_called_once_with(
            customer_id=self.customer.id,
            loan_xid=self.loan.loan_xid,
            loan_status_code=self.loan.loan_status_id,
        )

    @patch("juloserver.loan.services.loan_related.execute_after_transaction_safely")
    def test_notify_transaction_status_wrong_status_code(self, mock_execute):
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        test_status_codes = [218, 250]

        for code in test_status_codes:
            self.loan.loan_status = StatusLookupFactory(status_code=code)
            self.loan.save()

            notify_transaction_status_to_user(
                loan=self.loan,
                app=self.application,
            )
            mock_execute.assert_not_called()

    @patch("juloserver.loan.services.loan_related.send_transaction_status_event_to_moengage.delay")
    @patch("juloserver.loan.services.loan_related.execute_after_transaction_safely")
    def test_notify_transaction_status_to_julover_user(self, mock_execute, mock_send):
        # julover
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.application.product_line = product_line
        self.application.save()

        self.workflow.name = WorkflowConst.JULOVER
        self.workflow.save()

        # set loan to right status
        self.loan.loan_status = StatusLookupFactory(status_code=220)
        self.loan.save()

        notify_transaction_status_to_user(
            loan=self.loan,
            app=self.application,
        )

        # make sure execute_transaction_safely was called
        mock_execute.assert_called_once()
        self.assertTrue(callable(mock_execute.call_args[0][0]))  # Ensure it's a callable (lambda)

        # manually call what we passed in e
        execute_func_param = mock_execute.call_args[0][0]
        execute_func_param()

        mock_send.assert_called_once_with(
            customer_id=self.customer.id,
            loan_xid=self.loan.loan_xid,
            loan_status_code=self.loan.loan_status_id,
        )

    @patch("juloserver.loan.services.loan_related.execute_after_transaction_safely")
    def test_notify_transaction_status_feature_setting(self, mock_execute):
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.product_line = product_line
        self.application.save()

        self.loan.loan_status = StatusLookupFactory(status_code=220)
        self.loan.save()

        # case inactive
        self.fs.is_active = False
        self.fs.save()

        notify_transaction_status_to_user(
            loan=self.loan,
            app=self.application,
        )
        mock_execute.assert_not_called()

        # app too old
        self.fs.is_active = True
        self.fs.parameters['minimum_app_version'] = '8.25.1'
        self.fs.save()

        notify_transaction_status_to_user(
            loan=self.loan,
            app=self.application,
        )
        mock_execute.assert_not_called()

        self.fs.is_active = True
        self.fs.parameters['minimum_app_version'] = '8.24.1'
        self.fs.save()

        # transaction method is not allowed
        fake_number = 99999999
        self.loan.transaction_method_id = fake_number
        self.loan.save()
        self.loan.refresh_from_db()

        notify_transaction_status_to_user(
            loan=self.loan,
            app=self.application,
        )
        mock_execute.assert_not_called()

        # case ok
        self.loan.transaction_method_id = TransactionMethodCode.SELF.code
        self.loan.save()
        notify_transaction_status_to_user(
            loan=self.loan,
            app=self.application,
        )
        mock_execute.assert_called()

    @patch("juloserver.loan.services.loan_related.update_available_limit")
    @patch("juloserver.loan.services.loan_related.notify_transaction_status_to_user")
    def test_celery_run_when_update_loan_status(self, mock_notify, mock_update_available_limit):
        mock_update_available_limit.return_value = None

        update_loan_status_and_loan_history(
            loan_id=self.loan.id,
            new_status_code=220,
        )

        mock_notify.assert_called_once_with(
            loan=self.loan,
            app=self.application,
        )


class TestNameBankMismatchApplicationStatus(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        AccountPropertyFactory(account=self.account)
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.approved_status = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow_j1,
            application_status=self.approved_status,
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.FAILED_BANK_NAME_VALIDATION_DURING_UNDERWRITING,
            is_active=False,
            parameters={'allowed_transaction_methods': ["1"]},
        )
        ApplicationTagFactory(application_tag=IS_NAME_IN_BANK_MISMATCH_TAG)
        self.application_path_tag = ApplicationPathTagFactory(
            application_id=self.application.pk,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag=IS_NAME_IN_BANK_MISMATCH_TAG, status=1
            ),
        )

    def test_name_bank_mismatch(self):
        # turn fs off => not locked
        assert (
            is_name_in_bank_mismatch(self.account, None, TransactionMethodCode.SELF.code) == False
        )

        # turn fs on, method_code in allowed_transaction_methods => not locked (False)
        self.fs.is_active = True
        self.fs.save()
        assert (
            is_name_in_bank_mismatch(self.account, None, TransactionMethodCode.SELF.code) == False
        )

        self.fs.parameters['allowed_transaction_methods'] = []
        self.fs.save()
        # turn fs on, method_code not in allowed_transaction_methods => locked (True)
        assert (
            is_name_in_bank_mismatch(self.account, None, TransactionMethodCode.OTHER.code) == True
        )

        # the application doens't have is_name_in_bank_mismatch tag => not locked (False)
        self.application_path_tag.application_id = 0
        self.application_path_tag.save()
        assert (
            is_name_in_bank_mismatch(self.account, None, TransactionMethodCode.OTHER.code) == False
        )

    def test_is_locked_product_function(self):
        self.fs.is_active = True
        self.fs.save()
        result = is_julo_one_product_locked_and_reason(
            self.account, LoanJuloOneConstant.KIRIM_DANA, TransactionMethodCode.OTHER.code
        )
        assert result == (True, AccountLockReason.NAME_IN_BANK_MISMATCH)


class TestQrisWhitelistApplicationStatus(TestCase):
    def setUp(self):
        # whitelisted customer
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        AccountPropertyFactory(account=self.account)
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.approved_status = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application1 = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow_j1,
            application_status=self.approved_status,
        )

        # customer not whitelisted, but in allowed_last_digits
        self.customer2 = CustomerFactory(id=1000017081)
        self.account2 = AccountFactory(customer=self.customer2)
        AccountPropertyFactory(account=self.account2)
        self.application2 = ApplicationFactory(
            customer=self.customer2,
            account=self.account2,
            workflow=self.workflow_j1,
            application_status=self.approved_status,
        )

        # customer not whitelisted, and not in allowed_last_digits
        self.customer3 = CustomerFactory(id=1000017082)
        self.account3 = AccountFactory(customer=self.customer3)
        AccountPropertyFactory(account=self.account3)
        self.application3 = ApplicationFactory(
            customer=self.customer3,
            account=self.account3,
            workflow=self.workflow_j1,
            application_status=self.approved_status,
        )

        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER,
            is_active=False,
            parameters={
                'customer_ids': [self.customer.id],
                'allowed_last_digits': [1, 3, 5, 7, 9],
                'redis_customer_whitelist_active': False,
            },
        )

    def test_is_locked_product_function(self):
        self.fs.is_active = True
        self.fs.save()
        result = is_julo_one_product_locked_and_reason(
            self.account3, LoanJuloOneConstant.QRIS_1, TransactionMethodCode.QRIS_1.code
        )
        assert result == (True, AccountLockReason.QRIS_NOT_WHITELISTED)

    def test_is_not_locked_product_function(self):
        self.fs.is_active = True
        self.fs.save()
        result = is_julo_one_product_locked_and_reason(
            self.account, LoanJuloOneConstant.QRIS_1, TransactionMethodCode.QRIS_1.code
        )
        assert result == (False, None)

    def test_not_whitelisted_but_allowed_last_digit_function(self):
        self.fs.is_active = True
        self.fs.save()
        result = is_julo_one_product_locked_and_reason(
            self.account2, LoanJuloOneConstant.QRIS_1, TransactionMethodCode.QRIS_1.code
        )
        assert result == (False, None)

    def test_is_qris_blocked(self):
        # fs is active, and user is whitelisted -> return false
        self.fs.is_active = True
        self.fs.save()
        res = is_qris_1_blocked(self.account, TransactionMethodCode.QRIS_1.code)
        self.assertFalse(res)

        # fs is active, and user is not whitelisted -> return true
        self.fs.is_active = True
        self.fs.save()
        res = is_qris_1_blocked(self.account3, TransactionMethodCode.QRIS_1.code)
        self.assertTrue(res)

        # fs is inactive, and user is whitelisted -> return false
        self.fs.is_active = False
        self.fs.save()
        res = is_qris_1_blocked(self.account, TransactionMethodCode.QRIS_1.code)
        self.assertFalse(res)

        # fs is inactive, and user is not whitelisted -> return false
        self.fs.is_active = False
        self.fs.save()
        res = is_qris_1_blocked(self.account3, TransactionMethodCode.QRIS_1.code)
        self.assertFalse(res)

        # fs is active, user not whitelisted but in allowed last digits -> return false
        self.fs.is_active = True
        self.fs.save()
        res = is_qris_1_blocked(self.account2, TransactionMethodCode.QRIS_1.code)
        self.assertFalse(res)

        # fs is inactive, user not whitelisted but in allowed last digits -> return false
        self.fs.is_active = False
        self.fs.save()
        res = is_qris_1_blocked(self.account2, TransactionMethodCode.QRIS_1.code)
        self.assertFalse(res)

    @patch("juloserver.loan.services.loan_related.query_redis_ids_whitelist")
    def test_is_qris_blocked_redis_whitelist(self, mock_query_redis_whitelist):
        # case active
        self.fs.is_active = True
        self.fs.parameters['redis_customer_whitelist_active'] = True
        self.fs.parameters['customer_ids'] = [self.customer.id]

        self.fs.save()

        # is whitelisted => not blocked
        mock_query_redis_whitelist.return_value = True, True
        is_blocked = is_qris_1_blocked(self.account, TransactionMethodCode.QRIS_1.code)

        mock_query_redis_whitelist.assert_called_once_with(
            id=self.customer.id,
            key=RedisWhiteList.Key.SET_QRIS_WHITELISTED_CUSTOMER_IDS,
        )

        self.assertEqual(is_blocked, False)

        # is not whitelisted
        mock_query_redis_whitelist.return_value = True, False
        is_blocked = is_qris_1_blocked(self.account, TransactionMethodCode.QRIS_1.code)

        self.assertEqual(is_blocked, True)

        # redis down, uses django admin setting => not blocked
        mock_query_redis_whitelist.return_value = False, False
        is_blocked = is_qris_1_blocked(self.account, TransactionMethodCode.QRIS_1.code)

        self.assertEqual(is_blocked, False)

    @patch("juloserver.loan.services.loan_related.query_redis_ids_whitelist")
    def test_is_qris_blocked_redis_whitelist_not_active(self, mock_query_redis_whitelist):
        # redis whitelist not active => not blocked
        self.fs.is_active = True
        self.fs.parameters['redis_customer_whitelist_active'] = False
        self.fs.parameters['customer_ids'] = [self.customer.id]

        self.fs.save()

        is_blocked = is_qris_1_blocked(self.account, TransactionMethodCode.QRIS_1.code)

        mock_query_redis_whitelist.assert_not_called()
        self.assertEqual(is_blocked, False)


class TestJuloOneProductLockAndReason(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer, app_version='6.2.0')
        AccountPropertyFactory(account=self.account)
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.approved_status = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow_j1,
            application_status=self.approved_status,
        )
        MobileFeatureSettingFactory(
            feature_name=LoanJuloOneConstant.PRODUCT_LOCK_FEATURE_SETTING,
            is_active=True,
            parameters={
                "dompet_digital": {
                    "app_version": "6.3.0",
                    "locked": True
                }
            },
        )

    def test_is_locked_dompet_digital(self):
        result = is_julo_one_product_locked_and_reason(
            self.account, LoanJuloOneConstant.DOMPET_DIGITAL,
            TransactionMethodCode.DOMPET_DIGITAL.code
        )
        assert result == (True, AccountLockReason.PRODUCT_SETTING)


class TestShowDifferentPricing(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        TransactionMethod.objects.all().delete()
        self.self_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
            method=TransactionMethodCode.SELF,
        )
        self.other_method = TransactionMethodFactory(
            id=TransactionMethodCode.OTHER.code,
            method=TransactionMethodCode.OTHER,
        )
        self.product = ProductLookupFactory(origination_fee_pct=0.05, interest_rate=0.3)
        self.active_status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.current_status = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.approved_status = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.account = AccountFactory(customer=self.customer, status=self.active_status)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.approved_status,
        )
        self.credit_matrix = CreditMatrixFactory(
            min_threshold=0.95,
            max_threshold=1,
            product=self.product,
            version='1',
            transaction_type=TransactionType.SELF,
            is_salaried=True,
            is_premium_area=True,
            credit_matrix_type=CreditMatrixType.JULO1_PROVEN,
            parameter=None,
        )
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix, product=self.product_line
        )
        CurrentCreditMatrix.objects.create(
            credit_matrix=self.credit_matrix, transaction_type=TransactionType.SELF
        )
        self.account_property = AccountPropertyFactory(
            pgood=0.99,
            p0=0.99,
            account=self.account,
            is_proven=True,
            is_salaried=True,
            is_premium_area=True,
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=self.current_status,
            loan_amount=1_000_000,
            loan_duration=3,
            product=self.product,
            transaction_method_id=self.self_method.pk,
        )
        self.payment = PaymentFactory(
            loan=self.loan,
            due_amount=10000,
        )
        self.credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='active_a',
            product_line=self.application.product_line,
            transaction_method=self.self_method,
            version=1,
            interest=0.2,
            provision=0.02,
            max_tenure=6,
        )
        self.fs_showing_different_pricing = FeatureSettingFactory(
            feature_name=FeatureNameConst.SHOW_DIFFERENT_PRICING_ON_UI, is_active=False
        )

    @mock.patch('juloserver.loan.services.views_related.get_first_payment_date_by_application')
    @mock.patch('juloserver.loan.services.views_related.timezone.now')
    def test_get_crossed_interest_and_installment_amount_with_self_method(
        self, mock_time_zone, mock_first_payment_date
    ):
        current_date = datetime(2024, 5, 2)
        first_payment_date = datetime(2024, 5, 30).date()
        mock_time_zone.return_value = current_date
        mock_first_payment_date.return_value = first_payment_date
        # inactive fs
        interest, installment_amount, _ = get_crossed_interest_and_installment_amount(self.loan)
        assert interest == 0
        assert installment_amount == 0

        # active fs
        self.fs_showing_different_pricing.is_active = True
        self.fs_showing_different_pricing.save()

        # CMR not exists
        interest, installment_amount, _ = get_crossed_interest_and_installment_amount(self.loan)

        # 1. CMR exists
        CreditMatrixRepeatLoan.objects.create(
            loan=self.loan, credit_matrix_repeat=self.credit_matrix_repeat
        )
        # 2. CM interest =< CMR interest=> not show crossed interest
        interest_rate_cmr = 0.4
        # get interest_monthly by monthly_interest_rate not interest_rate field
        interest_rate_cm = 0.5 * 12
        self.credit_matrix_repeat.interest = interest_rate_cmr
        self.product.interest_rate = interest_rate_cm
        self.credit_matrix_repeat.save()
        self.product.save()
        interest, _, _ = get_crossed_interest_and_installment_amount(self.loan)
        assert interest > self.loan.interest_rate_monthly

        # 3. CM interest > CMR interest => show crossed interest
        interest_rate_cmr = 0.5
        interest_rate_cm = 0.4 * 12
        self.credit_matrix_repeat.interest = interest_rate_cmr
        self.product.interest_rate = interest_rate_cm
        self.credit_matrix_repeat.save()
        self.product.save()
        interest, _, _ = get_crossed_interest_and_installment_amount(self.loan)
        assert interest == 0

        # 4. CM installment_amount =< CMR => not show crossed installment amount
        provision_rate_cmr = 0.04
        provision_rate_cm = 0.02
        self.credit_matrix_repeat.provision = provision_rate_cmr
        self.product.origination_fee_pct = provision_rate_cm
        self.credit_matrix_repeat.save()
        self.product.save()
        original_loan_amount = self.loan.loan_amount
        adjusted_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_rate_cmr, True
        )
        _, _, adjust_installment_amount = compute_payment_installment_julo_one(
            adjusted_loan_amount, self.loan.loan_duration, self.loan.interest_rate_monthly
        )
        self.loan.installment_amount = adjust_installment_amount
        self.loan.save()

        _, installment_amount, _ = get_crossed_interest_and_installment_amount(self.loan)
        assert installment_amount == 0

        # 5. CM installment_amount > CMR => show crossed installment amount
        interest_rate_cmr = 0.5
        interest_rate_cm = 0.8 * 12
        self.credit_matrix_repeat.interest = interest_rate_cmr
        self.product.interest_rate = interest_rate_cm
        self.credit_matrix_repeat.save()
        self.product.save()
        original_loan_amount = self.loan.loan_amount
        adjusted_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_rate_cmr, True
        )
        _, _, adjust_installment_amount = compute_payment_installment_julo_one(
            adjusted_loan_amount, self.loan.loan_duration, self.loan.interest_rate_monthly
        )
        self.loan.installment_amount = adjust_installment_amount
        self.loan.loan_disbursement_amount = self.loan.loan_amount - self.loan.provision_fee()
        self.loan.save()
        _, installment_amount, disbursement_amount = get_crossed_interest_and_installment_amount(
            self.loan
        )
        assert installment_amount > self.loan.installment_amount
        assert disbursement_amount < self.loan.loan_disbursement_amount

        # 6. CM installment_amount > CMR => show crossed installment amount
        # and loan_duration = 1
        original_loan_amount = self.loan.loan_amount
        adjusted_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_rate_cmr, True
        )
        _, _, adjust_installment_amount = compute_first_payment_installment_julo_one(
            adjusted_loan_amount,
            self.loan.loan_duration,
            self.loan.interest_rate_monthly,
            current_date.date(),
            first_payment_date,
        )
        self.loan.installment_amount = adjust_installment_amount
        self.loan.save()

        _, installment_amount, disbursement_amount = get_crossed_interest_and_installment_amount(
            self.loan
        )
        assert installment_amount > self.loan.installment_amount
        assert disbursement_amount < self.loan.loan_disbursement_amount

    @mock.patch('juloserver.loan.services.views_related.get_first_payment_date_by_application')
    @mock.patch('juloserver.loan.services.views_related.timezone.now')
    def test_get_crossed_interest_and_installment_amount_with_other_method(
        self, mock_time_zone, mock_first_payment_date
    ):
        current_date = datetime(2024, 5, 2)
        first_payment_date = datetime(2024, 5, 30).date()
        mock_time_zone.return_value = current_date
        mock_first_payment_date.return_value = first_payment_date
        self.loan.transaction_method = self.other_method
        self.loan.save()
        # inactive fs
        interest, installment_amount, _ = get_crossed_interest_and_installment_amount(self.loan)
        assert interest == 0
        assert installment_amount == 0

        # active fs
        self.fs_showing_different_pricing.is_active = True
        self.fs_showing_different_pricing.save()

        # CMR not exists
        # interest, installment_amount = get_crossed_interest_and_installment_amount(self.loan)

        # 1. CMR exists
        CreditMatrixRepeatLoan.objects.create(
            loan=self.loan, credit_matrix_repeat=self.credit_matrix_repeat
        )
        # 2. CM interest =< CMR interest=> not show crossed interest
        interest_rate_cmr = 0.4
        # get interest_monthly by monthly_interest_rate not interest_rate field
        interest_rate_cm = 0.8 * 12
        self.credit_matrix_repeat.interest = interest_rate_cmr
        self.product.interest_rate = interest_rate_cm
        self.credit_matrix_repeat.save()
        self.product.save()
        interest, _, _ = get_crossed_interest_and_installment_amount(self.loan)
        assert interest > self.loan.interest_rate_monthly

        # 3. CM interest > CMR interest => show crossed interest
        interest_rate_cmr = 0.5
        interest_rate_cm = 0.4 * 12
        self.credit_matrix_repeat.interest = interest_rate_cmr
        self.product.interest_rate = interest_rate_cm
        self.credit_matrix_repeat.save()
        self.product.save()
        interest, _, _ = get_crossed_interest_and_installment_amount(self.loan)
        assert interest == 0

        interest_rate_cmr = 0.5
        interest_rate_cm = 0.5 * 12
        # 4. CM installment_amount =< CMR => not show crossed installment amount
        provision_rate_cmr = 0.04
        provision_rate_cm = 0.02
        self.credit_matrix_repeat.provision = provision_rate_cmr
        self.credit_matrix_repeat.interest = interest_rate_cmr
        self.product.origination_fee_pct = provision_rate_cm
        self.product.interest_rate = interest_rate_cm
        self.credit_matrix_repeat.save()
        self.product.save()
        original_loan_amount = self.loan.loan_amount - self.loan.provision_fee()
        adjusted_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_rate_cmr, False
        )
        _, _, adjust_installment_amount = compute_payment_installment_julo_one(
            adjusted_loan_amount, self.loan.loan_duration, self.loan.interest_rate_monthly
        )
        self.loan.installment_amount = adjust_installment_amount
        self.loan.save()

        interest, installment_amount, _ = get_crossed_interest_and_installment_amount(self.loan)
        assert installment_amount == 0

        # 5. CM installment_amount > CMR => show crossed installment amount
        provision_rate_cmr = 0.02
        provision_rate_cm = 0.08
        self.credit_matrix_repeat.provision = provision_rate_cmr
        self.product.origination_fee_pct = provision_rate_cm
        self.credit_matrix_repeat.save()
        self.product.save()

        original_loan_amount = self.loan.loan_amount - self.loan.provision_fee()
        adjusted_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_rate_cmr, False
        )
        _, _, adjust_installment_amount = compute_payment_installment_julo_one(
            adjusted_loan_amount, self.loan.loan_duration, self.loan.interest_rate_monthly
        )
        self.loan.installment_amount = adjust_installment_amount
        self.loan.loan_disbursement_amount = self.loan.loan_amount - self.loan.provision_fee()
        self.loan.save()

        (
            _,
            installment_amount,
            crossed_disbursement_amount,
        ) = get_crossed_interest_and_installment_amount(self.loan)
        assert installment_amount > self.loan.installment_amount
        assert crossed_disbursement_amount == 0

        # 6. CM installment_amount > CMR => show crossed installment amount
        # and loan_duration = 1
        original_loan_amount = self.loan.loan_amount - self.loan.provision_fee()
        adjusted_loan_amount = get_loan_amount_by_transaction_type(
            original_loan_amount, provision_rate_cmr, False
        )
        _, _, adjust_installment_amount = compute_first_payment_installment_julo_one(
            adjusted_loan_amount,
            self.loan.loan_duration,
            self.loan.interest_rate_monthly,
            current_date.date(),
            first_payment_date,
        )
        self.loan.installment_amount = adjust_installment_amount
        self.loan.save()

        (
            _,
            installment_amount,
            crossed_disbursement_amount,
        ) = get_crossed_interest_and_installment_amount(self.loan)
        assert installment_amount > self.loan.installment_amount
        assert crossed_disbursement_amount == 0


class TestCalculateMaxDurationFromAdditionalMonth(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)

        self.user_auth2 = AuthUserFactory()
        self.customer2 = CustomerFactory(user=self.user_auth2)

        self.additional_month = 10
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.LOAN_TENURE_ADDITIONAL_MONTH,
            is_active=True,
            parameters={
                'whitelist': {
                    'is_active': False,
                    'customer_id': [],
                },
                'additional_month': self.additional_month,
            },
        )

    def test_case_fs_not_active(self):
        """
        FS not active, use default additional value
        """
        self.fs.is_active = False
        self.fs.save()

        default_additional_month = 5
        min_duration = 1
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=self.customer,
            cm_max_duration=999,
            min_duration=min_duration,
        )
        self.assertEqual(result_max_duration, min_duration + default_additional_month)

    def test_case_whitelist_inactive(self):
        """
        Happy case, fs active, whitelist inactive
        """
        # gap within additional month
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=self.customer, cm_max_duration=6, min_duration=5
        )
        self.assertEqual(result_max_duration, 6)

        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=self.customer,
            cm_max_duration=6,
            min_duration=0,
        )
        self.assertEqual(result_max_duration, 6)

        # min_duration > cm_max_duration
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=self.customer,
            cm_max_duration=6,
            min_duration=10,
        )
        self.assertEqual(result_max_duration, 6)

        # big credit matrix max-duration
        min_duration = 5
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=self.customer,
            cm_max_duration=9999,
            min_duration=min_duration,
        )
        self.assertEqual(result_max_duration, min_duration + self.additional_month)

    def test_case_whitelist_active(self):
        """
        If whitelist active, only selected customers are affected
        """
        chosen_customer = self.customer
        self.fs.parameters['whitelist']['is_active'] = True
        self.fs.parameters['whitelist']['customer_ids'] = [chosen_customer.id]
        self.fs.save()

        min_duration = 5

        # chosen customer
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=chosen_customer,
            cm_max_duration=9999,
            min_duration=min_duration,
        )
        self.assertEqual(result_max_duration, min_duration + self.additional_month)

        # non chosen customer
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=self.customer2,
            cm_max_duration=9999,
            min_duration=min_duration,
        )
        self.assertEqual(result_max_duration, min_duration + 5)

        # non customer
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=None,
            cm_max_duration=9999,
            min_duration=min_duration,
        )
        self.assertEqual(result_max_duration, min_duration + 5)

    def test_case_whitelist_active_with_no_customer_ids(self):
        """
        If whitelist active but no chosen customer is specified
        All customers follow default
        """
        self.fs.parameters['whitelist']['is_active'] = True
        self.fs.parameters['whitelist']['customer_ids'] = []
        self.fs.save()

        min_duration = 5

        # customer 1
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=self.customer,
            cm_max_duration=9999,
            min_duration=min_duration,
        )
        self.assertEqual(result_max_duration, min_duration + 5)

        # non chosen customer
        result_max_duration = calculate_max_duration_from_additional_month_param(
            customer=self.customer2,
            cm_max_duration=9999,
            min_duration=min_duration,
        )
        self.assertEqual(result_max_duration, min_duration + 5)


class TestCrossSellingProduct(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user_auth.auth_expiry_token.key)
        self.account_limit = AccountLimitFactory(account=self.account, available_limit=100000)
        parameters = {
            'cross_selling_message': "Ada yang perlu dibeli atau dibayar? Sekalian aja!",
            'available_limit_image': "https://statics.julo.co.id/loan/available_limit.png",
            'number_of_products': 3,
            'info': {
                1: {"message": "Cairkan dana tunai kapan dan di mana aja!", "deeplink": "julo://product_transfer_self"},
                2: {"message": "Lebih gampang kirim uang ke orang tersayang!", "deeplink": "julo://nav_inapp_product_transfer_other"},
                3: {"message": "Tinggal pilih berapa nominal atau GB!", "deeplink": "julo://pulsa_data"},
                4: {"message": "Bayar tagihan, komunikasi bisa jalan terus!", "deeplink": "julo://kartu_pasca_bayar"},
                5: {"message": "Isi saldo cepat, bayarnya nanti!", "deeplink": "julo://e-wallet"},
                6: {"message": "Bayar tangihan/ beli token sebelum padam!", "deeplink": "julo://listrik_pln"},
                7: {"message": "Bayar tagihan, berobat gak pake terhambat!", "deeplink": "julo://bpjs_kesehatan"},
                8: {"message": "Belanja di e-commerce, bayar lewat JULO aja!", "deeplink": "julo://e-commerce"},
                11: {"message": "Beli tiket nyaman, bayarnya ntar aja abis gajian!", "deeplink": "julo://train_ticket"},
                12: {"message": "Bayar tagihan, air mengalir lancar dari keran!", "deeplink": "julo://pdam_home_page"},
                13: {"message": "Tagihan terbayar, belajar tenang!", "deeplink": "julo://education_spp"},
                15: {"message": "Tagihan terbayar, berobat tenang!", "deeplink": "julo://healthcare_main_page"},
                19: {"message": "Transaksi jadi lebih sat set, tinggal scan!", "deeplink": "julo://qris_main_page"}
            },
            'products': [
                {'priority': 1, 'method': 5, 'minimum_limit': 100000, 'is_locked': False},
                {'priority': 2, 'method': 3, 'minimum_limit': 100000, 'is_locked': True},
                {'priority': 3, 'method': 8, 'minimum_limit': 300000, 'is_locked': True},
                {'priority': 4, 'method': 1, 'minimum_limit': 300000, 'is_locked': False},
                {'priority': 5, 'method': 6, 'minimum_limit': 100000, 'is_locked': False},
                {'priority': 6, 'method': 12, 'minimum_limit': 50000, 'is_locked': False},
            ]
        }
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.CROSS_SELLING_CONFIG,
            is_active=True,
            parameters=parameters,
        )

        if not TransactionMethod.objects.filter(id=TransactionMethodCode.LISTRIK_PLN.code).exists():
            self.transaction_method1 = TransactionMethodFactory(
                id=TransactionMethodCode.LISTRIK_PLN.code,
                method=TransactionMethodCode.LISTRIK_PLN
            )
        else:
            self.transaction_method1 = TransactionMethod.objects.get(id=TransactionMethodCode.LISTRIK_PLN.code)

        if not TransactionMethod.objects.filter(id=TransactionMethodCode.PDAM.code).exists():
            self.transaction_method2 = TransactionMethodFactory(
                id=TransactionMethodCode.PDAM.code,
                method=TransactionMethodCode.PDAM
            )
        else:
            self.transaction_method2 = TransactionMethod.objects.get(id=TransactionMethodCode.PDAM.code)

        if not TransactionMethod.objects.filter(id=TransactionMethodCode.DOMPET_DIGITAL.code).exists():
            self.transaction_method3 = TransactionMethodFactory(
                id=TransactionMethodCode.DOMPET_DIGITAL.code,
                method=TransactionMethodCode.DOMPET_DIGITAL
            )
        else:
            self.transaction_method3 = TransactionMethod.objects.get(id=TransactionMethodCode.DOMPET_DIGITAL.code)

    def test_get_cross_selling_products_with_fs_inactive(self):
        self.fs.is_active = False
        self.fs.save()
        url = '/api/loan/v1/cross-selling-products?transaction_type_code=1'
        response = self.client.get(url)
        data = response.json()['data']
        self.assertEqual(
            data,
            {}
        )

    def test_get_cross_selling_products_with_fs_active(self):
        self.fs.is_active = True
        self.fs.save()

        self.transaction_method1.foreground_icon_url = "https://julofiles-staging/static_test/listrik_pln.png"
        self.transaction_method1.fe_display_name = "Electricity"
        self.transaction_method1.save()

        self.transaction_method2.foreground_icon_url = "https://julofiles-staging/static_test/PDAM.png"
        self.transaction_method2.fe_display_name = "PDAM"
        self.transaction_method2.save()

        self.transaction_method3.foreground_icon_url = "https://julofiles-staging/static_test/Dompet.png"
        self.transaction_method3.fe_display_name = "Dompet"
        self.transaction_method3.save()

        self.account_limit.available_limit = 100000
        self.account_limit.save()

        url = '/api/loan/v1/cross-selling-products?transaction_type_code=1'
        response = self.client.get(url)
        expected_response_data = {
            "available_limit": "Rp100.000",
            "available_limit_image": "https://statics.julo.co.id/loan/available_limit.png",
            "cross_selling_message": "Ada yang perlu dibeli atau dibayar? Sekalian aja!",
            "recommendation_products": [
                {
                    "product_name": "Dompet",
                    "product_image": "https://julofiles-staging/static_test/Dompet.png",
                    "product_description": "Isi saldo cepat, bayarnya nanti!",
                    "product_deeplink": "julo://e-wallet",
                },
                {
                    "product_name": "Electricity",
                    "product_image": "https://julofiles-staging/static_test/listrik_pln.png",
                    "product_description": "Bayar tangihan/ beli token sebelum padam!",
                    "product_deeplink": "julo://listrik_pln",
                },
                {
                    "product_name": "PDAM",
                    "product_image": "https://julofiles-staging/static_test/PDAM.png",
                    "product_description": "Bayar tagihan, air mengalir lancar dari keran!",
                    "product_deeplink": "julo://pdam_home_page",
                },
            ]
        }
        data = response.json()['data']
        self.assertEqual(
            data,
            expected_response_data
        )

    def test_get_cross_selling_products_with_less_than_3_products(self):
        self.fs.is_active = True
        self.fs.save()

        self.transaction_method1.foreground_icon_url = "https://julofiles-staging/static_test/listrik_pln.png"
        self.transaction_method1.fe_display_name = "Electricity"
        self.transaction_method1.save()

        self.transaction_method2.foreground_icon_url = "https://julofiles-staging/static_test/PDAM.png"
        self.transaction_method2.fe_display_name = "PDAM"
        self.transaction_method2.save()

        self.transaction_method3.foreground_icon_url = "https://julofiles-staging/static_test/Dompet.png"
        self.transaction_method3.fe_display_name = "Dompet"
        self.transaction_method3.save()

        self.account_limit.available_limit = 50000
        self.account_limit.save()

        url = '/api/loan/v1/cross-selling-products?transaction_type_code=1'
        response = self.client.get(url)
        expected_response_data = {
            "available_limit": "Rp50.000",
            "available_limit_image": "https://statics.julo.co.id/loan/available_limit.png",
            "cross_selling_message": "Ada yang perlu dibeli atau dibayar? Sekalian aja!",
            "recommendation_products": [
                {
                    "product_name": "PDAM",
                    "product_image": "https://julofiles-staging/static_test/PDAM.png",
                    "product_description": "Bayar tagihan, air mengalir lancar dari keran!",
                    "product_deeplink": "julo://pdam_home_page",
                },
            ]
        }
        data = response.json()['data']
        self.assertEqual(
            data,
            expected_response_data
        )
