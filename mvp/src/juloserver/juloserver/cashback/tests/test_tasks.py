
import pytest
from datetime import datetime, timedelta, date

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from django.test.testcases import TestCase

from django.utils import timezone
from unittest.mock import patch

from factory import Iterator

from django.test.testcases import TestCase
import pytest

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory, AccountLimitFactory,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.cashback.constants import (
    CashbackChangeReason,
    FeatureNameConst as CashbackFeatureNameConst
)
from juloserver.cashback.models import CashbackEarned
from juloserver.cashback.tasks import (
    system_used_on_payment_dpd,
    use_cashback_payment_and_expiry_cashback,
    use_cashback_payment_and_expiry_cashback_by_batch,
    unfreeze_referral_cashback,
    inject_cashback_promo_task,
)
from juloserver.cashback.tests.factories import CashbackEarnedFactory
from juloserver.cfs.tests.factories import CfsActionPointsFactory, CashbackBalanceFactory
from juloserver.customer_module.constants import CashbackBalanceStatusConstant
from juloserver.customer_module.models import CashbackBalance
from juloserver.julo.models import CustomerWalletHistory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    PaymentStatusCodes,
    LoanStatusCodes
)
from juloserver.julo.tests.factories import (
    CustomerWalletHistoryFactory,
    CustomerFactory,
    ApplicationFactory,
    StatusLookupFactory,
    PaymentFactory,
    AccountingCutOffDateFactory,
    CleanLoanFactory,
    ProductLineFactory,
    FeatureSettingFactory,
    ReferralSystemFactory,
    WorkflowFactory,
    LoanFactory,
    RefereeMappingFactory,
    LoanHistoryFactory,
)
from juloserver.promo.tests.factories import (
    PromoCodeFactory,
    PromoCodeBenefitFactory,
    PromoCodeUsageFactory,
)
from juloserver.promo.constants import PromoCodeTypeConst, PromoCodeBenefitConst
from juloserver.referral.tests.factories import (
    ReferralBenefitHistoryFactory,
    ReferralBenefitFactory,
    ReferralPersonTypeConst,
)
from juloserver.referral.constants import ReferralBenefitConst
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo.constants import WorkflowConst


def dummy_wallet_histories_data(application):
    wallet_histories = [
        {
            'wallet_balance_available': 18900,
            'change_reason': 'loan_paid_off',
            'cashback_earned': {
                'current_balance': 18900,
                'expired_on_date': datetime(2022, 12, 31),
                'verified': True,
            }
        },
        {
            'wallet_balance_available': 38900,
            'change_reason': 'cashback_over_paid',
            'cashback_earned': {
                'current_balance': 20000,
                'expired_on_date': datetime(2022, 12, 31),
                'verified': False,
            }
        },
        {
            'wallet_balance_available': 18900,
            'change_reason': 'verifying_overpaid',
        },
        {
            'wallet_balance_available': 38900,
            'change_reason': 'overpaid_verification_refund',
            'cashback_earned': {
                'current_balance': 20000,
                'expired_on_date': datetime(2022, 12, 31),
                'verified': True,
            },
            'latest_flag': True,
        }
    ]
    for wallet_history in wallet_histories:
        cashback_earned = wallet_history.get('cashback_earned')
        cashback_earned_obj = None
        if cashback_earned:
            cashback_earned_obj = CashbackEarnedFactory(
                current_balance=cashback_earned['current_balance'],
                expired_on_date=cashback_earned['expired_on_date'],
                verified=cashback_earned['verified']
            )
        CustomerWalletHistoryFactory(
            customer=application.customer, application=application,
            wallet_balance_available=wallet_history['wallet_balance_available'],
            change_reason=wallet_history['change_reason'],
            cashback_earned=cashback_earned_obj,
            latest_flag=wallet_history.get('latest_flag', False),
        )


