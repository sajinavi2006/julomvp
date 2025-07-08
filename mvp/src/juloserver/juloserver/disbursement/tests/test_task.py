from mock import patch

from django.test.testcases import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.disbursement.constants import (
    DisbursementStatus,
    DisbursementVendors,
    XenditDisbursementStep,
)
from juloserver.disbursement.exceptions import DisbursementServiceError, XfersCallbackError
from juloserver.disbursement.tasks import (
    check_disbursement_via_bca_subtask,
    process_callback_from_xfers,
    process_xendit_callback,
    check_disbursement_via_bca,
    auto_retry_disbursement_via_bca,
    application_bulk_disbursement_tasks,
    bca_pending_status_check_in_170,
    check_gopay_balance_threshold,
    process_disbursement_payment_gateway,
    process_daily_disbursement_limit_whitelist_task,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.cashback import CashbackRedemptionService
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.disbursement.tests.factories import DisbursementFactory, NameBankValidationFactory

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    ProductLineFactory,
    ProductLookupFactory,
    PartnerFactory,
    LenderBalanceFactory,
    LenderServiceRateFactory,
    CashbackTransferTransactionFactory,
    ApplicationFactory,
    FeatureSettingFactory,
    LoanFactory,
    ApplicationHistoryFactory,
    BcaTransactionRecordFactory,
    SepulsaProductFactory,
    WorkflowFactory,
    DocumentFactory,
)
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.disbursement.models import NameBankValidation, Disbursement
from juloserver.julo.models import StatusLookup
from juloserver.paylater.models import DisbursementSummary
from juloserver.followthemoney.factories import LenderCurrentFactory
from juloserver.payment_point.tests.factories import (
    XfersEWalletTransactionFactory,
    XfersProductFactory,
)
from juloserver.disbursement.constants import DailyDisbursementLimitWhitelistConst


class TestCheckDisbursementViaBcaSubtask(TestCase):

    def setUp(self):
        self.bank_validation = NameBankValidation()
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory()
        self.partner = PartnerFactory()
        self.lender = LenderCurrentFactory()
        self.lender_balance = LenderBalanceFactory()
        self.lender_service_rate = LenderServiceRateFactory()
        self.cashback_transfer_transaction = CashbackTransferTransactionFactory()


    def test_disbursement_not_found_case_1(self):
        statement = {
            'disburse_id': self.disbursement.id,
        }

        result = check_disbursement_via_bca_subtask(statement)
        assert result == None


    @patch('juloserver.disbursement.tasks.get_disbursement_process')
    def test_disbursement_found_not_success_case_2(self, mock_get_disbursement_process):
        statement = {
            'disburse_id': self.disbursement.id
        }
        mock_response_get_data = {}

        mock_get_disbursement_process.return_value.get_id.return_value = self.disbursement.id
        mock_get_disbursement_process.return_value.get_data.return_value = mock_response_get_data
        mock_get_disbursement_process.return_value.is_success.return_value = False
        mock_get_disbursement_process.return_value.get_type.return_value = 'loan'

        result = check_disbursement_via_bca_subtask(statement)

        assert not mock_get_disbursement_process.return_value.get_type.called
        mock_get_disbursement_process.assert_called_with(statement['disburse_id'])


    @patch('juloserver.disbursement.tasks.process_application_status_change')
    @patch('juloserver.disbursement.tasks.get_disbursement_process')
    def test_disbursement_found_success_loan_case_3(self, mock_get_disbursement_process, mock_process_application_status_change):
        self.disbursement.disbursement_type = 'loan'
        self.disbursement.name_bank_validation.bank_code = 'BCA'
        self.disbursement.name_bank_validation.account_number = '123'
        self.disbursement.name_bank_validation.validated_name = 'test'
        self.disbursement.method = 'Xendit'
        self.disbursement.save()

        self.loan.disbursement_id = self.disbursement.id
        self.loan.lender = self.lender
        self.loan.partner = self.partner

        self.loan.loan_amount = 10
        self.loan.save()

        self.lender.lender_status = 'active'
        self.lender.save()

        self.lender_balance.partner = self.loan.partner
        self.lender_balance.available_balance = 100
        self.lender_balance.save()

        self.lender_service_rate.partner = self.loan.partner
        self.lender_service_rate.save()

        statement = {
            'disburse_id': self.disbursement.id
        }
        mock_response_get_data = {
            'bank_info':{
                'bank_code':self.bank_validation.bank_code,
                'account_number':self.bank_validation.account_number,
                'validated_name':self.bank_validation.validated_name
            },
            'method': self.disbursement.method
        }

        mock_get_disbursement_process.return_value.get_id.return_value = self.disbursement.id
        mock_get_disbursement_process.return_value.get_data.return_value = mock_response_get_data
        mock_get_disbursement_process.return_value.is_success.return_value = True
        mock_get_disbursement_process.return_value.get_type.return_value = self.disbursement.disbursement_type

        result = check_disbursement_via_bca_subtask(statement)

        mock_get_disbursement_process.assert_called_with(statement['disburse_id'])
        assert mock_get_disbursement_process.return_value.get_type.called
        assert mock_process_application_status_change.called


    @patch('juloserver.disbursement.tasks.CashbackRedemptionService')
    @patch('juloserver.disbursement.tasks.get_disbursement_process')
    def test_disbursement_found_success_cashback_case_4(self, mock_get_disbursement_process, mock_CashbackRedemptionService):
        self.cashback_transfer_transaction.transfer_id = self.disbursement.id
        self.cashback_transfer_transaction.save()

        statement = {
            'disburse_id': self.disbursement.id
        }
        mock_response_get_data = {}

        mock_get_disbursement_process.return_value.get_id.return_value = self.disbursement.id
        mock_get_disbursement_process.return_value.get_data.return_value = mock_response_get_data
        mock_get_disbursement_process.return_value.is_success.return_value = True
        mock_get_disbursement_process.return_value.get_type.return_value = 'cashback'

        result = check_disbursement_via_bca_subtask(statement)

        mock_get_disbursement_process.assert_called_with(statement['disburse_id'])
        assert mock_get_disbursement_process.return_value.get_type.called
        assert mock_CashbackRedemptionService.called


