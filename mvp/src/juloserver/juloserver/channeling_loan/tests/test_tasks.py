import mock
from unittest.mock import patch

import pandas as pd
from datetime import timedelta
from bulk_update.helper import bulk_update
from dateutil.relativedelta import relativedelta
from django.conf import settings

from django.utils import timezone

from django.test.testcases import TestCase

from juloserver.channeling_loan.services.support_services import FAMAApprovalFileServices

from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
    CustomerFactory,
    AuthUserFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    PaymentFactory,
    PartnerFactory,
    DocumentFactory,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.account.tests.factories import AccountFactory
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
    LenderBalanceCurrentFactory,
)
from juloserver.channeling_loan.tests.factories import (
    LenderOspAccountFactory,
    LenderLoanLedgerFactory,
    LoanLenderTaggingDpdTempFactory,
    ChannelingLoanPaymentFactory,
    ChannelingEligibilityStatusFactory,
    ChannelingLoanStatusFactory,
)
from juloserver.channeling_loan.tasks import (
    process_ar_switching_task,
    execute_withdraw_batch_process,
    daily_checker_loan_tagging_task,
    daily_checker_loan_tagging_clone_task,
    update_loan_lender_task,
    insert_loan_write_off,
    update_loan_write_off,
    process_loan_write_off_task,
    process_dbs_approval_response,
    process_fama_approval_response,
    populate_fama_loan_after_cutoff,
    process_permata_approval_response,
    proceed_sync_channeling,
    process_upload_lender_switch_file,
    process_lender_switch_task,
    fama_auto_approval_loans,
    regenerate_summary_and_skrtp_agreement_for_ar_switching,
    send_loan_for_channeling_task,
    send_loan_for_channeling_to_bss_task,
)
from juloserver.julocore.python2.utils import py2round
from juloserver.channeling_loan.constants import (
    ChannelingConst,
    ChannelingLenderLoanLedgerConst,
    FeatureNameConst as ChannelingFeatureNameConst,
    GeneralIneligible,
    ChannelingStatusConst,
    ChannelingActionTypeConst,
    PermataChannelingConst,
    ChannelingLoanApprovalFileConst,
)
from juloserver.channeling_loan.models import (
    LenderLoanLedger,
    LoanLenderTaggingDpdTemp,
    ChannelingLoanStatus,
    ChannelingEligibilityStatus,
    ChannelingLoanWriteOff,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.models import LoanAdjustedRate
from juloserver.followthemoney.constants import LenderTransactionTypeConst
from juloserver.followthemoney.models import LenderTransactionType
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.loan.tests.factories import (
    TransactionMethodFactory,
    LoanZeroInterestFactory,
)
from juloserver.payment_point.models import TransactionMethod
import pytest

BASE_ELEMENT_VALUE_CHANNELING_CONFIGURATION = {
    "rac": {
        "TENOR": "Monthly",
        "MAX_AGE": 65,
        "MIN_AGE": 18,
        "VERSION": 2,
        "JOB_TYPE": [],
        "MAX_LOAN": 30000000,
        "MIN_LOAN": 150000,
        "MAX_RATIO": None,
        "MAX_TENOR": 12,
        "MIN_TENOR": 2,
        "MIN_INCOME": None,
        "INCOME_PROVE": False,
        "MIN_WORKTIME": 24,
        "HAS_KTP_OR_SELFIE": True,
        "MOTHER_MAIDEN_NAME": True,
        "TRANSACTION_METHOD": ["1", "2"],
    },
    "cutoff": {
        "LIMIT": None,
        "is_active": True,
        "CUTOFF_TIME": {"hour": 13, "minute": 0, "second": 0},
        "INACTIVE_DAY": [],
        "OPENING_TIME": {"hour": 0, "minute": 1, "second": 0},
        "INACTIVE_DATE": [],
        "CHANNEL_AFTER_CUTOFF": True,
    },
    "b_score": {"is_active": True, "MAX_B_SCORE": 1.0, "MIN_B_SCORE": 0.8},
    "general": {
        "LENDER_NAME": "fama_channeling",
        "DAYS_IN_YEAR": 360,
        "CHANNELING_TYPE": "manual",
        "BUYBACK_LENDER_NAME": "jh",
        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
        "INTEREST_PERCENTAGE": 13.5,
        "RISK_PREMIUM_PERCENTAGE": 45.1,
    },
    "due_date": {"is_active": True, "EXCLUSION_DAY": ["25", "26", "27", "28"]},
    "is_active": True,
    "whitelist": {"is_active": False, "APPLICATIONS": ["2006526129", "2006369269"]},
    "credit_score": {"SCORE": [], "is_active": False},
    "force_update": {"VERSION": 3, "is_active": True},
    "lender_dashboard": {"is_active": False},
    "filename_counter_suffix": {"LENGTH": 2, "is_active": True},
    "process_approval_response": {"DELAY_MINS": 60},
}


class TestTaskARS(TestCase):
    @classmethod
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.lender = LenderCurrentFactory(
            lender_name='jtp'
        )
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=self.application,
            lender=self.lender,
        )
        self.user_auth = AuthUserFactory()

    def test_process_ar_switching_task(self):
        form_data = {'url_field': '', 'lender_name': 'jh'}
        reason = "AR switching by rachmat batch:20230404050800"
        process_ar_switching_task(self.user_auth.username, None, form_data, reason)


