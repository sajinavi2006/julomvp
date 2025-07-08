import json
from datetime import datetime, timedelta

from freezegun import freeze_time
from unittest.mock import patch
from django.utils import timezone
from django.test import TestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.ana_api.tests.factories import CustomerSegmentationCommsFactory
from juloserver.apiv2.tests.test_apiv2_services import AuthUserFactory
from juloserver.cashback.tests.factories import CashbackEarnedFactory
from juloserver.cfs.tests.factories import CashbackBalanceFactory
from juloserver.customer_module.constants import CashbackBalanceStatusConstant
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.models import (
    CustomerWalletHistory,
    Payment,
    PaymentEvent,
    ApplicationHistory
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    CreditScoreFactory,
    CustomerFactory,
    LoanFactory,
    PartnerFactory,
    ProductLineFactory,
    StatusLookupFactory,
    ApplicationJ1Factory,
    CustomerWalletHistoryFactory,
    FeatureSettingFactory,
    PaymentFactory,
    WorkflowFactory,
    ApplicationUpgradeFactory,
)
from juloserver.julo.utils import display_rupiah
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod
from juloserver.promo.constants import (
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoCodeMessage,
    PromoCodeTypeConst,
    PromoCMSRedisConstant,
    PromoCodeTimeConst,
)
from juloserver.promo.exceptions import (
    NoBenefitForPromoCode,
    BenefitTypeDoesNotExist,
    NoPromoPageFound,
)
from juloserver.promo.services import (
    check_failed_criteria,
    check_if_loan_has_promo_benefit_type,
    check_promo_code_and_get_message,
    create_promo_code_usage,
    get_benefit_message,
    get_existing_promo_code,
    check_and_apply_promo_code_benefit,
    PromoCodeHandler,
    get_promo_code_benefit_tnc,
    is_eligible_promo_entry_page,
    fill_cache_promo_cms,
    check_and_apply_application_promo_code,
)