class TestCheckDisbursementViaBca(TestCase):

    def setUp(self):
        self.disbursement = DisbursementFactory(
            disburse_id='1'
        )

    @patch.object(Disbursement.objects, 'checking_statuses_bca_disbursement')
    @patch('juloserver.disbursement.tasks.BcaService')
    @patch('juloserver.disbursement.tasks.check_disbursement_via_bca_subtask')
    def test_check_disbursement_via_bca_case_1(self, mock_check_disbursement_via_bca_subtask, mock_bca_service, mock_disbursement):

        mock_response_get_statements = [
            {
                'Trailer': 'JULO-Disburse,'+self.disbursement.disburse_id
            }
        ]

        mock_bca_service.return_value.get_statements.return_value = mock_response_get_statements

        mock_disbursement.return_value.values_list.return_value = [self.disbursement.disburse_id]

        check_disbursement_via_bca()

        assert mock_check_disbursement_via_bca_subtask.delay.called


class TestAutoRetryDisbursementViaBca(TestCase):
    def setUp(self):
        self.disbursement = DisbursementFactory(
            disburse_id='1'
        )
        self.application = ApplicationFactory()
        self.feature_setting = FeatureSettingFactory()
        self.loan = LoanFactory()
        self.application_history = ApplicationHistoryFactory()
        self.bca_transaction_record = BcaTransactionRecordFactory()

    def test_auto_retry_feature_feature_not_found_case_1(self):
        result = auto_retry_disbursement_via_bca()

        assert result == None


    @patch('juloserver.disbursement.tasks.get_service')
    @patch('juloserver.disbursement.tasks.BcaService')
    def test_auto_retry_feature_case_2(self, mock_bca_service, mock_get_service):
        self.feature_setting.feature_name = 'bca_disbursement_auto_retry'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.parameters = {
            'delay_in_hours': 1
        }
        self.feature_setting.save()

        self.application.application_status_id = 181
        self.application.save()

        result = auto_retry_disbursement_via_bca()


    @patch('juloserver.disbursement.tasks.get_service')
    @patch('juloserver.disbursement.tasks.BcaService')
    def test_auto_retry_feature_case_3(self, mock_bca_service, mock_get_service):
        self.feature_setting.feature_name = 'bca_disbursement_auto_retry'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.parameters = {
            'delay_in_hours': -1
        }
        self.feature_setting.save()

        self.disbursement.method = 'Bca'
        self.disbursement.disburse_status = 'FAILED'
        self.disbursement.save()

        self.application_history.application = self.application
        self.application_history.status_new = 181
        self.application_history.save()

        self.loan.application = self.application
        self.loan.disbursement_id = 0
        self.loan.save()

        self.application.application_status_id = 181
        self.application.loan = self.loan
        self.application.save()

        result = auto_retry_disbursement_via_bca()

    @patch('juloserver.disbursement.tasks.process_application_status_change')
    @patch('juloserver.disbursement.tasks.get_service')
    @patch('juloserver.disbursement.tasks.BcaService')
    def test_auto_retry_feature_case_4(self, mock_bca_service, mock_get_service, mock_process_application_status_change):
        self.feature_setting.feature_name = 'bca_disbursement_auto_retry'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.parameters = {
            'delay_in_hours': -1
        }
        self.feature_setting.save()

        self.disbursement.method = 'Bca'
        self.disbursement.disburse_status = 'FAILED'
        self.disbursement.external_id = 'test'
        self.disbursement.save()

        self.application_history.application = self.application
        self.application_history.status_new = 181
        self.application_history.save()

        self.loan.application = self.application
        self.loan.disbursement_id = self.disbursement.id
        self.loan.save()

        self.application.application_status_id = 181
        self.application.loan = self.loan
        self.application.save()

        self.bca_transaction_record.id
        self.bca_transaction_record.reference_id = self.disbursement.external_id
        self.bca_transaction_record.save()

        mock_get_service.return_value.filter_disburse_id_from_statements.return_value = [self.disbursement.disburse_id]


        result = auto_retry_disbursement_via_bca()

        assert mock_process_application_status_change.called

    @patch('juloserver.disbursement.tasks.process_application_status_change')
    @patch('juloserver.disbursement.tasks.get_service')
    @patch('juloserver.disbursement.tasks.BcaService')
    def test_auto_retry_feature_case_5(self, mock_bca_service, mock_get_service, mock_process_application_status_change):
        self.feature_setting.feature_name = 'bca_disbursement_auto_retry'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.parameters = {
            'delay_in_hours': -1,
            'max_retries': 0
        }
        self.feature_setting.save()

        self.disbursement.method = 'Bca'
        self.disbursement.disburse_status = 'FAILED'
        self.disbursement.retry_times = 1
        self.disbursement.save()

        self.application_history.application = self.application
        self.application_history.status_new = 181
        self.application_history.save()

        self.loan.application = self.application
        self.loan.disbursement_id = self.disbursement.id
        self.loan.save()

        self.application.application_status_id = 181
        self.application.loan = self.loan
        self.application.save()

        result = auto_retry_disbursement_via_bca()

        assert mock_process_application_status_change.called


    @patch('juloserver.disbursement.tasks.process_application_status_change')
    @patch('juloserver.disbursement.tasks.get_service')
    @patch('juloserver.disbursement.tasks.BcaService')
    def test_auto_retry_feature_case_6(self, mock_bca_service, mock_get_service, mock_process_application_status_change):
        self.feature_setting.feature_name = 'bca_disbursement_auto_retry'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.parameters = {
            'delay_in_hours': -1,
            'max_retries': 1
        }
        self.feature_setting.save()

        self.disbursement.method = 'Bca'
        self.disbursement.disburse_status = 'FAILED'
        self.disbursement.retry_times = 0
        self.disbursement.save()

        self.application_history.application = self.application
        self.application_history.status_new = 181
        self.application_history.save()

        self.loan.application = self.application
        self.loan.disbursement_id = self.disbursement.id
        self.loan.save()

        self.application.application_status_id = 181
        self.application.loan = self.loan
        self.application.save()

        result = auto_retry_disbursement_via_bca()

        assert mock_process_application_status_change.called