class TestUseCashbackEarnedAndExpiryCashback(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        FeatureSettingFactory(
            feature_name='expire_cashback_date_setting',
            is_active=True,
            parameters={'month': 12, 'day': 31}
        )
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            account=self.account, customer=self.customer,
            product_line=self.product_line,
        )
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application.save()
        dummy_wallet_histories_data(self.application)

        #  customer 2 has cashback expiry in next year
        self.customer_2 = CustomerFactory()
        self.account_2 = AccountFactory(
            customer=self.customer_2,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application_2 = ApplicationFactory(
            account=self.account_2, customer=self.customer_2,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.customer_wallet_history = CustomerWalletHistoryFactory(
            customer=self.application_2.customer, application=self.application_2,
            wallet_balance_available=2000,
            change_reason='cfs_claim_reward',
            cashback_earned=CashbackEarnedFactory(
                current_balance=2000,
                expired_on_date=datetime(2023, 12, 31),
                verified=True
            ),
            latest_flag=True,
        )

    @patch('juloserver.cashback.tasks.use_cashback_payment_and_expiry_cashback_by_batch.delay')
    def test_use_cashback_payment_and_expiry_cashback(
            self, mock_use_cashback_payment_and_expiry_cashback_by_batch
    ):
        use_cashback_payment_and_expiry_cashback()
        mock_use_cashback_payment_and_expiry_cashback_by_batch.assert_called_once_with(
            [self.customer.id]
        )

    @patch('juloserver.cashback.tasks.use_cashback_payment_and_expiry_cashback_by_batch.delay')
    def test_use_cashback_payment_and_expiry_cashback_case_2(
            self, mock_use_cashback_payment_and_expiry_cashback_by_batch
    ):
        CashbackEarned.objects.update(expired_on_date=datetime(9999, 12, 31))
        use_cashback_payment_and_expiry_cashback()
        mock_use_cashback_payment_and_expiry_cashback_by_batch.assert_not_called()

    @patch('juloserver.julo.models.WorkflowStatusPath.objects')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.julo.signals.tracking_repayment_case_for_action_points')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_use_cashback_payment_and_expiry_cashback_by_batch(
        self,
        mock_cashback_experiment,
        mock_tracking_repayment_case_for_action_points,
        mock_get_appsflyer_service,
        mock_workflow_status_path,
    ):
        AccountLimitFactory(account=self.account)
        workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        mock_cashback_experiment.return_value = False
        mock_workflow_status_path.get_or_none.return_value = WorkflowStatusPathFactory(
            status_previous=210, status_next=220, workflow=workflow
        )
        loan = CleanLoanFactory(
            customer=self.customer, application=self.application,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_30DPD),
            loan_amount=10000, loan_duration=3, account=self.account
        )
        account_payments = AccountPaymentFactory.create_batch(
            3, account=self.account, due_date=Iterator([
                datetime(2022, 1, 10),
                datetime(2022, 2, 11),
                datetime(2022, 3, 30),
            ]), due_amount=Iterator([2000, 3000, 5000]),
            status_id=Iterator([
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_30DPD
            ])
        )
        PaymentFactory.create_batch(
            3, loan=loan, is_restructured=False,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_30DPD),
            due_amount=Iterator([2000, 3000, 5000]),
            installment_principal=Iterator([2000, 3000, 5000]),
            account_payment=Iterator(account_payments)
        )
        LoanRefinancingRequestFactory(status='Requested', account=self.account)
        use_cashback_payment_and_expiry_cashback_by_batch([self.customer.id])
        account_payments = AccountPayment.objects.filter(
            account_id=self.customer.account.id
        ).order_by('id')
        # because customer blocked for payment refinancing then due amount not change
        self.assertEqual(account_payments[0].due_amount, 2000)
        self.assertEqual(account_payments[1].due_amount, 3000)
        self.assertEqual(account_payments[2].due_amount, 5000)

        # unblocked for payment refinancing
        LoanRefinancingRequest.objects.filter(account=self.account).delete()
        use_cashback_payment_and_expiry_cashback_by_batch([self.customer.id])
        account_payments = AccountPayment.objects.filter(
            account_id=self.customer.account.id
        ).order_by('id')
        # paid all account payments with sum = 10000
        for account_payment in account_payments:
            self.assertEqual(account_payment.due_amount, 0)
            self.assertEqual(account_payment.status_id, 332)

        self.assertEqual(account_payments[0].paid_amount, 2000)
        self.assertEqual(account_payments[1].paid_amount, 3000)
        self.assertEqual(account_payments[2].paid_amount, 5000)
        # loan.refresh_from_db()
        # self.assertEqual(loan.loan_status_id, 250)

        # all the remaining cashback expired
        self.assertEqual(self.customer.wallet_balance_available, 0)

        # wallet balance system use on payment = 38900 - 10000 = 28900
        system_used_on_payment_expiry_date = CustomerWalletHistory.objects.filter(
            customer=self.customer,
            change_reason=CashbackChangeReason.SYSTEM_USED_ON_PAYMENT_EXPIRY_DATE
        ).last()
        self.assertEqual(system_used_on_payment_expiry_date.wallet_balance_available, 28900)

        cashback_expired_end_of_year = CustomerWalletHistory.objects.filter(
            customer=self.customer, change_reason=CashbackChangeReason.CASHBACK_EXPIRED_END_OF_YEAR
        ).last()
        self.assertEqual(cashback_expired_end_of_year.wallet_balance_available, 0)

        # customer 2 has cashback earned expiry next year
        system_used_on_payment_expiry_date = CustomerWalletHistory.objects.filter(
            customer=self.customer_2,
            change_reason=CashbackChangeReason.CASHBACK_EXPIRED_END_OF_YEAR
        ).last()
        self.assertIsNone(system_used_on_payment_expiry_date)