class TestTaskLoanTagging(TestCase):
    def setUp(self):
        self.lender = LenderCurrentFactory(lender_name="jtp")
        self.lender_osp_account = LenderOspAccountFactory(
            lender_withdrawal_percentage=115, lender_account_name="FAMA"
        )
        self.margin = 10000000
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOAN_TAGGING_CONFIG,
            is_active=True,
            parameters={
                "margin": self.margin,
                "loan_query_batch_size": 1000,
                "lenders": ["jtp"],
                "lenders_match_for_lender_osp_account": {
                    "BSS": ["jtp", "helicap"],
                    "BSS2": ["jtp", "helicap"],
                    "FAMA": ["jtp", "helicap"],
                    "Lend East": ["jh"],
                    "Helicap": ["jh"],
                },
                "is_daily_checker_active": True,
            },
        )
        self.status = StatusLookupFactory(status_code=220)
        self.loans = []
        for i in range(100, 116):
            loan = LoanFactory(
                loan_xid=i,
                application=ApplicationFactory(),
                loan_amount=1000000,
                loan_status=self.status,
                lender=self.lender,
            )
            self.loans.append(
                loan
            )
            LoanLenderTaggingDpdTempFactory(
                loan_id = loan.id,
                loan_dpd = 0
            )
        self.get_loans_replenish_query = """
            SELECT loan.loan_id, loan.application_id, loan.loan_amount,
            loan.loan_xid, loan.application_id2
            FROM loan
            INNER JOIN lender ON (loan.lender_id = lender.lender_id)
            INNER JOIN loan_lender_tagging_loan_dpd_temp ON (
                loan.loan_id = loan_lender_tagging_loan_dpd_temp.loan_id
            )
            LEFT JOIN lender_loan_ledger ON (
                loan.loan_id = lender_loan_ledger.loan_id
                and (
                    lender_loan_ledger.tag_type IN (%s, %s, %s)
                    or (lender_loan_ledger.tag_type = %s and lender_loan_ledger.lender_osp_account_id = %s)
                )
            )
            WHERE lender.lender_name = ANY(%s)
            AND loan_lender_tagging_loan_dpd_temp.loan_dpd > 0
            AND loan_lender_tagging_loan_dpd_temp.loan_dpd < 90
            AND lender_loan_ledger.loan_id is null
        """
        self.get_loans_initial_query = """
            SELECT loan.loan_id, loan.application_id, loan.loan_amount,
            loan.loan_xid, loan.application_id2
            FROM loan
            INNER JOIN lender ON (loan.lender_id = lender.lender_id)
            INNER JOIN loan_lender_tagging_loan_dpd_temp ON (
                loan.loan_id = loan_lender_tagging_loan_dpd_temp.loan_id
            )
            LEFT JOIN lender_loan_ledger ON (
                loan.loan_id = lender_loan_ledger.loan_id
                and (
                    lender_loan_ledger.tag_type IN (%s, %s, %s)
                    or (lender_loan_ledger.tag_type = %s and lender_loan_ledger.lender_osp_account_id = %s)
                )
            )
            WHERE lender.lender_name = ANY(%s)
            AND loan_lender_tagging_loan_dpd_temp.loan_dpd <= 0
            AND lender_loan_ledger.loan_id is null
        """

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_replenishment_tag_query')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_success(self, mock_get_initial_tag_query, mock_get_replenishment_tag_query):
        self.lender_osp_account.balance_amount = 10000000
        self.lender_osp_account.total_outstanding_principal = 0
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query
        balance = int(
            py2round(
                (
                    self.lender_osp_account.balance_amount * 115 / 100
                ) - self.lender_osp_account.total_outstanding_principal
            )
        )

        execute_withdraw_batch_process(self.lender_osp_account.id)
        self.lender_osp_account.refresh_from_db()
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account
        )

        amount = 0
        total_lender = 0
        total_julo = 0
        for loan_tag in lender_loan_ledgers:
            self.assertEqual(loan_tag.loan.loan_xid, loan_tag.loan_xid)
            amount += loan_tag.osp_amount
            if loan_tag.is_fund_by_julo:
                total_julo += loan_tag.osp_amount
            else:
                total_lender += loan_tag.osp_amount

        self.assertTrue(amount >= balance and amount <= balance + self.margin)
        self.assertTrue(total_lender >= self.lender_osp_account.balance_amount)
        self.assertTrue(
            total_julo >= self.lender_osp_account.balance_amount * (15/100)
        )

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_replenishment_tag_query')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_success_with_processed_balance(
        self,
        mock_get_initial_tag_query,
        mock_get_replenishment_tag_query
    ):
        self.lender_osp_account.balance_amount = 10000000
        self.lender_osp_account.total_outstanding_principal = 5000000
        self.lender_osp_account.fund_by_lender = 5000000
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query
        balance = int(
            py2round(
                (
                    self.lender_osp_account.balance_amount * 115 / 100
                ) - self.lender_osp_account.total_outstanding_principal
            )
        )

        loan = LoanFactory(
            loan_xid=999,
            application=ApplicationFactory(),
            loan_amount=50000000,
            loan_status=self.status,
            lender=self.lender,
        )

        execute_withdraw_batch_process(self.lender_osp_account.id)
        loan.delete()
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account
        )

        amount = 0
        for loan_tag in lender_loan_ledgers:
            amount += loan_tag.osp_amount

        self.assertTrue(amount >= balance and amount <= balance + self.margin)

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_replenishment_tag_query')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_failed_with_previous_processed_loan(
        self,
        mock_get_initial_tag_query,
        mock_get_replenishment_tag_query
    ):
        self.lender_osp_account.balance_amount = 10000000
        self.lender_osp_account.total_outstanding_principal = 0
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query
        balance = int(
            py2round(
                (
                    self.lender_osp_account.balance_amount * 115 / 100
                ) - self.lender_osp_account.total_outstanding_principal
            )
        )

        ctr = 0
        for loan in self.loans:
            LenderLoanLedgerFactory(loan_id=loan.id, loan_xid=loan.loan_xid, osp_amount=1000000)
            ctr += 1
            if ctr == 5:
                break

        execute_withdraw_batch_process(self.lender_osp_account.id)
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account
        )

        amount = 0
        for loan_tag in lender_loan_ledgers:
            amount += loan_tag.osp_amount

        # balance not enough, so false is returned
        self.assertFalse(amount >= balance and amount <= balance + self.margin)
        self.assertTrue(lender_loan_ledgers) == 10

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_replenishment_tag_query')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_daily_checker_one_lender(
        self,
        mock_get_initial_tag_query,
        mock_get_replenishment_tag_query
    ):
        # first is inital tag
        self.lender_osp_account.balance_amount = 10_000_000
        self.lender_osp_account.total_outstanding_principal = 0
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query
        execute_withdraw_batch_process(self.lender_osp_account.id)

        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account,
            tag_type=ChannelingLenderLoanLedgerConst.INITIAL_TAG,
        )
        # release dpd 90
        first_loan = lender_loan_ledgers.first().loan
        first_loan.loan_status_id = LoanStatusCodes.LOAN_90DPD
        first_loan.save()

        loan_dpd = LoanLenderTaggingDpdTemp.objects.filter(loan=first_loan).first()
        loan_dpd.loan_dpd = 90
        loan_dpd.save()
        # repayment
        last_loan = lender_loan_ledgers.last().loan
        PaymentFactory(
            payment_number=1,
            loan=last_loan,
            paid_principal=last_loan.loan_amount,
        )
        last_loan.loan_status_id = LoanStatusCodes.PAID_OFF
        last_loan.save()
        daily_checker_loan_tagging_task()

        # there was amount reduced by payment
        repayment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF
        ).exists()
        # there was new loan replacing those missing loan
        replenishment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG
        ).exists()

        self.lender_osp_account.refresh_from_db()
        # check total balance
        self.assertTrue(self.lender_osp_account.total_outstanding_principal >= 11_500_000)
        self.assertTrue(self.lender_osp_account.fund_by_lender >= 10_000_000)
        self.assertTrue(self.lender_osp_account.fund_by_julo >= 1_500_000)
        self.assertTrue(repayment)
        self.assertTrue(replenishment)

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_replenishment_tag_query')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_daily_checker_dpd_90(
        self,
        mock_get_initial_tag_query,
        mock_get_replenishment_tag_query
    ):
        # first is inital tag
        self.lender_osp_account.balance_amount = 10_000_000
        self.lender_osp_account.total_outstanding_principal = 0
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query
        execute_withdraw_batch_process(self.lender_osp_account.id)

        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account,
            tag_type=ChannelingLenderLoanLedgerConst.INITIAL_TAG,
        )
        # release dpd 90
        first_loan = lender_loan_ledgers.first().loan
        first_loan.loan_status_id = LoanStatusCodes.LOAN_90DPD
        first_loan.save()

        loan_dpd = LoanLenderTaggingDpdTemp.objects.filter(loan=first_loan).first()
        loan_dpd.loan_dpd = 90
        loan_dpd.save()
        # repayment
        last_loan = lender_loan_ledgers.last().loan
        PaymentFactory(
            payment_number=1,
            loan=last_loan,
            paid_principal=last_loan.loan_amount,
        )
        last_loan.loan_status_id = LoanStatusCodes.PAID_OFF
        last_loan.save()
        daily_checker_loan_tagging_clone_task()

        # there was loan released by dpd_90
        released_dpd_90 = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90
        ).exists()

        self.lender_osp_account.refresh_from_db()
        self.assertTrue(released_dpd_90)

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_replenishment_tag_query')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_daily_checker_one_lender_not_triggered(
        self,
        mock_get_initial_tag_query,
        mock_get_replenishment_tag_query
    ):
        # first is inital tag
        self.lender_osp_account.balance_amount = 10000000
        self.lender_osp_account.total_outstanding_principal = 0
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query

        execute_withdraw_batch_process(self.lender_osp_account.id)
        daily_checker_loan_tagging_task()
        self.lender_osp_account.refresh_from_db()

        # there was loan released by dpd_90
        released_dpd_90 = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90
        ).exists()
        # there was amount reduced by payment
        repayment = LenderLoanLedger.objects.filter(
            osp_amount=500_000
        ).exists()

        # there was new loan replacing those missing loan
        replenishment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG
        ).exists()

        self.lender_osp_account.refresh_from_db()
        # check total balance
        self.assertTrue(self.lender_osp_account.total_outstanding_principal >= 11_500_000)
        self.assertTrue(self.lender_osp_account.fund_by_lender >= 10_000_000)
        self.assertTrue(self.lender_osp_account.fund_by_julo >= 1_500_000)
        self.assertFalse(released_dpd_90)
        self.assertFalse(repayment)
        self.assertFalse(replenishment)

    @pytest.mark.skip(reason="Flaky")
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_replenishment_tag_query')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_daily_checker_multiple_lender(
        self,
        mock_get_initial_tag_query,
        mock_get_replenishment_tag_query
    ):
        # first is inital tag
        # this process no longer handle dpd90
        self.lender_osp_account.balance_amount = 5_000_000
        self.lender_osp_account.total_outstanding_principal = 0
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query

        self.lender_osp_account2 = LenderOspAccountFactory(
            lender_withdrawal_percentage=115,
            lender_account_name="BSS",
            balance_amount=4_000_000,
        )
        self.lender_osp_account3 = LenderOspAccountFactory(
            lender_withdrawal_percentage=115,
            lender_account_name="BSS2",
            balance_amount=7_000_000,
        )

        # currently have 15 mil loan,
        # adding another 20 mil (@ 0.5 mil)
        for i in range(0, 40):
            loan = LoanFactory(
                loan_xid=i,
                application=ApplicationFactory(),
                loan_amount=500_000,
                loan_status=self.status,
                lender=self.lender,
            )
            self.loans.append(loan)
            LoanLenderTaggingDpdTempFactory(
                loan_id = loan.id,
                loan_dpd = 0,
            )

        execute_withdraw_batch_process(self.lender_osp_account.id)
        execute_withdraw_batch_process(self.lender_osp_account2.id)
        execute_withdraw_batch_process(self.lender_osp_account3.id)

        # lender 1 will be released by dpd 90
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account,
            tag_type=ChannelingLenderLoanLedgerConst.INITIAL_TAG,
        )
        first_loan = lender_loan_ledgers.first().loan
        first_loan.loan_status_id = LoanStatusCodes.LOAN_90DPD
        first_loan.save()

        loan_dpd = LoanLenderTaggingDpdTemp.objects.filter(loan=first_loan).first()
        loan_dpd.loan_dpd = 90
        loan_dpd.save()

        last_loan = lender_loan_ledgers.last().loan
        last_loan.loan_status_id = LoanStatusCodes.LOAN_90DPD
        last_loan.save()

        loan_dpd = LoanLenderTaggingDpdTemp.objects.filter(loan=last_loan).first()
        loan_dpd.loan_dpd = 90
        loan_dpd.save()

        # lender 2 will be released by repayment only
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account2,
            tag_type=ChannelingLenderLoanLedgerConst.INITIAL_TAG,
        )
        first_loan = lender_loan_ledgers.first().loan
        PaymentFactory(
            payment_number=1,
            loan=first_loan,
            paid_principal=first_loan.loan_amount,
        )
        last_loan = lender_loan_ledgers.last().loan
        last_loan.loan_status_id = LoanStatusCodes.PAID_OFF
        last_loan.save()
        PaymentFactory(
            payment_number=1,
            loan=last_loan,
            paid_principal=250_000,
        )

        # lender3 will be repayment and dpd_90
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account3,
            tag_type=ChannelingLenderLoanLedgerConst.INITIAL_TAG,
        )
        first_loan = lender_loan_ledgers.first().loan
        first_loan.loan_status_id = LoanStatusCodes.LOAN_90DPD
        first_loan.save()
        loan_dpd = LoanLenderTaggingDpdTemp.objects.filter(loan=first_loan).first()
        loan_dpd.loan_dpd = 90
        loan_dpd.save()

        last_loan = lender_loan_ledgers.last().loan
        last_loan.loan_status_id = LoanStatusCodes.PAID_OFF
        last_loan.save()
        PaymentFactory(
            payment_number=1,
            loan=last_loan,
            paid_principal=last_loan.loan_amount,
        )

        daily_checker_loan_tagging_clone_task()
        daily_checker_loan_tagging_task()
        self.lender_osp_account.refresh_from_db()
        self.lender_osp_account2.refresh_from_db()
        self.lender_osp_account3.refresh_from_db()

        # FIRST LENDER
        # there was loan released by dpd_90
        released_dpd_90 = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90,
            lender_osp_account=self.lender_osp_account,
        ).exists()
        # there was amount reduced by payment
        repayment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF,
            lender_osp_account=self.lender_osp_account,
        ).exists()

        # there was new loan replacing those missing loan
        replenishment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
            lender_osp_account=self.lender_osp_account,
        ).exists()

        # check total balance
        self.assertTrue(self.lender_osp_account.total_outstanding_principal >= 5_750_000)
        self.assertTrue(self.lender_osp_account.fund_by_lender >= 5_000_000)
        self.assertTrue(self.lender_osp_account.fund_by_julo >= 750_000)
        self.assertTrue(released_dpd_90)
        self.assertFalse(repayment)
        self.assertTrue(replenishment)

        # SECOND LENDER
        # there was loan released by dpd_90
        released_dpd_90 = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90,
            lender_osp_account=self.lender_osp_account2,
        ).exists()
        # there was amount reduced by payment
        repayment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF,
            lender_osp_account=self.lender_osp_account2,
        ).exists()

        # there was new loan replacing those missing loan
        replenishment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
            lender_osp_account=self.lender_osp_account2,
        ).exists()

        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account2,
        )

        # check total balance
        self.assertTrue(self.lender_osp_account2.total_outstanding_principal >= 4_600_000)
        self.assertTrue(self.lender_osp_account2.fund_by_lender >= 4_000_000)
        self.assertTrue(self.lender_osp_account2.fund_by_julo >= 600_000)
        self.assertFalse(released_dpd_90)
        self.assertTrue(repayment)
        self.assertTrue(replenishment)

        # THIRD LENDER
        # there was loan released by dpd_90
        released_dpd_90 = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90,
            lender_osp_account=self.lender_osp_account3,
        ).exists()
        # there was amount reduced by payment
        repayment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF,
            lender_osp_account=self.lender_osp_account3,
        ).exists()

        # there was new loan replacing those missing loan
        replenishment = LenderLoanLedger.objects.filter(
            tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
            lender_osp_account=self.lender_osp_account3,
        ).exists()

        # check total balance
        self.assertTrue(self.lender_osp_account3.total_outstanding_principal >= 8_050_000)
        self.assertTrue(self.lender_osp_account3.fund_by_lender >= 7_000_000)
        self.assertTrue(self.lender_osp_account3.fund_by_julo >= 1_050_000)
        self.assertTrue(released_dpd_90)
        self.assertTrue(repayment)
        self.assertTrue(replenishment)


