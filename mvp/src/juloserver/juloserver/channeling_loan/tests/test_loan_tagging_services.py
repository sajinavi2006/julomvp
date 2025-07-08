from django.test.testcases import TestCase
from unittest.mock import patch, call

from juloserver.julo.constants import FeatureNameConst
from juloserver.channeling_loan.constants import (
    ChannelingLenderLoanLedgerConst,
)
from juloserver.channeling_loan.models import (
    LenderLoanLedger,
    LenderOspBalanceHistory,
    LenderLoanLedgerHistory,
    LoanLenderTaggingDpdTemp,
)
from juloserver.julo.models import (
    Loan
)
from juloserver.channeling_loan.services.loan_tagging_services import (
    loan_tagging_process_extend_for_replenishment,
    execute_find_replenishment_loan_payment_by_user,
    execute_replenishment_loan_payment_by_user_process,
    execute_replenishment_matchmaking,
    execute_repayment_process_service,
    release_loan_tagging_dpd_90,
    update_lender_osp_balance,
    loan_tagging_process,
    delete_temporary_dpd_table,
    clone_ana_table,
)
from juloserver.julo.tests.factories import (
    LoanFactory,
    StatusLookupFactory,
    PaymentFactory,
    FeatureSettingFactory,
    ApplicationFactory,
)
from juloserver.followthemoney.factories import (
    LenderCurrentFactory,
)
from juloserver.channeling_loan.tests.factories import (
    LenderOspAccountFactory,
    LenderLoanLedgerFactory,
    LoanLenderTaggingDpdTempFactory,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.ana_api.models import LoanLenderTaggingDpd


class TestLoanTaggingServices(TestCase):
    def setUp(self):
        self.lender = LenderCurrentFactory(lender_name="jtp")
        self.lender_osp_account1 = LenderOspAccountFactory(
            lender_withdrawal_percentage=100,
            lender_account_name="FAMA1",
            balance_amount=50_000,
            priority=1,
        )
        self.lender_osp_account2 = LenderOspAccountFactory(
            lender_withdrawal_percentage=100,
            lender_account_name="FAMA2",
            balance_amount=2_000_000,
            priority=2,
        )
        self.lender_osp_account3 = LenderOspAccountFactory(
            lender_withdrawal_percentage=100,
            lender_account_name="FAMA3",
            balance_amount=3_000_000,
            fund_by_lender=1_000_000,
            total_outstanding_principal=1_000_000,
            priority=3,
        )
        self.status_current = StatusLookupFactory(status_code=220)
        self.status_5dpd = StatusLookupFactory(status_code=231)
        self.status_90dpd = StatusLookupFactory(status_code=234)
        self.status_paid_off = StatusLookupFactory(status_code=250)
        self.loan1 = LoanFactory(
            loan_xid=1,
            loan_amount=500,
            loan_status=self.status_current,
            lender=self.lender,
        )
        self.loan2 = LoanFactory(
            loan_xid=2,
            loan_amount=500,
            loan_status=self.status_current,
            lender=self.lender,
        )
        self.loan3 = LoanFactory(
            loan_xid=3,
            loan_amount=500,
            loan_status=self.status_90dpd,
            lender=self.lender,
        )
        self.loan_dpd1 = LoanLenderTaggingDpdTempFactory(
            loan_id = self.loan1.id,
            loan_dpd = 0,
        )
        self.loan_dpd2 = LoanLenderTaggingDpdTempFactory(
            loan_id = self.loan2.id,
            loan_dpd = 0,
        )
        self.loan_dpd3 = LoanLenderTaggingDpdTempFactory(
            loan_id = self.loan3.id,
            loan_dpd = 90,
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
                    "FAMA1": ["jtp", "helicap"],
                    "FAMA2": ["jtp", "helicap"],
                    "FAMA3": ["jtp", "helicap"],
                    "Lend East": ["jh"],
                    "Helicap": ["jh"],
                },
            },
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
    def test_loan_tagging_process_extend_for_replenishment(
        self,
        mock_get_initial_tag_query,
        mock_get_replenishment_tag_query,
    ):
        # NOT FOUND RELEASED LOAN
        # batch 1, 2, 3 don't tagged any loan
        # => find for batch 1: not found
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        total_loan_lender, total_loan_julo, tagged_loan = loan_tagging_process_extend_for_replenishment(
            lender_osp_account_id=self.lender_osp_account1.id,
            total_lender=10_000,
            total_julo=0,
        )
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertEqual(total_tagged_loan, 0)

        # batch1: loan1, loan2, & loan3
        for loan in [self.loan1, self.loan2, self.loan3]:
            LenderLoanLedgerFactory(
                loan_id=loan.id, loan_xid=loan.loan_xid, osp_amount=loan.loan_amount,
                tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
                lender_osp_account=self.lender_osp_account1,
            )
        # batch2: loan2
        LenderLoanLedgerFactory(
            loan_id=self.loan2.id, loan_xid=self.loan2.loan_xid, osp_amount=self.loan2.loan_amount,
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            lender_osp_account=self.lender_osp_account2,
        )
        # batch 2 didn't tag loan 1 and loan 3, but loan 3 is 90dpd
        # => find for batch 2: only found loan 1
        total_loan_lender, total_loan_julo, tagged_loan = loan_tagging_process_extend_for_replenishment(
            lender_osp_account_id=self.lender_osp_account2.id,
            total_lender=10_000,
            total_julo=0,
        )
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertEqual(total_tagged_loan, 0)
        self.assertFalse(self.loan1.id in tagged_loan)

        # update loan1 status to dpd_5 to test step 2
        self.loan1.loan_status = self.status_5dpd
        self.loan1.save()
        self.loan_dpd1.loan_dpd = 5
        self.loan_dpd1.save()

        total_loan_lender, total_loan_julo, tagged_loan = loan_tagging_process_extend_for_replenishment(
            lender_osp_account_id=self.lender_osp_account2.id,
            total_lender=10_000,
            total_julo=0,
        )
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertEqual(total_tagged_loan, 500)
        self.assertTrue(self.loan1.id in tagged_loan)

        # batch2: loan1 & loan2 (previously)
        LenderLoanLedgerFactory(
            loan_id=self.loan1.id, loan_xid=self.loan1.loan_xid, osp_amount=self.loan1.loan_amount,
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            lender_osp_account=self.lender_osp_account2,
        )
        # DON'T USE LOAN ALREADY RELEASED BY THIS LENDER
        # - loan 1 has been released by lender osp account 1, but still not DPD 90,
        # - loan 1 has been released by lender osp account 2, but still not DPD 90
        # => find for batch 2: not found
        total_loan_lender, total_loan_julo, tagged_loan = loan_tagging_process_extend_for_replenishment(
            lender_osp_account_id=self.lender_osp_account2.id,
            total_lender=10_000,
            total_julo=0,
        )
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertEqual(total_tagged_loan, 0)

        # LOAN RELEASED MULTIPLE TIMES => ONLY GET ONCE
        # batch3: nothing, but both loan1 & loan2 were released by batch1 & batch2
        # => find for batch 3: loan1 & loan2
        self.loan2.loan_status = self.status_5dpd
        self.loan2.save()
        self.loan_dpd2.loan_dpd = 5
        self.loan_dpd2.save()
        total_loan_lender, total_loan_julo, tagged_loan = loan_tagging_process_extend_for_replenishment(
            lender_osp_account_id=self.lender_osp_account3.id,
            total_lender=10_000,
            total_julo=0,
        )
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertEqual(total_tagged_loan, 1_000)
        self.assertTrue(self.loan1.id in tagged_loan)
        self.assertTrue(self.loan2.id in tagged_loan)

    @patch('juloserver.channeling_loan.services.loan_tagging_services.'
           'loan_tagging_process_extend_for_replenishment')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_replenishment_tag_query')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_execute_find_replenishment_loan_payment_by_user(
        self, mock_get_initial_tag_query,
        mock_get_replenishment_tag_query,
        mock_loan_tagging_process_extend_for_replenishment,
    ):
        # only test type 1. loan status = 220 that never been initial tagged or replenishment tagged
        # type 2. already cover in test_loan_tagging_process_extend_for_replenishment
        mock_get_replenishment_tag_query.return_value = self.get_loans_replenish_query
        mock_get_initial_tag_query.return_value = self.get_loans_initial_query
        mock_loan_tagging_process_extend_for_replenishment.return_value = 0, 0, {}

        self.lender_osp_account1.balance_amount = 1_000_000
        self.lender_osp_account1.total_outstanding_principal = 990_000
        self.lender_osp_account1.fund_by_lender = 990_000
        self.lender_osp_account1.save()

        # FOUND LOAN1 & LOAN 2
        execute_find_replenishment_loan_payment_by_user(
            lender_osp_account_id=self.lender_osp_account1.id,
            need_replenishment_lender=10_000,
            need_replenishment_julo=0,
        )
        mock_loan_tagging_process_extend_for_replenishment.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
            total_lender=9_000,
            total_julo=0
        )
        for loan in [self.loan1, self.loan2]:
            lender_loan_ledger_batch1 = LenderLoanLedger.objects.get_or_none(
                lender_osp_account=self.lender_osp_account1,
                loan=loan
            )
            self.assertIsNotNone(lender_loan_ledger_batch1)
            self.assertEqual(
                lender_loan_ledger_batch1.notes,
                '{} Fund'.format(self.lender_osp_account1.lender_account_name)
            )

        self.lender_osp_account1.refresh_from_db()
        # processed_balance_amount before is 1_000_000, need replenishment 10_000,
        # but only found 2*500=1_000, so processed_balance_amount will be 991_000
        self.assertEqual(self.lender_osp_account1.total_outstanding_principal, 991_000)
        self.assertEqual(self.lender_osp_account1.fund_by_lender,
                         991_000)
        self.assertEqual(self.lender_osp_account1.fund_by_julo,
                         0)

        self.lender_osp_account1.refresh_from_db()

        # Discarded because how osp & balance changed
        # # OSP before is 50_000, need replenishment 10_000, but only found 2*500=1_000
        # # so OSP will be 41_000
        # self.assertEqual(self.lender_osp_balance1.osp_amount, 41_000)

        # # balance before is 0, need replenishment 10_000, but only found 2*500=1_000
        # # so balance will be 9_000
        # self.assertEqual(self.lender_osp_balance1.balance_amount, 9_000)

        # Since no longer using balance, need to refactor for this case
        # last_lender_osp_balance_history = LenderOspBalanceHistory.objects.filter(
        #     lender_osp_account=self.lender_osp_account1
        # ).last()
        # self.assertEqual(last_lender_osp_balance_history.osp_amount_old, 50_000)
        # self.assertEqual(last_lender_osp_balance_history.osp_amount_new, 41_000)
        # self.assertEqual(last_lender_osp_balance_history.balance_amount_old, 0)
        # self.assertEqual(last_lender_osp_balance_history.balance_amount_new, 9_000)

        ############################################################################################
        # NOT FOUND LOAN

        self.lender_osp_account1.total_outstanding_principal = self.lender_osp_account1.total_outstanding_principal - 10_000
        self.lender_osp_account1.fund_by_lender = self.lender_osp_account1.fund_by_lender - 10_000
        self.lender_osp_account1.save()
        execute_find_replenishment_loan_payment_by_user(
            lender_osp_account_id=self.lender_osp_account1.id,
            need_replenishment_lender=10_000,
            need_replenishment_julo=0
        )
        mock_loan_tagging_process_extend_for_replenishment.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
            total_lender=10_000,
            total_julo=0
        )
        self.assertEqual(
            len(
                LenderLoanLedger.objects.filter(
                    lender_osp_account=self.lender_osp_account1,
                ).all()
            ),
            2  # still 2 because no loan tagged
        )

        self.lender_osp_account1.refresh_from_db()
        # processed_balance_amount before is 991_000, need replenishment 10_000, but not found
        # so processed_balance_amount will be 981_000
        self.assertEqual(self.lender_osp_account1.total_outstanding_principal, 981_000)
        self.assertEqual(self.lender_osp_account1.fund_by_lender, 981_000)
        self.assertEqual(self.lender_osp_account1.fund_by_julo,0)

        self.lender_osp_account1.refresh_from_db()

        # Discarded because how osp & balance changed
        # # OSP before is 41_000, need replenishment 10_000, but not found
        # # so OSP will be 31_000
        # self.assertEqual(self.lender_osp_balance1.osp_amount, 31_000)

        # # balance before is 9_000, need replenishment 10_000, but not found
        # # so balance will be 19_000
        # self.assertEqual(self.lender_osp_balance1.balance_amount, 19_000)

        # last_lender_osp_balance_history = LenderOspBalanceHistory.objects.filter(
        #     lender_osp_balance=self.lender_osp_balance1
        # ).last()
        # self.assertEqual(last_lender_osp_balance_history.osp_amount_old, 41_000)
        # self.assertEqual(last_lender_osp_balance_history.osp_amount_new, 31_000)
        # self.assertEqual(last_lender_osp_balance_history.balance_amount_old, 9_000)
        # self.assertEqual(last_lender_osp_balance_history.balance_amount_new, 19_000)

        # ############################################################################################
        # # NOTES funded by JULO Equity
        loan_temp = LoanFactory(
            loan_xid=4,
            loan_amount=123,
            loan_status=self.status_current,
            lender=self.lender,
        )
        LoanLenderTaggingDpdTempFactory(
            loan_id = loan_temp.id,
            loan_dpd = 0
        )
        self.lender_osp_account1.fund_by_lender = self.lender_osp_account1.balance_amount
        self.lender_osp_account1.lender_withdrawal_percentage = 115
        self.lender_osp_account1.save()
        execute_find_replenishment_loan_payment_by_user(
            lender_osp_account_id=self.lender_osp_account1.id,
            need_replenishment_lender=0,
            need_replenishment_julo=10_000
        )
        self.assertTrue(
            LenderLoanLedger.objects.filter(
                lender_osp_account=self.lender_osp_account1,
                is_fund_by_julo=True,
            ).last(),
            '{} funded by JULO Equity'.format(self.lender_osp_account1.lender_account_name)
        )
        self.lender_osp_account1.refresh_from_db()
        self.assertEqual(
            self.lender_osp_account1.fund_by_lender,
            self.lender_osp_account1.balance_amount
        )
        self.assertEqual(self.lender_osp_account1.fund_by_julo, 123)

        # ############################################################################################
        # # NOT FOUND LOAN in case is_fund_by_julo=True to test need_replenishment_amount_fund_by_julo
        execute_find_replenishment_loan_payment_by_user(
            lender_osp_account_id=self.lender_osp_account1.id,
            need_replenishment_lender=0,
            need_replenishment_julo=5_000
        )
        self.lender_osp_account1.refresh_from_db()
        self.assertEqual(
            self.lender_osp_account1.fund_by_lender,
            self.lender_osp_account1.balance_amount
        )
        self.assertEqual(self.lender_osp_account1.fund_by_julo, 123)

    @patch('juloserver.channeling_loan.services.loan_tagging_services.'
           'execute_find_replenishment_loan_payment_by_user')
    def test_execute_replenishment_loan_payment_by_user_process(
        self, mock_execute_find_replenishment_loan_payment_by_user
    ):
        mock_execute_find_replenishment_loan_payment_by_user.return_value = None

        lender_loan_ledger1 = LenderLoanLedgerFactory(
            loan_id=self.loan1.id,
            loan_xid=self.loan1.loan_xid,
            osp_amount=self.loan1.loan_amount,
            tag_type=ChannelingLenderLoanLedgerConst.INITIAL_TAG,
            lender_osp_account=self.lender_osp_account1,
            notes='{} Fund'.format(self.lender_osp_account1.lender_account_name),
        )
        PaymentFactory(
            payment_number=1,
            loan=self.loan1,
            paid_principal=200,
        )
        PaymentFactory(
            payment_number=2,
            loan=self.loan1,
            paid_principal=100,
        )
        self.lender_osp_account2.lender_withdrawal_percentage = 115
        self.lender_osp_account2.save()
        lender_loan_ledger2 = LenderLoanLedgerFactory(
            loan_id=self.loan2.id,
            loan_xid=self.loan2.loan_xid,
            osp_amount=self.loan2.loan_amount,
            tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
            lender_osp_account=self.lender_osp_account2,
            notes='{} funded by JULO Equity'.format(self.lender_osp_account2.lender_account_name),
            is_fund_by_julo=True,
        )
        PaymentFactory(
            payment_number=1,
            loan=self.loan2,
            paid_principal=self.loan2.loan_amount,
        )
        self.loan2.loan_status = self.status_paid_off
        self.loan2.save()

        # loan2 is replenishment tagged for batch2 & batch3
        lender_loan_ledger3 = LenderLoanLedgerFactory(
            loan_id=self.loan2.id,
            loan_xid=self.loan2.loan_xid,
            osp_amount=self.loan2.loan_amount,
            tag_type=ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG,
            lender_osp_account=self.lender_osp_account3,
            notes='{} Fund'.format(self.lender_osp_account3.lender_account_name),
        )
        self.lender_osp_account1.fund_by_lender += self.loan1.loan_amount
        self.lender_osp_account1.total_outstanding_principal += self.loan1.loan_amount
        self.lender_osp_account2.fund_by_julo += self.loan2.loan_amount
        self.lender_osp_account2.total_outstanding_principal += self.loan2.loan_amount
        self.lender_osp_account3.fund_by_lender += self.loan2.loan_amount
        self.lender_osp_account3.total_outstanding_principal += self.loan2.loan_amount
        self.lender_osp_account1.save()
        self.lender_osp_account2.save()
        self.lender_osp_account3.save()

        execute_replenishment_loan_payment_by_user_process()
        execute_replenishment_matchmaking()

        # Check LenderLoanLedgerHistory
        self.assertEqual(
            len(
                LenderLoanLedgerHistory.objects.filter(
                    lender_loan_ledger_id=lender_loan_ledger1.id
                )
            ),
            1
        )
        lender_loan_ledger_history1 = LenderLoanLedgerHistory.objects.filter(
            lender_loan_ledger_id=lender_loan_ledger1.id,
            field_name='osp_amount'
        ).last()
        self.assertEqual(lender_loan_ledger_history1.old_value, str(self.loan1.loan_amount))
        self.assertEqual(lender_loan_ledger_history1.new_value, str(self.loan1.loan_amount-300))

        self.assertEqual(
            len(
                LenderLoanLedgerHistory.objects.filter(
                    lender_loan_ledger=lender_loan_ledger2
                )
            ),
            2
        )
        lender_loan_ledger_history21 = LenderLoanLedgerHistory.objects.filter(
            lender_loan_ledger=lender_loan_ledger2,
            field_name='osp_amount'
        ).last()
        self.assertEqual(lender_loan_ledger_history21.old_value,
                         str(self.loan2.loan_amount))
        self.assertEqual(lender_loan_ledger_history21.new_value, '0')
        lender_loan_ledger_history22 = LenderLoanLedgerHistory.objects.filter(
            lender_loan_ledger=lender_loan_ledger2,
            field_name='tag_type'
        ).last()
        self.assertEqual(lender_loan_ledger_history22.old_value,
                         ChannelingLenderLoanLedgerConst.REPLENISHMENT_TAG)
        self.assertEqual(lender_loan_ledger_history22.new_value,
                         ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF)
        self.assertEqual(
            len(
                LenderLoanLedgerHistory.objects.filter(
                    lender_loan_ledger=lender_loan_ledger3
                )
            ),
            2
        )

        # Check LenderLoanLedger
        lender_loan_ledger1.refresh_from_db()
        self.assertEqual(lender_loan_ledger1.osp_amount, self.loan1.loan_amount-300)
        self.assertEqual(lender_loan_ledger1.tag_type,
                         ChannelingLenderLoanLedgerConst.INITIAL_TAG)

        lender_loan_ledger2.refresh_from_db()
        self.assertEqual(lender_loan_ledger2.osp_amount, 0)
        self.assertEqual(lender_loan_ledger2.tag_type,
                         ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF)

        lender_loan_ledger3.refresh_from_db()
        self.assertEqual(lender_loan_ledger3.osp_amount, 0)
        self.assertEqual(lender_loan_ledger3.tag_type,
                         ChannelingLenderLoanLedgerConst.RELEASED_BY_PAID_OFF)

        # Check find loan total_replenishment_amount
        # will be mocked based on priority first
        mock_execute_find_replenishment_loan_payment_by_user.assert_has_calls(
            [
                call(
                    lender_osp_account_id=self.lender_osp_account1.id,
                    need_replenishment_lender=(
                        self.lender_osp_account1.balance_amount-self.lender_osp_account1.fund_by_lender
                    )+300,
                    need_replenishment_julo=0,
                ),
                call(
                    lender_osp_account_id=self.lender_osp_account2.id,
                    need_replenishment_lender=(
                        self.lender_osp_account2.balance_amount-self.lender_osp_account2.fund_by_lender
                    ),
                    need_replenishment_julo=(
                        self.lender_osp_account2.balance_amount*15/100-self.lender_osp_account2.fund_by_julo
                    ) + self.loan2.loan_amount,
                ),
                call(
                    lender_osp_account_id=self.lender_osp_account3.id,
                    need_replenishment_lender=(
                        self.lender_osp_account3.balance_amount-self.lender_osp_account3.fund_by_lender
                    )+self.loan2.loan_amount,
                    need_replenishment_julo=0,
                ),

            ]
        )

        ############################################################################################
        # re-run replenishment loan payment by user process => no change because no new payment
        execute_replenishment_loan_payment_by_user_process()
        execute_replenishment_matchmaking()

        self.assertEqual(len(LenderLoanLedgerHistory.objects.all()), 5)  # still 8

        self.assertEqual(lender_loan_ledger1,
                         LenderLoanLedger.objects.get(id=lender_loan_ledger1.id))
        self.assertEqual(lender_loan_ledger2,
                         LenderLoanLedger.objects.get(id=lender_loan_ledger2.id))
        self.assertEqual(lender_loan_ledger3,
                         LenderLoanLedger.objects.get(id=lender_loan_ledger3.id))

        # reset loan status for other unit tests
        self.loan2.loan_status = self.status_current
        self.loan2.save()

    @patch('juloserver.channeling_loan.services.loan_tagging_services.loan_tagging_process')
    @patch('juloserver.channeling_loan.services.loan_tagging_services.'
           'loan_tagging_process_extend_for_replenishment')
    def test_reduced_margin_amount(
        self,
        mock_loan_tagging_process_extend_for_replenishment,
        mock_loan_tagging_process,
    ):
        mock_loan_tagging_process.return_value = {}, 0, 0
        mock_loan_tagging_process_extend_for_replenishment.return_value = 0, 0, {}
        total_replenishment_amount = 1_000_000

        # lender_withdrawal_percentage = 100%
        # balance_amount = 2_000_000
        # processed_balance_amount = 1_000_000
        # => not exceed the margin => reduced_margin_amount = 0
        execute_find_replenishment_loan_payment_by_user(
            lender_osp_account_id=self.lender_osp_account1.id,
            need_replenishment_lender=total_replenishment_amount,
            need_replenishment_julo=0
        )
        mock_loan_tagging_process.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
        )
        mock_loan_tagging_process_extend_for_replenishment.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
            total_lender=total_replenishment_amount,
            total_julo=0
        )

        # lender_withdrawal_percentage = 100%
        # balance_amount = 2_000_000
        # processed_balance_amount = 2_500_000
        # => exceed the margin => reduced_margin_amount = 500_000
        self.lender_osp_account1.total_outstanding_principal = 2_500_000
        self.lender_osp_account1.fund_by_lender = 2_500_000
        self.lender_osp_account1.save()
        execute_find_replenishment_loan_payment_by_user(
            lender_osp_account_id=self.lender_osp_account1.id,
            need_replenishment_lender=total_replenishment_amount,
            need_replenishment_julo=0
        )
        mock_loan_tagging_process.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
        )
        mock_loan_tagging_process_extend_for_replenishment.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
            total_lender=total_replenishment_amount,
            total_julo=0
        )

        # lender_withdrawal_percentage = 115%
        # balance_amount = 2_000_000 -> withdraw_balance = 2_300_000
        # processed_balance_amount = 2_000_000
        # => not exceed the margin => reduced_margin_amount = 0
        self.lender_osp_account1.lender_withdrawal_percentage = 115
        self.lender_osp_account1.total_outstanding_principal = 2_000_000
        self.lender_osp_account1.fund_by_lender = 2_000_000
        self.lender_osp_account1.save()
        execute_find_replenishment_loan_payment_by_user(
            lender_osp_account_id=self.lender_osp_account1.id,
            need_replenishment_lender=total_replenishment_amount,
            need_replenishment_julo=0
        )
        mock_loan_tagging_process.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
        )
        mock_loan_tagging_process_extend_for_replenishment.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
            total_lender=total_replenishment_amount,
            total_julo=0
        )

        # lender_withdrawal_percentage = 115%
        # balance_amount = 2_000_000 -> withdraw_balance = 2_300_000
        # processed_balance_amount = 2_500_000
        # => exceed the margin => reduced_margin_amount = 200_000
        self.lender_osp_account1.lender_withdrawal_percentage = 115
        self.lender_osp_account1.balance_amount = 2_000_000
        self.lender_osp_account1.fund_by_lender = 2_500_000
        self.lender_osp_account1.total_outstanding_principal = 2_500_000
        self.lender_osp_account1.save()

        execute_find_replenishment_loan_payment_by_user(
            lender_osp_account_id=self.lender_osp_account1.id,
            need_replenishment_lender=total_replenishment_amount,
            need_replenishment_julo=0
        )
        mock_loan_tagging_process.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id
        )
        mock_loan_tagging_process_extend_for_replenishment.assert_called_with(
            lender_osp_account_id=self.lender_osp_account1.id,
            total_lender=total_replenishment_amount,
            total_julo=0
        )

        # roll back data
        self.lender_osp_account1.lender_withdrawal_percentage = 100
        self.lender_osp_account1.fund_by_lender = 1_000_000
        self.lender_osp_account1.total_outstanding_principal = 1_000_000
        self.lender_osp_account1.save()

    def test_update_lender_osp_balance(self):
        lender_osp_account = LenderOspAccountFactory()
        balance_amount = 500
        fund_by_lender = 500
        fund_by_julo = 500
        res = update_lender_osp_balance(lender_osp_account,
                                        balance_amount,
                                        fund_by_lender,
                                        fund_by_julo,
                                        None)
        self.assertEqual(res, True)
        balance_amount = 1000
        fund_by_lender = 1000
        fund_by_julo = 1000
        res = update_lender_osp_balance(lender_osp_account,
                                        balance_amount,
                                        fund_by_lender,
                                        fund_by_julo,
                                        None)
        self.assertEqual(res, True)