from juloserver.promo.tests.factories import (
    CriteriaControlListFactory,
    PromoCodeBenefitFactory,
    PromoCodeCriteriaFactory,
    PromoCodeFactory,
    PromoCodeLoanFactory,
    PromoCodeUsageFactory,
    PromoPageFactory,
    PromoEntryPageFeatureSetting,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.sales_ops.tests.factories import SalesOpsRScoreFactory, SalesOpsRMScoringFactory, \
    SalesOpsAccountSegmentHistoryFactory


class TestPromoCodeServices(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            referral_code='referral_code_test'
        )
        self.user2 = AuthUserFactory()
        self.customer2 = CustomerFactory(user=self.user2)
        self.account2 = AccountFactory(
            customer=self.customer2,
        )
        self.application2 = ApplicationFactory(
            customer=self.customer2,
            account=self.account2,
            product_line=self.product_line,
        )
        self.credit_score = CreditScoreFactory(
            score='A',
            application_id=self.application.id,
        )
        self.partner = PartnerFactory(name='batman')
        self.transaction_method = TransactionMethod.objects.get(
            pk=TransactionMethodCode.SELF.code,
        )
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            loan_amount=200000,
            transaction_method=self.transaction_method,
            account=self.account
        )
        self.fixed_cash_benefit = PromoCodeBenefitFactory(
            name="It's not you who are beneath --",
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value={
                'amount': 20000,
            },
        )
        self.installment_from_cashback_benefit = PromoCodeBenefitFactory(
            name="It's promo code installment from cashback benefit --",
            type=PromoCodeBenefitConst.CASHBACK_FROM_INSTALLMENT,
            value={
                'percent': 10,
                'max_cashback': 30000,
            },
        )
        self.loan_cashback_benefit = PromoCodeBenefitFactory(
            name='...but what you do --',
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={
                'percent': 10,
                'max_cashback': 30000,
            },
        )
        self.installment_benefit = PromoCodeBenefitFactory(
            name='...that defines you.',
            type=PromoCodeBenefitConst.INSTALLMENT_DISCOUNT,
            value={
                'percent': 10,
                'duration': 1,
            },
        )
        self.criterion_partner = PromoCodeCriteriaFactory(
            name="You're Spider-Man? -- No...",
            type=PromoCodeCriteriaConst.APPLICATION_PARTNER,
            value={
                 'partners': [self.partner.id],
            }
        )
        self.criterion_product_line = PromoCodeCriteriaFactory(
            name='Super-Man...? -- No!',
            type=PromoCodeCriteriaConst.PRODUCT_LINE,
            value={
                 'product_line_codes': [
                     self.product_line.product_line_code,
                 ],
            }
        )
        self.criterion_credit_score = PromoCodeCriteriaFactory(
            name='Joker? -- Jesus Christ, NO!',
            type=PromoCodeCriteriaConst.CREDIT_SCORE,
            value={
                 'credit_scores': ['A-', 'A'],
            }
        )
        self.criterion_transaction_method = PromoCodeCriteriaFactory(
            name='Ahh, I got it. -- ...Thank you.',
            type=PromoCodeCriteriaConst.TRANSACTION_METHOD,
            value={
                 'transaction_method_ids': [1],
            }
        )
        self.criterion_limit = PromoCodeCriteriaFactory(
            name='Catwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
            value={}
        )
        self.criterion_limit_per_promo_code = PromoCodeCriteriaFactory(
            name='Wonderwoman!',
            type=PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
            value={}
        )
        self.criterion_r_score = PromoCodeCriteriaFactory(
            name='Sike, it is Damian Wayne',
            type=PromoCodeCriteriaConst.R_SCORE,
            value={
                'r_scores': [1, 2, 3, 4, 5]
            }
        )
        # init whitelist criteria
        self.criterion_whitelist = PromoCodeCriteriaFactory(
            name="whitelist for premium customer",
            type=PromoCodeCriteriaConst.WHITELIST_CUSTOMERS,
            value={}
        )

        self.promo_code = PromoCodeFactory(
            promo_code_benefit=self.fixed_cash_benefit,
            criteria=[
            ],
            promo_code='BATMAN01',
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
            promo_code_daily_usage_count=1,
            promo_code_usage_count=1,
        )
        self.interest_benefit = PromoCodeBenefitFactory(
            name='...that defines you.',
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={
                'percent': 10,
                'duration': 1,
                'max_amount': 10000
            },
        )
        self.voucher_benefit = PromoCodeBenefitFactory(
            name='...that defines you.',
            type=PromoCodeBenefitConst.VOUCHER,
        )

    def test_get_existing_promo_code(self):
        code = get_existing_promo_code('BATMAN01')
        self.assertIsNotNone(code)

        code = get_existing_promo_code('JOKER')
        self.assertIsNone(code)

        #case insensitive
        code = get_existing_promo_code('baTmAn01')
        self.assertIsNotNone(code)

        # case promo_code has space in prefix/suffix
        code = get_existing_promo_code(' baTmAn01 ')
        self.assertIsNotNone(code)

        # case promo_code is type application (somehow)
        self.promo_code.type = PromoCodeTypeConst.APPLICATION
        self.promo_code.save()
        code = get_existing_promo_code('baTmAn01')
        self.assertIsNone(code)

    @freeze_time("2023-10-20 15:00:00")
    def test_get_available_time_promo_code(self):
        self.promo_code.start_date = datetime(2023, 10, 20, 19, 0, 0)
        self.promo_code.end_date = datetime(2023, 10, 20, 21, 0, 0)
        self.promo_code.save()

        is_valid, message = check_promo_code_and_get_message(self.promo_code, self.loan)
        self.assertFalse(is_valid)
        self.assertEqual(message, PromoCodeMessage.ERROR.INVALID)

        self.promo_code.start_date = datetime(2023, 10, 20, 10, 0, 0)
        self.promo_code.end_date = datetime(2023, 10, 20, 23, 0, 0)
        self.promo_code.save()
        is_valid, message = check_promo_code_and_get_message(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.assertTrue(is_valid)

    def test_get_fixed_cashback_benefit_message(self):
        self.fixed_cash_benefit.value['amount'] = 5000
        self.fixed_cash_benefit.save()
        expected = PromoCodeMessage.BENEFIT.CASHBACK.format(
            amount=display_rupiah(5000),
        )
        self.promo_code.promo_code_benefit = self.fixed_cash_benefit
        self.promo_code.save()
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

    def test_get_cashback_from_loan_amount_benefit_message(self):
        self.loan.loan_amount = 3000000
        self.loan_cashback_benefit.value['percent'] = 10
        self.loan_cashback_benefit.value['max_cashback'] = 400000
        self.loan.save()
        self.fixed_cash_benefit.save()

        expected = PromoCodeMessage.BENEFIT.CASHBACK.format(
            amount=display_rupiah(300000),
        )
        self.promo_code.promo_code_benefit = self.loan_cashback_benefit
        self.promo_code.save()
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )
        self.loan_cashback_benefit.value['max_cashback'] = 100000
        self.loan_cashback_benefit.save()

        expected = PromoCodeMessage.BENEFIT.CASHBACK.format(
            amount=display_rupiah(self.loan_cashback_benefit.value['max_cashback']),
        )
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

    def test_get_installment_from_cashback_benefit_message(self):
        self.installment_from_cashback_benefit.value['percent'] = 10
        self.installment_from_cashback_benefit.value['max_cashback'] = 400000
        self.installment_from_cashback_benefit.save()

        expected = PromoCodeMessage.BENEFIT.CASHBACK.format(
            amount=display_rupiah(4500),
        )
        self.promo_code.promo_code_benefit = self.installment_from_cashback_benefit
        self.promo_code.save()
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

        self.installment_from_cashback_benefit.value['max_cashback'] = 4400
        self.installment_from_cashback_benefit.save()
        expected = PromoCodeMessage.BENEFIT.CASHBACK.format(
            amount=display_rupiah(4400),
        )
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

    def test_get_installment_discount_benefit_message(self):
        # loan_amount = 200000, duration = 4
        self.installment_benefit.value['percent'] = 5
        self.installment_benefit.value['duration'] = 2
        self.installment_benefit.value['max_amount'] = 500000
        self.installment_benefit.save()

        expected = PromoCodeMessage.BENEFIT.INSTALLMENT_DISCOUNT.format(
            amount=display_rupiah(2200),
        )
        self.promo_code.promo_code_benefit = self.installment_benefit
        self.promo_code.save()
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

        self.installment_benefit.value['max_amount'] = 2000
        self.installment_benefit.save()
        expected = PromoCodeMessage.BENEFIT.INSTALLMENT_DISCOUNT.format(
            amount=display_rupiah(2000),
        )
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

    def test_get_interest_discount_benefit_message(self):
        self.interest_benefit.value['percent'] = 50
        self.interest_benefit.value['duration'] = 3
        self.interest_benefit.value['max_amount'] = 500000
        self.interest_benefit.save()
        expected = PromoCodeMessage.BENEFIT.INTEREST_DISCOUNT.format(
            amount=display_rupiah(7500),
        )
        self.promo_code.promo_code_benefit = self.interest_benefit
        self.promo_code.save()
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

        self.interest_benefit.value['max_amount'] = 2000
        self.interest_benefit.save()
        expected = PromoCodeMessage.BENEFIT.INTEREST_DISCOUNT.format(
            amount=display_rupiah(2000*3),
        )
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

    def test_get_voucher_benefit_message(self):
        self.promo_code.promo_code_benefit = self.voucher_benefit
        self.promo_code.save()
        expected = self.promo_code.promo_code
        self.assertEqual(
            expected,
            get_benefit_message(self.promo_code, self.loan),
        )

    def test_check_failed_credit_score(self):
        # credit score
        self.promo_code.criteria = [
            self.criterion_credit_score.id,
        ]
        self.criterion_credit_score.value['credit_scores'] = [
            'C',
            'B',
        ]
        self.promo_code.save()
        self.criterion_credit_score.save()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.CREDIT_SCORE,
        )

    def test_check_failed_transaction_method(self):
        self.promo_code.criteria = [
            self.criterion_transaction_method.id,
        ]
        self.criterion_transaction_method.value['transaction_method_ids'] = [
            TransactionMethodCode.OTHER,
        ]
        self.promo_code.save()
        self.criterion_transaction_method.save()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.TRANSACTION_METHOD,
        )

        self.criterion_transaction_method.value['transaction_method_ids'] = [
            TransactionMethodCode.SELF.code,
        ]
        self.criterion_transaction_method.save()
        self.assertIsNone(
            check_failed_criteria(
                loan=self.loan,
                promo_code=self.promo_code,
                application=self.application,
            )
        )

        # test case for transaction history
        criterion_transaction_method_val = self.criterion_transaction_method.value
        # case never transaction history
        self.loan.update_safely(loan_status_id=LoanStatusCodes.CURRENT)
        criterion_transaction_method_val['transaction_history'] = 'never'
        self.criterion_transaction_method.update_safely(value=criterion_transaction_method_val)
        self.promo_code.refresh_from_db()
        self.assertIsNotNone(
            check_failed_criteria(
                loan=self.loan,
                promo_code=self.promo_code,
                application=self.application,
            )
        )

        # case ever transaction history
        self.loan.update_safely(loan_status_id=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        criterion_transaction_method_val['transaction_history'] = 'ever'
        self.criterion_transaction_method.update_safely(value=criterion_transaction_method_val)
        self.promo_code.refresh_from_db()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.TRANSACTION_METHOD,
        )
        self.assertIsNotNone(
            check_failed_criteria(
                loan=self.loan,
                promo_code=self.promo_code,
                application=self.application,
            )
        )

    def test_check_failed_application_partner(self):
        self.promo_code.criteria = [
            self.criterion_partner.id,
        ]
        self.criterion_partner.value['partners'] = [
            self.partner.id,
        ]
        self.promo_code.save()
        self.criterion_partner.save()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.APPLICATION_PARTNER,
        )

        self.application.partner = self.partner
        self.application.save()
        self.assertIsNone(
            check_failed_criteria(
                loan=self.loan,
                promo_code=self.promo_code,
                application=self.application,
            )
        )

    def test_check_failed_product_line(self):
        self.promo_code.criteria = [
            self.criterion_product_line.id,
        ]
        self.criterion_product_line.value['product_line_codes'] = [
            ProductLineCodes.GRAB,
            ProductLineCodes.MTL1,
        ]
        self.promo_code.save()
        self.criterion_product_line.save()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.PRODUCT_LINE,
        )

        self.criterion_product_line.value['product_line_codes'] = [
            ProductLineCodes.J1,
        ]
        self.criterion_product_line.save()
        self.assertIsNone(
            check_failed_criteria(
                loan=self.loan,
                promo_code=self.promo_code,
                application=self.application,
            )
        )

    @patch.object(timezone, 'now')
    def test_check_failed_daily_limit_per_customer_1(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 19, 12, 25, 40)
        create_promo_code_usage(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.promo_code.criteria = [
            self.criterion_limit.id,
        ]
        self.criterion_limit.value['limit'] = 1
        self.criterion_limit.value['times'] = PromoCodeTimeConst.DAILY
        self.promo_code.save()
        self.criterion_limit.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
        )

        # case code used by other users:
        loan2 = LoanFactory(
            customer=self.customer2,
            application=self.application2,
            loan_amount=300000,
            transaction_method=self.transaction_method,
        )

        self.assertIsNone(
            check_failed_criteria(
                loan=loan2,
                promo_code=self.promo_code,
                application=self.application2,
            )
        )

    @patch.object(timezone, 'now')
    def test_check_failed_daily_limit_per_customer_2(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 19, 12, 25, 40)
        create_promo_code_usage(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.promo_code.criteria = [
            self.criterion_limit.id,
        ]
        self.criterion_limit.value['limit'] = 1
        self.criterion_limit.value['times'] = PromoCodeTimeConst.DAILY
        self.promo_code.save()
        self.criterion_limit.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
        )

        # case code is applied on the next day
        mock_now.return_value = datetime(2024, 2, 20, 12, 25, 40)
        self.promo_code.promo_code_daily_usage_count = 0
        self.promo_code.save()

        self.assertIsNone(
            check_failed_criteria(
                loan=self.loan,
                promo_code=self.promo_code,
                application=self.application,
            )
        )

    @patch.object(timezone, 'now')
    def test_check_failed_all_time_limit_per_customer_1(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 19, 12, 25, 40)
        create_promo_code_usage(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.promo_code.criteria = [
            self.criterion_limit.id,
        ]
        self.criterion_limit.value['limit'] = 1
        self.criterion_limit.value['times'] = PromoCodeTimeConst.ALL_TIME
        self.promo_code.save()
        self.criterion_limit.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
        )

        # case code used by other users:
        loan2 = LoanFactory(
            customer=self.customer2,
            application=self.application2,
            loan_amount=300000,
            transaction_method=self.transaction_method,
        )

        self.assertIsNone(
            check_failed_criteria(
                loan=loan2,
                promo_code=self.promo_code,
                application=self.application2,
            )
        )

    @patch.object(timezone, 'now')
    def test_check_failed_all_time_limit_per_customer_2(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 19, 12, 25, 40)
        create_promo_code_usage(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.promo_code.criteria = [
            self.criterion_limit.id,
        ]
        self.criterion_limit.value['limit'] = 1
        self.criterion_limit.value['times'] = PromoCodeTimeConst.ALL_TIME
        self.promo_code.save()
        self.criterion_limit.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
        )

        # case code is applied on the next day
        mock_now.return_value = datetime(2024, 2, 20, 12, 25, 40)
        self.promo_code.promo_code_daily_usage_count = 0
        self.promo_code.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER,
        )

    @patch.object(timezone, 'now')
    def test_check_failed_daily_limit_per_promo_code_1(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 19, 12, 25, 40)
        create_promo_code_usage(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.promo_code.criteria = [
            self.criterion_limit_per_promo_code.id,
        ]
        self.criterion_limit_per_promo_code.value['limit_per_promo_code'] = 1
        self.criterion_limit_per_promo_code.value['times'] = PromoCodeTimeConst.DAILY
        self.promo_code.save()
        self.criterion_limit_per_promo_code.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
        )

        # case code used by other users:
        loan2 = LoanFactory(
            customer=self.customer2,
            application=self.application2,
            loan_amount=300000,
            transaction_method=self.transaction_method,
        )

        failed = check_failed_criteria(
            loan=loan2,
            promo_code=self.promo_code,
            application=self.application2,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
        )

    @patch.object(timezone, 'now')
    def test_check_failed_daily_limit_per_promo_code_2(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 19, 12, 25, 40)
        create_promo_code_usage(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.promo_code.criteria = [
            self.criterion_limit_per_promo_code.id,
        ]
        self.criterion_limit_per_promo_code.value['limit_per_promo_code'] = 1
        self.criterion_limit_per_promo_code.value['times'] = PromoCodeTimeConst.DAILY
        self.promo_code.save()
        self.criterion_limit_per_promo_code.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
        )

        # case code is applied on the next day -> reset promo code daily usage count
        mock_now.return_value = datetime(2024, 2, 20, 12, 25, 40)
        self.promo_code.promo_code_daily_usage_count = 0
        self.promo_code.save()

        self.assertIsNone(
            check_failed_criteria(
                loan=self.loan,
                promo_code=self.promo_code,
                application=self.application,
            )
        )

    @patch.object(timezone, 'now')
    def test_check_failed_all_time_limit_per_promo_code_1(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 19, 12, 25, 40)
        create_promo_code_usage(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.promo_code.criteria = [
            self.criterion_limit_per_promo_code.id,
        ]
        self.criterion_limit_per_promo_code.value['limit_per_promo_code'] = 1
        self.criterion_limit_per_promo_code.value['times'] = PromoCodeTimeConst.ALL_TIME
        self.promo_code.save()
        self.criterion_limit_per_promo_code.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
        )

        # case code used by other users:
        loan2 = LoanFactory(
            customer=self.customer2,
            application=self.application2,
            loan_amount=300000,
            transaction_method=self.transaction_method,
        )

        failed = check_failed_criteria(
            loan=loan2,
            promo_code=self.promo_code,
            application=self.application2,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
        )

    @patch.object(timezone, 'now')
    def test_check_failed_all_time_limit_per_promo_code_2(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 19, 12, 25, 40)
        create_promo_code_usage(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.promo_code.criteria = [
            self.criterion_limit_per_promo_code.id,
        ]
        self.criterion_limit_per_promo_code.value['limit_per_promo_code'] = 1
        self.criterion_limit_per_promo_code.value['times'] = PromoCodeTimeConst.ALL_TIME
        self.promo_code.save()
        self.criterion_limit_per_promo_code.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
        )

        # case code is applied on the next day -> reset promo code daily usage count
        mock_now.return_value = datetime(2024, 2, 20, 12, 25, 40)
        self.promo_code.promo_code_daily_usage_count = 0
        self.promo_code.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.LIMIT_PER_PROMO_CODE,
        )

    def test_check_failed_minimum_loan_amount(self):
        promo_criteria = PromoCodeCriteriaFactory(
            type=PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT,
            value={'minimum_loan_amount': 200001}
        )
        self.promo_code.criteria = [
            promo_criteria.id,
        ]
        self.promo_code.save()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(PromoCodeCriteriaConst.MINIMUM_LOAN_AMOUNT, failed.type)

        expected_message = PromoCodeMessage.ERROR.MINIMUM_LOAN_AMOUNT.format(
            minimum_amount=display_rupiah(promo_criteria.value['minimum_loan_amount'])
        )
        ret_val = check_promo_code_and_get_message(self.promo_code, self.loan)
        self.assertFalse(ret_val[0])
        self.assertEqual(expected_message, ret_val[1])

    def test_check_failed_r_score(self):
        SalesOpsRScoreFactory(account_id=self.account.id, ranking=1)
        sales_ops_rm_score = SalesOpsRMScoringFactory(
            criteria='recency', is_active=True,
            bottom_percentile=80,
            top_percentile=100,
            score=6)
        account_segment_history = SalesOpsAccountSegmentHistoryFactory(
            account_id=self.account.id, r_score_id=sales_ops_rm_score.id
        )
        self.promo_code.criteria = [
            self.criterion_r_score.id,
        ]
        self.promo_code.save()

        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.R_SCORE,
        )

        sales_ops_rm_score.score = 5
        sales_ops_rm_score.save()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        failed_type = failed.type if failed else None
        self.assertNotEqual(
            failed_type,
            PromoCodeCriteriaConst.R_SCORE,
        )

        account_segment_history.r_score_id = None
        account_segment_history.save()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.R_SCORE,
        )

        account_segment_history.delete()
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.R_SCORE,
        )

    def test_check_failed_whitelist(self):
        self.promo_code.criteria = [self.criterion_whitelist.id]
        self.promo_code.save()

        # case failed
        CriteriaControlListFactory(
            promo_code_criteria=self.criterion_whitelist
        )
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertEqual(
            failed.type,
            PromoCodeCriteriaConst.WHITELIST_CUSTOMERS,
        )

        # case passed
        CriteriaControlListFactory(
            customer_id=self.customer.id,
            promo_code_criteria=self.criterion_whitelist
        )
        failed = check_failed_criteria(
            loan=self.loan,
            promo_code=self.promo_code,
            application=self.application,
        )
        self.assertIsNone(failed)

    def test_check_promo_code_and_get_message_exceptions(self):
        self.promo_code.promo_code_benefit = None
        self.promo_code.save()
        self.assertRaises(
            NoBenefitForPromoCode,
            check_promo_code_and_get_message,
            loan=self.loan,
            promo_code=self.promo_code,
        )

        self.promo_code.promo_code_benefit = self.fixed_cash_benefit
        self.fixed_cash_benefit.type = "heisenberg"
        self.fixed_cash_benefit.save()
        self.promo_code.save()

        self.fixed_cash_benefit.type = PromoCodeBenefitConst.FIXED_CASHBACK
        self.fixed_cash_benefit.save()
        self.promo_code.criteria = []
        self.promo_code.save()
        is_valid, message = check_promo_code_and_get_message(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.assertEqual(is_valid, True)

        now = timezone.localtime(timezone.now())
        self.promo_code.end_date = now - timedelta(days=1)

        is_valid, message = check_promo_code_and_get_message(
            loan=self.loan,
            promo_code=self.promo_code,
        )
        self.assertEqual(is_valid, False)
        self.assertEqual(message, PromoCodeMessage.ERROR.INVALID)

    def test_get_benefit_tnc_error(self):
        # error since we haven't make a PromoPage
        self.assertRaises(
            NoPromoPageFound,
            get_promo_code_benefit_tnc,
            self.promo_code,
        )

        self.promo_code.promo_benefit = PromoCodeBenefitConst.FIXED_CASHBACK
        self.promo_code.start_date = timezone.localtime(
            datetime.strptime('01-01-1999', '%d-%m-%Y'),
        )
        self.promo_code.end_date = timezone.localtime(
            datetime.strptime('01-02-1999', '%d-%m-%Y'),
        )
        self.promo_code.save()

        page = PromoPageFactory.tnc_cashback()
        page.content = "start_date:{start_date} end_date:{end_date}"
        page.save()

        result = get_promo_code_benefit_tnc(self.promo_code)

        self.assertIn(
            "start_date:01-01-1999 end_date:01-02-1999",
            result,
        )

    @patch('juloserver.promo.services.get_used_promo_code_for_loan')
    def test_check_if_loan_has_promo_benefit_type(self, mock_get_used_promo_code):
        promo_code_usage = PromoCodeUsageFactory(
            loan_id=self.loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=self.promo_code,
        )
        interest_discount_benefit = PromoCodeBenefitFactory(
            name='just testing over here',
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={},
        )
        promo_code_usage.promo_code_benefit = interest_discount_benefit
        promo_code_usage.save()

        mock_get_used_promo_code.return_value = promo_code_usage
        result = check_if_loan_has_promo_benefit_type(self.loan, PromoCodeBenefitConst.INTEREST_DISCOUNT)
        self.assertTrue(result)

    def test_check_minimum_tenor(self):
        min_tenor_criteria = PromoCodeCriteriaFactory(
            name='Min tenor criteria',
            type=PromoCodeCriteriaConst.MINIMUM_TENOR,
            value={'minimum_tenor': 4}
        )
        min_tenor_criteria.save()
        self.promo_code.criteria = [min_tenor_criteria.id]
        self.promo_code.save()
        self.promo_code.refresh_from_db()
        self.loan.update_safely(loan_duration=3)

        is_valid, message = check_promo_code_and_get_message(self.promo_code, self.loan)
        self.assertFalse(is_valid)
        self.assertEqual(message, PromoCodeMessage.ERROR.MINIMUM_TENOR.format(minimum_tenor=4))

        self.loan.update_safely(loan_duration=4)
        is_valid, message = check_promo_code_and_get_message(self.promo_code, self.loan)
        self.assertTrue(is_valid)
        self.assertNotEqual(message, PromoCodeMessage.ERROR.MINIMUM_TENOR.format(minimum_tenor=4))

        self.loan.update_safely(loan_duration=5)
        is_valid, message = check_promo_code_and_get_message(self.promo_code, self.loan)
        self.assertTrue(is_valid)
        self.assertNotEqual(message, PromoCodeMessage.ERROR.MINIMUM_TENOR.format(minimum_tenor=4))

    def test_check_failed_whitelist_message(self):
        self.promo_code.criteria = [self.criterion_whitelist.id]
        self.promo_code.save()

        # case failed
        CriteriaControlListFactory(
            promo_code_criteria=self.criterion_whitelist
        )
        is_valid, message = check_promo_code_and_get_message(
            promo_code=self.promo_code,
            loan=self.loan,
        )
        self.assertFalse(is_valid)
        self.assertEqual(
            message,
            PromoCodeMessage.ERROR.WHITELIST_CUSTOMER,
        )

        # case passed
        CriteriaControlListFactory(
            customer_id=self.customer.id,
            promo_code_criteria=self.criterion_whitelist
        )
        is_valid, message = check_promo_code_and_get_message(
            promo_code=self.promo_code,
            loan=self.loan,
        )
        self.assertTrue(is_valid)
        self.assertIsNotNone(message)

    def test_check_and_apply_application_promo_code(self):
        is_valid = check_and_apply_application_promo_code(self.loan)
        self.assertFalse(is_valid)

    def test_check_failed_churn_day(self):
        cust_seg_comms = CustomerSegmentationCommsFactory(
            customer_id=self.customer.id,
            extra_params={'churn_day': 7},
        )
        churn_day_criteria = PromoCodeCriteriaFactory(
            name='Churn day criteria',
            type=PromoCodeCriteriaConst.CHURN_DAY,
            value={'min_churn_day': 5, 'max_churn_day': 10}
        )

        self.promo_code.criteria = [churn_day_criteria.id]
        self.promo_code.save()
        is_valid, message = check_promo_code_and_get_message(
            promo_code=self.promo_code,
            loan=self.loan,
        )
        self.assertTrue(is_valid)

        # Failed case: customer is not in whitelist
        cust_seg_comms.customer_id = 111
        cust_seg_comms.save()
        is_valid, message = check_promo_code_and_get_message(
            promo_code=self.promo_code,
            loan=self.loan,
        )
        self.assertFalse(is_valid)
        self.assertEqual(message, PromoCodeMessage.ERROR.CHURN_DAY)

        # Failed case: churn day not in range
        cust_seg_comms.customer_id = self.customer.id
        cust_seg_comms.extra_params['churn_day'] = 11
        cust_seg_comms.save()
        is_valid, message = check_promo_code_and_get_message(
            promo_code=self.promo_code,
            loan=self.loan,
        )
        self.assertFalse(is_valid)
        self.assertEqual(message, PromoCodeMessage.ERROR.CHURN_DAY)

        # Failed case: churn day not in range
        cust_seg_comms.customer_id = self.customer.id
        cust_seg_comms.extra_params['churn_day'] = 7
        cust_seg_comms.save()
        churn_day_criteria.value['min_churn_day'] = 7
        churn_day_criteria.value['max_churn_day'] = 7
        churn_day_criteria.save()
        is_valid, message = check_promo_code_and_get_message(
            promo_code=self.promo_code,
            loan=self.loan,
        )
        self.assertTrue(is_valid)

    @patch.object(timezone, 'now')
    def test_check_failed_application_approved_day(self, mock_now):
        mock_now.return_value = datetime(2024, 2, 11, 12, 25, 40)
        application_approved_day_criteria = PromoCodeCriteriaFactory(
            name='Application approved day criteria',
            type=PromoCodeCriteriaConst.APPLICATION_APPROVED_DAY,
            value={'min_days_before': 5, 'max_days_before': 10}
        )
        app_hist = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            status_new=ApplicationStatusCodes.LOC_APPROVED
        )
        app_hist.save()
        ApplicationHistory.objects.filter(id=app_hist.id).update(cdate=datetime(2024, 2, 1, 12, 25, 40))

        self.promo_code.criteria = [application_approved_day_criteria.id]
        self.promo_code.save()
        criterion = check_failed_criteria(
            promo_code=self.promo_code,
            loan=self.loan,
            application=self.application
        )
        self.assertIsNone(criterion)

        ApplicationHistory.objects.filter(id=app_hist.id).update(cdate=datetime(2024, 2, 6, 12, 25, 40))
        criterion = check_failed_criteria(
            promo_code=self.promo_code,
            loan=self.loan,
            application=self.application
        )
        self.assertIsNone(criterion)

        ApplicationHistory.objects.filter(id=app_hist.id).update(status_new=ApplicationStatusCodes.DIGISIGN_FACE_FAILED)
        criterion = check_failed_criteria(
            promo_code=self.promo_code,
            loan=self.loan,
            application=self.application
        )
        self.assertIsNotNone(criterion)
        self.assertEqual(criterion.id, application_approved_day_criteria.id)

        ApplicationHistory.objects.filter(id=app_hist.id).update(cdate=datetime(2024, 2, 7, 12, 25, 40))
        criterion = check_failed_criteria(
            promo_code=self.promo_code,
            loan=self.loan,
            application=self.application
        )
        self.assertIsNotNone(criterion)
        self.assertEqual(criterion.id, application_approved_day_criteria.id)

        app_hist_1 = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            status_new=ApplicationStatusCodes.LOC_APPROVED
        )
        app_hist_1.save()
        ApplicationHistory.objects.filter(id=app_hist_1.id).update(cdate=datetime(2024, 2, 3, 12, 25, 40))
        criterion = check_failed_criteria(
            promo_code=self.promo_code,
            loan=self.loan,
            application=self.application
        )
        self.assertIsNone(criterion)

        ApplicationHistory.objects.filter(id__in=[app_hist.id, app_hist_1.id]).delete()
        criterion = check_failed_criteria(
            promo_code=self.promo_code,
            loan=self.loan,
            application=self.application
        )
        self.assertIsNotNone(criterion)
        self.assertEqual(criterion.id, application_approved_day_criteria.id)