class TestReleaseLenderLoanLedgerARS(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.partner = PartnerFactory()
        self.lender = LenderCurrentFactory(lender_name='JTP', user=self.partner.user)
        self.current_ts = timezone.localtime(timezone.now())
        LenderTransactionType.objects.create(
            transaction_type=LenderTransactionTypeConst.CHANNELING_PREFUND_REJECT
        )

    @patch(
        'juloserver.channeling_loan.tasks.regenerate_summary_and_skrtp_agreement_for_ar_switching'
    )
    @patch('juloserver.followthemoney.services.get_available_balance')
    def test_loan_tagging_when_ars(
        self,
        mock_get_available_balance,
        regenerate_summary_skrtp_agreement_for_ar_switching
    ):
        """
        Covering:
        1. Change lender but lender still within list
        2. Change lender outside list
        3. Make sure when lender outside list is changed,
        not replacing tag when its not initial_tag / replenishment_tag
        """
        self.lender_osp_account = LenderOspAccountFactory(
            lender_withdrawal_percentage=100,
            lender_account_name="FAMA",
            balance_amount=50_000,
            priority=1,
            fund_by_julo=1000000,
            fund_by_lender=1000000,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOAN_TAGGING_CONFIG,
            is_active=True,
            parameters={
                "margin": 1000000,
                "loan_query_batch_size": 1000,
                "lenders": ["jtp"],
                "lenders_match_for_lender_osp_account": {
                    "BSS": ["jtp", "helicap"],
                    "FAMA": ["jtp", "helicap"],
                    "Lend East": ["jh"],
                    "Helicap": ["jh"],
                },
            },
        )
        partner_1 = PartnerFactory()
        partner_2 = PartnerFactory()
        partner_3 = PartnerFactory()
        self.lender = LenderCurrentFactory(
            lender_name='jtp', user=partner_1.user, is_manual_lender_balance=True
        )
        self.lender2 = LenderCurrentFactory(
            lender_name='helicap', user=partner_2.user, is_manual_lender_balance=True
        )
        self.lender3 = LenderCurrentFactory(
            lender_name='bf', user=partner_3.user, is_manual_lender_balance=True
        )
        self.loan.lender = self.lender
        self.loan.save()
        LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=2 * self.loan.loan_amount
        )

        LenderLoanLedgerFactory(
            loan_id=self.loan.id, loan_xid=self.loan.loan_xid, osp_amount=self.loan.loan_amount,
            tag_type=ChannelingLenderLoanLedgerConst.INITIAL_TAG,
            lender_osp_account=self.lender_osp_account,
        )

        self.loan2 = LoanFactory(lender=self.lender2)
        LenderBalanceCurrentFactory(
            lender=self.lender2, available_balance=2 * self.loan2.loan_amount
        )
        LenderLoanLedgerFactory(
            loan_id=self.loan2.id, loan_xid=self.loan2.loan_xid, osp_amount=self.loan2.loan_amount,
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90,
            lender_osp_account=self.lender_osp_account,
        )

        self.loan3 = LoanFactory(lender=self.lender2)
        LenderBalanceCurrentFactory(
            lender=self.lender3, available_balance=2 * self.loan3.loan_amount
        )
        LenderLoanLedgerFactory(
            loan_id=self.loan3.id, loan_xid=self.loan3.loan_xid, osp_amount=self.loan3.loan_amount,
            tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
            lender_osp_account=self.lender_osp_account,
        )
        mock_get_available_balance.return_value = 5 * self.loan3.loan_amount

        # Lender should be updated without releasing the Lender loan ledger
        update_loan_lender_task(
            self.loan.id, self.lender2.lender_name, 'test', 'test', None, None
        )
        lender_loan_ledger = LenderLoanLedger.objects.filter(loan=self.loan).last()
        self.assertEqual(lender_loan_ledger.tag_type, ChannelingLenderLoanLedgerConst.INITIAL_TAG)
        regenerate_summary_skrtp_agreement_for_ar_switching.delay.assert_called()

        # Lender should be updated and releasing the Lender loan ledger
        update_loan_lender_task(
            self.loan.id, self.lender3.lender_name, 'test', 'test', None, None
        )
        lender_loan_ledger.refresh_from_db()
        self.assertEqual(lender_loan_ledger.tag_type, ChannelingLenderLoanLedgerConst.RELEASED_BY_LENDER)
        old_balance = self.lender_osp_account.fund_by_lender
        self.lender_osp_account.refresh_from_db()
        self.assertEqual(self.lender_osp_account.fund_by_lender, old_balance - lender_loan_ledger.osp_amount)
        self.assertEqual(
            self.lender_osp_account.total_outstanding_principal,
            self.lender_osp_account.fund_by_lender + self.lender_osp_account.fund_by_julo
        )

        # should release reason should not be changed
        update_loan_lender_task(
            self.loan2.id, self.lender3.lender_name, 'test', 'test', None, None
        )
        lender_loan_ledger2 = LenderLoanLedger.objects.filter(loan=self.loan2).last()
        self.assertEqual(lender_loan_ledger2.tag_type, ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90)

        # replenishment_tag also should behave same as initial tag
        # Lender should be updated and releasing the Lender loan ledger
        update_loan_lender_task(
            self.loan3.id, self.lender.lender_name, 'test', 'test', None, None
        )
        lender_loan_ledger3 = LenderLoanLedger.objects.filter(loan=self.loan3).last()
        self.assertEqual(lender_loan_ledger3.tag_type, ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG)

        # Lender should be updated and releasing the Lender loan ledger
        update_loan_lender_task(
            self.loan3.id, self.lender3.lender_name, 'test', 'test', None, None
        )
        lender_loan_ledger3.refresh_from_db()
        self.assertEqual(lender_loan_ledger3.tag_type, ChannelingLenderLoanLedgerConst.RELEASED_BY_LENDER)
        old_balance = self.lender_osp_account.fund_by_lender
        self.lender_osp_account.refresh_from_db()
        self.assertEqual(self.lender_osp_account.fund_by_lender, old_balance - lender_loan_ledger.osp_amount)
        self.assertEqual(
            self.lender_osp_account.total_outstanding_principal,
            self.lender_osp_account.fund_by_lender + self.lender_osp_account.fund_by_julo
        )

    @patch('juloserver.channeling_loan.tasks.execute_after_transaction_safely')
    def test_regenerate_summary_and_skrtp_agreement_for_ar_switching(
        self, mock_execute_after_transaction_safely
    ):
        self.loan.lender = self.lender
        self.loan.save()
        regenerate_summary_and_skrtp_agreement_for_ar_switching(self.loan.pk)
        assert mock_execute_after_transaction_safely.call_count == 2


class TestSendLoanChannelingTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.loan = LoanFactory(
            application=self.application,
            account=self.account,
            fund_transfer_ts=timezone.localtime(timezone.now()),
            lender=LenderCurrentFactory(),
        )
        self.ineligibilities_feature = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_EDITABLE_INELIGIBILITIES,
            is_active=True,
            parameters={
                GeneralIneligible.ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT.name: True,
                GeneralIneligible.LOAN_HAS_INTEREST_BENEFIT.name: True,
                GeneralIneligible.HAVENT_PAID_OFF_A_LOAN.name: True,
                GeneralIneligible.HAVENT_PAID_OFF_AN_INSTALLMENT.name: True,
            }
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.BSS: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bss_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 15,
                        "RISK_PREMIUM_PERCENTAGE": 18,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.API_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": 59,
                        "MIN_AGE": 21,
                        "JOB_TYPE": ["Pegawai swasta", "Pegawai negeri", "Pengusaha"],
                        "MAX_LOAN": 15000000,
                        "MIN_LOAN": 500000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "INCOME_PROVE": False,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "INCLUDE_LOAN_ADJUSTED": False,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 18,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "INCLUDE_LOAN_ADJUSTED": False,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                },
            },
        )

    @patch("juloserver.channeling_loan.tasks.loan_risk_acceptance_criteria_check")
    @patch("juloserver.channeling_loan.tasks.retroload_address")
    @patch("juloserver.channeling_loan.tasks.get_fama_channeling_admin_fee")
    @patch("juloserver.channeling_loan.tasks.send_loan_for_channeling_to_bss_task")
    @patch("juloserver.channeling_loan.tasks.is_channeling_lender_dashboard_active")
    @patch("juloserver.channeling_loan.services.general_services.update_channeling_loan_status")
    @patch("juloserver.channeling_loan.services.general_services.is_loan_is_zero_interest")
    @patch("juloserver.channeling_loan.services.general_services.is_account_had_loan_paid_off")
    @patch("juloserver.channeling_loan.services.general_services.is_account_had_installment_paid_off")
    @patch("juloserver.channeling_loan.services.general_services.is_account_status_entered_gt_420")
    @patch("juloserver.channeling_loan.services.general_services.check_if_loan_has_promo_benefit_type")
    @patch("juloserver.channeling_loan.services.general_services.loan_from_partner")
    @patch("juloserver.account.models.Account.is_account_eligible_to_hit_channeling_api")
    @patch("juloserver.channeling_loan.tasks.initiate_channeling_loan_status")
    @patch("juloserver.channeling_loan.tasks.get_selected_channeling_type")
    def test_send_loan_channeling_with_general_ineligibilities(
        self,
        mock_get_selected_channeling_type,
        mock_initiate_channeling_loan_status,
        mock_is_acc_eligible_to_hit_api,
        mock_loan_from_partner,
        mock_if_loan_has_promo_benefit_type,
        mock_is_account_status_entered_gt_420,
        mock_is_account_had_installment_paid_off,
        mock_is_account_had_loan_paid_off,
        mock_is_loan_is_zero_interest,
        mock_update_channeling_loan_status,
        mock_is_channeling_lender_dashboard_active,
        mock_send_loan_for_channeling_to_bss_task,
        mock_get_fama_channeling_admin_fee,
        mock_retroload_address,
        mock_loan_risk_acceptance_criteria_check,
    ):
        def _reset_to_eligible():
            # default so that it's all eligible
            mock_is_account_had_loan_paid_off.return_value = True
            mock_is_account_had_installment_paid_off.return_value = True
            mock_is_account_status_entered_gt_420.return_value = False
            mock_is_acc_eligible_to_hit_api.return_value = True
            mock_if_loan_has_promo_benefit_type.return_value = False
            mock_loan_from_partner.return_value = False
            mock_is_loan_is_zero_interest.return_value = False
            LoanAdjustedRate.objects.filter(loan=self.loan).delete()

        mock_loan_risk_acceptance_criteria_check.return_value = True, ""
        # test zero interest
        _reset_to_eligible()
        mock_is_loan_is_zero_interest.return_value = True
        send_loan_for_channeling_task(self.loan.id)
        mock_is_loan_is_zero_interest.assert_called_once()
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.ZERO_INTEREST_LOAN_NOT_ALLOWED.message,
        )

        # test paid off loan
        _reset_to_eligible()
        mock_is_account_had_loan_paid_off.return_value = False
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.HAVENT_PAID_OFF_A_LOAN.message,
        )

        # test paid off installment
        _reset_to_eligible()
        mock_is_account_had_installment_paid_off.return_value = False
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.HAVENT_PAID_OFF_AN_INSTALLMENT.message,
        )

        # test account got 420
        _reset_to_eligible()
        mock_is_account_status_entered_gt_420.return_value = True
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT.message,
        )

        # test autodebit benefit
        _reset_to_eligible()
        mock_is_acc_eligible_to_hit_api.return_value = False
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.AUTODEBIT_INTEREST_BENEFIT.message,
        )

        # test promo interest benefit
        _reset_to_eligible()
        mock_if_loan_has_promo_benefit_type.return_value = True
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.LOAN_HAS_INTEREST_BENEFIT.message,
        )

        # test partner loan
        _reset_to_eligible()
        mock_loan_from_partner.return_value = True
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.LOAN_FROM_PARTNER.message,
        )

        # test loan adjusted rate
        self.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.BSS: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bss_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 15,
                        "RISK_PREMIUM_PERCENTAGE": 18,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.API_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": 59,
                        "MIN_AGE": 21,
                        "JOB_TYPE": ["Pegawai swasta", "Pegawai negeri", "Pengusaha"],
                        "MAX_LOAN": 15000000,
                        "MIN_LOAN": 500000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": False,
                        "HAS_KTP_OR_SELFIE": False,
                        "MOTHER_MAIDEN_NAME": False,
                        "INCLUDE_LOAN_ADJUSTED": False,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 18,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": False,
                        "HAS_KTP_OR_SELFIE": False,
                        "MOTHER_MAIDEN_NAME": False,
                        "INCLUDE_LOAN_ADJUSTED": False,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
                ChannelingConst.PERMATA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "permata_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 0,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
            },
        )
        mock_get_selected_channeling_type.return_value = (
            [ChannelingConst.BSS, ChannelingConst.FAMA],
            self.feature_setting.parameters,
        )
        _reset_to_eligible()
        LoanAdjustedRate.objects.create(
            loan=self.loan,
            adjusted_monthly_interest_rate=0,
            adjusted_provision_rate=0,
            max_fee=0,
            simple_fee=0,
        )
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.LOAN_ADJUSTED_RATE.message,
        )

        _reset_to_eligible()
        # LoanAdjustedRate blocked with SETTING on
        LoanAdjustedRate.objects.create(
            loan=self.loan,
            adjusted_monthly_interest_rate=0.3,
            adjusted_provision_rate=0,
            max_fee=0,
            simple_fee=0,
        )
        self.feature_setting.parameters[ChannelingConst.BSS]['rac']['INCLUDE_LOAN_ADJUSTED'] = True
        self.feature_setting.save()
        mock_get_selected_channeling_type.return_value = (
            [ChannelingConst.BSS, ChannelingConst.FAMA],
            self.feature_setting.parameters,
        )
        mock_update_channeling_loan_status.return_value = None
        mock_is_channeling_lender_dashboard_active.return_value = True
        mock_send_loan_for_channeling_to_bss_task.return_value = None
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.BSS,
            '',
        )

        # all editable conditions passed
        _reset_to_eligible()
        mock_get_selected_channeling_type.return_value = (None, None)
        send_loan_for_channeling_task(self.loan.id)
        mock_initiate_channeling_loan_status.assert_called_with(
            self.loan,
            ChannelingConst.GENERAL,
            GeneralIneligible.CHANNELING_TARGET_MISSING.message,
        )

        # success case
        _reset_to_eligible()
        mock_get_selected_channeling_type.return_value = (
            [ChannelingConst.FAMA],
            self.feature_setting.parameters,
        )
        self.loan.transaction_method_id = 1
        self.loan.save()
        mock_get_fama_channeling_admin_fee.return_value = True
        return_value = send_loan_for_channeling_task(self.loan.id)
        mock_get_fama_channeling_admin_fee.assert_called_once()

        # check permata address updated
        _reset_to_eligible()
        mock_get_selected_channeling_type.return_value = (
            [ChannelingConst.PERMATA],
            self.feature_setting.parameters,
        )
        self.loan.transaction_method_id = 1
        self.loan.save()
        mock_get_fama_channeling_admin_fee.return_value = True
        send_loan_for_channeling_task(self.loan.id)
        mock_retroload_address.assert_called()


