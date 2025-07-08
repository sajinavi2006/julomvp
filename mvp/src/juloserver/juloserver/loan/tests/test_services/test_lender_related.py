from mock import patch
from django.test.testcases import TestCase
import mock
from datetime import datetime, time, timedelta
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from juloserver.balance_consolidation.constants import BalanceConsolidationStatus
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
)
from juloserver.disbursement.tests.test_client_ayoconnect import (
    mocked_requests_success,
    mocked_requests_ayoconnect_system_error_maintenance,
)
from juloserver.grab.models import (
    PaymentGatewayVendor,
    PaymentGatewayCustomerData,
)
from juloserver.grab.tests.factories import (
    PaymentGatewayBankCodeFactory,
    PaymentGatewayCustomerDataFactory,
)
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import Payment
from juloserver.account_payment.models import AccountPayment
from juloserver.payment_point.models import TransactionMethod
from juloserver.loan.services.lender_related import (
    julo_one_loan_disbursement_failed,
    julo_one_lender_auto_matchmaking,
    process_disburse,
    julo_one_loan_disbursement_success,
    is_disbursement_stuck_less_than_threshold,
    switch_disbursement_to_xfers,
    handle_ayoconnect_beneficiary_errors_on_disbursement,
    julo_one_get_fama_buyback_lender,
)
from juloserver.julo.tests.factories import (
    AccountingCutOffDateFactory,
    ApplicationFactory,
    StatusLookupFactory,
    CustomerFactory,
    LoanFactory,
    PaymentFactory,
    SepulsaTransactionFactory,
    FeatureSettingFactory,
    ProductLineFactory,
    ApplicationJ1Factory,
    LenderDisburseCounterFactory,
    AuthUserFactory,
    PartnerFactory,
    PartnerPropertyFactory,
    LenderFactory,
    WorkflowFactory,
    VoiceCallRecordFactory,
    BankFactory,
    ProductLookupFactory,
    SepulsaProductFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.followthemoney.factories import LenderCurrentFactory, LenderBalanceCurrentFactory
from juloserver.followthemoney.models import (
    LenderTransactionType,
    LenderApproval,
    LoanLenderHistory,
)
from juloserver.followthemoney.constants import LenderName
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    CreditScoreFactory,
    AccountPropertyFactory,
    AccountLookupFactory,
)
from juloserver.account.constants import AccountConstant
from juloserver.promo.constants import (
    PromoCodeBenefitConst,
)
from juloserver.promo.tests.factories import (
    PromoCodeFactory,
    PromoCodeBenefitFactory,
    PromoCodeUsageFactory,
    PromoCodeLoanFactory,
)
from juloserver.portal.object.product_profile.tests.test_product_profile_services import (
    ProductProfileFactory,
)
from juloserver.disbursement.tests.factories import (
    DisbursementFactory,
    NameBankValidationFactory,
    PaymentGatewayCustomerDataLoanFactory,
)
from juloserver.julo.models import StatusLookup
from juloserver.partnership.tests.factories import (
    PartnershipConfigFactory,
    PartnershipTypeFactory,
    PartnerLoanRequestFactory,
)
from juloserver.partnership.constants import PartnershipTypeConstant
from juloserver.disbursement.constants import (
    NameBankValidationStatus,
    DisbursementVendors,
    AyoconnectBeneficiaryStatus,
    DisbursementStatus,
    AyoconnectErrorReason,
    XfersDisbursementStep,
    PaymentGatewayVendorConst,
    AyoconnectErrorCodes,
    NameBankValidationVendors,
)
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.loan.tasks.lender_related import (
    send_promo_code_robocall_subtask,
    reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task,
)
from juloserver.loan.services.robocall import construct_loan_infos_for_robocall_script
from juloserver.loan.models import Loan
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.ana_api.models import DynamicCheck
from juloserver.channeling_loan.services.bss_services import is_holdout_users_from_bss_channeling
from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from juloserver.disbursement.models import Disbursement2History, DisbursementHistory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.tests.factories import (
    XfersEWalletTransactionFactory,
    XfersProductFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.apiv1.constants import BankCodes


class TestJuloOneDisbursementFailed(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.promo_code = PromoCodeFactory()
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, referral_code=self.promo_code.promo_code
        )
        self.lender = LenderCurrentFactory()
        self.lender_balance_current = LenderBalanceCurrentFactory(lender=self.lender)
        self.repayment_transaction_type = LenderTransactionType.objects.create(
            transaction_type='repayment'
        )
        self.loan = LoanFactory(customer=self.customer, account=self.account, lender=self.lender)
        self.payment = PaymentFactory(loan=self.loan)
        self.credit_score = CreditScoreFactory()
        self.feature = FeatureSettingFactory(
            feature_name='disbursement_auto_retry',
            category="disbursement",
            is_active=True,
            parameters={'max_retries': 3, 'waiting_hours': 1},
        )
        self.pulsa_method = TransactionMethod.objects.get(pk=3)
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=212, status_next=220, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=218, status_next=215, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=218, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=218, status_next=213, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=213, status_next=216, workflow=self.workflow)

    @patch('juloserver.account_payment.services.account_payment_related.void_ppob_transaction')
    @patch('juloserver.loan.services.lender_related.get_julo_pn_client')
    @patch('juloserver.loan.tasks.lender_related.loan_payment_point_disbursement_retry_task')
    @patch('juloserver.loan.tasks.lender_related.loan_disbursement_retry_task')
    @patch('juloserver.followthemoney.services.get_available_balance')
    def test_not_forced_failed(
        self,
        mock_get_available_balance,
        mock_loan_disbursement_retry_task,
        mock_payemnt_point_disbursement_retry_task,
        mock_get_julo_pn_client,
        mock_void_ppob_transaction,
    ):
        credit_score = CreditScoreFactory(application_id=self.application.id)
        account_limit = AccountLimitFactory(account=self.account, latest_credit_score=credit_score)
        mock_get_available_balance.return_value = 300000
        self.loan.loan_status_id = 212
        self.loan.save()
        self.loan.refresh_from_db()
        julo_one_loan_disbursement_failed(self.loan)
        mock_loan_disbursement_retry_task.apply_async.assert_called_once_with(
            (self.loan.id, 3), eta=mock.ANY
        )
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 218)

        # no feature
        self.feature.is_active = False
        self.feature.save()
        mock_get_available_balance.return_value = 300000
        julo_one_loan_disbursement_failed(self.loan)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 213)

        # has sepulsa transaction
        self.loan.transaction_method = self.pulsa_method
        self.loan.loan_status_id = 218
        self.loan.save()
        sepulsa_trans = SepulsaTransactionFactory(loan=self.loan)
        mock_get_available_balance.return_value = 300000
        julo_one_loan_disbursement_failed(self.loan)
        mock_payemnt_point_disbursement_retry_task.apply_async.assert_not_called()
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 215)

    @patch('juloserver.loan.services.lender_related.get_julo_pn_client')
    @patch('juloserver.followthemoney.services.get_available_balance')
    def test_forced_failed(self, mock_get_available_balance, mock_get_julo_pn_client):
        credit_score = CreditScoreFactory(application_id=self.application.id)
        account_limit = AccountLimitFactory(account=self.account, latest_credit_score=credit_score)
        mock_get_available_balance.return_value = 300000
        self.loan.loan_status_id = 218
        self.loan.transaction_method = self.pulsa_method
        self.loan.save()
        self.loan.refresh_from_db()
        sepulsa_trans = SepulsaTransactionFactory(loan=self.loan)
        julo_one_loan_disbursement_failed(self.loan, force_failed=True)
        mock_get_julo_pn_client().infrom_cashback_sepulsa_transaction.assert_called_once()
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 215)

    @patch('juloserver.loan.services.lender_related.mark_loan_transaction_failed')
    def test_xfers_ewallet_transaction_force_failed(self, mock_mark_failed):
        xfers_product = XfersProductFactory(sepulsa_product=SepulsaProductFactory())
        XfersEWalletTransactionFactory(
            loan=self.loan, customer=self.loan.customer, xfers_product=xfers_product
        )
        credit_score = CreditScoreFactory(application_id=self.application.id)
        AccountLimitFactory(account=self.account, latest_credit_score=credit_score)
        self.loan.loan_status_id = 218
        self.loan.save()

        julo_one_loan_disbursement_failed(self.loan, force_failed=True)
        self.loan.refresh_from_db()
        mock_mark_failed.assert_called_once()