class TestCheckAndApplyPromoCodeBenefit(TestCase):
    def setUp(self):
        self.loan = LoanFactory(loan_status=StatusLookupFactory(status_code=220))
        self.customer = self.loan.customer
        self.application = ApplicationJ1Factory(customer=self.customer)

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=StatusLookupFactory(status_code=190)
        )
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application.pk,
            application_id_first_approval=self.application.pk,
            is_upgrade=1,
        )

        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=StatusLookupFactory(status_code=220),
                                disbursement_id=self.disbursement.id)
        self.account_payment.refresh_from_db()
        self.payment1 = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
                payment_number=1
            )
        self.payment2 = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
                payment_number=2
            )


        # Cashback balance is created during 190
        self.cashback_balance = CashbackBalanceFactory(
            customer=self.customer,
            status=CashbackBalanceStatusConstant.UNFREEZE,
            cashback_balance=5000,
            cashback_accruing=3000
        )
        CustomerWalletHistoryFactory(
            wallet_balance_available=5000,
            wallet_balance_accruing=3000,
            customer=self.customer,
            application=self.application,
            latest_flag=True,
            cashback_earned=CashbackEarnedFactory(current_balance=5000, verified=True)
        )

        # setup for test_max_amount_from_interest_discount
        self.loan2 = LoanFactory(
            account=self.account, customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=500000,
            installment_amount=206000,
            loan_duration=3,
            loan_disbursement_amount=465000,
            first_installment_amount=186000
        )
        payments_data = [{
            'loan': self.loan2,
            'due_amount': 182133,
            'paid_amount': 0,
            'installment_interest': 20000,
            'installment_principal': 166000,
            'payment_number': 1,
        }, {
            'loan': self.loan2,
            'due_amount': 198133,
            'paid_amount': 0,
            'installment_interest': 40000,
            'installment_principal': 16600,
            'payment_number': 2,
        }, {
            'loan': self.loan2,
            'due_amount': 198134,
            'paid_amount': 0,
            'installment_interest': 40000,
            'installment_principal': 166000,
            'payment_number': 3,
        }]
        for payment, updated_payment in zip(list(self.loan2.payment_set.all().order_by('payment_number')), payments_data):
            payment.update_safely(**updated_payment)

    @classmethod
    def setUpTestData(cls):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.CASHBACK_EXPIRED_CONFIGURATION,
            parameters={'months': 1},
            is_active=True
        )

    def test_raise_exception_not_active_loan(self):
        promo_code = PromoCodeLoanFactory()

        for status_code in LoanStatusCodes.loan_status_not_active():
            loan_status = StatusLookupFactory(status_code=status_code)
            loan = LoanFactory(loan_status=loan_status)
            PromoCodeUsageFactory(loan_id=loan.id, promo_code=promo_code)

            with self.assertRaises(Exception) as cm:
                check_and_apply_promo_code_benefit(loan)

            expected_exception = Exception(
                'Cannot applied promo code because the loan is not active',
                {
                    'loan_id': loan.id,
                    'loan_status': status_code,
                }
            )
            self.assertEquals(str(expected_exception), str(cm.exception))

    def test_fixed_cashback_promo_code(self):
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value={'amount': 10000}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit
        )
        promo_code_usage = PromoCodeUsageFactory(
            loan_id=self.loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=promo_code,
            version='v1',
        )

        check_and_apply_promo_code_benefit(self.loan)

        promo_code_usage.refresh_from_db()
        self.assertEqual(10000, promo_code_usage.benefit_amount)
        self.assertEqual(promo_code_benefit.id, promo_code_usage.promo_code_benefit_id)
        self.assertIsNotNone(promo_code_usage.applied_at)
        self.assertIsNone(promo_code_usage.cancelled_at)

        self.cashback_balance.refresh_from_db()
        self.assertEqual(15000, self.cashback_balance.cashback_balance)
        self.assertEqual('unfreeze', self.cashback_balance.status)

        customer_wallet_history = CustomerWalletHistory.objects.filter(
            application=self.application,
            loan=self.loan,
            customer=self.customer,
        ).last()
        self.assertEquals('promo_code:TESTPROMO', customer_wallet_history.change_reason)
        self.assertEquals(15000, customer_wallet_history.wallet_balance_available)
        self.assertEquals(13000, customer_wallet_history.wallet_balance_accruing)
        self.assertEquals(5000, customer_wallet_history.wallet_balance_available_old)
        self.assertTrue(customer_wallet_history.latest_flag)

        cashback_earned = customer_wallet_history.cashback_earned
        self.assertIsNotNone(cashback_earned)
        self.assertEquals(10000, cashback_earned.current_balance)

    def test_cashback_from_loan_amount_promo_code(self):
        loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
            loan_amount=111000,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={'percent': 1, 'max_cashback': 10000},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit
        )
        promo_code_usage = PromoCodeUsageFactory(
            loan_id=loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=promo_code,
            version='v1',
        )

        check_and_apply_promo_code_benefit(loan)

        promo_code_usage.refresh_from_db()
        self.assertEqual(1100, promo_code_usage.benefit_amount)
        self.assertEqual(promo_code_benefit.id, promo_code_usage.promo_code_benefit_id)
        self.assertIsNotNone(promo_code_usage.applied_at)
        self.assertIsNone(promo_code_usage.cancelled_at)
        expected_configuration_log = {
            'promo_code_benefit': {
                'id': promo_code_usage.promo_code_benefit_id,
                'type': 'cashback_from_loan_amount',
                'value': {'percent': 1, 'max_cashback': 10000}
            }
        }
        self.assertEqual(promo_code_usage.configuration_log, expected_configuration_log)

        self.cashback_balance.refresh_from_db()
        self.assertEqual(6100, self.cashback_balance.cashback_balance)
        self.assertEqual('unfreeze', self.cashback_balance.status)

        customer_wallet_history = CustomerWalletHistory.objects.filter(
            application=self.application,
            loan=loan,
            customer=self.customer,
        ).last()
        self.assertEquals('promo_code:TESTPROMO', customer_wallet_history.change_reason)
        self.assertEquals(6100, customer_wallet_history.wallet_balance_available)
        self.assertEquals(4100, customer_wallet_history.wallet_balance_accruing)
        self.assertEquals(5000, customer_wallet_history.wallet_balance_available_old)
        self.assertTrue(customer_wallet_history.latest_flag)

        cashback_earned = customer_wallet_history.cashback_earned
        self.assertIsNotNone(cashback_earned)
        self.assertEquals(1100, cashback_earned.current_balance)

    def test_get_cashback_from_loan_amount_benefit_amount_round_up(self):
        loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
            loan_amount=115000,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={'percent': 1, 'max_cashback': 10000},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler.get_cashback_from_loan_amount_benefit_amount(loan=loan)

        self.assertEqual(1200, amount)

    def test_get_cashback_from_loan_amount_benefit_amount_round_down(self):
        loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
            loan_amount=111149,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={'percent': 1, 'max_cashback': 10000},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler.get_cashback_from_loan_amount_benefit_amount(loan=loan)

        self.assertEqual(1100, amount)

    def test_get_cashback_from_loan_amount_benefit_amount_max_cashback(self):
        loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
            loan_amount=999999,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={'percent': 10, 'max_cashback': 10000},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler.get_cashback_from_loan_amount_benefit_amount(loan=loan)

        self.assertEqual(10000, amount)

    def test_get_cashback_from_installment_benefit(self):
        loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
            loan_amount=999999,
        )
        loan.payment_set.filter(payment_number=1).update(installment_principal=1000000)
        loan.save()
        # Test Case 1: The calculation is above the max_cashback
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.CASHBACK_FROM_INSTALLMENT,
            value={'percent': 10, 'max_cashback': 10000},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler.get_cashback_from_installment_benefit_amount(loan=loan)
        self.assertEqual(10000, amount)

        # Test Case 1: The calculation is below the max_cashback
        promo_code_benefit.value = {'percent': 15, 'max_cashback': 5000000}
        promo_code_benefit.save()
        promo_code.promo_code_benefit = promo_code_benefit
        promo_code.save()
        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler.get_cashback_from_installment_benefit_amount(loan=loan)
        self.assertEqual(150000, amount)

    def test_get_cashback_from_interest_discount(self):
        loan = self.loan
        loan.loan_amount = 3000000
        loan.payment_set.filter(payment_number__in=[1,2]).update(
            installment_interest=30000,
            due_amount=600000,
            account_payment=self.account_payment)
        loan.save()



        # Test Case 1: The calculation is above the max_cashback
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 10, 'duration': 2},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMOINTEREST',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler._get_and_process_interest_discount_benefit(loan=loan)
        self.assertEqual(6000, amount)

    # Testcase 1: apply max_amount all duration
    def test_max_amount_from_interest_discount_tc1(self):
        loan = self.loan2
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 20, 'duration': 3, 'max_amount': 3000}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMOINTERRESTMAX1',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler._get_and_process_interest_discount_benefit(loan=loan)
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')
        self.assertEqual(3, len(payments))
        payment1, payment2, payment3 = payments
        self.assertEqual(3000, payment1.paid_amount)
        self.assertEqual(3000, payment1.paid_interest)
        self.assertEqual(3000, payment2.paid_amount)
        self.assertEqual(3000, payment2.paid_interest)
        self.assertEqual(3000, payment3.paid_amount)
        self.assertEqual(3000, payment3.paid_interest)
        self.assertEqual(9000, amount)

        payment_events = PaymentEvent.objects.filter(payment__in=payments, event_type='waive_interest')
        self.assertEqual(3, payment_events.count())
        account_transaction = payment_events[0].account_transaction
        self.assertIsNotNone(account_transaction)
        self.assertEqual(9000, account_transaction.towards_interest)
        self.assertEqual(9000, account_transaction.transaction_amount)

    # Testcase 2 apply max_amount for partial duration
    def test_max_amount_from_interest_discount_tc2(self):
        loan = self.loan2
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 20, 'duration': 3, 'max_amount': 4001}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMOINTERRESTMAX2',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler._get_and_process_interest_discount_benefit(loan=loan)
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')
        self.assertEqual(3, len(payments))

        payment1, payment2, payment3 = payments
        self.assertEqual(4000, payment1.paid_amount)
        self.assertEqual(4000, payment1.paid_interest)
        self.assertEqual(4001, payment2.paid_amount)
        self.assertEqual(4001, payment2.paid_interest)
        self.assertEqual(4001, payment3.paid_amount)
        self.assertEqual(4001, payment3.paid_interest)
        self.assertEqual(12002, round(amount))

        payment_events = PaymentEvent.objects.filter(payment__in=payments, event_type='waive_interest')
        self.assertEqual(3, payment_events.count())
        account_transaction = payment_events[0].account_transaction
        self.assertIsNotNone(account_transaction)
        self.assertEqual(12002, account_transaction.towards_interest)
        self.assertEqual(12002, account_transaction.transaction_amount)

    # Testcase 3 dont apply max_amount all duration, because max_amount is the highest
    def test_max_amount_from_interest_discount_tc3(self):
        loan = self.loan2
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 20, 'duration': 3, 'max_amount': 8001}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMOINTERRESTMAX2',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler._get_and_process_interest_discount_benefit(loan=loan)
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')
        self.assertEqual(3, len(payments))

        payment1, payment2, payment3 = payments
        self.assertEqual(4000, payment1.paid_amount)
        self.assertEqual(4000, payment1.paid_interest)
        self.assertEqual(8000, payment2.paid_amount)
        self.assertEqual(8000, payment2.paid_interest)
        self.assertEqual(8000, payment3.paid_amount)
        self.assertEqual(8000, payment3.paid_interest)
        self.assertEqual(20000, round(amount))

        payment_events = PaymentEvent.objects.filter(payment__in=payments, event_type='waive_interest')
        self.assertEqual(3, payment_events.count())
        account_transaction = payment_events[0].account_transaction
        self.assertIsNotNone(account_transaction)
        self.assertEqual(20000, account_transaction.towards_interest)
        self.assertEqual(20000, account_transaction.transaction_amount)

    def test_max_amount_from_interest_discount_without_max_amount(self):
        loan = self.loan2
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 20, 'duration': 3,}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMOINTERRESTMAX2',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler._get_and_process_interest_discount_benefit(loan=loan)
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')
        self.assertEqual(3, len(payments))

        payment1, payment2, payment3 = payments
        self.assertEqual(4000, payment1.paid_amount)
        self.assertEqual(4000, payment1.paid_interest)
        self.assertEqual(8000, payment2.paid_amount)
        self.assertEqual(8000, payment2.paid_interest)
        self.assertEqual(8000, payment3.paid_amount)
        self.assertEqual(8000, payment3.paid_interest)
        self.assertEqual(20000, round(amount))

        payment_events = PaymentEvent.objects.filter(payment__in=payments, event_type='waive_interest')
        self.assertEqual(3, payment_events.count())
        account_transaction = payment_events[0].account_transaction
        self.assertIsNotNone(account_transaction)
        self.assertEqual(20000, account_transaction.towards_interest)
        self.assertEqual(20000, account_transaction.transaction_amount)

    def test_rounding_interest_discount_with_promo_code(self):
        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            loan_amount=10_000_000,
            loan_duration=3,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 50, 'duration': 1,}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTROUNDINGPROMOCODE1',
            promo_code_benefit=promo_code_benefit
        )

        handler = PromoCodeHandler(promo_code=promo_code)
        amount = handler._get_and_process_interest_discount_benefit(loan=loan)
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')
        self.assertEqual(3, len(payments))

        payment1 = payments[0]
        self.assertEqual(166_666, payment1.paid_amount)
        self.assertEqual(166_666, payment1.paid_interest)
        self.assertEqual(3_166_667, payment1.due_amount)
        self.assertEqual(166_666, round(amount))

        payment_events = PaymentEvent.objects.filter(payment__in=payments, event_type='waive_interest')
        self.assertEqual(1, payment_events.count())
        account_transaction = payment_events[0].account_transaction
        self.assertIsNotNone(account_transaction)
        self.assertEqual(166_666, account_transaction.towards_interest)
        self.assertEqual(166_666, account_transaction.transaction_amount)

    @patch('juloserver.promo.services.execute_after_transaction_safely')
    def test_moengage_send_event_promo_code_benefit_220_status(
        self,
        mock_execute_transaction_safely
    ):
        loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=220),
            customer=self.customer,
            loan_amount=111000,
        )
        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.FIXED_CASHBACK,
            value={'amount': 10000}
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMO',
            promo_code_benefit=promo_code_benefit
        )
        create_promo_code_usage(
            loan=loan,
            promo_code=promo_code,
            version='v1',
        )

        check_and_apply_promo_code_benefit(loan)
        mock_execute_transaction_safely.assert_called_once()