class TestApplicationBulkDisbursementTasks(TestCase):
    def setUp(self):
        self.disbursement = DisbursementFactory()

    @patch('juloserver.disbursement.tasks.application_bulk_disbursement')
    def test_application_bulk_disbursment_tasks_case_1(self, mock_application_bulk_disbursement):
        application_bulk_disbursement_tasks(self.disbursement.id,100,'test')

        mock_application_bulk_disbursement.assert_called_with(self.disbursement.id,100,'test')


class TestBcaPendingStatusCheckIn170(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory()
        self.disbursement = DisbursementFactory(
            disburse_id='1'
        )
        self.application = ApplicationFactory()
        self.loan = LoanFactory()


    @patch('juloserver.disbursement.tasks.get_service')
    def test_bca_pending_status_170_case_1(self, mock_get_service):
        bca_pending_status_check_in_170()
        assert not mock_get_service.called


    @patch('juloserver.disbursement.tasks.get_service')
    def test_bca_pending_status_170_case_2(self, mock_get_service):
        self.feature_setting.feature_name = 'bca_pending_status_check_in_170'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.save()

        self.disbursement.method = ''
        self.disbursement.save()

        self.loan.application = self.application
        self.loan.disbursement_id = '0'
        self.loan.save()

        self.application.application_status_id = 170
        self.application.loan = self.loan
        self.application.save()

        mock_get_service.return_value.get_statements.return_value = {}

        bca_pending_status_check_in_170()
        assert mock_get_service.called


    @patch('juloserver.disbursement.tasks.process_application_status_change')
    @patch('juloserver.disbursement.tasks.get_service')
    def test_bca_pending_status_170_case_3(self, mock_get_service, mock_process_application_status_change):
        self.feature_setting.feature_name = 'bca_pending_status_check_in_170'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.save()

        self.disbursement.method = ''
        self.disbursement.save()

        self.loan.application = self.application
        self.loan.disbursement_id = '0'
        self.loan.save()

        self.application.application_status_id = 170
        self.application.loan = self.loan
        self.application.save()

        bca_pending_status_check_in_170()
        assert not mock_process_application_status_change.called


    @patch('juloserver.disbursement.tasks.process_application_status_change')
    @patch('juloserver.disbursement.tasks.get_service')
    def test_bca_pending_status_170_case_4(self, mock_get_service, mock_process_application_status_change):
        self.feature_setting.feature_name = 'bca_pending_status_check_in_170'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.save()

        self.disbursement.method = 'Bca'
        self.disbursement.save()

        self.loan.application = self.application
        self.loan.disbursement_id = self.disbursement.id
        self.loan.save()

        self.application.application_status_id = 170
        self.application.loan = self.loan
        self.application.save()
        mock_get_service.return_value.filter_disburse_id_from_statements.return_value = [self.disbursement.disburse_id]

        bca_pending_status_check_in_170()
        assert mock_process_application_status_change.called


    @patch('juloserver.disbursement.tasks.process_application_status_change')
    @patch('juloserver.disbursement.tasks.get_service')
    def test_bca_pending_status_170_case_5(self, mock_get_service, mock_process_application_status_change):
        self.feature_setting.feature_name = 'bca_pending_status_check_in_170'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.parameters = {
            'max_retries': 6
        }
        self.feature_setting.save()

        self.disbursement.method = 'Bca'
        self.disbursement.retry_times = 6
        self.disbursement.save()

        self.loan.application = self.application
        self.loan.disbursement_id = self.disbursement.id
        self.loan.save()

        self.application.application_status_id = 170
        self.application.loan = self.loan
        self.application.save()

        mock_get_service.return_value.filter_disburse_id_from_statements.return_value = ['0']

        bca_pending_status_check_in_170()

        assert mock_process_application_status_change.called


    @patch('juloserver.disbursement.tasks.get_service')
    def test_bca_pending_status_170_case_6(self, mock_get_service):
        self.feature_setting.feature_name = 'bca_pending_status_check_in_170'
        self.feature_setting.category = 'disbursement'
        self.feature_setting.parameters = {
            'max_retries': 6
        }
        self.feature_setting.save()

        self.disbursement.method = 'Bca'
        self.disbursement.retry_times = 5
        self.disbursement.save()

        self.loan.application = self.application
        self.loan.disbursement_id = self.disbursement.id
        self.loan.save()

        self.application.application_status_id = 170
        self.application.loan = self.loan
        self.application.save()

        mock_get_service.return_value.filter_disburse_id_from_statements.return_value = ['0']

        bca_pending_status_check_in_170()
        self.disbursement.refresh_from_db()
        assert self.disbursement.retry_times == 6


class TestXenditTasks(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.external_id = 'secret_code'
        self.disbursement = DisbursementFactory(
            disburse_id=self.external_id,
            disburse_status=DisbursementStatus.PENDING,
            method=DisbursementVendors.XENDIT,
            step=XenditDisbursementStep.SECOND_STEP,
            amount=100_000_000,
            original_amount=110_000_000,
        )
        self.j1_product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.product = ProductLookupFactory(
            product_line=self.j1_product_line,
        )
        self.lender = LenderCurrentFactory()
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            disbursement_id=self.disbursement.id,
            product=self.product,
            loan_amount=self.disbursement.amount,
            loan_disbursement_amount=self.disbursement.original_amount,
            lender=self.lender,
        )


    @patch('juloserver.disbursement.tasks.update_lender_balance_current_for_disbursement')
    @patch('juloserver.disbursement.tasks.julo_one_loan_disbursement_success')
    def test_process_xendit_callback_status_completed(
        self,
        mock_disburse_success,
        mock_update_lender_balance,
    ):
        ecommerce_method = TransactionMethodFactory.ecommerce()
        self.loan.transaction_method = ecommerce_method
        self.loan.save()
        xendit_data = {
            "id": "57e214ba82b034c325e84d6e",
            "created": "2021-07-10T08:15:03.404Z",
            "updated": "2021-07-10T08:15:03.404Z",
            "external_id": self.external_id,
            "user_id": "57c5aa7a36e3b6a709b6e148",
            "amount": 150000,
            "bank_code": "BCA",
            "account_holder_name": "MICHAEL CHEN",
            "disbursement_description": "Refund for shoes",
            "status": "COMPLETED",
            "is_instant": True,
        }
        process_xendit_callback(
            disburse_id=xendit_data['external_id'],
            xendit_response=xendit_data,
        )
        mock_disburse_success.assert_called_once_with(self.loan)
        mock_update_lender_balance.assert_not_called()


    @patch('juloserver.disbursement.tasks.julo_one_loan_disbursement_failed')
    def test_process_xendit_callback_status_failed(
        self,
        mock_disburse_failed,
    ):
        ecommerce_method = TransactionMethodFactory.ecommerce()
        self.loan.transaction_method = ecommerce_method
        self.loan.save()
        xendit_data = {
            "id": "57e214ba82b034c325e84d6e",
            "created": "2021-07-10T08:15:03.404Z",
            "updated": "2021-07-10T08:15:03.404Z",
            "external_id": self.external_id,
            "user_id": "57c5aa7a36e3b6a709b6e148",
            "amount": 150000,
            "bank_code": "BCA",
            "account_holder_name": "MICHAEL CHEN",
            "disbursement_description": "Refund for shoes",
            "status": "FAILED",
            "is_instant": True,
        }
        process_xendit_callback(
            disburse_id=xendit_data['external_id'],
            xendit_response=xendit_data,
        )
        mock_disburse_failed.assert_called_once_with(self.loan)

    @patch('juloserver.disbursement.tasks.update_lender_balance_current_for_disbursement')
    @patch('juloserver.disbursement.tasks.julo_one_loan_disbursement_success')
    def test_process_xendit_callback_status_completed_case_escrow_lender(
        self,
        mock_disburse_success,
        mock_update_lender_balance,
    ):
        ecommerce_method = TransactionMethodFactory.ecommerce()
        self.loan.transaction_method = ecommerce_method
        escrow_lender = LenderCurrentFactory(is_only_escrow_balance=True)
        self.loan.lender = escrow_lender
        self.loan.save()
        xendit_data = {
            "id": "57e214ba82b034c325e84d6e",
            "created": "2021-07-10T08:15:03.404Z",
            "updated": "2021-07-10T08:15:03.404Z",
            "external_id": self.external_id,
            "user_id": "57c5aa7a36e3b6a709b6e148",
            "amount": 150000,
            "bank_code": "BCA",
            "account_holder_name": "MICHAEL CHEN",
            "disbursement_description": "Refund for shoes",
            "status": "COMPLETED",
            "is_instant": True,
        }
        process_xendit_callback(
            disburse_id=xendit_data['external_id'],
            xendit_response=xendit_data,
        )
        mock_update_lender_balance.assert_called_once_with(self.loan.id)


class TestXfersCallbackProcess(TestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name='test')
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer, partner=self.partner)
        self.application.application_status_id = 150
        self.application.save()
        self.validation_id = 100
        self.bank_validation = NameBankValidationFactory(
            validation_id=self.validation_id,
            method='Xfers',
            account_number=123,
            name_in_bank='test',
            bank_code='BCA_SYR')
        self.disbursement = DisbursementFactory(
            name_bank_validation=self.bank_validation,
            disburse_id=123456,
            method='Xfers',
            disbursement_type='loan_one',
            step=1,
            original_amount=1000000)
        self.loan = LoanFactory(
            name_bank_validation_id=self.bank_validation.id,
            disbursement_id=self.disbursement.id,
            application=self.application)

    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback(self, _mock_change_status):
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test'
        }
        with self.assertRaises(XfersCallbackError) as err:
            process_callback_from_xfers(
                data=data,
                current_step="1",
                is_reversal_payment=True,
            )
        self.assertEqual(str(err.exception), "lender id not found {}".format("12345"))
        self.assertEqual(err.exception.__class__, XfersCallbackError)

    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback_case_2(self, _mock_change_status):
        data = {
            'idempotency_id': str(34534),
            'status': 'failed',
            'failure_reason': 'test'
        }
        with self.assertRaises(DisbursementServiceError) as err:
            process_callback_from_xfers(
                data=data,
                current_step="1",
                is_reversal_payment=False,
            )
        self.assertEqual(str(err.exception), "disbursement process not found")
        self.assertEqual(err.exception.__class__, DisbursementServiceError)

    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback_case_3(self, _mock_change_status):
        self.disbursement.method = 'test'
        self.disbursement.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test'
        }

        with self.assertRaises(XfersCallbackError) as err:
            process_callback_from_xfers(
                data=data,
                current_step="1",
                is_reversal_payment=False,
            )
        self.assertEqual(
            str(err.exception),
            "disbursement method xfers is not valid method for disbursement {}".format(
                self.disbursement.disburse_id)
            )
        self.assertEqual(err.exception.__class__, XfersCallbackError)

    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback_case_4(self, _mock_change_status):
        self.disbursement.disburse_status = 'NOT PENDING'
        self.disbursement.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test'
        }
        with self.assertRaises(XfersCallbackError) as err:
            process_callback_from_xfers(
                data=data,
                current_step="1",
                is_reversal_payment=False,
            )
        self.assertEqual(
            str(err.exception),
            "Wrong step of Xfers"
        )
        self.assertEqual(err.exception.__class__, XfersCallbackError)


    @patch.object(CashbackRedemptionService, 'update_transfer_cashback_xfers')
    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback_case_5(self, _mock_change_status, mock_update_transfer):
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.disbursement_type = 'cashback'
        self.disbursement.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test',
            'amount': 1000000
        }
        process_callback_from_xfers(
            data=data,
            current_step="1",
            is_reversal_payment=False,
        )
        mock_update_transfer.assert_called_once()

    @patch('juloserver.disbursement.tasks.xfers_second_step_disbursement_task')
    @patch('juloserver.disbursement.tasks.update_lender_balance_current_for_disbursement')
    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback_case_6(
            self, _mock_change_status,
            mock_update_lender_balance,
            mock_xfers_second_step,

    ):
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.disbursement_type = 'bulk'
        self.disbursement.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'completed',
            'failure_reason': 'test',
            'amount': 1000000
        }
        process_callback_from_xfers(
            data=data,
            current_step="1",
            is_reversal_payment=False,
        )
        mock_xfers_second_step.delay.assert_called_once()

    @patch('juloserver.disbursement.tasks.xfers_second_step_disbursement_task')
    @patch('juloserver.disbursement.tasks.update_lender_balance_current_for_disbursement')
    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback_with_ewallet_transaction(
        self,
        _mock_change_status,
        mock_update_lender_balance,
        mock_xfers_second_step,
    ):
        self.xfers_product = XfersProductFactory(sepulsa_product=SepulsaProductFactory())
        XfersEWalletTransactionFactory(
            loan=self.loan, customer=self.loan.customer, xfers_product=self.xfers_product
        )
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.disbursement_type = 'bulk'
        self.disbursement.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'completed',
            'failure_reason': 'test',
            'amount': 1000000,
        }
        process_callback_from_xfers(
            data=data,
            current_step="1",
            is_reversal_payment=False,
        )
        mock_xfers_second_step.delay.assert_called_once()

    @patch('juloserver.disbursement.tasks.application_bulk_disbursement_tasks')
    @patch('juloserver.disbursement.tasks.record_bulk_disbursement_transaction')
    @patch.object(DisbursementSummary.objects, 'filter')
    @patch('juloserver.disbursement.tasks.update_lender_balance_current_for_disbursement')
    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback_case_7(
        self, _mock_change_status,
        mock_update_lender_balance,
        mock_disbursement_summary,
        mock_record_bulk_disbursement_transaction,
        mock_application_bulk_disbursement_task
    ):
        mock_disbursement_summary.return_value.last \
            .return_value.transaction_ids = [self.application.id]
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.disbursement_type = 'bulk'
        self.disbursement.step = 2
        self.disbursement.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'completed',
            'failure_reason': 'test',
            'amount': 1000000
        }
        process_callback_from_xfers(
            data=data,
            current_step="2",
            is_reversal_payment=False,
        )
        mock_application_bulk_disbursement_task.delay.assert_called_once()
        mock_record_bulk_disbursement_transaction.assert_called_once()

    @patch.object(DisbursementSummary.objects, 'filter')
    @patch('juloserver.disbursement.tasks.update_lender_balance_current_for_disbursement')
    @patch('juloserver.disbursement.tasks.process_application_status_change')
    def test_disburse_xfers_event_callback_case_8(
        self, _mock_change_status,
        mock_update_lender_balance,
        mock_disbursement_summary,
    ):
        mock_disbursement_summary.return_value.last \
            .return_value.transaction_ids = [self.application.id]
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.disbursement_type = 'loan'
        self.disbursement.step = 2
        self.disbursement.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test',
            'amount': 1000000
        }
        process_callback_from_xfers(
            data=data,
            current_step="2",
            is_reversal_payment=False,
        )
        _mock_change_status.assert_called_once()

    @patch('juloserver.disbursement.tasks.get_ecommerce_disbursement_experiment_method')
    @patch('juloserver.disbursement.tasks.xfers_second_step_disbursement_task')
    def test_disburse_xfers_event_callback_case_xendit_experiment(self, xfers_second_step, get_experiment_method):
        self.loan.transaction_method = TransactionMethodFactory.ecommerce()
        self.loan.save()
        get_experiment_method.return_value = DisbursementVendors.XENDIT
        self.disbursement.disburse_status = 'PENDING'
        self.disbursement.disbursement_type = 'loan'
        self.disbursement.step = 1
        self.disbursement.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'completed',
            'failure_reason': 'test',
            'amount': 1000000,
        }
        process_callback_from_xfers(
            data=data,
            current_step="1",
            is_reversal_payment=False,
        )
        xfers_second_step.delay.assert_called_once_with(
            str(self.disbursement.disburse_id),
        )
        self.disbursement.refresh_from_db()
        self.assertEqual(self.disbursement.method, DisbursementVendors.XENDIT)
        self.assertEqual(self.disbursement.step, XenditDisbursementStep.SECOND_STEP)