class TestJuloOneLenderAutoMatchmaking(TestCase):
    def setUp(self):
        self.j1_product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1, product_profile=ProductProfileFactory()
        )
        self.account = AccountFactory()
        self.application = ApplicationJ1Factory(account=self.account)
        self.loan = LoanFactory(account=self.account)
        self.lender = LenderCurrentFactory(lender_name='test-lender')
        self.lender_counter = LenderDisburseCounterFactory(
            lender=self.lender, actual_count=1, rounded_count=2
        )
        self.force_assign_lender = FeatureSettingFactory(
            feature_name='force_channeling',
            is_active=False,
        )

    def test_julo_one_lender_auto_matchmaking_bypass_product_line(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE,
            category='followthemoney',
            is_active=True,
            parameters={str(self.j1_product_line.pk): self.lender.id},
        )

        ret_val = julo_one_lender_auto_matchmaking(self.loan)

        self.assertEquals(self.lender, ret_val)

        self.lender_counter.refresh_from_db()
        self.assertEquals(3, self.lender_counter.rounded_count)
        self.assertEquals(2, self.lender_counter.actual_count)

    def test_julo_one_lender_auto_matchmaking_default_lender(self):
        lender = LenderCurrentFactory(lender_name='new-insufficient-lender', lender_status='active')
        LenderBalanceCurrentFactory(lender=lender)
        self.assertEquals(None, julo_one_lender_auto_matchmaking(self.loan))

        FeatureSettingFactory(
            feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
            category='followthemoney',
            is_active=True,
            parameters={"lender_name": self.lender.lender_name},
        )
        # default lender has insufficient balance
        default_lender_balance = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=0
        )
        self.assertEquals(self.lender, julo_one_lender_auto_matchmaking(self.loan))

        # default lender has sufficient balance
        default_lender_balance.available_balance = self.loan.loan_amount
        default_lender_balance.save()
        self.assertEquals(self.lender, julo_one_lender_auto_matchmaking(self.loan))

    def test_julo_one_lender_auto_matchmaking_grab_account(self):
        loan = LoanFactory(account=AccountFactory(account_lookup__name='GRAB'))
        lender = LenderCurrentFactory(lender_name='ska', lender_status='active')
        LenderDisburseCounterFactory(lender=lender, actual_count=1, rounded_count=2)
        LenderBalanceCurrentFactory(lender=lender)
        self.assertEquals(lender, julo_one_lender_auto_matchmaking(loan))

    @patch('juloserver.loan.services.lender_related.force_assigned_lender')
    def test_force_assign_lender_fs_active(self, mock_force_assigned_lender):
        lender_name = 'fama_channeling'
        lender = LenderFactory(lender_name=lender_name)
        mock_force_assigned_lender.return_value = lender
        self.loan.loan_duration = 10
        self.loan.save()
        self.force_assign_lender.is_active = True
        self.force_assign_lender.parameters = {"FAMA": [10, 12]}
        self.force_assign_lender.save()

        product_line = ProductLineFactory(product_line_code=1)
        product = ProductLookupFactory(product_line=product_line)

        self.loan.product = product
        self.loan.save()

        LenderDisburseCounterFactory(lender=lender, actual_count=1, rounded_count=2)
        LenderBalanceCurrentFactory(lender=lender)
        res = julo_one_lender_auto_matchmaking(self.loan)
        self.assertEquals(lender_name, res.lender_name)