class TestLoanTaggingRepaymentServices(TestCase):
    def setUp(self):
        self.lender = LenderCurrentFactory(lender_name="jtp")
        self.lender_osp_account = LenderOspAccountFactory(
            lender_withdrawal_percentage=115,
            lender_account_name="FAMA",
            balance_amount=2_000_000,
            total_outstanding_principal=3_000_000,
            fund_by_lender=2_000_000,
            fund_by_julo=1_000_000,
        )
        self.status_current = StatusLookupFactory(status_code=220)
        self.status_90dpd = StatusLookupFactory(status_code=234)
        self.status_paid_off = StatusLookupFactory(status_code=250)

    def test_repayment_happy_path_one_only(self):
        self.lender_loan_ledgers1 = [
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=1_000_000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=1_000_000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=1_000_000,
                is_fund_by_julo=True,
            ),
        ]

        # Julo was released
        self.lender_osp_account.balance_amount = 3_000_000
        repayment_amount = 1_000_000
        old_amount = self.lender_osp_account.balance_amount
        execute_repayment_process_service(self.lender_osp_account.id, repayment_amount)
        self.lender_osp_account.refresh_from_db()
        new_amount = self.lender_osp_account.balance_amount

        self.assertEqual(new_amount, old_amount - 2_000_000)

        # repay another 1 million
        old_amount = self.lender_osp_account.balance_amount
        execute_repayment_process_service(self.lender_osp_account.id, repayment_amount)
        self.lender_osp_account.refresh_from_db()
        new_amount = self.lender_osp_account.balance_amount

        # if balance_amount is 0, release all the Lender Loan Ledger
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account
        )
        lender_loan_ledger_ids = []
        for lender_loan_ledger in lender_loan_ledgers:
            lender_loan_ledger_ids.append(lender_loan_ledger.id)
            self.assertEqual(
                lender_loan_ledger.tag_type,
                ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT
            )

        # check history
        lender_loan_ledger_histories = LenderLoanLedgerHistory.objects.filter(lender_loan_ledger_id__in=(
            lender_loan_ledger_ids
        ))
        for lender_loan_ledger_history in lender_loan_ledger_histories:
            self.assertEqual(lender_loan_ledger_history.field_name, 'tag_type')
            self.assertEqual(
                lender_loan_ledger_history.old_value,
                ChannelingLenderLoanLedgerConst.INITIAL_TAG,
            )
            self.assertEqual(
                lender_loan_ledger_history.new_value,
                ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            )

        lender_osp_balance_histories = LenderOspBalanceHistory.objects.filter(
            lender_osp_account=self.lender_osp_account
        )
        for lender_osp_balance_history in lender_osp_balance_histories:
            self.assertEqual(lender_osp_balance_history.reason, 'released_by_repayment')

    def test_repaymentexceeded_batch(self):
        # released amount more than total,
        # in this case all withdraw batch should be released
        self.lender_loan_ledgers1 = [
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=1000000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=1000000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=1000000,
                is_fund_by_julo=False,
            ),
        ]

        repayment_amount = 999999999
        execute_repayment_process_service(self.lender_osp_account.id, repayment_amount)

        self.lender_osp_account.refresh_from_db()
        new_amount1 = self.lender_osp_account.balance_amount
        self.assertEqual(new_amount1, 0)

        lender_loan_ledger_ids = []
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account
        )
        for lender_loan_ledger in lender_loan_ledgers:
            lender_loan_ledger_ids.append(lender_loan_ledger.id)
            self.assertEqual(
                lender_loan_ledger.tag_type,
                ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT
            )

        lender_loan_ledger_histories = LenderLoanLedgerHistory.objects.filter(
            lender_loan_ledger_id__in=lender_loan_ledger_ids
        )
        for lender_loan_ledger_history in lender_loan_ledger_histories:
            self.assertEqual(lender_loan_ledger_history.field_name, 'tag_type')
            self.assertEqual(
                lender_loan_ledger_history.old_value,
                ChannelingLenderLoanLedgerConst.INITIAL_TAG,
            )
            self.assertEqual(
                lender_loan_ledger_history.new_value,
                ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            )

        lender_osp_balance_histories = LenderOspBalanceHistory.objects.filter(
            lender_osp_account=self.lender_osp_account
        )
        for lender_osp_balance_history in lender_osp_balance_histories:
            self.assertEqual(lender_osp_balance_history.reason, 'released_by_repayment')

    def test_repayment_with_julo_fund_batch(self):
        # happy path, but still not cover for re-matchmaking
        self.lender_osp_account.balance_amount = 10_000_000
        self.lender_osp_account.total_outstanding_principal = 11_500_000
        self.lender_osp_account.fund_by_julo = 1_500_000
        self.lender_osp_account.fund_by_lender = 10_000_000
        self.lender_osp_account.save()

        self.lender_loan_ledgers = [
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=2_000_000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=2_000_000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=2_000_000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=2_000_000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=2_000_000,
                is_fund_by_julo=False,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=750_000,
                is_fund_by_julo=True,
            ),
            LenderLoanLedgerFactory(
                lender_osp_account=self.lender_osp_account,
                osp_amount=750_000,
                is_fund_by_julo=True,
            ),
        ]
        repayment_amount = 4_000_000
        execute_repayment_process_service(self.lender_osp_account.id, repayment_amount)
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account,
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            is_fund_by_julo=False,
        )
        total_lender = 0
        for lender_loan_ledger in lender_loan_ledgers:
            total_lender += lender_loan_ledger.osp_amount

        self.assertEqual(total_lender, 4_000_000)

        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account,
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            is_fund_by_julo=True,
        )
        total_julo = 0
        for lender_loan_ledger in lender_loan_ledgers:
            total_julo += lender_loan_ledger.osp_amount

        self.assertEqual(total_julo, 750_000)
        self.lender_osp_account.refresh_from_db()

        repayment_amount = 1_000_000
        execute_repayment_process_service(self.lender_osp_account.id, repayment_amount)
        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account,
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            is_fund_by_julo=False,
        )
        total_lender = 0
        for lender_loan_ledger in lender_loan_ledgers:
            total_lender += lender_loan_ledger.osp_amount

        self.assertEqual(total_lender, 6_000_000)

        lender_loan_ledgers = LenderLoanLedger.objects.filter(
            lender_osp_account=self.lender_osp_account,
            tag_type=ChannelingLenderLoanLedgerConst.RELEASED_BY_REPAYMENT,
            is_fund_by_julo=True,
        )
        total_julo = 0
        for lender_loan_ledger in lender_loan_ledgers:
            total_julo += lender_loan_ledger.osp_amount

        self.assertEqual(total_julo, 750_000)

        lender_osp_balance_histories = LenderOspBalanceHistory.objects.filter(
            lender_osp_account=self.lender_osp_account
        )
        for lender_osp_balance_history in lender_osp_balance_histories:
            self.assertEqual(lender_osp_balance_history.reason, 'released_by_repayment')