class TestGopayAlert(TestCase):
    def setUp(self):
        from django.conf import settings
        settings.GOPAY_API_KEY = 'IRIS-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
        settings.GOPAY_APPROVER_API_KEY = 'IRIS-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
        settings.GOPAY_CASHBACK_BASE_URL = 'https://app.sandbox.midtrans.com/iris'

        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.GOPAY_BALANCE_ALERT, is_active=True,
            parameters={
                'threshold': 10000,
                'message': 'Gopay available balance is less then threshold. '
                           '<@U02B843J7V0> , <@U04H63S2XC7>, please top up!',
                'channel': '#partner_balance'
            }
        )

    @patch('requests.get')
    @patch('juloserver.disbursement.tasks.send_slack_bot_message')
    def test_gopay_alert_success(self, mock_slack, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'balance': 10000}
        check_gopay_balance_threshold()
        self.assertEquals(mock_slack.call_count, 1)

        mock_get.return_value.json.return_value = {'balance': 6000}
        check_gopay_balance_threshold()
        self.assertEquals(mock_slack.call_count, 2)

    @patch('requests.get')
    @patch('juloserver.disbursement.tasks.send_slack_bot_message')
    def test_gopay_alert_failed(self, mock_slack, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'balance': 20000}
        check_gopay_balance_threshold()
        self.assertEquals(mock_slack.call_count, 0)

    @patch('juloserver.disbursement.tasks.send_slack_bot_message')
    def test_gopay_alert_off(self, mock_slack):
        self.fs.update_safely(is_active=False)
        check_gopay_balance_threshold()
        self.assertEquals(mock_slack.call_count, 0)