class TestProcessDisburse(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name=PartnerNameConstant.VOSPAY)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.lender = LenderFactory(lender_name='jtp')
        self.lender_balance_current = LenderBalanceCurrentFactory(lender=self.lender)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE', validation_status=NameBankValidationStatus.SUCCESS
        )
        self.disbursement = DisbursementFactory(
            method='Xfers', name_bank_validation=self.name_bank_validation
        )
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1, product_line_type='J1'
        )
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            disbursement_id=self.disbursement.id,
            loan_status=self.loan_status,
            lender=self.lender,
            product=ProductLookupFactory(product_line=self.product_line),
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.partner_property = PartnerPropertyFactory(
            partner=self.partner, account=self.account, is_active=True
        )
        self.partnership_type = PartnershipTypeFactory(
            partner_type_name=PartnershipTypeConstant.WHITELABEL_PAYLATER
        )
        self.partnership_config = PartnershipConfigFactory(
            partner=self.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30],
        )
        PartnerLoanRequestFactory(
            loan=self.loan,
            partner=self.partner,
            distributor=None,
            loan_amount=self.loan.loan_amount,
            loan_disbursement_amount=self.loan.loan_disbursement_amount,
            loan_original_amount=self.loan.loan_amount,
            partner_origin_name=None,
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=212, status_next=220, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=218, status_next=212, workflow=self.workflow)
        WorkflowStatusPathFactory(status_previous=212, status_next=213, workflow=self.workflow)

    def test_process_disburse(self):
        data_to_disburse = {
            'disbursement_id': self.loan.disbursement_id,
            'name_bank_validation_id': self.name_bank_validation.id,
            'amount': self.loan.loan_disbursement_amount,
            'external_id': self.loan.loan_xid,
            'type': 'loan',
            'original_amount': self.loan.loan_amount,
        }
        self.loan.loan_status_id = 218
        self.loan.save()
        process_disburse(data_to_disburse, self.loan)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING)

    @patch('requests.post', side_effect=mocked_requests_success)
    def test_process_disburse_ayoconnect(self, mock_requests):
        bank = BankFactory(xfers_bank_code=self.name_bank_validation.bank_code)
        ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(name="ayoconnect")
        bank_account_dest = BankAccountDestinationFactory(
            bank=bank, name_bank_validation=self.name_bank_validation
        )
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_dest.bank_id,
            swift_bank_code=self.name_bank_validation.bank_code,
        )
        data_to_disburse = {
            'disbursement_id': self.loan.disbursement_id,
            'name_bank_validation_id': self.name_bank_validation.id,
            'amount': self.loan.loan_disbursement_amount,
            'external_id': self.loan.loan_xid,
            'type': 'loan',
            'original_amount': self.loan.loan_amount,
        }
        self.disbursement.method = DisbursementVendors.AYOCONNECT
        self.disbursement.step = 2
        self.disbursement.external_id = self.loan.loan_xid
        self.disbursement.save()

        # if beneficiary doesn't exist, create new beneficiary
        process_disburse(data_to_disburse, self.loan)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        pg_cust_data = PaymentGatewayCustomerData.objects.last()
        self.assertEqual(pg_cust_data.customer_id, self.customer.id)
        self.assertEqual(pg_cust_data.phone_number, self.customer.phone)
        self.assertEqual(pg_cust_data.account_number, self.name_bank_validation.account_number)
        self.assertEqual(pg_cust_data.bank_code, self.name_bank_validation.bank_code)
        self.assertIsNotNone(pg_cust_data.beneficiary_id)
        self.assertEqual(pg_cust_data.status, AyoconnectBeneficiaryStatus.INACTIVE)

        # if beneficiary exist but inactive, need to wait to activate beneficiary via callback
        self.loan.loan_status = self.loan_status
        self.loan.save()
        process_disburse(data_to_disburse, self.loan)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        new_pg_cust_data = PaymentGatewayCustomerData.objects.last()
        self.assertEqual(new_pg_cust_data.id, pg_cust_data.id)

    @patch('juloserver.disbursement.services.xfers.JTFXfersService.disburse')
    @patch('juloserver.disbursement.services.xfers.JTFXfersService.check_balance')
    @patch('juloserver.grab.services.loan_related.check_grab_auth_success')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_beneficiary')
    @patch('requests.post', side_effect=mocked_requests_ayoconnect_system_error_maintenance)
    def test_process_disburse_ayoconnect_with_error_system_maintenance(
        self,
        mock_requests,
        mock_check_beneficiary,
        mock_check_grab_auth_success,
        mock_xfers_check_balance,
        mock_xfers_disburse,
    ):
        mock_check_grab_auth_success.return_value = True
        mock_check_beneficiary.return_value = True, AyoconnectBeneficiaryStatus.ACTIVE
        mock_xfers_check_balance.return_value = 'sufficient balance', True
        mock_xfers_disburse.return_value = {
            'response_time': timezone.localtime(timezone.now()),
            'status': DisbursementStatus.PENDING,
            'id': 'haishiahsihad',
            'amount': 2000000,
            'reason': None,
            'reference_id': 'xfers7813201313',
        }
        workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        account_lookup = AccountLookupFactory(workflow=workflow, name=GRAB_ACCOUNT_LOOKUP_NAME)
        customer = CustomerFactory()
        account = AccountFactory(customer=customer, account_lookup=account_lookup)
        application = ApplicationFactory(customer=customer, account=account, workflow=workflow)
        lender = LenderFactory(lender_name='ska')
        lender_balance_current = LenderBalanceCurrentFactory(lender=lender)
        loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE', validation_status=NameBankValidationStatus.SUCCESS
        )
        disbursement = DisbursementFactory(
            method='Xfers', name_bank_validation=name_bank_validation
        )
        product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB, product_line_type='J1'
        )
        bank = BankFactory(xfers_bank_code=name_bank_validation.bank_code)
        bank_account_dest = BankAccountDestinationFactory(
            bank=bank, name_bank_validation=name_bank_validation
        )
        loan = LoanFactory(
            customer=customer,
            account=account,
            disbursement_id=disbursement.id,
            loan_status=loan_status,
            lender=lender,
            product=ProductLookupFactory(product_line=product_line),
            bank_account_destination=bank_account_dest,
        )
        account_limit = AccountLimitFactory(account=account)
        ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(name="ayoconnect")
        beneficiary_id = "test123"
        external_customer_id = "JULO-XXI"
        payment_gateway_customer_data = PaymentGatewayCustomerData.objects.create(
            customer_id=customer.id,
            payment_gateway_vendor=ayoconnect_payment_gateway_vendor,
            beneficiary_id=beneficiary_id,
            external_customer_id=external_customer_id,
        )
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_dest.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        grab_disbursement_retry_ft = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_DISBURSEMENT_RETRY,
            is_active=True,
            category='grab',
            description='configuration for GRAB disbursement retry',
            parameters={'max_retry_times': 3, 'delay_in_min': 5},
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_AYOCONNECT_XFERS_FAILOVER, is_active=True
        )
        data_to_disburse = {
            'disbursement_id': loan.disbursement_id,
            'name_bank_validation_id': name_bank_validation.id,
            'amount': loan.loan_disbursement_amount,
            'external_id': loan.loan_xid,
            'type': 'loan',
            'original_amount': loan.loan_amount,
        }
        disbursement.method = DisbursementVendors.AYOCONNECT
        disbursement.step = 2
        disbursement.external_id = loan.loan_xid
        disbursement.save()

        application.update_safely(name_bank_validation=disbursement.name_bank_validation)

        process_disburse(data_to_disburse, loan)
        loan.refresh_from_db()
        disbursement.refresh_from_db()
        # check disbursement updated to PG services
        self.assertEqual(loan.loan_status_id, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        self.assertEqual(disbursement.method, DisbursementVendors.PG)
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)

        # make sure 'system under maintenance' history only recorded 1
        disbursement_history = Disbursement2History.objects.filter(
            method=DisbursementVendors.AYOCONNECT,
            disbursement=disbursement,
            reason=AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE,
        )
        self.assertEqual(disbursement_history.count(), 1)

    @patch('requests.post', side_effect=mocked_requests_success)
    def test_process_disburse_ayoconnect_with_nbv_PG(self, mock_requests):
        bank = BankFactory(bank_code=BankCodes.BCA)
        name_bank_validation = NameBankValidationFactory(
            bank=bank,
            method=NameBankValidationVendors.PAYMENT_GATEWAY,
            validation_status=NameBankValidationStatus.SUCCESS,
        )
        ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(name="ayoconnect")
        bank_account_dest = BankAccountDestinationFactory(
            bank=bank, name_bank_validation=name_bank_validation
        )
        PaymentGatewayBankCodeFactory(
            payment_gateway_vendor=ayoconnect_payment_gateway_vendor,
            bank_id=bank_account_dest.bank_id,
            swift_bank_code=name_bank_validation.bank_code,
        )
        data_to_disburse = {
            'disbursement_id': self.loan.disbursement_id,
            'name_bank_validation_id': name_bank_validation.id,
            'amount': self.loan.loan_disbursement_amount,
            'external_id': self.loan.loan_xid,
            'type': 'loan',
            'original_amount': self.loan.loan_amount,
        }
        self.disbursement.method = DisbursementVendors.AYOCONNECT
        self.disbursement.step = 2
        self.disbursement.external_id = self.loan.loan_xid
        self.disbursement.save()

        # if beneficiary doesn't exist, create new beneficiary
        process_disburse(data_to_disburse, self.loan)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        pg_cust_data = PaymentGatewayCustomerData.objects.last()
        self.assertEqual(pg_cust_data.customer_id, self.customer.id)
        self.assertEqual(pg_cust_data.phone_number, self.customer.phone)
        self.assertEqual(pg_cust_data.account_number, name_bank_validation.account_number)
        self.assertEqual(pg_cust_data.bank_code, name_bank_validation.bank_code)
        self.assertIsNotNone(pg_cust_data.beneficiary_id)
        self.assertEqual(pg_cust_data.status, AyoconnectBeneficiaryStatus.INACTIVE)

        # if beneficiary exist but inactive, need to wait to activate beneficiary via callback
        self.loan.loan_status = self.loan_status
        self.loan.save()
        process_disburse(data_to_disburse, self.loan)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        new_pg_cust_data = PaymentGatewayCustomerData.objects.last()
        self.assertEqual(new_pg_cust_data.id, pg_cust_data.id)