class TestLoanTaggingDPD90(TestCase):
    def setUp(self):
        self.lender = LenderCurrentFactory(lender_name="jtp")
        self.lender_osp_account = LenderOspAccountFactory(
            lender_withdrawal_percentage=100,
            lender_account_name="FAMA",
            balance_amount=10_000_000,
            fund_by_lender=10_000_000,
            total_outstanding_principal=10_000_000,
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
                    "FAMA": ["jtp", "helicap"],
                    "Lend East": ["jh"],
                    "Helicap": ["jh"],
                },
            },
        )
        self.status = StatusLookupFactory(status_code=LoanStatusCodes.CURRENT)
        self.status_dpd90 = StatusLookupFactory(status_code=LoanStatusCodes.LOAN_90DPD)

        for i in range(1, 21):
            loan = LoanFactory(
                application=ApplicationFactory(),
                loan_amount=1000000,
                loan_status=self.status,
                lender=self.lender,
            )
            LoanLenderTaggingDpdTempFactory(
                loan_id = loan.id,
                loan_dpd = 0
            )
            if i < 11:
                LenderLoanLedgerFactory(
                    loan_id=loan.id,
                    loan_xid=loan.loan_xid,
                    osp_amount=1000000,
                    lender_osp_account=self.lender_osp_account,
                )

    def test_no_refinance_all_to_dpd_90(self):
        release_loan_tagging_dpd_90()
        lender_loan_ledgers = LenderLoanLedger.objects.all()
        # all lender_loan_ledger not updating to dpd 90
        for lender_loan_ledger in lender_loan_ledgers:
            self.assertNotEqual(
                lender_loan_ledger.tag_type,
                ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90
            )
        self.lender_osp_account.refresh_from_db()
        self.assertEqual(self.lender_osp_account.total_outstanding_principal, 10_000_000)
        self.assertEqual(self.lender_osp_account.fund_by_lender, 10_000_000)

        histories = LenderOspBalanceHistory.objects.all()
        self.assertEqual(len(histories), 0)

    def test_refinance_all_to_dpd_90(self):
        loan_ids = LenderLoanLedger.objects.all().values_list('loan_id', flat=True)
        loans = Loan.objects.filter(id__in=loan_ids).update(loan_status=self.status_dpd90)

        loan_dpd = LoanLenderTaggingDpdTemp.objects.filter(loan__in=loan_ids)
        loan_dpd.update(loan_dpd=90)

        release_loan_tagging_dpd_90()
        lender_loan_ledgers = LenderLoanLedger.objects.all()
        # all lender_loan_ledger have to be updated to dpd 90
        for lender_loan_ledger in lender_loan_ledgers:
            if lender_loan_ledger.tag_type != ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90:
                self.assertEqual(
                    lender_loan_ledger.tag_type,
                    ChannelingLenderLoanLedgerConst.RELEASED_BY_DPD_90
                )

        self.lender_osp_account.refresh_from_db()
        self.assertEqual(self.lender_osp_account.total_outstanding_principal, 0)
        self.assertEqual(self.lender_osp_account.fund_by_lender, 0)

        histories = LenderOspBalanceHistory.objects.all()
        for history in histories:
            self.assertEqual(int(history.new_value), 0)

