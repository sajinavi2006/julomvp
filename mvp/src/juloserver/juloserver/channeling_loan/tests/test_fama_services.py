from unittest.mock import patch, MagicMock
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.channeling_loan.services.fama_services import (
    update_fama_eligibility_rejected_by_dpd,
    FAMARepaymentApprovalServices,
)
from juloserver.channeling_loan.models import FAMAChannelingRepaymentApproval
from juloserver.julo.tests.factories import (
    PartnerFactory,
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    ProductLineFactory,
    StatusLookupFactory,
    ProductLookupFactory,
    LoanFactory,
    LenderFactory,
    ApplicationJ1Factory,
    LenderDisburseCounterFactory,
    DocumentFactory,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.product_lines import ProductLineCodes

from juloserver.account.tests.factories import AccountFactory

from juloserver.followthemoney.constants import LenderName
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory

from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import TransactionMethod

from juloserver.channeling_loan.tests.factories import (
    ChannelingLoanStatusFactory,
    ChannelingEligibilityStatusFactory,
    ChannelingLoanApprovalFileFactory,
)
from juloserver.channeling_loan.constants.constants import (
    ChannelingConst,
    ChannelingStatusConst,
    ChannelingActionTypeConst,
    FAMAChannelingConst,
)
from juloserver.channeling_loan.services.fama_services import reassign_lender_fama_rejected_loans


class TestUpdateChannelingEligibility(TestCase):
    def setUp(self):
        self.app = ApplicationFactory()
        self.loan = LoanFactory(application=self.app)
        self.cles = ChannelingEligibilityStatusFactory(channeling_type='FAMA', application=self.app)

    def test_succesfully_update_channeling_eligibility_reject_dpd(self):
        new_version = 99
        reason = 'rejected because DPD in Superbank'
        ineligible = 'ineligible'

        update_fama_eligibility_rejected_by_dpd(self.loan)
        self.cles.refresh_from_db()

        # Verify
        self.assertEqual(self.cles.reason, reason)
        self.assertEqual(self.cles.version, new_version)
        self.assertEqual(self.cles.eligibility_status, ineligible)


class TestReassignLenderFAMARejectedLoansService(TestCase):
    def setUp(self):
        self.lender = LenderFactory(
            id=99, lender_name='fama_channeling', is_pre_fund_channeling_flow=True
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.product_lookup = ProductLookupFactory(product_line=self.product_line, admin_fee=3000)

        self.transaction_method = TransactionMethod.objects.filter(
            id=TransactionMethodCode.SELF.code
        ).last()

        self.blue_finc_lender_user = AuthUserFactory(username='blue_finc_lender_user')
        self.blue_finc_lender_partner = PartnerFactory(user=self.blue_finc_lender_user)
        self.blue_finc_lender = LenderFactory(
            id=101,
            user=self.blue_finc_lender_user,
            lender_status="active",
            lender_name=LenderName.BLUEFINC,
        )
        self.blue_finc_lender_balance = LenderBalanceCurrentFactory(
            lender=self.blue_finc_lender, available_balance=999999999
        )
        self.blue_finc_lender_counter = LenderDisburseCounterFactory(
            lender=self.blue_finc_lender, partner=self.blue_finc_lender_partner
        )

        self.legend_capital_lender_user = AuthUserFactory(username='legend_capital_lender_user')
        self.legend_capital_lender_partner = PartnerFactory(user=self.legend_capital_lender_user)
        self.legend_capital_lender = LenderFactory(
            id=102,
            user=self.legend_capital_lender_user,
            lender_status="active",
            lender_name=LenderName.LEGEND_CAPITAL,
        )
        self.legend_capital_lender_balance = LenderBalanceCurrentFactory(
            lender=self.legend_capital_lender, available_balance=999999999
        )
        self.legend_capital_lender_counter = LenderDisburseCounterFactory(
            lender=self.legend_capital_lender, partner=self.legend_capital_lender_partner
        )

        # setup approved loan data
        self.approved_loan_user = AuthUserFactory(username='approved_loan_user')
        self.approved_loan_partner = PartnerFactory(user=self.approved_loan_user)
        self.approved_loan_customer = CustomerFactory(user=self.approved_loan_user)
        self.approved_loan_account = AccountFactory(customer=self.approved_loan_customer)

        self.approved_loan_last_application = ApplicationFactory(
            customer=self.approved_loan_customer,
            partner=self.approved_loan_partner,
            product_line=self.product_line,
            application_xid=123456789,
            account=self.approved_loan_account,
            monthly_income=10000000,
        )
        self.approved_loan_new_account = AccountFactory(
            last_application=self.approved_loan_last_application
        )
        self.approved_loan_new_application = ApplicationJ1Factory(
            account=self.approved_loan_new_account, monthly_income=10000000
        )

        self.approved_loan = LoanFactory(
            id=1,
            account=self.approved_loan_new_account,
            loan_amount=1000000,
            lender=self.lender,
            partner=self.approved_loan_partner,
            product=self.product_lookup,
            loan_duration=1,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            transaction_method=self.transaction_method,
            loan_xid=123456781,
        )

        self.approved_loan_ces = ChannelingEligibilityStatusFactory(
            channeling_type=ChannelingConst.FAMA,
            eligibility_status=ChannelingStatusConst.ELIGIBLE,
            application=self.approved_loan.account.last_application,
        )
        self.approved_loan_cls = ChannelingLoanStatusFactory(
            loan=self.approved_loan,
            channeling_type=ChannelingConst.FAMA,
            channeling_status=ChannelingStatusConst.PROCESS,
            channeling_eligibility_status=self.approved_loan_ces,
        )

        # setup reject loan data
        self.reject_loan_user = AuthUserFactory(username='reject_loan_user')
        self.reject_loan_partner = PartnerFactory(user=self.reject_loan_user)
        self.reject_loan_customer = CustomerFactory(user=self.reject_loan_user)
        self.reject_loan_account = AccountFactory(customer=self.reject_loan_customer)

        self.reject_loan_last_application = ApplicationFactory(
            customer=self.reject_loan_customer,
            partner=self.reject_loan_partner,
            product_line=self.product_line,
            application_xid=123456789,
            account=self.reject_loan_account,
            monthly_income=10000000,
        )
        self.reject_loan_new_account = AccountFactory(
            last_application=self.reject_loan_last_application
        )
        self.reject_loan_new_application = ApplicationJ1Factory(
            account=self.reject_loan_new_account, monthly_income=10000000
        )

        self.reject_loan = LoanFactory(
            id=2,
            account=self.reject_loan_new_account,
            loan_amount=1000000,
            lender=self.lender,
            partner=self.reject_loan_partner,
            product=self.product_lookup,
            loan_duration=1,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            transaction_method=self.transaction_method,
            loan_xid=123456782,
        )

        self.reject_loan_ces = ChannelingEligibilityStatusFactory(
            channeling_type=ChannelingConst.FAMA,
            eligibility_status=ChannelingStatusConst.ELIGIBLE,
            application=self.reject_loan.account.last_application,
        )
        self.reject_loan_cls = ChannelingLoanStatusFactory(
            loan=self.reject_loan,
            channeling_type=ChannelingConst.FAMA,
            channeling_status=ChannelingStatusConst.PROCESS,
            channeling_eligibility_status=self.reject_loan_ces,
        )

        self.approval_data = [
            {
                "document_id": 84095437,
                "filename": "JTF_Confirmation_Disbursement_20250424171917766.csv",
                "total": 2,
                "existing_loan_ids": [],
                "nok_loan_ids": [],
                "ok_loan_ids": [self.approved_loan.id, self.reject_loan.id],
                "loan_ids": [self.approved_loan.id, self.reject_loan.id],
                "approved_loan_ids": [self.approved_loan.id],
                "rejected_loan_ids": [self.reject_loan.id],
            }
        ]

    @patch('juloserver.channeling_loan.services.fama_services.update_lender_disbursement_counter')
    @patch('juloserver.channeling_loan.services.fama_services.calculate_new_lender_balance')
    @patch('juloserver.channeling_loan.services.fama_services.calculate_old_lender_balance')
    def test_reassign_lender_fama_rejected_loans(
        self, mock_calculate_old, mock_calculate_new, mock_update_counter
    ):
        reassign_lender_fama_rejected_loans(self.approval_data)

        mock_calculate_old.assert_called_once()
        mock_calculate_new.assert_called_once()
        mock_update_counter.assert_called_once()

        self.approved_loan.refresh_from_db()
        self.reject_loan.refresh_from_db()

        self.assertEquals(self.approved_loan.lender.id, self.lender.id)
        self.assertIn(
            self.reject_loan.lender.id, [self.blue_finc_lender.id, self.legend_capital_lender.id]
        )


class TestFAMARepaymentApprovalServices(TestCase):
    def setUp(self):
        self.service = FAMARepaymentApprovalServices()
        self.loan1 = LoanFactory(loan_xid=991)
        self.loan2 = LoanFactory(loan_xid=992)
        self.records = [
            {
                'loan_xid': self.loan1.loan_xid,
                'account_id': self.loan1.loan_xid,
                'account_no': self.loan1.loan_xid,
                'country_currency': 'IDR',
                'payment_type': 'PYM',
                'payment_date': '20250410',
                'posting_date': '20250414',
                'partner_payment_id': self.loan1.loan_xid,
                'interest_amount': 1,
                'principal_amount': 2,
                'installment_amount': 3,
                'payment_amount': 4,
                'over_payment': 0,
                'term_payment': '0',
                'late_charge_amount': 0,
                'early_payment_fee': 0,
                'annual_fee_amount': 0,
                'status': 'Success',
            },
            {
                'loan_xid': self.loan2.loan_xid,
                'account_id': self.loan2.loan_xid,
                'account_no': self.loan2.loan_xid,
                'country_currency': 'IDR',
                'payment_type': 'PYM',
                'payment_date': '20250410',
                'posting_date': '20250414',
                'partner_payment_id': self.loan2.loan_xid,
                'interest_amount': 5,
                'principal_amount': 6,
                'installment_amount': 7,
                'payment_amount': 8,
                'over_payment': 0,
                'term_payment': '1',
                'late_charge_amount': 0,
                'early_payment_fee': 0,
                'annual_fee_amount': 0,
                'status': 'Reject',
            },
            {
                'loan_xid': self.loan2.loan_xid,
                'account_id': self.loan2.loan_xid,
                'account_no': self.loan2.loan_xid,
                'country_currency': 'IDR',
                'payment_type': 'PYM',
                'payment_date': '20250410',
                'posting_date': '20250414',
                'partner_payment_id': self.loan2.loan_xid,
                'interest_amount': 5,
                'principal_amount': 6,
                'installment_amount': 7,
                'payment_amount': 8,
                'over_payment': 0,
                'term_payment': '1',
                'late_charge_amount': 0,
                'early_payment_fee': 0,
                'annual_fee_amount': 0,
                'status': 'Reject',
            },
        ]
        self.loan_mapping = {self.loan1.loan_xid: self.loan1, self.loan2.loan_xid: self.loan2}

    def test_parse_data_from_txt_content(self):
        txt_content = (
            "JTF|JULO|20250414|6156|2157479087.00\n"
            "JTF1007264431|LCJTF2025021400016|IDR|LTP|20250410|20250414|1744287870055418|"
            "13000.00|61872.00|74872.00|74871.00|0.00|2|0.00|0.00|0.00|Posted Successfully\n"
            "JTF1039222507|LCJTF2025022800011|IDR|PYM|20250411|20250414|1744287870055419|"
            "333063.00|1237201.00|1570264.00|1570263.00|0.00|3|0.00|0.00|0.00|Rejected : reason...,\n\n"
        )

        result = self.service.parse_data_from_txt_content(txt_content=txt_content)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['loan_xid'], 1007264431)
        self.assertEqual(result[1]['loan_xid'], 1039222507)
        self.assertEqual(result[0]['interest_amount'], 13000)
        self.assertEqual(result[1]['interest_amount'], 333063)
        self.assertEqual(result[0]['principal_amount'], 61872)
        self.assertEqual(result[1]['principal_amount'], 1237201)
        self.assertEqual(result[0]['installment_amount'], 74872)
        self.assertEqual(result[1]['installment_amount'], 1570264)
        self.assertEqual(result[0]['payment_amount'], 74871)
        self.assertEqual(result[1]['payment_amount'], 1570263)
        self.assertEqual(result[0]['term_payment'], "2")
        self.assertEqual(result[1]['term_payment'], "3")
        self.assertEqual(result[0]['status'], "Posted Successfully")
        self.assertEqual(result[1]['status'], "Rejected : reason...,")

    def test_validate_loans_exist_and_get_mapping(self):
        result = self.service.validate_loans_exist_and_get_mapping(records=self.records)

        self.assertEqual(result, self.loan_mapping)

    def test_create_approval_objects(self):
        approvals = self.service.create_approval_objects(
            records=self.records, loan_mapping=self.loan_mapping, channeling_loan_approval_file_id=1
        )

        self.assertEqual(len(approvals), 3)
        approvals[0].loan_id = self.loan1.id
        approvals[1].loan_id = self.loan2.id

    def test_is_processed_file(self):
        self.assertFalse(self.service.is_processed_file(filename='file1.txt'))

        processed_filename = 'file1.txt'
        document = DocumentFactory(filename=processed_filename)
        ChannelingLoanApprovalFileFactory(
            channeling_type=ChannelingConst.FAMA,
            file_type=ChannelingActionTypeConst.REPAYMENT,
            is_processed=True,
            is_uploaded=True,
            document_id=document.id,
        )
        self.assertTrue(self.service.is_processed_file(filename=processed_filename))

    def test_handle_processed_file_with_today_in_filename(self):
        approval_file = ChannelingLoanApprovalFileFactory(
            channeling_type=ChannelingConst.FAMA,
            file_type=ChannelingActionTypeConst.REPAYMENT,
        )
        today = timezone.now().date().strftime(FAMAChannelingConst.FILENAME_DATE_FORMAT)

        # TODAY NOT IN FILENAME
        result = self.service.handle_processed_file(
            approval_file=approval_file, filename=f"FAMA_REPAYMENT_123_test.txt"
        )
        self.assertFalse(result)
        approval_file.refresh_from_db()
        self.assertFalse(approval_file.is_uploaded)

        # TODAY IN FILENAME
        result = self.service.handle_processed_file(
            approval_file=approval_file, filename=f"FAMA_REPAYMENT_{today}_test.txt"
        )
        self.assertTrue(result)
        approval_file.refresh_from_db()
        self.assertTrue(approval_file.is_uploaded)

    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.parse_data_from_txt_content'
    )
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.validate_loans_exist_and_get_mapping'
    )
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.create_approval_objects'
    )
    def test_process_approval_file(
        self, mock_create_approval, mock_validate_loans, mock_parse_data
    ):
        approval_file = ChannelingLoanApprovalFileFactory(
            channeling_type=ChannelingConst.FAMA,
            file_type=ChannelingActionTypeConst.REPAYMENT,
        )
        file_content = "Sample content"

        mock_parse_data.return_value = self.records
        mock_validate_loans.return_value = self.loan_mapping

        self.service.process_approval_file(approval_file=approval_file, txt_content=file_content)

        mock_parse_data.assert_called_once_with(txt_content=file_content)
        mock_validate_loans.assert_called_once_with(records=self.records)
        mock_create_approval.assert_called_once_with(
            records=self.records,
            loan_mapping=self.loan_mapping,
            channeling_loan_approval_file_id=approval_file.id,
        )

    @patch('juloserver.channeling_loan.services.fama_services.redis_lock_for_update')
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.is_processed_file'
    )
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.process_approval_file'
    )
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.send_success_store_slack_notification'
    )
    def test_store_data_and_notify_slack_new_file(
        self,
        mock_send_slack_notification,
        mock_process_approval_file,
        mock_is_processed_file,
        mock_redis_lock,
    ):
        # Arrange
        approval_file = ChannelingLoanApprovalFileFactory(
            channeling_type=ChannelingConst.FAMA,
            file_type=ChannelingActionTypeConst.REPAYMENT,
        )
        filename = "FAMA_REPAYMENT_TEST.txt"
        txt_content = "Sample content"

        # Mock the methods
        mock_redis_lock = MagicMock()
        mock_is_processed_file.return_value = False
        mock_process_approval_file.return_value = [
            FAMAChannelingRepaymentApproval(
                channeling_loan_approval_file=approval_file,
            )
        ]

        # Act
        result = self.service.store_data_and_notify_slack(
            approval_file_id=approval_file.id, filename=filename, txt_content=txt_content
        )

        # Assert
        self.assertTrue(result)
        mock_is_processed_file.assert_called_once_with(filename=filename)
        mock_process_approval_file.assert_called_once()
        self.assertEqual(FAMAChannelingRepaymentApproval.objects.count(), 1)
        approval_file.refresh_from_db()
        self.assertTrue(approval_file.is_uploaded)
        mock_send_slack_notification.assert_called_once()

    @patch('juloserver.channeling_loan.services.fama_services.redis_lock_for_update')
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.is_processed_file'
    )
    @patch(
        'juloserver.channeling_loan.services.fama_services.FAMARepaymentApprovalServices.handle_processed_file'
    )
    def test_store_data_and_notify_slack_processed_file(
        self, mock_handle_processed_file, mock_is_processed_file, mock_redis_lock
    ):
        # Arrange
        approval_file = ChannelingLoanApprovalFileFactory(
            channeling_type=ChannelingConst.FAMA,
            file_type=ChannelingActionTypeConst.REPAYMENT,
        )
        filename = "FAMA_REPAYMENT_TEST.txt"
        txt_content = "Sample content"

        # Mock the methods
        mock_redis_lock = MagicMock()
        mock_is_processed_file.return_value = True
        mock_handle_processed_file.return_value = False

        # Act
        result = self.service.store_data_and_notify_slack(
            approval_file_id=approval_file.id, filename=filename, txt_content=txt_content
        )

        # Assert
        self.assertFalse(result)
        mock_is_processed_file.assert_called_once_with(filename=filename)
        mock_handle_processed_file.assert_called_once()