class TestJuloOneLoanDisbursementSuccessWithPromoCode(TestCase):
    def setUp(self):
        # Init user info
        AccountingCutOffDateFactory()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
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
        )
        AccountLimitFactory(account=self.account, available_limit=10000000)

        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            loan_amount=500000,
            installment_amount=206000,
            loan_duration=3,
            loan_disbursement_amount=465000,
            first_installment_amount=186000,
            lender=LenderFactory(lender_name='jtp'),
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=212, status_next=220, workflow=self.workflow)

        payments_data = [
            {
                'loan': self.loan,
                'due_amount': 182133,
                'paid_amount': 0,
                'installment_interest': 20000,
                'installment_principal': 166000,
                'payment_number': 1,
            },
            {
                'loan': self.loan,
                'due_amount': 198133,
                'paid_amount': 0,
                'installment_interest': 40000,
                'installment_principal': 16600,
                'payment_number': 2,
            },
            {
                'loan': self.loan,
                'due_amount': 198134,
                'paid_amount': 0,
                'installment_interest': 40000,
                'installment_principal': 166000,
                'payment_number': 3,
            },
        ]

        for payment, updated_payment in zip(list(self.loan.payment_set.all()), payments_data):
            payment.update_safely(**updated_payment)

    def test_disbursement_success_with_max_amount_promo_code_tc1(self):
        loan = self.loan

        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 20, 'duration': 3, 'max_amount': 3000},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMOINTERRESTMAX', promo_code_benefit=promo_code_benefit
        )
        promo_code_usage = PromoCodeUsageFactory(
            loan_id=loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=promo_code,
            version='v1',
        )

        julo_one_loan_disbursement_success(loan)
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')
        self.assertEqual(3, len(payments))
        payment1, payment2, payment3 = payments
        account_payment1 = AccountPayment.objects.filter(payment=payment1).first()
        account_payment2 = AccountPayment.objects.filter(payment=payment2).first()
        account_payment3 = AccountPayment.objects.filter(payment=payment3).first()
        self.assertIsNotNone(account_payment1)
        self.assertIsNotNone(account_payment2)
        self.assertIsNotNone(account_payment3)

        self.assertEqual(3000, payment1.paid_amount)
        self.assertEqual(3000, payment1.paid_interest)
        self.assertEqual(3000, payment2.paid_amount)
        self.assertEqual(3000, payment2.paid_interest)
        self.assertEqual(3000, payment3.paid_amount)
        self.assertEqual(3000, payment3.paid_interest)
        self.assertEqual(3000, account_payment1.paid_amount)
        self.assertEqual(3000, account_payment1.paid_interest)
        self.assertEqual(3000, account_payment2.paid_amount)
        self.assertEqual(3000, account_payment2.paid_interest)
        self.assertEqual(3000, account_payment3.paid_amount)
        self.assertEqual(3000, account_payment3.paid_interest)

    def test_disbursement_success_with_max_amount_promo_code_tc2(self):
        loan = self.loan

        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 20, 'duration': 3, 'max_amount': 4001},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMOINTERRESTMAX2', promo_code_benefit=promo_code_benefit
        )
        promo_code_usage = PromoCodeUsageFactory(
            loan_id=loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=promo_code,
            version='v1',
        )

        julo_one_loan_disbursement_success(loan)
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')
        self.assertEqual(3, len(payments))
        payment1, payment2, payment3 = payments
        account_payment1 = AccountPayment.objects.filter(payment=payment1).first()
        account_payment2 = AccountPayment.objects.filter(payment=payment2).first()
        account_payment3 = AccountPayment.objects.filter(payment=payment3).first()
        self.assertIsNotNone(account_payment1)
        self.assertIsNotNone(account_payment2)
        self.assertIsNotNone(account_payment3)

        self.assertEqual(4000, payment1.paid_amount)
        self.assertEqual(4000, payment1.paid_interest)
        self.assertEqual(4001, payment2.paid_amount)
        self.assertEqual(4001, payment2.paid_interest)
        self.assertEqual(4001, payment3.paid_amount)
        self.assertEqual(4001, payment3.paid_interest)

        self.assertEqual(4000, account_payment1.paid_amount)
        self.assertEqual(4000, account_payment1.paid_interest)
        self.assertEqual(4001, account_payment2.paid_amount)
        self.assertEqual(4001, account_payment2.paid_interest)
        self.assertEqual(4001, account_payment3.paid_amount)
        self.assertEqual(4001, account_payment3.paid_interest)

    def test_disbursement_success_with_max_amount_promo_code_tc3(self):
        loan = self.loan

        promo_code_benefit = PromoCodeBenefitFactory(
            type=PromoCodeBenefitConst.INTEREST_DISCOUNT,
            value={'percent': 20, 'duration': 3, 'max_amount': 8001},
        )
        promo_code = PromoCodeLoanFactory(
            promo_code='TESTPROMOINTERRESTMAX3', promo_code_benefit=promo_code_benefit
        )
        promo_code_usage = PromoCodeUsageFactory(
            loan_id=loan.id,
            customer_id=self.customer.id,
            application_id=self.application.id,
            promo_code=promo_code,
            version='v1',
        )

        julo_one_loan_disbursement_success(loan)
        payments = Payment.objects.filter(loan=loan).order_by('payment_number')
        self.assertEqual(3, len(payments))
        payment1, payment2, payment3 = payments
        account_payment1 = AccountPayment.objects.filter(payment=payment1).first()
        account_payment2 = AccountPayment.objects.filter(payment=payment2).first()
        account_payment3 = AccountPayment.objects.filter(payment=payment3).first()
        self.assertIsNotNone(account_payment1)
        self.assertIsNotNone(account_payment2)
        self.assertIsNotNone(account_payment3)

        self.assertEqual(4000, payment1.paid_amount)
        self.assertEqual(4000, payment1.paid_interest)
        self.assertEqual(8000, payment2.paid_amount)
        self.assertEqual(8000, payment2.paid_interest)
        self.assertEqual(8000, payment3.paid_amount)
        self.assertEqual(8000, payment3.paid_interest)
        self.assertEqual(4000, account_payment1.paid_amount)
        self.assertEqual(4000, account_payment1.paid_interest)
        self.assertEqual(8000, account_payment2.paid_amount)
        self.assertEqual(8000, account_payment2.paid_interest)
        self.assertEqual(8000, account_payment3.paid_amount)
        self.assertEqual(8000, account_payment3.paid_interest)