class TestUseCashbackPaymentDpd(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            account=self.account, customer=self.customer,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.product_line = self.product_line
        self.application.save()
        self.cashback_earned = CashbackEarnedFactory.create_batch(
            3, current_balance=100000, expired_on_date=datetime(2022, 12, 31), verified=True
        )
        self.customer_wallet_history = CustomerWalletHistoryFactory.create_batch(
            3, customer=self.customer, application=self.application,
            wallet_balance_available=Iterator([
                100000, 200000, 300000
            ]),
            wallet_balance_available_old=Iterator([
                0, 100000, 200000
            ]),
            latest_flag=Iterator([False, False, True]),
            cashback_earned=Iterator(self.cashback_earned)
        )
        self.account_payments = AccountPaymentFactory.create_batch(
            3, account=self.account, due_date=Iterator([
                datetime(2022, 1, 10),
                datetime(2022, 2, 11),
                datetime(2022, 3, 30),
            ]), due_amount=Iterator([
                10000, 20000, 50000
            ]), status_id=Iterator([
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_30DPD
            ])
        )
        self.loan = CleanLoanFactory(
            customer=self.customer, application=self.application, account=self.account,
            loan_amount=80000, loan_duration=3,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_30DPD)
        )
        self.payment = PaymentFactory.create_batch(
            3, loan=self.loan, is_restructured=False, due_amount=Iterator([
                10000, 20000, 50000
            ]), installment_principal=Iterator([
                5000, 10000, 25000
            ]), installment_interest=Iterator([
                2000, 5000, 10000
            ]), late_fee_amount=Iterator([
                3000, 5000, 15000
            ]),
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_30DPD),
            account_payment=Iterator(self.account_payments)
        )
        AccountLimitFactory(account=self.account)
        FeatureSettingFactory(
            feature_name='cashback_dpd_pay_off', is_active=True, parameters={'days_past_due': 7}
        )
        AccountingCutOffDateFactory()
        self.cfs_action_points = CfsActionPointsFactory(
            id=99999, multiplier=0.001, floor=5, ceiling=25,
            default_expiry=180
        )

        self.customer_2 = CustomerFactory()
        self.product_line_2 = ProductLineFactory(product_line_code=ProductLineCodes.MTL1)
        self.application_2 = ApplicationFactory(customer=self.customer_2)
        self.application_2.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )
        self.application_2.product_line = self.product_line_2
        self.application_2.save()
        self.cashback_earned_2 = CashbackEarnedFactory.create_batch(
            3, current_balance=100000, expired_on_date=datetime(2022, 12, 31), verified=True
        )
        self.customer_wallet_history_2 = CustomerWalletHistoryFactory.create_batch(
            3, customer=self.customer_2, application=self.application_2,
            wallet_balance_available=Iterator([
                100000, 200000, 300000
            ]),
            wallet_balance_available_old=Iterator([
                0, 100000, 200000
            ]),
            latest_flag=Iterator([False, False, True]),
            cashback_earned=Iterator(self.cashback_earned_2)
        )
        self.loan_2 = CleanLoanFactory(
            customer=self.customer_2, application=self.application_2,
            loan_amount=80000, loan_duration=3,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_30DPD)
        )
        self.payment_2 = PaymentFactory.create_batch(
            3, loan=self.loan_2, is_restructured=False, due_amount=Iterator([
                10000, 20000, 50000
            ]), installment_principal=Iterator([
                5000, 10000, 25000
            ]), installment_interest=Iterator([
                2000, 5000, 10000
            ]), late_fee_amount=Iterator([
                3000, 5000, 15000
            ]),
            due_date=Iterator([
                datetime(2022, 1, 6),
                datetime(2022, 2, 6),
                datetime(2022, 3, 6)
            ]),
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_30DPD),
        )
        ReferralSystemFactory(name='PromoReferral', is_active=True)
        self.cashback_balance = CashbackBalanceFactory(
            customer=self.customer, status=CashbackBalanceStatusConstant.UNFREEZE,
            cashback_balance=300000)
        self.cashback_balance_2 = CashbackBalanceFactory(
            customer=self.customer_2, status=CashbackBalanceStatusConstant.UNFREEZE,
            cashback_balance=300000)
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=232, status_next=250, workflow=self.workflow)

    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_paid_all_dpd(
        self, mock_cashback_experiment, mock_appsflyer_update_status_task, mock_cfs_action_points
    ):
        mock_cfs_action_points.get.return_value = self.cfs_action_points
        mock_cashback_experiment.return_value = False
        system_used_on_payment_dpd()

        for account_payment in self.account_payments:
            account_payment.refresh_from_db()
            self.assertEqual(account_payment.due_amount, 0)
            self.assertEqual(account_payment.status_id, 332)

        updated_customer_wallet = CustomerWalletHistory.objects.get(
            customer=self.customer, wallet_balance_available=220000
        )

        self.assertIsNotNone(updated_customer_wallet)
        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 220000)

    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_ignore_account_payment_less_than_dpd(
        self, mock_cashback_experiment, mock_cfs_action_points
    ):
        account_payment_less_than_dpd = AccountPaymentFactory.create_batch(
            2, account=self.account, due_date=Iterator([
                datetime(2022, 10, 10),
                datetime(2022, 11, 10)
            ]), due_amount=Iterator([
                10000, 20000
            ]), status_id=Iterator([
                PaymentStatusCodes.PAYMENT_NOT_DUE,
                PaymentStatusCodes.PAYMENT_NOT_DUE
            ])
        )

        PaymentFactory.create_batch(
            2, loan=self.loan, is_restructured=False,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE),
            installment_principal=Iterator([10000, 20000]),
            account_payment=Iterator(account_payment_less_than_dpd),
        )
        mock_cfs_action_points.get.return_value = self.cfs_action_points
        mock_cashback_experiment.return_value = False
        system_used_on_payment_dpd()

        unpaid_amount = [10000, 20000]
        unpaid_account_payments = AccountPayment.objects.filter(due_amount__in=unpaid_amount)
        self.assertIsNotNone(unpaid_account_payments)

        for account_payment in unpaid_account_payments:
            self.assertEqual(account_payment.status_id, 310)

        cashback = CashbackBalance.objects.filter(customer=self.customer, cashback_balance=220000)
        self.assertIsNotNone(cashback)

    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_exclude_cashback_overpaid_change_reason(self,
                                                     mock_cashback_experiment,
                                                     mock_cfs_action_points):
        cashback_earned_overpaid = CashbackEarnedFactory(
            current_balance=600000, expired_on_date=datetime(2022, 12, 31), verified=False
        )

        wallet_history_overpaid = CustomerWalletHistoryFactory(
            customer=self.customer, application=self.application,
            wallet_balance_available=900000,
            wallet_balance_available_old=300000,
            cashback_earned=cashback_earned_overpaid,
            latest_flag=True
        )

        account_payment_dpd = AccountPaymentFactory.create_batch(
            2, account=self.account, due_date=Iterator([
                datetime(2022, 4, 10),
                datetime(2022, 5, 11),
            ]), due_amount=Iterator([
                300000, 400000
            ]), status_id=Iterator([
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_30DPD
            ])
        )

        payment = PaymentFactory.create_batch(
            2, loan=self.loan, is_restructured=False,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_30DPD),
            installment_principal=Iterator([300000, 400000]),
            account_payment=Iterator(account_payment_dpd),
        )
        mock_cfs_action_points.get.return_value = self.cfs_action_points
        mock_cashback_experiment.return_value = False
        system_used_on_payment_dpd()

        updated_customer_wallet = CustomerWalletHistory.objects.get(
            customer=self.customer, wallet_balance_available=600000
        )
        self.assertIsNotNone(updated_customer_wallet)
        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 0)

    @patch('juloserver.julo.models.WorkflowStatusPath.objects')
    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_multiple_dpds(
        self, mock_cashback_experiment, mock_cfs_action_points, mock_workflow_status_path
    ):
        mock_workflow_status_path.get_or_none.return_value = WorkflowStatusPathFactory(
            status_previous=232, status_next=250, workflow=self.workflow
        )
        self.loan.loan_duration = 6
        self.loan.loan_amount = 240000
        self.loan.save()

        account_payments = AccountPaymentFactory.create_batch(
            3, account=self.account, due_date=Iterator([
                datetime(2022, 11, 6),
                datetime(2021, 12, 11),
                datetime(2022, 11, 7),
            ]), due_amount=Iterator([
                150000, 5000, 5000
            ]), status_id=Iterator([
                PaymentStatusCodes.PAYMENT_1DPD,
                PaymentStatusCodes.PAYMENT_120DPD,
                PaymentStatusCodes.PAYMENT_NOT_DUE
            ])
        )
        payment = PaymentFactory.create_batch(
            3, loan=self.loan, is_restructured=False, due_amount=Iterator([
                150000, 5000, 5000
            ]), installment_principal=Iterator([
                140000, 3000, 4000
            ]), installment_interest=Iterator([
                5000, 1000, 1000
            ]), late_fee_amount=Iterator([
                5000, 1000, 0
            ]),
            account_payment=Iterator(account_payments)
        )
        payment[0].payment_status = StatusLookupFactory(
            status_code=PaymentStatusCodes.PAYMENT_1DPD
        )
        payment[1].payment_status = StatusLookupFactory(
            status_code=PaymentStatusCodes.PAYMENT_120DPD
        )
        payment[2].payment_status = StatusLookupFactory(
            status_code=PaymentStatusCodes.PAYMENT_NOT_DUE
        )
        payment[0].save()
        payment[1].save()
        payment[2].save()

        mock_cfs_action_points.get.return_value = self.cfs_action_points
        mock_cashback_experiment.return_value = False
        # Paid 1st loan with 3 payments (80,000Rp)
        # Paid 2nd loan with 3 payemnts (160,000Rp)
        system_used_on_payment_dpd()

        updated_customer_wallet = CustomerWalletHistory.objects.get(
            customer=self.customer, wallet_balance_available=60000
        )
        self.assertIsNotNone(updated_customer_wallet)

        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 60000)

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    def test_due_amount_larger_than_cashback_available(self):
        account_payment = AccountPaymentFactory(
            account=self.account, due_amount=1000000, due_date=datetime(2022, 4, 10),
            status_id=PaymentStatusCodes.PAYMENT_30DPD
        )
        self.loan.loan_duration = 4
        self.loan.loan_amount = 1080000
        self.loan.save()

        PaymentFactory(
            loan=self.loan, is_restructured=False,
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_30DPD),
            installment_principal=1000000,
            account_payment=account_payment
        )

        system_used_on_payment_dpd()

        unfinished_payment = AccountPayment.objects.filter(
            due_amount=780000, status_id=PaymentStatusCodes.PAYMENT_30DPD
        )
        self.assertIsNotNone(unfinished_payment)

        remaining_customer_wallet = CustomerWalletHistory.objects.filter(
            customer=self.customer, wallet_balance_available=0
        )
        lmao = CustomerWalletHistory.objects.filter(customer=self.customer).order_by('id')
        self.assertIsNotNone(remaining_customer_wallet)

        cashback = CashbackBalance.objects.filter(customer=self.customer, cashback_balance=0)
        self.assertIsNotNone(cashback)

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    @patch('juloserver.julo.services.get_agent_service_for_bucket')
    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_different_product_line_user_one_late_loan(
        self,
        mock_cashback_experiment,
        mock_appsflyer_update_status_task,
        mock_cfs_action_points,
        mock_agent,
    ):
        mock_cfs_action_points.get.return_value = self.cfs_action_points
        mock_cashback_experiment.return_value = False
        system_used_on_payment_dpd()

        for payment in self.payment_2:
            payment.refresh_from_db()
            self.assertEqual(payment.due_amount, 0)
            self.assertEqual(payment.payment_status, StatusLookupFactory(
                status_code=PaymentStatusCodes.PAID_LATE)
                             )

        updated_customer_wallet = CustomerWalletHistory.objects.filter(
            customer=self.customer_2, wallet_balance_available=220000
        )

        self.assertIsNotNone(updated_customer_wallet)

        self.cashback_balance.refresh_from_db()
        self.assertEquals(self.cashback_balance.cashback_balance, 220000)

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    @patch('juloserver.julo.services.get_agent_service_for_bucket')
    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_different_product_line_user_multiple_late_loans(
        self,
        mock_cashback_experiment,
        mock_appsflyer_update_status_task,
        mock_cfs_action_points,
        mock_agent,
    ):
        self.loan_2.loan_duration = 12
        self.loan_2.loan_amount = 290000
        self.loan_2.save()

        payment = PaymentFactory.create_batch(
            9, loan=self.loan_2,
            is_restructured=False, due_amount=Iterator([
                30000, 10000, 10000,
                20000, 20000, 20000,
                20000, 50000, 30000
            ]), installment_principal=Iterator([
                20000, 5000, 5000,
                10000, 10000, 10000,
                10000, 35000, 20000
            ]), installment_interest=Iterator([
                6000, 3000, 30000,
                5000, 5000, 5000,
                5000, 10000, 5000
            ]), late_fee_amount=Iterator([
                4000, 2000, 2000,
                5000, 5000, 5000,
                5000, 5000, 5000
            ]),
            due_date=Iterator([
                datetime(2021, 10, 6),
                datetime(2021, 11, 6),
                datetime(2021, 12, 6),
                datetime(2022, 4, 6),
                datetime(2022, 5, 6),
                datetime(2022, 6, 6),
                datetime(2022, 7, 6),
                datetime(2022, 8, 6),
                datetime(2022, 9, 6)
            ]),
            payment_status=Iterator([
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_180DPD),
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_180DPD),
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_180DPD),
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_1DPD),
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_1DPD),
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_1DPD),
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE),
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE),
                StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE),
            ]),
        )

        mock_cfs_action_points.get.return_value = self.cfs_action_points
        mock_cashback_experiment.return_value = False
        system_used_on_payment_dpd()

        for index in range(len(self.payment_2) - 6):
            self.payment_2[index].refresh_from_db()
            self.assertEqual(self.payment_2[index].due_amount, 0)
            self.assertEqual(
                self.payment_2[index].payment_status,
                StatusLookupFactory(status_code=PaymentStatusCodes.PAID_LATE)
            )

        updated_customer_wallet = CustomerWalletHistory.objects.filter(
            customer=self.customer_2, wallet_balance_available=170000
        )

        self.assertIsNotNone(updated_customer_wallet)

        self.cashback_balance_2.refresh_from_db()
        self.assertEquals(self.cashback_balance_2.cashback_balance, 10000)

    @patch('juloserver.julo.services.get_agent_service_for_bucket')
    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    @patch('juloserver.loan.services.loan_event.get_appsflyer_service')
    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_user_change_product_line(
        self,
        mock_cashback_experiment,
        mock_appsflyer_update_status_task,
        mock_cfs_action_points,
        mock_agent,
    ):
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        account = AccountFactory(
            customer=self.customer_2, status=StatusLookupFactory(
                status_code=AccountConstant.STATUS_CODE.active
            )
        )
        application = ApplicationFactory(
            account=account, customer=self.customer_2,
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        application.product_line = product_line
        application.save()

        for customer_wallet in self.customer_wallet_history_2:
            customer_wallet.application = application
            customer_wallet.save()

        self.loan_2.application = application
        self.loan_2.account = account
        self.loan_2.save()

        account_payments = AccountPaymentFactory.create_batch(
            3, account=account, due_date=Iterator([
                datetime(2022, 1, 10),
                datetime(2022, 2, 11),
                datetime(2022, 3, 30),
            ]), due_amount=Iterator([
                10000, 20000, 50000
            ]), status_id=Iterator([
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_30DPD
            ])
        )
        AccountLimitFactory(account=account)

        for index in range(len(self.payment_2)):
            self.payment_2[index].account_payment = account_payments[index]
            self.payment_2[index].save()

        mock_cfs_action_points.get.return_value = self.cfs_action_points
        mock_cashback_experiment.return_value = False
        system_used_on_payment_dpd()

        for index in range(len(self.account_payments)):
            self.account_payments[index].refresh_from_db()
            account_payments[index].refresh_from_db()

            self.assertEqual(self.account_payments[index].due_amount, 0)
            self.assertEqual(account_payments[index].due_amount, 0)

            self.assertEqual(self.account_payments[index].status_id, 332)
            self.assertEqual(account_payments[index].status_id, 332)


class TestCashbackUnfreeze(TestCase):
    def setUp(self):
        self.setup_referrer_referee()
        self.setup_customer_balance()
        self.setup_referral_program()

    def setup_referrer_referee(self):
        self.referrer = CustomerFactory()
        self.referee = CustomerFactory()
        self.account = AccountFactory(
            customer=self.referee,
            status=StatusLookupFactory(status_code=420)
        )
        self.application = ApplicationFactory(
            customer=self.referee,
            account=self.account,
            referral_code='TEST_REFERRAL_CODE',
            product_line=ProductLineFactory(product_line_code=1),
        )

    def setup_customer_balance(self):
        self.cashback_earned = CashbackEarnedFactory.create_batch(
            3,
            current_balance=Iterator([10000, 20000, 40000]),
            verified=Iterator([True, False, True])
        )
        self.customer_wallet_history = CustomerWalletHistoryFactory.create_batch(
            3,
            customer=self.referee,
            wallet_balance_available=Iterator([10000, 10000, 50000]),
            change_reason=Iterator([
                CashbackChangeReason.PAYMENT_ON_TIME,
                CashbackChangeReason.PROMO_REFERRAL_FRIEND,
                CashbackChangeReason.LOAN_PAID_OFF
            ]),
            cashback_earned=Iterator(self.cashback_earned)
        )
        self.cashback_balance = CashbackBalanceFactory(
            customer=self.referee, cashback_balance=50000,
            status=CashbackBalanceStatusConstant.UNFREEZE
        )

    def setup_referral_program(self):
        self.freeze_cashback_fs = FeatureSettingFactory(
            feature_name=CashbackFeatureNameConst.CASHBACK_TEMPORARY_FREEZE,
            parameters={
                'first_repayment_logic': {
                    'is_active': True
                },
                'period_logic': {
                    'is_active': True,
                    'start_date': '2023-11-01',
                    'end_date': '2023-12-31',
                    'mimimum_freeze_date': '2024-01-01',
                    'freeze_period': 45
                }
            }
        )
        self.referral_system = ReferralSystemFactory(
            name='PromoReferral',
            minimum_transaction_amount=80000
        )
        self.referral_benefit = ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=50000,
            referee_benefit=20000, min_disburse_amount=100000, is_active=True
        )
        self.referee_mapping = RefereeMappingFactory(referee=self.referee)
        self.benefit_history = ReferralBenefitHistoryFactory.create_batch(
            2,
            benefit_unit=ReferralBenefitConst.CASHBACK,
            referee_mapping=self.referee_mapping,
            referral_person_type=Iterator([ReferralPersonTypeConst.REFERRER, ReferralPersonTypeConst.REFEREE]),
            customer=Iterator([self.referrer, self.referee]),
            amount=Iterator([50000, 20000])
        )

    @patch.object(timezone, 'now')
    def test_task_unfreeze_referral_cashback_valid(self, mock_now):
        mock_now.return_value = datetime(2024, 1, 10, 0, 0, 15)
        loan = LoanFactory(
            customer=self.referee,
            application=self.application,
            account=self.account,
            loan_amount=300000,
        )
        PaymentFactory.create_batch(
            3,
            loan=loan,
            due_amount=0,
            paid_amount=Iterator([100000, 100000, 100000]),
            payment_number=Iterator([1, 2, 3]),
            payment_status=StatusLookupFactory(status_code=330)
        )

        self.cashback_earned[1].update_safely(cdate=datetime(2023, 11, 9, 0, 0, 10))
        unfreeze_referral_cashback()
        self.cashback_earned[1].refresh_from_db()
        self.cashback_balance.refresh_from_db()
        self.assertTrue(self.cashback_earned[1].verified)
        self.assertEqual(self.cashback_balance.cashback_balance, 70000)

    @patch.object(timezone, 'now')
    def test_task_unfreeze_referral_cashback_invalid_period(self, mock_now):
        mock_now.return_value = datetime(2024, 1, 15, 0, 0, 15)
        loan = LoanFactory(
            customer=self.referee,
            application=self.application,
            account=self.account,
            loan_amount=300000,
        )
        PaymentFactory.create_batch(
            3,
            loan=loan,
            due_amount=0,
            paid_amount=Iterator([100000, 100000, 100000]),
            payment_number=Iterator([1, 2, 3]),
            payment_status=StatusLookupFactory(status_code=330)
        )

        self.cashback_earned[1].update_safely(cdate=datetime(2023, 12, 20, 0, 0, 10))
        unfreeze_referral_cashback()
        self.cashback_earned[1].refresh_from_db()
        self.cashback_balance.refresh_from_db()
        self.assertFalse(self.cashback_earned[1].verified)
        self.assertEqual(self.cashback_balance.cashback_balance, 50000)

    @patch.object(timezone, 'now')
    def test_task_unfreeze_referral_cashback_invalid_first_repayment(self, mock_now):
        mock_now.return_value = datetime(2024, 1, 15, 0, 0, 15)

        self.cashback_earned[1].update_safely(cdate=datetime(2023, 11, 9, 0, 0, 10))
        unfreeze_referral_cashback()
        self.cashback_earned[1].refresh_from_db()
        self.cashback_balance.refresh_from_db()
        self.assertFalse(self.cashback_earned[1].verified)
        self.assertEqual(self.cashback_balance.cashback_balance, 50000)