# send_loan_for_channeling_task
class TestTaskSendLoanChanneling(TestCase):
    @classmethod
    def setUp(cls):
        transaction_method = TransactionMethod.objects.filter(
            id=TransactionMethodCode.SELF.code
        ).last()
        if transaction_method:
            transaction_method.delete()

        cls.all_feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.BSS: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bss_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 15,
                        "RISK_PREMIUM_PERCENTAGE": 18,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.API_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": 59,
                        "MIN_AGE": 21,
                        "JOB_TYPE": ["Pegawai swasta", "Pegawai negeri", "Pengusaha"],
                        "MAX_LOAN": 15000000,
                        "MIN_LOAN": 500000,
                        "MAX_RATIO": 0.3,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": False,
                        "HAS_KTP_OR_SELFIE": False,
                        "MOTHER_MAIDEN_NAME": False,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
                ChannelingConst.BJB: {
                    "is_active": False,
                    "general": {
                        "LENDER_NAME": "bjb_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 0,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 50,
                    },
                    "force_update": {
                        "is_active": False,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 0,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                },
            },
        )
        cls.channeling_loan_priority = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_PRIORITY,
            is_active=True,
            parameters=["BJB", "BSS"],
        )
        cls.disbursement = DisbursementFactory()
        cls.lender = LenderCurrentFactory(
            xfers_token="xfers_tokenforlender", lender_name="bss_channeling"
        )
        cls.account = AccountFactory()
        cls.transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.SELF.code,
        )
        cls.loan = LoanFactory(
            application=None,
            account=cls.account,
            lender=cls.lender,
            disbursement_id=cls.disbursement.id,
            fund_transfer_ts=timezone.localtime(timezone.now()),
            transaction_method=cls.transaction_method,
        )
        LenderBalanceCurrentFactory(lender=cls.lender, available_balance=2 * cls.loan.loan_amount)
        cls.application = ApplicationFactory(
            account=cls.account,
            marital_status="Menikah",
            last_education="SD",
            address_kabupaten="Kab. Bekasi",
        )
        cls.feature_setting = FeatureSettingFactory(feature_name="bss_channeling_mock_response")
        cls.today = timezone.localtime(timezone.now())
        FeatureSettingFactory(
            feature_name="mock_available_balance",
            is_active=True,
            parameters={"available_balance": 1000000000},
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.BSS_CHANNELING, is_active=True, parameters={}
        )
        LenderTransactionType.objects.create(transaction_type=LenderTransactionTypeConst.CHANNELING)
        cls.channeling_eligibility_status = ChannelingEligibilityStatus.objects.create(
            application=cls.application,
            channeling_type=ChannelingConst.BSS,
            eligibility_status=ChannelingStatusConst.ELIGIBLE,
        )
        cls.channeling_loan_status = ChannelingLoanStatus.objects.create(
            channeling_eligibility_status=cls.channeling_eligibility_status,
            loan=cls.loan,
            channeling_type=ChannelingConst.BSS,
            channeling_status=ChannelingStatusConst.PENDING,
            channeling_interest_amount=0.5 * cls.loan.loan_amount,
        )
        cls.loan2 = LoanFactory(
            application=None,
            account=cls.account,
            lender=cls.lender,
            disbursement_id=cls.disbursement.id,
            fund_transfer_ts=timezone.localtime(timezone.now()),
            transaction_method=cls.transaction_method,
        )

    @patch('juloserver.channeling_loan.tasks.loan_risk_acceptance_criteria_check')
    @patch('juloserver.channeling_loan.tasks.send_loan_for_channeling_to_bss_task')
    @patch('juloserver.channeling_loan.tasks.get_general_channeling_ineligible_conditions')
    def test_bss_lender_dashboard_disabled(
        cls,
        mock_get_conditions,
        mock_send_loan_for_channeling_to_bss_task,
        mock_loan_risk_acceptance_criteria_check,
    ):
        # if disabled, function send_loan_for_channeling_to_bss_task must be called
        mock_loan_risk_acceptance_criteria_check.return_value = True, "test"
        mock_get_conditions.return_value = {}
        send_loan_for_channeling_task(cls.loan2.id)
        mock_send_loan_for_channeling_to_bss_task.assert_called_once()

    @patch('juloserver.channeling_loan.tasks.loan_risk_acceptance_criteria_check')
    @patch('juloserver.channeling_loan.tasks.send_loan_for_channeling_to_bss_task')
    def test_bss_lender_dashboard_enabled(
        cls, mock_send_loan_for_channeling_to_bss_task, mock_loan_risk_acceptance_criteria_check
    ):
        # if enabled, function send_loan_for_channeling_to_bss_task must not called
        mock_loan_risk_acceptance_criteria_check.return_value = True, "test"
        cls.all_feature_setting.parameters[ChannelingConst.BSS]["lender_dashboard"][
            "is_active"
        ] = True
        cls.all_feature_setting.save()
        send_loan_for_channeling_task(cls.loan.id)
        mock_send_loan_for_channeling_to_bss_task.assert_not_called()

    @patch('juloserver.channeling_loan.tasks.loan_risk_acceptance_criteria_check')
    def test_bss_lender_dashboard_enabled_zero_interest(
        cls, mock_loan_risk_acceptance_criteria_check
    ):
        cls.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.ZERO_INTEREST_HIGHER_PROVISION,
            parameters={
                "condition": {
                    "min_loan_amount": 30_000,
                    "max_loan_amount": 1_000_000,
                    "min_duration": 1,
                    "max_duration": 3,
                    "list_transaction_method_code": ['1', '2'],
                },
                "whitelist": {
                    "is_active": False,
                    "list_customer_id": [],
                },
                "is_experiment_for_last_digit_customer_id_is_even": False,
                "customer_segments": {"is_ftc": True, "is_repeat": True},
            },
            is_active=True,
            category="Loan",
            description="Test",
        )
        mock_loan_risk_acceptance_criteria_check.return_value = True, "test"
        cls.all_feature_setting.parameters[ChannelingConst.BSS]["lender_dashboard"][
            "is_active"
        ] = True
        cls.all_feature_setting.save()
        LoanZeroInterestFactory(loan=cls.loan)
        res = send_loan_for_channeling_task(cls.loan.id)
        cls.assertEqual(res, False)

    @patch('juloserver.channeling_loan.tasks.check_disburse_transaction_task.apply_async')
    @patch('juloserver.channeling_loan.tasks.send_loan_for_channeling_to_bss')
    def test_send_loan_for_channeling_to_bss_task(
        cls, mock_send_loan_for_channeling_to_bss, mock_check_disburse_transaction_task
    ):
        channeling_type = ChannelingConst.BSS
        channeling_loan_config = cls.all_feature_setting.parameters
        mock_send_loan_for_channeling_to_bss.return_value = (
            ChannelingStatusConst.SUCCESS,
            {},
            ChannelingConst.DEFAULT_INTERVAL,
        )
        send_loan_for_channeling_to_bss_task(
            [cls.loan.id], channeling_loan_config[channeling_type], channeling_type
        )
        cls.assertEqual(mock_check_disburse_transaction_task.call_count, 0)

    @patch('juloserver.channeling_loan.tasks.check_disburse_transaction_task.apply_async')
    @patch('juloserver.channeling_loan.tasks.send_loan_for_channeling_to_bss')
    def test_send_loan_for_channeling_to_bss_task_retry(
        cls, mock_send_loan_for_channeling_to_bss, mock_check_disburse_transaction_task
    ):
        channeling_type = ChannelingConst.BSS
        channeling_loan_config = cls.all_feature_setting.parameters
        mock_send_loan_for_channeling_to_bss.return_value = (
            ChannelingStatusConst.RETRY,
            {},
            ChannelingConst.DEFAULT_INTERVAL,
        )
        send_loan_for_channeling_to_bss_task(
            [cls.loan.id], channeling_loan_config[channeling_type], channeling_type
        )

        cls.assertEqual(mock_check_disburse_transaction_task.call_count, 1)

    @patch('juloserver.channeling_loan.tasks.get_general_channeling_ineligible_conditions')
    @patch('juloserver.channeling_loan.tasks.is_holdout_users_from_bss_channeling')
    @patch('juloserver.channeling_loan.tasks.get_selected_channeling_type')
    @patch('juloserver.channeling_loan.tasks.filter_loan_adjusted_rate')
    @patch('juloserver.channeling_loan.tasks.get_channeling_eligibility_status')
    @patch('juloserver.channeling_loan.tasks.initiate_channeling_loan_status')
    @patch('juloserver.channeling_loan.tasks.loan_risk_acceptance_criteria_check')
    @patch("juloserver.channeling_loan.tasks.is_channeling_lender_dashboard_active")
    @patch("juloserver.channeling_loan.tasks.send_loans_for_channeling_to_dbs_task")
    def test_trigger_send_loans_for_channeling_to_dbs_task(
        self,
        mock_send_loans_for_channeling_to_dbs_task,
        mock_is_channeling_lender_dashboard_active,
        mock_loan_risk_acceptance_criteria_check,
        mock_initiate_channeling_loan_status,
        mock_get_channeling_eligibility_status,
        mock_filter_loan_adjusted_rate,
        mock_get_selected_channeling_type,
        mock_is_holdout_users_from_bss_channeling,
        mock_get_general_channeling_ineligible_conditions,
    ):
        mock_get_general_channeling_ineligible_conditions.return_value = {}
        mock_is_holdout_users_from_bss_channeling.return_value = False
        temp = BASE_ELEMENT_VALUE_CHANNELING_CONFIGURATION
        temp['general']['CHANNELING_TYPE'] = 'api'
        mock_get_selected_channeling_type.return_value = (
            ['DBS'],
            {'DBS': temp},
        )
        mock_filter_loan_adjusted_rate.return_value = ['DBS']
        mock_get_channeling_eligibility_status.return_value = ChannelingEligibilityStatusFactory()
        mock_initiate_channeling_loan_status.return_value = ChannelingLoanStatusFactory(
            channeling_status="eligible"
        )
        mock_loan_risk_acceptance_criteria_check.return_value = (True, "test")
        mock_is_channeling_lender_dashboard_active.return_value = False

        send_loan_for_channeling_task(loan_id=self.loan.id)
        mock_send_loans_for_channeling_to_dbs_task.assert_called_once_with(loan_ids=[self.loan.id])