class TestJuloOneLoanBalanceConsolidationDisbursementSuccess(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        account_property = AccountPropertyFactory(account=self.account)
        account_property.save()
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            lender=LenderFactory(lender_name='jtp'),
        )
        self.status_lookup = StatusLookupFactory(status_code=212)
        self.loan.loan_status = self.status_lookup
        self.loan.account = self.account
        balance_consolidation = BalanceConsolidationFactory(customer=self.customer)
        consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=balance_consolidation,
            validation_status=BalanceConsolidationStatus.APPROVED,
        )
        consolidation_verification.account_limit_histories = {
            "upgrade": {"max_limit": 385918, "set_limit": 385919, "available_limit": 385920}
        }
        consolidation_verification.loan = self.loan
        self.loan.save()
        consolidation_verification.save()

    @patch('juloserver.loan.services.loan_related.update_available_limit')
    def test_account_payment_is_updated_in_loan_balance_consolidation(
        self, mock_update_available_limit
    ):
        julo_one_loan_disbursement_success(self.loan)

        payments = Payment.objects.filter(loan_id=self.loan.id)
        for payment in payments:
            self.assertEqual(payment.installment_interest, payment.account_payment.paid_interest)
            self.assertEqual(payment.installment_interest, payment.account_payment.paid_amount)