class TestLoanTagging(TestCase):
    def setUp(self):
        self.lender = LenderCurrentFactory(lender_name="jtp")
        self.lender_osp_account = LenderOspAccountFactory(
            lender_withdrawal_percentage=100, lender_account_name="FAMA"
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
                    "BSS": ["jtp"],
                    "FAMA": ["jtp"],
                    "Lend East": ["jh"],
                    "Helicap": ["jh"],
                },
            },
        )
        self.status = StatusLookupFactory(status_code=220)
        for i in range(1, 16):
            loan = LoanFactory(
                loan_xid=i,
                application=ApplicationFactory(),
                loan_amount=1000000,
                loan_status=self.status,
                lender=self.lender,
            )
            LoanLenderTaggingDpdTempFactory(
                loan_id = loan.id,
                loan_dpd = 0
            )
        self.get_loans_query = """
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

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_success(self, mock_get_initial_tag_query):
        self.lender_osp_account.balance_amount = 2000000
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_query

        processed_loan, total_loan_lender, total_loan_julo = loan_tagging_process(self.lender_osp_account.id)
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertTrue(
            total_tagged_loan >= 2000000 and total_tagged_loan <= 2000000 + self.margin
        )

        self.lender_osp_account.balance_amount = 20000000
        self.lender_osp_account.save()
        processed_loan, total_loan_lender, total_loan_julo = loan_tagging_process(self.lender_osp_account.id)
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertFalse(
            total_tagged_loan >= 20000000
            and total_tagged_loan <= 20000000 + self.margin
        )

        self.lender_osp_account.balance_amount = 20_000_000
        self.lender_osp_account.total_outstanding_principal = 18_000_000
        self.lender_osp_account.fund_by_lender = 18_000_000
        self.lender_osp_account.save()
        tagged_loans, total_loan_lender, total_loan_julo = loan_tagging_process(
            self.lender_osp_account.id,
        )
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertEqual(total_tagged_loan, 2_000_000)

        self.lender_osp_account.balance_amount = 20_000_000
        self.lender_osp_account.total_outstanding_principal = 19_999_880
        self.lender_osp_account.fund_by_lender = 19_999_880
        self.lender_osp_account.save()
        tagged_loans, total_loan_lender, total_loan_julo = loan_tagging_process(
            self.lender_osp_account.id,
        )
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertEqual(total_tagged_loan, 1_000_000)

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_pending_for_schedule(self, mock_get_initial_tag_query):
        self.lender_osp_account.balance_amount = 15000000
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_query

        loans = [
            LoanFactory(
                application=ApplicationFactory(),
                loan_amount=17000000,
                loan_status=self.status,
                lender=self.lender,
            )
        ]
        LoanLenderTaggingDpdTempFactory(
            loan_id = loans[0].id,
            loan_dpd = 0
        )

        processed_loan, total_loan_lender, total_loan_julo = loan_tagging_process(self.lender_osp_account.id)
        total_tagged_loan = total_loan_lender + total_loan_julo
        for loan in loans:
            loan.delete()
        self.assertFalse(
            total_tagged_loan >= 15000000
            and total_tagged_loan >= 15000000 + self.margin
        )

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_success_with_processed_balance_amount(self, mock_get_initial_tag_query):
        self.lender_osp_account.balance_amount = 2000000
        self.lender_osp_account.fund_by_lender = 1000000
        self.lender_osp_account.total_outstanding_principal = 1000000
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_query

        need_to_fund_amount = (
            self.lender_osp_account.balance_amount - self.lender_osp_account.total_outstanding_principal
        )

        processed_loan, total_loan_lender, total_loan_julo = loan_tagging_process(self.lender_osp_account.id)
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertTrue(
            total_tagged_loan >= need_to_fund_amount and total_tagged_loan <= need_to_fund_amount + self.margin
        )

        # case already fulfilled
        self.lender_osp_account.balance_amount = 20000000
        self.lender_osp_account.fund_by_lender = 20000000
        self.lender_osp_account.total_outstanding_principal = 20000000
        self.lender_osp_account.save()

        processed_loan, total_loan_lender, total_loan_julo = loan_tagging_process(self.lender_osp_account.id)
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertFalse(processed_loan)

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_notes_fund(self, mock_get_initial_tag_query):
        self.lender_osp_account.balance_amount = 2000000
        self.lender_osp_account.save()
        mock_get_initial_tag_query.return_value = self.get_loans_query

        tagged_loans, total_loan_lender, total_loan_julo = loan_tagging_process(self.lender_osp_account.id)
        self.assertTrue(tagged_loans.items)

        self.assertEqual(list(tagged_loans.items())[-1][1]['notes'], 'FAMA Fund')

    @patch('juloserver.channeling_loan.services.loan_tagging_services.get_initial_tag_query')
    def test_notes_fund_by_equity(self, mock_get_initial_tag_query):
        # lender already fulfilled, so tag for julo if 115%
        self.lender_osp_account.balance_amount = 20000000
        self.lender_osp_account.fund_by_lender = 20000000
        self.lender_osp_account.total_outstanding_principal = 20000000
        self.lender_osp_account.lender_withdrawal_percentage = 115
        self.lender_osp_account.save()

        mock_get_initial_tag_query.return_value = self.get_loans_query

        tagged_loans, total_loan_lender, total_loan_julo = loan_tagging_process(self.lender_osp_account.id)
        total_tagged_loan = total_loan_lender + total_loan_julo
        self.assertTrue(
            total_loan_julo >= 3000000 and total_loan_julo <= 3000000 + self.margin
        )
        self.assertEqual(list(tagged_loans.items())[-1][1]['notes'], 'FAMA funded by JULO Equity')


class TestLoanTaggingCloneTable(TestCase):
    def setUp(self):
        self.lender = LenderCurrentFactory(lender_name="jtp")
        self.lender_osp_account = LenderOspAccountFactory(
            lender_withdrawal_percentage=100, lender_account_name="FAMA"
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
                    "BSS": ["jtp"],
                    "FAMA": ["jtp"],
                    "Lend East": ["jh"],
                    "Helicap": ["jh"],
                },
            },
        )
        self.status = StatusLookupFactory(status_code=220)
        self.loans = []
        for i in range(1, 16):
            loan = LoanFactory(
                loan_xid=i,
                application=ApplicationFactory(),
                loan_amount=1000000,
                loan_status=self.status,
                lender=self.lender,
            )
            self.loans.append(loan)

    def test_clone_ana_table(self):
        # test clone ana table,
        # cannot test delete temp table because of schema
        loan_ids = set()
        for loan in self.loans:
            LoanLenderTaggingDpd.objects.create(
                loan_id=loan.id,
                loan_dpd=90
            )
            loan_ids.add(loan.id)

        clone_ana_table()
        loan_dpds = LoanLenderTaggingDpdTemp.objects.all()

        for loan in loan_dpds:
            self.assertEqual(loan.loan_dpd, 90)
            self.assertTrue(loan.loan_id in loan_ids)