class TestProcessDisbursementPaymentGateway(TestCase):
    def setUp(self):
        self.disbursement = DisbursementFactory(disburse_id=123, method='PG')
        self.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.loan = LoanFactory(
            disbursement_id=self.disbursement.id,
            application=self.application,
            account=self.account,
            customer=self.customer,
        )
        self.loan.loan_status_id = 212
        self.loan.save()

    @patch('juloserver.disbursement.tasks.julo_one_loan_disbursement_success')
    def test_process_success_disbursement(self, mock_julo_one_loan_disbursement_success):
        data = {
            'transaction_id': 123,
            'object_transfer_id': 'transfer_123',
            'object_transfer_type': 'payout',
            'transaction_date': '2024-02-07',
            'status': 'success',
            'amount': '100.00',
            'bank_id': 456,
            'bank_account': '1234567890',
            'bank_account_name': 'John Doe',
            'bank_code': 'BANK001',
            'preferred_pg': 'stripe',
            'can_retry': False,
        }
        process_disbursement_payment_gateway(data)
        self.loan.refresh_from_db()
        mock_julo_one_loan_disbursement_success.assert_called_once_with(self.loan)

    @patch('juloserver.disbursement.tasks.julo_one_loan_disbursement_failed')
    def test_process_success_disbursement(self, mock_julo_one_loan_disbursement_failed):
        data = {
            'transaction_id': 123,
            'object_transfer_id': 'transfer_123',
            'object_transfer_type': 'payout',
            'transaction_date': '2024-02-07',
            'status': 'failed',
            'amount': '100.00',
            'bank_id': 456,
            'bank_account': '1234567890',
            'bank_account_name': 'John Doe',
            'bank_code': 'BANK001',
            'preferred_pg': 'stripe',
            'can_retry': False,
        }
        process_disbursement_payment_gateway(data)
        self.loan.refresh_from_db()
        mock_julo_one_loan_disbursement_failed.assert_called_once_with(
            self.loan, payment_gateway_failed=True
        )


class TestDailyDisbursementLimitWhitelist(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username="prod_only")
        self.document = DocumentFactory(
            document_type=DailyDisbursementLimitWhitelistConst.DOCUMENT_TYPE
        )

    @patch("juloserver.disbursement.tasks.process_daily_disbursement_limit_whitelist")
    def test_process_daily_disbursement_limit_whitelist_task_url_field(self, mock_process):
        process_daily_disbursement_limit_whitelist_task(
            user_id=self.user.id,
            document_id=None,
            form_data={"url_field": "https://docs.google.com/spreadsheets"}
        )
        mock_process.assert_called_once_with(
            url="https://docs.google.com/spreadsheets",
            user_id=self.user.id
        )

    @patch("juloserver.disbursement.tasks.process_daily_disbursement_limit_whitelist")
    def test_process_daily_disbursement_limit_whitelist_task_file_field(self, mock_process):
        process_daily_disbursement_limit_whitelist_task(
            user_id=self.user.id,
            document_id=self.document.id,
            form_data={"url_field": ""}
        )
        mock_process.assert_called_once_with(
            url=self.document.document_url,
            user_id=self.user.id
        )