class TestChannelingLoanWriteOff(TestCase):
    @classmethod
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.lender = LenderCurrentFactory(lender_name='jtp')
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=self.application,
            lender=self.lender,
        )
        self.user_auth = AuthUserFactory()
        self.channeling_type = ChannelingConst.BSS

        self.data_frame = pd.DataFrame(
            [
                [1, '123456111111', 'a'],
                [2, '123456222222', 'b'],
                [3, '123456333333', 'c'],
            ],
            columns=["No", "rek_loan", "Nama Debitur"],
        )

    def test_insert_loan_write_off(self):
        insert_loan_write_off([self.loan.id], self.channeling_type, None, None, None)

        inserted = ChannelingLoanWriteOff.objects.filter(loan_id=self.loan.id).exists()
        self.assertTrue(inserted)

    def test_update_loan_write_off(self):
        channeling_write_off = ChannelingLoanWriteOff.objects.create(
            loan_id=self.loan.id,
            is_write_off=False,
            channeling_type=self.channeling_type,
        )
        update_loan_write_off([channeling_write_off.id], self.channeling_type, None, None, None)
        updated = ChannelingLoanWriteOff.objects.filter(
            loan_id=self.loan.id,
            is_write_off=True,
        ).exists()
        self.assertTrue(updated)

    @patch('juloserver.channeling_loan.tasks.insert_loan_write_off.delay')
    @patch('juloserver.channeling_loan.tasks.construct_channeling_url_reader')
    def test_process_loan_write_off_task(
        self, mock_construct_channeling_url_reader, mock_insert_loan_write_off
    ):
        form_data = {'url_field': 'test_url', 'lender_name': 'jh'}
        reason = "Write off by test batch:20230404050800"

        reader = mock.MagicMock()
        reader.empty = False
        reader.iterrows.return_value = self.data_frame.iterrows()
        mock_construct_channeling_url_reader.return_value = reader

        self.loan.loan_xid = '111111'
        self.loan.save()

        ChannelingLoanStatus.objects.create(
            loan=self.loan,
            channeling_type=ChannelingConst.BSS,
            channeling_status=ChannelingStatusConst.SUCCESS,
        )

        process_loan_write_off_task(
            self.user_auth.username,
            None,
            form_data,
            reason,
            self.channeling_type,
            self.user_auth.pk,
        )
        mock_insert_loan_write_off.assert_called_once()


class TestChannelingLenderSwitching(TestCase):
    @classmethod
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.lender = LenderCurrentFactory(lender_name='jtp')
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            application=self.application,
            lender=self.lender,
        )
        self.user_auth = AuthUserFactory()
        self.channeling_type = ChannelingConst.BSS

        self.data_frame = pd.DataFrame(
            [
                [1, '123456111111', 'Not Ok'],
                [2, '123456' + str(self.loan.loan_xid), 'Ok'],
                [3, '123456333333', 'Not Ok'],
            ],
            columns=["No", "Refno", "Status"],
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.BSS: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "bss_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 15,
                        "RISK_PREMIUM_PERCENTAGE": 18,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.API_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": 59,
                        "MIN_AGE": 21,
                        "JOB_TYPE": ["Pegawai swasta", "Pegawai negeri", "Pengusaha"],
                        "MAX_LOAN": 15000000,
                        "MIN_LOAN": 500000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": 9,
                        "MIN_TENOR": 1,
                        "MIN_INCOME": 2000000,
                        "MIN_WORKTIME": 3,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": False,
                        "HAS_KTP_OR_SELFIE": False,
                        "MOTHER_MAIDEN_NAME": False,
                        "INCLUDE_LOAN_ADJUSTED": False,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": False,
                        "OPENING_TIME": {"hour": 7, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 19, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": [],
                        "LIMIT": None,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                },
            },
        )

    @patch('juloserver.channeling_loan.tasks.process_lender_switch_task.delay')
    @patch('juloserver.julo.tasks.upload_document')
    def test_process_upload_lender_switch_file(
        self, mock_upload_document, mock_process_lender_switch_task
    ):
        document = DocumentFactory(
            url='test/path/file.txt', filename='test_file.txt', document_type='channeling'
        )
        process_upload_lender_switch_file(
            'test', self.data_frame, "batch:1", document.pk, "", self.channeling_type
        )
        mock_process_lender_switch_task.assert_called()

    @patch('juloserver.channeling_loan.tasks.update_loan_lender_task.delay')
    @patch("juloserver.channeling_loan.tasks.send_notification_to_slack")
    @patch('juloserver.channeling_loan.tasks.construct_channeling_url_reader')
    def test_process_lender_switch_task_pending(
        self,
        mock_construct_channeling_url_reader,
        mock_send_notification_to_slack,
        mock_update_loan_lender_task,
    ):
        reader = mock.MagicMock()
        reader.empty = False
        reader.iterrows.return_value = self.data_frame.iterrows()
        mock_construct_channeling_url_reader.return_value = reader

        document = DocumentFactory(
            url='test/path/file.txt', filename='test_file.txt', document_type='channeling'
        )
        channeling_loan_status = ChannelingLoanStatus.objects.create(
            loan_id=self.loan.pk,
            channeling_type=self.channeling_type,
            channeling_status=ChannelingStatusConst.PENDING,
        )
        process_lender_switch_task(
            'test', document.pk, {'url_field': None}, "batch:1", self.channeling_type
        )
        mock_update_loan_lender_task.assert_not_called()

    @patch('juloserver.channeling_loan.tasks.update_loan_lender_task.delay')
    @patch("juloserver.channeling_loan.tasks.approve_loan_for_channeling")
    @patch('juloserver.channeling_loan.tasks.construct_channeling_url_reader')
    def test_process_lender_switch_task(
        self,
        mock_construct_channeling_url_reader,
        mock_approve_loan_for_channeling,
        mock_update_loan_lender_task,
    ):
        reader = mock.MagicMock()
        reader.empty = False
        reader.iterrows.return_value = self.data_frame.iterrows()
        mock_construct_channeling_url_reader.return_value = reader

        document = DocumentFactory(
            url='test/path/file.txt', filename='test_file.txt', document_type='channeling'
        )
        channeling_loan_status = ChannelingLoanStatus.objects.create(
            loan_id=self.loan.pk,
            channeling_type=self.channeling_type,
            channeling_status=ChannelingStatusConst.PROCESS,
        )
        process_lender_switch_task(
            'test', document.pk, {'url_field': None}, "batch:1", self.channeling_type
        )
        channeling_loan_status.refresh_from_db()
        mock_update_loan_lender_task.assert_called_once()
        mock_approve_loan_for_channeling.assert_called_once()