class TestPromoEntryPage(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user,
            fullname='customer name 1'
        )
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.feature_setting = PromoEntryPageFeatureSetting()

    def test_fs_turn_off(self):
        self.feature_setting.update_safely(is_active=False)
        is_valid = is_eligible_promo_entry_page(self.application)
        self.assertEqual(is_valid, False)

    def test_is_eligible_for_promo_entry_page(self):
        self.application.update_safely(application_status_id=190)
        result = self.application.eligible_for_promo_entry_page
        self.assertTrue(result)

        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        result = self.application.eligible_for_promo_entry_page
        self.assertFalse(result)

        # julo turbo
        self.application.update_safely(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        )
        self.assertTrue(self.application.eligible_for_promo_entry_page)


class TestFetchPromoCMS(TestCase):
    def setUp(self):
        self.feature_setting = PromoEntryPageFeatureSetting()
        self.fake_redis = MockRedisHelper()

    @patch('juloserver.promo.services.get_promo_cms_client')
    @patch('juloserver.promo.services.get_redis_client')
    def test_fetch_promo_cms(self, mock_get_client, mock_get_promo_cms_client):
        mock_get_client.return_value = self.fake_redis
        mock_value = {
            "header": {
                "info_title": "Cek Info Menarik Untukmu!",
                "banner": "banner.png",
                "info_link": "https://www.julo.co.id/",
                "content_type": "image"
            },
            "promo_codes": [
                {
                    "general": {
                        "nid": 55,
                        "promo_code": "habunkan",
                        "promo_type": "undian",
                        "promo_image": "https://cms-static.julo.co.id/media/650d02c85b123.png",
                        "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!",
                        "start_date": "2022-09-30 00:00:00",
                        "end_date": "2022-09-30 00:00:00",
                        "description": "promo description",
                    },
                    "detail": {
                        "info_alert": "Jika kamu gagal menggunakan kode promo HIDUPKAN",
                        "detail_contents": [{
                            "order_number": 1,
                            "title": "promo title",
                            "content": "content could be HTML",
                            "icon": "image link"
                        }],
                        "share_promo": {
                            "title": "share title",
                            "description": "description",
                            "url": "add url here"
                        }
                    }
                }
            ]
        }
        mock_get_promo_cms_client.return_value.promo_list.return_value = mock_value
        fill_cache_promo_cms()
        expected_response = {
            "header": {
                "info_title": "Cek Info Menarik Untukmu!",
                "banner": "banner.png",
                "info_link": "https://www.julo.co.id/",
                "content_type": "image"
            },
            "promo_codes": [
                {
                    "nid": 55,
                    "promo_type": "undian",
                    "promo_image": "https://cms-static.julo.co.id/media/650d02c85b123.png",
                    "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!",
                    "start_date": "2022-09-30 00:00:00",
                    "end_date": "2022-09-30 00:00:00",
                    "promo_code": "habunkan",
                    "description": "promo description",
                }
            ]
        }
        self.assertEqual(
            json.loads(self.fake_redis.get(PromoCMSRedisConstant.PROMO_CMS_LIST)),
            expected_response
        )
        expected_response_detail = {
            "general": {
                "nid": 55,
                "promo_code": "habunkan",
                "promo_type": "undian",
                "promo_image": "https://cms-static.julo.co.id/media/650d02c85b123.png",
                "promo_title": "Pakai Kode Promo HIDUPKAN, Dapatkan Cashback Rp 20.002!",
                "start_date": "2022-09-30 00:00:00",
                "end_date": "2022-09-30 00:00:00",
                "description": "promo description",
            },
            "detail": {
                "info_alert": "Jika kamu gagal menggunakan kode promo HIDUPKAN",
                "detail_contents": [{
                    "order_number": 1,
                    "title": "promo title",
                    "content": "content could be HTML",
                    "icon": "image link"
                }],
                "share_promo": {
                    "title": "share title",
                    "description": "description",
                    "url": "add url here"
                }
            }
        }
        self.assertEqual(
            json.loads(self.fake_redis.get(PromoCMSRedisConstant.PROMO_CMS_DETAIL.format(55))),
            expected_response_detail
        )