class TestPromoCodeRobocall(TestCase):
    def setUp(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.NEXMO_NUMBER_RANDOMIZER, is_active=False
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.j1_product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1, product_profile=ProductProfileFactory()
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.j1_product_line,
            application_status=StatusLookupFactory(status_code=190),
        )
        self.call_to = "08123321123"
        VoiceCallRecordFactory(application=self.application, call_to=self.call_to)

    @patch('django.utils.timezone.now')
    @patch('nexmo.Client')
    def test_sending_promo_code_robocall(self, mock_nexmo_client, mock_time_zone):
        mock_time_zone.return_value = datetime(2022, 9, 30, 15, 0, 0)
        mock_nexmo_client().create_call.return_value = dict(
            status="success", direction="test", uuid="321312321", conversation_uuid="32132131232"
        )
        template_code = 'promo_code_june_2023'
        data = [
            dict(
                customer_id=1008514217,
                phone_number="08111566123",
                gender="Wanita",
                full_name="Linh Le",
                address_kodepos="9766",
                customer_segment='graduation_script',
            )
        ]
        loan_info_dict = construct_loan_infos_for_robocall_script(data[0])
        response = send_promo_code_robocall_subtask(
            customer_id=self.customer.pk,
            phone_number="085262348669",
            gender="Pria",
            full_name="Test",
            loan_info_dict=loan_info_dict,
            template_text="Test template",
            list_phone_numbers=["03213021391"],
            template_code=template_code,
        )
        assert response != None
        mock_nexmo_client().create_call.assert_called_once()

    @patch('django.utils.timezone.now')
    @patch('nexmo.Client')
    def test_sending_promo_code_robocall_with_old_phone(self, mock_nexmo_client, mock_time_zone):
        mock_time_zone.return_value = datetime(2022, 9, 30, 15, 0, 0)
        mock_nexmo_client().create_call.return_value = dict(
            status="success", direction="test", uuid="321312321", conversation_uuid="32132131232"
        )
        template_code = 'promo_code_june_2023'
        data = [
            dict(
                customer_id=1008514217,
                phone_number="08111566123",
                gender="Wanita",
                full_name="Linh Le",
                address_kodepos="9766",
                customer_segment='graduation_script',
            )
        ]
        loan_info_dict = construct_loan_infos_for_robocall_script(data[0])
        response = send_promo_code_robocall_subtask(
            customer_id=self.customer.pk,
            phone_number="085262348669",
            gender="Pria",
            full_name="Test",
            loan_info_dict=loan_info_dict,
            template_text="Test template",
            list_phone_numbers=[self.call_to],
            template_code=template_code,
        )
        assert response != None
        mock_nexmo_client().create_call.assert_called_once()

    @patch('django.utils.timezone.now')
    @patch('nexmo.Client')
    def test_sending_promo_code_robocall_with_loan_amount_data(
        self, mock_nexmo_client, mock_time_zone
    ):
        mock_time_zone.return_value = datetime(2023, 9, 30, 15, 0, 0)
        mock_nexmo_client().create_call.return_value = dict(
            status="success", direction="test", uuid="321312321", conversation_uuid="32132131232"
        )
        template_code = 'promo_code_june_2024'
        data = [
            dict(
                customer_id=1008514217,
                phone_number="08111566123",
                gender="Wanita",
                full_name="Linh Le",
                address_kodepos="9766",
                customer_segment='graduation_script',
                loan_amount="3000000",
                existing_monthly_installment="500000",
                new_monthly_installment="450000",
                saving_amount="50000",
            )
        ]
        loan_info_dict = construct_loan_infos_for_robocall_script(data[0])
        response = send_promo_code_robocall_subtask(
            customer_id=self.customer.pk,
            phone_number="085262348669",
            gender="Pria",
            full_name="Test",
            loan_info_dict=loan_info_dict,
            template_text="Test template",
            list_phone_numbers=["03213021391"],
            template_code=template_code,
        )
        assert response != None
        mock_nexmo_client().create_call.assert_called_once()

    @patch('django.utils.timezone.now')
    @patch('nexmo.Client')
    def test_sending_promo_code_robocall_with_interest(self, mock_nexmo_client, mock_time_zone):
        mock_time_zone.return_value = datetime(2023, 9, 30, 15, 0, 0)
        mock_nexmo_client().create_call.return_value = dict(
            status="success", direction="test", uuid="321312321", conversation_uuid="32132131232"
        )
        template_code = 'promo_code_june_2024'
        data = [
            dict(
                customer_id=1008514217,
                phone_number="08111566123",
                gender="Wanita",
                full_name="Linh Le",
                address_kodepos="9766",
                customer_segment='graduation_script',
                new_interest="10%",
                existing_interest="12%",
            )
        ]
        loan_info_dict = construct_loan_infos_for_robocall_script(data[0])
        response = send_promo_code_robocall_subtask(
            customer_id=self.customer.pk,
            phone_number="085262348669",
            gender="Pria",
            full_name="Test",
            loan_info_dict=loan_info_dict,
            template_text="Test template",
            list_phone_numbers=["03213021391"],
            template_code=template_code,
        )
        assert response != None
        mock_nexmo_client().create_call.assert_called_once()