class TestProcessApprovalResponseTask(TestCase):
    @patch('juloserver.channeling_loan.tasks.download_latest_fama_approval_file_from_sftp_server')
    @patch('juloserver.channeling_loan.tasks.decrypt_data')
    @patch('juloserver.channeling_loan.tasks.convert_fama_approval_content_from_txt_to_csv')
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.store_data_and_notify_slack'
    )
    @patch('juloserver.channeling_loan.tasks.process_fama_approval_response.apply_async')
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.send_exceed_max_retry_slack_notification'
    )
    @patch('juloserver.channeling_loan.tasks.upload_approval_file_to_oss_and_create_document')
    @patch('juloserver.channeling_loan.tasks.mark_approval_file_processed')
    def test_process_fama_approval_response(
        self,
        mock_mark,
        mock_upload,
        mock_repayment_exceed_retry_slack,
        mock_repayment_retry,
        mock_repayment_store,
        mock_convert,
        mock_decrypt,
        mock_download,
    ):
        # Test case 1: No file found
        mock_download.return_value = (None, None)
        process_fama_approval_response(file_type='test_file_type', approval_file_id=1)
        mock_mark.assert_called_once_with(approval_file_id=1)
        mock_mark.reset_mock()

        # Test case 2: Decryption failed
        mock_download.return_value = ('encrypted.txt.gpg', b'encrypted_data')
        mock_decrypt.return_value = None
        process_fama_approval_response(file_type='test_file_type', approval_file_id=1)
        mock_mark.assert_called_once_with(approval_file_id=1)
        mock_mark.reset_mock()

        # Test case 3: Non-disbursement file type
        mock_download.return_value = ('encrypted.txt.gpg', b'encrypted_data')
        mock_decrypt.return_value = 'decrypted_content'
        mock_upload.return_value = 2
        process_fama_approval_response(file_type='test_file_type', approval_file_id=1)
        mock_upload.assert_called_once_with(
            channeling_type=ChannelingConst.FAMA,
            file_type='test_file_type',
            filename='encrypted.txt',
            approval_file_id=1,
            content='decrypted_content',
        )
        mock_mark.assert_called_once_with(approval_file_id=1, document_id=2)
        mock_upload.reset_mock()
        mock_mark.reset_mock()

        # Test case 4: Disbursement file type
        mock_convert.return_value = 'converted_csv_content'
        process_fama_approval_response(ChannelingActionTypeConst.DISBURSEMENT, 1)
        mock_convert.assert_called_once_with(content='decrypted_content')
        mock_upload.assert_called_once_with(
            channeling_type=ChannelingConst.FAMA,
            file_type=ChannelingActionTypeConst.DISBURSEMENT,
            filename='encrypted.csv',
            approval_file_id=1,
            content='converted_csv_content',
        )
        mock_mark.assert_called_once_with(approval_file_id=1, document_id=2)

        # Test case 5: Repayment file type
        mock_repayment_store.return_value = True
        process_fama_approval_response(ChannelingActionTypeConst.REPAYMENT, 1)
        mock_repayment_store.assert_called_once()
        mock_repayment_retry.assert_not_called()
        mock_repayment_exceed_retry_slack.assert_not_called()

        # Test case 6: Repayment file type and retry
        mock_repayment_store.reset_mock()
        mock_repayment_store.return_value = False
        process_fama_approval_response(ChannelingActionTypeConst.REPAYMENT, 1, 2)
        mock_repayment_store.assert_called_once()
        mock_repayment_retry.assert_called_once()
        mock_repayment_exceed_retry_slack.assert_not_called()

        # Test case 7: Repayment file type and exceed max retry
        mock_repayment_store.reset_mock()
        mock_repayment_store.return_value = False
        mock_repayment_retry.reset_mock()
        process_fama_approval_response(ChannelingActionTypeConst.REPAYMENT, 1, 3)
        mock_repayment_store.assert_called_once()
        mock_repayment_retry.assert_not_called()
        mock_repayment_exceed_retry_slack.assert_called_once()

    @patch('juloserver.channeling_loan.tasks.download_latest_file_from_sftp_server')
    @patch('juloserver.channeling_loan.tasks.decrypt_data')
    @patch('juloserver.channeling_loan.tasks.upload_approval_file_to_oss_and_create_document')
    @patch('juloserver.channeling_loan.tasks.mark_approval_file_processed')
    def test_process_dbs_approval_response(
        self, mock_mark, mock_upload, mock_decrypt, mock_download
    ):
        # Test case 1: No file found
        mock_download.return_value = (None, None)
        process_dbs_approval_response(file_type='test_file_type', approval_file_id=1)
        mock_mark.assert_called_once_with(approval_file_id=1)
        mock_mark.reset_mock()

        # Test case 2: Decryption failed
        mock_download.return_value = ('encrypted.txt.gpg', b'encrypted_data')
        mock_decrypt.return_value = None
        process_dbs_approval_response(file_type='test_file_type', approval_file_id=1)
        mock_mark.assert_called_once_with(approval_file_id=1)
        mock_mark.reset_mock()

        # Test case 3: Repayment file type
        mock_download.return_value = ('encrypted.txt.gpg', b'encrypted_data')
        mock_decrypt.return_value = 'decrypted_content'
        mock_upload.return_value = 2
        process_dbs_approval_response(file_type='test_file_type', approval_file_id=1)
        mock_upload.assert_called_once_with(
            channeling_type=ChannelingConst.DBS,
            file_type='test_file_type',
            filename='encrypted.txt',
            approval_file_id=1,
            content='decrypted_content',
        )
        mock_mark.assert_called_once_with(approval_file_id=1, document_id=2)
        mock_upload.reset_mock()
        mock_mark.reset_mock()

    @patch('juloserver.channeling_loan.tasks.construct_permata_disbursement_approval_file')
    @patch('juloserver.channeling_loan.tasks.construct_permata_single_approval_file')
    @patch('juloserver.channeling_loan.tasks.upload_approval_file_to_oss_and_create_document')
    @patch('juloserver.channeling_loan.tasks.mark_approval_file_processed')
    def process_permata_approval_response(
        self, mock_mark_processed, mock_upload, mock_single_response, mock_disbursement_response
    ):
        # Test disbursement approval
        mock_disbursement_response.return_value = ('disbursement_file.csv', 'content')
        mock_upload.return_value = 123  # document_id

        process_permata_approval_response(
            file_type=PermataChannelingConst.FILE_TYPE_DISBURSEMENT, approval_file_id=456
        )

        mock_disbursement_response.assert_called_once()
        mock_single_response.assert_not_called()
        mock_upload.assert_called_once_with(
            channeling_type=ChannelingConst.PERMATA,
            file_type=PermataChannelingConst.FILE_TYPE_DISBURSEMENT,
            filename='disbursement_file.csv',
            approval_file_id=456,
            content='content',
        )
        mock_mark_processed.assert_called_once_with(approval_file_id=456, document_id=123)

        # Test not disbursement approval
        mock_upload.reset_mock()
        mock_mark_processed.reset_mock()
        mock_single_response.return_value = ('repayment_file.txt', 'content')
        mock_upload.return_value = 789  # document_id

        process_permata_approval_response(
            file_type=PermataChannelingConst.FILE_TYPE_REPAYMENT, approval_file_id=567
        )

        mock_disbursement_response.assert_not_called()
        mock_single_response.assert_called_once_with(
            filename_prefix=PermataChannelingConst.REPAYMENT_FILENAME_PREFIX
        )
        mock_upload.assert_called_once_with(
            channeling_type=ChannelingConst.PERMATA,
            file_type=PermataChannelingConst.FILE_TYPE_REPAYMENT,
            filename='repayment_file.txt',
            approval_file_id=567,
            content='content',
        )
        mock_mark_processed.assert_called_once_with(approval_file_id=567, document_id=789)

        # Test unknown file type
        mock_upload.reset_mock()
        mock_mark_processed.reset_mock()
        mock_single_response.return_value = (None, None)
        mock_disbursement_response.return_value = (None, None)

        process_permata_approval_response(file_type='UNKNOWN_FILE_TYPE', approval_file_id=999)

        mock_single_response.assert_not_called()
        mock_disbursement_response.assert_not_called()
        mock_upload.assert_not_called()
        mock_mark_processed.assert_called_once_with(approval_file_id=999)