class TestCashbackPromoInjection(TestCase):
    def setUp(self):
        FeatureSettingFactory(
            feature_name='promo_code_for_cashback_injection',
            is_active=True,
            parameters={'promo_code_list': ["BBSCCL"]},
        )
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

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
            application_status=StatusLookupFactory(status_code=190),
        )
        self.loan = CleanLoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_amount=80000,
            loan_duration=3,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
            cdate=datetime(2024, 4, 30, 13, 0, 0),
        )
        self.loan_history = LoanHistoryFactory(
            loan=self.loan,
            status_old=220,
            status_new=250,
        )
        self.loan_history.cdate = datetime(2024, 4, 30, 13, 0, 0)
        self.loan_history.save()
        self.payment = PaymentFactory.create_batch(
            3,
            loan=self.loan,
            is_restructured=False,
            due_amount=Iterator([10000, 20000, 50000]),
            installment_principal=Iterator([5000, 10000, 25000]),
            installment_interest=Iterator([2000, 5000, 10000]),
            late_fee_amount=Iterator([3000, 5000, 15000]),
            due_date=Iterator([datetime(2022, 1, 6), datetime(2022, 2, 6), datetime(2022, 3, 6)]),
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME),
        )
        self.cashback_benefit = PromoCodeBenefitFactory(
            name="BBSCCL",
            type=PromoCodeBenefitConst.VOUCHER,
            value={},
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
            applied_at=datetime(2024, 4, 30, 13, 0, 0),
        )
        CustomerWalletHistoryFactory(
            wallet_balance_available=5000,
            wallet_balance_accruing=3000,
            customer=self.customer,
            application=self.application,
            latest_flag=True,
            cashback_earned=CashbackEarnedFactory(current_balance=5000, verified=True),
        )

        # 2nd Application
        self.customer_2 = CustomerFactory()
        self.product_line_2 = ProductLineFactory(product_line_code=ProductLineCodes.MTL1)
        self.application_2 = ApplicationFactory(customer=self.customer_2)
        self.application_2.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )
        self.application_2.product_line = self.product_line_2
        self.application_2.save()
        self.loan_2 = CleanLoanFactory(
            customer=self.customer_2,
            application=self.application_2,
            loan_amount=80000,
            loan_duration=3,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_30DPD),
        )
        self.payment_2 = PaymentFactory.create_batch(
            3,
            loan=self.loan_2,
            is_restructured=False,
            due_amount=Iterator([10000, 20000, 50000]),
            installment_principal=Iterator([5000, 10000, 25000]),
            installment_interest=Iterator([2000, 5000, 10000]),
            late_fee_amount=Iterator([3000, 5000, 15000]),
            due_date=Iterator([datetime(2022, 1, 6), datetime(2022, 2, 6), datetime(2022, 3, 6)]),
            payment_status=StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_30DPD),
        )
        CustomerWalletHistoryFactory(
            wallet_balance_available=10000,
            wallet_balance_accruing=3000,
            customer=self.customer_2,
            application=self.application_2,
            latest_flag=True,
            cashback_earned=CashbackEarnedFactory(current_balance=10000, verified=True),
        )

    @patch('django.utils.timezone.now')
    def test_cashback_injection_promo_bbsccl(self, mock_now):
        mock_now.return_value = datetime(2024, 5, 25, 0, 0, 0)
        # Execute async task
        inject_cashback_promo_task()
        customer_wallet_history = CustomerWalletHistory.objects.filter(
            application=self.application,
            loan=self.loan,
            customer=self.customer,
        ).last()
        self.assertEquals('promo:BBSCCL_1', customer_wallet_history.change_reason)
        self.assertEquals(40000, customer_wallet_history.wallet_balance_available)
        self.assertEquals(38000, customer_wallet_history.wallet_balance_accruing)
        self.assertEquals(5000, customer_wallet_history.wallet_balance_available_old)
        self.assertTrue(customer_wallet_history.latest_flag)

    @patch('django.utils.timezone.now')
    def test_failed_inject_cashback_promo_bbsccl(self, mock_now):
        mock_now.return_value = datetime(2024, 5, 25, 0, 0, 0)
        self.promo_code_usage = PromoCodeUsageFactory(
            loan_id=self.loan_2.id,
            customer_id=self.customer_2.id,
            application_id=self.application_2.id,
            promo_code=self.promo_code,
            applied_at=datetime(2024, 5, 22, 13, 0, 0),
        )
        # Execute async task
        inject_cashback_promo_task()
        customer_wallet_history_2 = CustomerWalletHistory.objects.filter(
            application=self.application_2,
            customer=self.customer_2,
        ).last()
        self.assertEquals(10000, customer_wallet_history_2.wallet_balance_available)
        self.assertEquals(3000, customer_wallet_history_2.wallet_balance_accruing)
        self.assertTrue(customer_wallet_history_2.latest_flag)