class TestPromoCodeUsage(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.application = ApplicationJ1Factory(account=self.account, customer=self.customer)
        TransactionMethodFactory(
            id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
            method=TransactionMethodCode.BALANCE_CONSOLIDATION.name,
            fe_display_name='Balance Consolidation'
        )
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            transaction_method_id=TransactionMethodCode.BALANCE_CONSOLIDATION.code,
        )
        self.cashback_benefit = PromoCodeBenefitFactory(
            name="BBSCCL",
            type=PromoCodeBenefitConst.CASHBACK_FROM_LOAN_AMOUNT,
            value={"percent": 10, "max_cashback": 100000},
        )
        self.promo_code = PromoCodeFactory(
            promo_code_benefit=self.cashback_benefit,
            criteria=[],
            promo_code='BBSCCL',
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
            promo_code_daily_usage_count=1,
            promo_code_usage_count=1,
        )
        self.promo_code_usage = PromoCodeUsageFactory(
            loan_id=self.loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=self.promo_code,
            benefit_amount=10000,
            configuration_log={
                'promo_code_benefit': {
                    'id': self.cashback_benefit.id,
                    'type': self.cashback_benefit.type,
                    'value': self.cashback_benefit.value,
                }
            },
            applied_at=datetime(2024, 4, 30, 13, 0, 0),
        )

    def test_get_promo_code_usage(self):
        promo_code_usage_str = self.loan.get_promo_code_usage
        self.assertEqual(
            promo_code_usage_str,
            'BBSCCL, cashback_from_loan_amount, Rp 10.000'
        )