class TestExpiredLoanNotAutoApprove(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.user2 = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user2, name=PartnerNameConstant.J1)
        self.lender = LenderCurrentFactory(lender_name='jtp', user=self.user2)
        self.lender_balance_current = LenderBalanceCurrentFactory(lender=self.lender)
        self.repayment_transaction_type = LenderTransactionType.objects.create(
            transaction_type='repayment'
        )
        self.number_loans = 3
        self.loans = LoanFactory.create_batch(
            3,
            customer=self.customer,
            account=self.account,
            lender=self.lender,
            partner=self.partner,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL),
        )
        self.feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.FTM_CONFIGURATION,
            category="followthemoney",
            is_active=True,
            parameters={'expired_loan_for_lenders': ['jtp', 'pascal', 'jh']},
        )
        self.lender_approval = LenderApproval.objects.create(
            partner=self.partner,
            is_auto=False,
            expired_in=time(12, 0),
            expired_start_time=time(6, 0),
            expired_end_time=time(20, 0),
        )

    @patch('django.utils.timezone.now')
    @patch('juloserver.loan.services.lender_related.auto_expired_loan_tasks')
    def test_expired_loan_after_expired_time_lender(
        self, _mock_auto_expired_loan_tasks, _mock_time_zone
    ):
        _mock_time_zone.return_value = Loan.objects.first().cdate + relativedelta(hours=13)
        self.lender_approval.expired_start_time = time(0, 0)
        self.lender_approval.expired_end_time = time(23, 59)
        self.lender_approval.save()
        reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task()

        assert _mock_auto_expired_loan_tasks.delay.call_count == self.number_loans

    @patch('django.utils.timezone.now')
    @patch('juloserver.loan.services.lender_related.auto_expired_loan_tasks')
    def test_not_expired_loan_after_expired_time_lender(
        self, _mock_auto_expired_loan_tasks, _mock_time_zone
    ):
        # current time - cdate < expired_in
        _mock_time_zone.return_value = Loan.objects.first().cdate + relativedelta(hours=10)
        reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task()
        assert _mock_auto_expired_loan_tasks.delay.call_count == 0

    @patch('django.utils.timezone.now')
    @patch('juloserver.loan.services.lender_related.auto_expired_loan_tasks')
    def test_not_expired_loan_after_expired_time_lender_with_start_and_end_time(
        self, _mock_auto_expired_loan_tasks, _mock_time_zone
    ):
        # current time - cdate < expired_in
        _mock_time_zone.return_value = Loan.objects.first().cdate + relativedelta(days=2, hour=21)
        self.lender_approval.expired_start_time = time(5, 0)
        self.lender_approval.expired_end_time = time(5, 1)
        self.lender_approval.save()

        reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task()
        assert _mock_auto_expired_loan_tasks.delay.call_count == 0

    @patch('django.utils.timezone.now')
    @patch('juloserver.loan.services.lender_related.auto_expired_loan_tasks')
    def test_not_expired_loan_has_loan_lender_history(
        self, _mock_auto_expired_loan_tasks, _mock_time_zone
    ):
        # current time - cdate < expired_in
        _mock_time_zone.return_value = Loan.objects.first().cdate + relativedelta(hours=12)
        self.lender_approval.expired_start_time = time(0, 0)
        self.lender_approval.expired_end_time = time(23, 59)
        self.lender_approval.save()
        for loan in Loan.objects.all():
            LoanLenderHistory.objects.create(loan=loan, lender_id=loan.lender_id)

        _mock_time_zone.return_value = LoanLenderHistory.objects.first().cdate + relativedelta(
            hours=10
        )
        reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task()
        assert _mock_auto_expired_loan_tasks.delay.call_count == 0

    @patch('django.utils.timezone.now')
    @patch('juloserver.loan.services.lender_related.auto_expired_loan_tasks')
    def test_expired_loan_has_loan_lender_history(
        self, _mock_auto_expired_loan_tasks, _mock_time_zone
    ):
        # current time - cdate < expired_in
        _mock_time_zone.return_value = Loan.objects.first().cdate + relativedelta(hours=12)
        self.lender_approval.expired_start_time = time(0, 0)
        self.lender_approval.expired_end_time = time(23, 59)
        self.lender_approval.save()
        for loan in Loan.objects.all():
            LoanLenderHistory.objects.create(loan=loan, lender_id=loan.lender_id)

        _mock_time_zone.return_value = LoanLenderHistory.objects.first().cdate + relativedelta(
            hours=13
        )
        reassign_lender_or_expire_loans_x211_for_lenders_not_auto_approve_task()
        assert _mock_auto_expired_loan_tasks.delay.call_count == self.number_loans


class TestHoldoutUserBSSChanneling(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.HOLDOUT_USERS_FROM_BSS_CHANNELING,
            is_active=True,
        )
        self.dynamic_check = DynamicCheck.objects.create(
            application_id=self.application.pk,
            is_okay=False,
            is_holdout=True,
            check_name='test',
            version='test',
        )

    def test_is_holdout_users_from_bss_channeling(self):
        # is holdout users
        assert is_holdout_users_from_bss_channeling(self.application.pk) == True

        # fs is turned off
        self.feature.is_active = False
        self.feature.save()
        assert is_holdout_users_from_bss_channeling(self.application.pk) == False

        # fs is turned on, dynamic check doesn't exist
        self.feature.is_active = True
        self.feature.save()
        self.dynamic_check.is_okay = True
        self.dynamic_check.save()
        assert is_holdout_users_from_bss_channeling(self.application.pk) == False

        # No dynamic check exists in the db
        self.dynamic_check.delete()
        assert is_holdout_users_from_bss_channeling(self.application.pk) == False


class TestHandleAyoconnectBeneficiaryErrorsOnDisbursement(TestCase):
    def setUp(self):
        self.disbursement = DisbursementFactory(method=DisbursementVendors.AYOCONNECT)
        self.customer = CustomerFactory()
        self.loan = LoanFactory(disbursement_id=self.disbursement.id, customer=self.customer)
        self.ayoconnect_payment_gateway_vendor, _ = PaymentGatewayVendor.objects.get_or_create(
            name=PaymentGatewayVendorConst.AYOCONNECT
        )
        self.pg_customer_data = PaymentGatewayCustomerDataFactory(
            customer_id=self.customer.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            beneficiary_id="random_beneficiary_id",
            status=AyoconnectBeneficiaryStatus.ACTIVE,
        )
        self.pg_customer_data_loan = PaymentGatewayCustomerDataLoanFactory(
            loan=self.loan,
            disbursement=self.disbursement,
            beneficiary_id=self.pg_customer_data.beneficiary_id,
        )

    def test_handle_ayoconnect_beneficiary_errors_on_disbursement(self):
        handle_ayoconnect_beneficiary_errors_on_disbursement(
            loan=self.loan, disbursement_reason=self.disbursement.reason
        )
        self.pg_customer_data.refresh_from_db()
        self.assertNotEqual(
            self.pg_customer_data.status,
            AyoconnectBeneficiaryStatus.UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK,
        )

        self.disbursement.reason = AyoconnectErrorCodes.J1_RECREATE_BEN_IDS[0]
        self.disbursement.save()
        handle_ayoconnect_beneficiary_errors_on_disbursement(
            loan=self.loan, disbursement_reason=self.disbursement.reason
        )
        self.pg_customer_data.refresh_from_db()
        self.assertEqual(
            self.pg_customer_data.status,
            AyoconnectBeneficiaryStatus.UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK,
        )