class TestFAMACutOff(TestCase):
    @classmethod
    def setUp(cls):
        cls.all_feature_setting = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
            is_active=True,
            parameters={
                ChannelingConst.FAMA: {
                    "is_active": True,
                    "general": {
                        "LENDER_NAME": "fama_channeling",
                        "BUYBACK_LENDER_NAME": "jh",
                        "EXCLUDE_LENDER_NAME": ["ska", "gfin", "helicap", "ska2"],
                        "INTEREST_PERCENTAGE": 14,
                        "RISK_PREMIUM_PERCENTAGE": 0,
                        "DAYS_IN_YEAR": 360,
                        "CHANNELING_TYPE": ChannelingConst.MANUAL_CHANNELING_TYPE,
                    },
                    "rac": {
                        "TENOR": "Monthly",
                        "MAX_AGE": None,
                        "MIN_AGE": None,
                        "JOB_TYPE": [],
                        "MAX_LOAN": 20000000,
                        "MIN_LOAN": 1000000,
                        "MAX_RATIO": None,
                        "MAX_TENOR": None,
                        "MIN_TENOR": None,
                        "MIN_INCOME": None,
                        "MIN_WORKTIME": 24,
                        "TRANSACTION_METHOD": ['1', '2', '3', '4', '5', '6', '7', '12', '11', '16'],
                        "INCOME_PROVE": True,
                        "HAS_KTP_OR_SELFIE": True,
                        "MOTHER_MAIDEN_NAME": True,
                        "VERSION": 2,
                    },
                    "cutoff": {
                        "is_active": True,
                        "OPENING_TIME": {"hour": 1, "minute": 0, "second": 0},
                        "CUTOFF_TIME": {"hour": 9, "minute": 0, "second": 0},
                        "INACTIVE_DATE": [],
                        "INACTIVE_DAY": ["Saturday", "Sunday"],
                        "LIMIT": 1,
                        "CHANNEL_AFTER_CUTOFF": True,
                    },
                    "force_update": {
                        "is_active": True,
                        "VERSION": 2,
                    },
                    "due_date": {"is_active": False, "ESCLUSION_DAY": [25, 26]},
                    "credit_score": {"is_active": False, "SCORE": ["A", "B-"]},
                    "b_score": {"is_active": False, "MAX_B_SCORE": None, "MIN_B_SCORE": None},
                    "whitelist": {"is_active": False, "APPLICATIONS": []},
                    "lender_dashboard": {"is_active": False},
                }
            },
        )
        cls.channeling_loan_priority = FeatureSettingFactory(
            feature_name=ChannelingFeatureNameConst.CHANNELING_PRIORITY,
            is_active=True,
            parameters=["FAMA"],
        )
        cls.disbursement = DisbursementFactory()
        cls.lender = LenderCurrentFactory(xfers_token="xfers_tokenforlender", lender_name="fama")
        cls.account = AccountFactory()
        cls.transaction_method = TransactionMethod.objects.filter(
            pk=TransactionMethodCode.SELF.code
        ).first()
        if not cls.transaction_method:
            cls.transaction_method = TransactionMethodFactory(
                id=TransactionMethodCode.SELF.code,
            )
        cls.loan = LoanFactory(
            application=None,
            account=cls.account,
            lender=cls.lender,
            disbursement_id=cls.disbursement.id,
            fund_transfer_ts=timezone.localtime(timezone.now()),
            transaction_method=cls.transaction_method,
            loan_duration=3,
        )
        LenderBalanceCurrentFactory(lender=cls.lender, available_balance=2 * cls.loan.loan_amount)
        cls.application = ApplicationFactory(
            account=cls.account,
            marital_status="Menikah",
            last_education="SD",
            address_kabupaten="Kab. Bekasi",
        )
        cls.today = timezone.localtime(timezone.now())
        LenderTransactionType.objects.create(transaction_type=LenderTransactionTypeConst.CHANNELING)
        cls.channeling_eligibility_status = ChannelingEligibilityStatus.objects.create(
            application=cls.application,
            channeling_type=ChannelingConst.FAMA,
            eligibility_status=ChannelingStatusConst.ELIGIBLE,
        )
        cls.channeling_loan_status = ChannelingLoanStatus.objects.create(
            channeling_eligibility_status=cls.channeling_eligibility_status,
            loan=cls.loan,
            channeling_type=ChannelingConst.FAMA,
            channeling_status=ChannelingStatusConst.PENDING,
            channeling_interest_amount=0.5 * cls.loan.loan_amount,
        )
        cls.channeling_loan_payment = ChannelingLoanPaymentFactory(
            payment=cls.loan.payment_set.first(),
            interest_amount=0.5 * cls.loan.loan_amount,
            actual_daily_interest=0,
            channeling_type=ChannelingConst.FAMA,
        )

    @patch('juloserver.channeling_loan.tasks.timezone')
    def test_populate_fama_loan_after_cutoff(self, mock_timezone):
        self.lender = LenderCurrentFactory(lender_name="fama_channeling")
        mock_now = timezone.localtime(timezone.now())
        # tuesday
        mock_now = mock_now.replace(
            year=2024, month=10, day=2, hour=14, minute=59, second=59, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now

        self.channeling_loan_status.cdate = mock_now - timedelta(days=1)
        bulk_update([self.channeling_loan_status], update_fields=['cdate'])

        self.all_feature_setting.parameters[ChannelingConst.FAMA]['cutoff']['INACTIVE_DATE'] = [
            '2024/10/02'
        ]
        self.all_feature_setting.save()
        populate_fama_loan_after_cutoff()
        self.channeling_loan_payment.refresh_from_db()
        self.assertEqual(self.channeling_loan_payment.actual_daily_interest, 0)

        self.all_feature_setting.parameters[ChannelingConst.FAMA]['cutoff']['INACTIVE_DATE'] = []
        self.all_feature_setting.parameters[ChannelingConst.FAMA]['cutoff']['INACTIVE_DAY'] = [
            'Wednesday'
        ]
        self.all_feature_setting.save()
        populate_fama_loan_after_cutoff()
        self.channeling_loan_payment.refresh_from_db()
        self.assertEqual(self.channeling_loan_payment.actual_daily_interest, 0)

        self.all_feature_setting.parameters[ChannelingConst.FAMA]['cutoff']['INACTIVE_DATE'] = []
        self.all_feature_setting.parameters[ChannelingConst.FAMA]['cutoff']['INACTIVE_DAY'] = []
        self.all_feature_setting.save()
        self.channeling_loan_status.cdate = mock_now - timedelta(days=15)
        bulk_update([self.channeling_loan_status], update_fields=['cdate'])
        populate_fama_loan_after_cutoff()
        self.channeling_loan_payment.refresh_from_db()
        self.assertEqual(self.channeling_loan_payment.actual_daily_interest, 0)

        self.all_feature_setting.parameters[ChannelingConst.FAMA]['cutoff']['INACTIVE_DATE'] = []
        self.all_feature_setting.parameters[ChannelingConst.FAMA]['cutoff']['INACTIVE_DAY'] = []
        self.all_feature_setting.save()
        mock_now = timezone.localtime(timezone.now())
        # tuesday
        mock_now = mock_now.replace(
            year=2024, month=10, day=2, hour=14, minute=59, second=59, microsecond=0, tzinfo=None
        )
        mock_timezone.localtime.return_value = mock_now
        self.channeling_loan_status.cdate = mock_now - timedelta(days=1)
        bulk_update([self.channeling_loan_status], update_fields=['cdate'])
        populate_fama_loan_after_cutoff()
        self.channeling_loan_payment.refresh_from_db()
        self.assertNotEqual(self.channeling_loan_payment.actual_daily_interest, 0)


class TestAsyncChannelingLoan(TestCase):
    @patch("juloserver.channeling_loan.tasks.send_notification_to_slack")
    @patch("juloserver.channeling_loan.tasks.check_loan_and_approve_channeling")
    @patch("juloserver.channeling_loan.tasks.xls_to_dict")
    def test_async_with_file_invalid_loan_id(
        self,
        mock_download_from_file_or_url,
        mock_check_loan_and_approve_channeling,
        mock_send_notification_to_slack,
    ):
        errors = "Error: Loan_xid %s not found\n" % str(8795383546)

        mock_check_loan_and_approve_channeling.return_value = errors
        mock_download_from_file_or_url.return_value = {
            'csv': [{'application_xid': '8795383546', 'disetujui': 'y'}]
        }
        proceed_sync_channeling(None, mock_download_from_file_or_url, "FAMA")
        mock_send_notification_to_slack.assert_has_calls(
            [
                mock.call(errors, settings.SYNC_FAILED_SLACK_NOTIFICATION_CHANNEL),
                mock.call("Upload successful", settings.SYNC_COMPLETE_SLACK_NOTIFICATION_CHANNEL),
            ]
        )
        self.assertEqual(mock_send_notification_to_slack.call_count, 2)

    @patch("juloserver.channeling_loan.tasks.send_notification_to_slack")
    @patch("juloserver.channeling_loan.tasks.check_loan_and_approve_channeling")
    @patch("juloserver.channeling_loan.tasks.xls_to_dict")
    def test_async_with_file_success(
        self,
        mock_download_from_file_or_url,
        mock_check_loan_and_approve_channeling,
        mock_send_notification_to_slack,
    ):
        mock_check_loan_and_approve_channeling.return_value = ""
        mock_download_from_file_or_url.return_value = {
            'csv': [{'application_xid': '8795383546', 'disetujui': 'y'}]
        }
        proceed_sync_channeling(None, mock_download_from_file_or_url, "FAMA")
        mock_send_notification_to_slack.assert_has_calls(
            [mock.call("Upload successful", settings.SYNC_COMPLETE_SLACK_NOTIFICATION_CHANNEL)]
        )
        self.assertEqual(mock_send_notification_to_slack.call_count, 1)

    @patch("juloserver.channeling_loan.tasks.send_notification_to_slack")
    @patch("juloserver.channeling_loan.tasks.check_loan_and_approve_channeling")
    @patch("juloserver.channeling_loan.tasks.construct_channeling_url_reader")
    def test_async_url_success(
        self,
        mock_download_from_file_or_url,
        mock_check_loan_and_approve_channeling,
        mock_send_notification_to_slack,
    ):
        mock_download_from_file_or_url.return_value = pd.DataFrame(
            [{'Application_XID': '8795383546', 'disetujui': 'y'}]
        )
        mock_check_loan_and_approve_channeling.return_value = ""
        proceed_sync_channeling("https://iniurl.com", None, "FAMA")
        mock_send_notification_to_slack.assert_has_calls(
            [mock.call("Upload successful", settings.SYNC_COMPLETE_SLACK_NOTIFICATION_CHANNEL)]
        )
        self.assertEqual(mock_check_loan_and_approve_channeling.call_count, 1)
        self.assertEqual(mock_send_notification_to_slack.call_count, 1)

    @patch("juloserver.channeling_loan.tasks.send_notification_to_slack")
    @patch("juloserver.channeling_loan.tasks.check_loan_and_approve_channeling")
    @patch("juloserver.channeling_loan.tasks.construct_channeling_url_reader")
    def test_async_url_failed_loan_id(
        self,
        mock_download_from_file_or_url,
        mock_check_loan_and_approve_channeling,
        mock_send_notification_to_slack,
    ):
        errors = "Error: Loan_xid %s not found\n" % str(8795383546)
        mock_download_from_file_or_url.return_value = pd.DataFrame(
            [{'Application_XID': '8795383546', 'disetujui': 'y'}]
        )
        mock_check_loan_and_approve_channeling.return_value = errors

        proceed_sync_channeling("https://iniurl.com", None, "FAMA")

        mock_send_notification_to_slack.assert_has_calls(
            [
                mock.call(errors, settings.SYNC_FAILED_SLACK_NOTIFICATION_CHANNEL),
                mock.call("Upload successful", settings.SYNC_COMPLETE_SLACK_NOTIFICATION_CHANNEL),
            ]
        )
        self.assertEqual(mock_check_loan_and_approve_channeling.call_count, 1)
        self.assertEqual(mock_send_notification_to_slack.call_count, 2)


class TestFAMAAutoApprovalLoans(TestCase):
    def setUp(self):
        self.current_date = timezone.localtime(timezone.now()).date().strftime("%Y%m%d")
        self.lender = LenderCurrentFactory(lender_name='fama_channeling')
        self.loan1 = LoanFactory(id=1, loan_amount=1000000, loan_xid=123456788)
        self.loan2 = LoanFactory(id=2, loan_amount=1000000, loan_xid=123456789)
        self.document = DocumentFactory(
            filename=self.current_date,
            document_type=ChannelingLoanApprovalFileConst.DOCUMENT_TYPE,
            document_source=self.lender.id,
        )

    @patch.object(FAMAApprovalFileServices, 'execute_upload_fama_disbursement_approval_files')
    @patch.object(FAMAApprovalFileServices, 'download_multi_fama_approval_file_from_sftp_server')
    @patch('juloserver.channeling_loan.tasks.reassign_lender_fama_rejected_loans')
    def test_success_process_approval(self, mock_reassign, mock_download, mock_execute):
        mock_download.return_value = [(self.current_date + '.txt.gpg', b'encrypted_data')]
        mock_execute.return_value = (
            [
                {
                    "document_id": 84095437,
                    "filename": "JTF_Confirmation_Disbursement_20250424171917766.csv",
                    "total": 2,
                    "existing_loan_ids": [],
                    "nok_loan_ids": [],
                    "ok_loan_ids": [self.loan1.id, self.loan2.id],
                    "loan_ids": [self.loan1.id, self.loan2.id],
                    "approved_loan_ids": [self.loan1.id],
                    "rejected_loan_ids": [self.loan2.id],
                }
            ],
            [
                {
                    "document_id": 84095437,
                    "filename": "JTF_Confirmation_Disbursement_20250424171917766.csv",
                    "total": 2,
                    "existing_loan_ids": 0,
                    "nok_loan_ids": 0,
                    "ok_loan_ids": 2,
                    "loan_ids": 2,
                    "approved_loan_ids": 1,
                    "rejected_loan_ids": 1,
                }
            ],
            ["JTF_Confirmation_Disbursement_20250424171917766.txt.gpg"],
        )

        fama_auto_approval_loans()
        mock_reassign.assert_called_once()

    @patch.object(FAMAApprovalFileServices, 'execute_upload_fama_disbursement_approval_files')
    @patch.object(FAMAApprovalFileServices, 'download_multi_fama_approval_file_from_sftp_server')
    @patch('juloserver.channeling_loan.tasks.reassign_lender_fama_rejected_loans')
    def test_approval_file_not_available(self, mock_reassign, mock_download, mock_execute):
        current_date = (
            (timezone.localtime(timezone.now()) - relativedelta(days=1)).date().strftime("%Y%m%d")
        )
        mock_download.return_value = [(current_date + '.txt.gpg', b'encrypted_data')]
        mock_execute.return_value = ([], [], [])
        fama_auto_approval_loans()
        mock_reassign.assert_not_called()