class TestFailoverToXfers(TestCase):
    def test_is_disbursement_stuck_less_than_threshold(self):
        now = timezone.localtime(timezone.now())
        # disbursement created at 2 days ago => stuck
        disbursement_created_at = now - timedelta(days=2)
        self.assertFalse(is_disbursement_stuck_less_than_threshold(disbursement_created_at))

        # disbursement created at 25 hours ago => stuck
        disbursement_created_at = now - timedelta(hours=25)
        self.assertFalse(is_disbursement_stuck_less_than_threshold(disbursement_created_at))

        # disbursement created at 23 hours ago => still in threshold
        disbursement_created_at = now - timedelta(hours=23)
        self.assertTrue(is_disbursement_stuck_less_than_threshold(disbursement_created_at))

        # disbursement just created 12 hours => still in threshold
        disbursement_created_at = now - timedelta(hours=12)
        self.assertTrue(is_disbursement_stuck_less_than_threshold(disbursement_created_at))

        # disbursement just created => still in threshold
        disbursement_created_at = now
        self.assertTrue(is_disbursement_stuck_less_than_threshold(disbursement_created_at))

    def test_switch_disbursement_to_xfers(self):
        disbursement = DisbursementFactory(
            amount=10_000,
            original_amount=10_000,
            method=DisbursementVendors.AYOCONNECT,
        )
        reason = "Example reason"

        switch_disbursement_to_xfers(disbursement=disbursement, lender_name='random', reason=reason)
        self.assertEqual(disbursement.retry_times, 0)
        self.assertEqual(disbursement.disburse_status, DisbursementStatus.INITIATED)
        self.assertEqual(disbursement.method, DisbursementVendors.XFERS)
        self.assertEqual(disbursement.reason, None)
        self.assertIsNone(disbursement.disburse_id)
        self.assertIsNone(disbursement.reference_id)
        self.assertEqual(disbursement.step, XfersDisbursementStep.FIRST_STEP)
        self.assertEqual(DisbursementHistory.objects.filter(disbursement=disbursement).count(), 1)
        self.assertEqual(Disbursement2History.objects.filter(disbursement=disbursement).count(), 1)

        lender = LenderCurrentFactory(lender_name='support_escrow', is_only_escrow_balance=True)
        switch_disbursement_to_xfers(
            disbursement=disbursement, lender_name=lender.lender_name, reason=reason
        )
        self.assertEqual(disbursement.step, XfersDisbursementStep.SECOND_STEP)
        self.assertEqual(DisbursementHistory.objects.filter(disbursement=disbursement).count(), 2)
        self.assertEqual(Disbursement2History.objects.filter(disbursement=disbursement).count(), 2)


class TestJuloOneCorrectPaymentDueDate(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        account_property = AccountPropertyFactory(account=self.account)
        account_property.save()
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.lender = LenderFactory(lender_name='jtp')
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            lender=self.lender,
            loan_duration=9,
        )
        self.loan_paid_off = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
            lender=self.lender,
            loan_duration=9,
        )
        self.status_lookup = StatusLookupFactory(status_code=212)
        self.loan_success_status = StatusLookupFactory(status_code=220)
        self.loan.loan_status = self.status_lookup
        self.loan.account = self.account
        self.loan.save()

    @patch('juloserver.loan.services.loan_related.update_available_limit')
    def test_account_payments_are_updated_follow_payment_due_date(
        self, mock_update_available_limit
    ):
        for payment in Payment.objects.filter(loan_id=self.loan_paid_off).all():
            payment.due_date = datetime(2024, payment.payment_number, 2)
            payment.account_payment = AccountPaymentFactory(
                account=self.account,
                due_date=payment.due_date,
                late_fee_amount=0,
                paid_amount=0,
                principal_amount=9000,
                interest_amount=1000,
                is_restructured=False,
            )

            payment.save()

        expected_day = 28
        for payment in Payment.objects.filter(loan_id=self.loan.id):
            payment.due_date = datetime(2024, payment.payment_number, expected_day)
            payment.save()

        julo_one_loan_disbursement_success(self.loan)
        self.loan.refresh_from_db()
        account_payment_ids = []
        # check due_date of payment
        for payment in Payment.objects.filter(loan_id=self.loan.id):
            assert payment.due_date.day == expected_day
            account_payment_ids.append(payment.account_payment_id)

        # check new account_payments are created
        for account_payment in AccountPayment.objects.filter(pk__in=account_payment_ids):
            assert account_payment.due_date.day == expected_day

        for payment in Payment.objects.filter(loan_id=self.loan_paid_off).all():
            assert payment.due_date.day != expected_day


class TestJuloOneGetFAMABuybackLender(TestCase):
    def setUp(self):
        self.blue_finc_lender = LenderFactory(
            id=101,
            lender_status="active",
            lender_name=LenderName.BLUEFINC,
        )
        self.blue_finc_lender_balance = LenderBalanceCurrentFactory(
            lender=self.blue_finc_lender, available_balance=999999999
        )

        self.legend_capital_lender = LenderFactory(
            id=102,
            lender_status="active",
            lender_name=LenderName.LEGEND_CAPITAL,
        )
        self.legend_capital_lender_balance = LenderBalanceCurrentFactory(
            lender=self.legend_capital_lender, available_balance=999999999
        )

        self.loan = LoanFactory(
            id=1,
            loan_amount=1000000,
        )

    def test_julo_one_get_fama_buyback_lender(self):
        assigned_lender = julo_one_get_fama_buyback_lender(self.loan)

        self.assertIn(assigned_lender.id, [self.blue_finc_lender.id, self.legend_capital_lender.id])
