from mock import MagicMock, patch
from django.test.testcases import TestCase
from rest_framework.test import APIClient
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory
)
from juloserver.partnership.tests.factories import (
    DistributorFactory,
    MerchantDistributorCategoryFactory,
    PartnershipTypeFactory,
    PartnershipConfigFactory
)
from juloserver.account.tests.factories import AccountLookupFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    ProductLine, Partner, Application
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    CustomerFactory,
    PartnerFactory,
    ProductLookupFactory,
    WorkflowFactory,
    AuthUserFactory,
    ProductProfileFactory,
    ProductLineFactory,
    ApplicationFactory,
    StatusLookupFactory,
    PaymentFactory,
    LoanFactory,
    GlobalPaymentMethodFactory,
    PaymentMethodFactory,
    PaymentMethodLookupFactory,
    DocumentFactory,
)
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.banks import BankCodes
from juloserver.julo.exceptions import JuloException
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.merchant_financing.constants import (
    AXIATA_FEE_RATE,
    LoanDurationUnit,
    AxiataReportType
)
from juloserver.merchant_financing.services import (
    PartnerApplicationService,
    BankAccount,
    get_account_payments_and_virtual_accounts,
    LoanMerchantFinancing,
    get_payment_methods,
    generate_encrypted_application_xid,
    get_urls_axiata_report,
    process_mf_customer_validate_bank
)
from juloserver.partnership.constants import MERCHANT_FINANCING_PREFIX
from juloserver.merchant_financing.tests.factories import (
    ApplicationSubmissionFactory,
    MerchantFactory,
    MasterPartnerConfigProductLookupFactory,
    HistoricalPartnerConfigProductLookupFactory
)
from juloserver.sdk.tests.factories import AxiataCustomerDataFactory
from juloserver.merchant_financing.tests.factories import (
    MerchantFactory, MasterPartnerConfigProductLookupFactory,
    HistoricalPartnerConfigProductLookupFactory
)

from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.models import (
    NameBankValidation,
    BankNameValidationLog,
)
from juloserver.disbursement.tests.factories import NameBankValidationFactory


class TestPartnerApplicationService(TestCase):
    def setUp(self):
        super().setUp()
        self.partner = PartnerFactory(name='axiata')
        self.product_lookup = ProductLookupFactory(
            product_line=ProductLine.objects.get(pk=ProductLineCodes.AXIATA1),
            interest_rate=0.10,
            origination_fee_pct=0.10,
            admin_fee=1000,
            late_fee_pct=AXIATA_FEE_RATE,
        )
        self.axiata_customer_data = AxiataCustomerDataFactory(
            ktp='1234561212000001',
            interest_rate=0.1,
            origination_fee=0.1,
            admin_fee=1000,
            loan_duration=1,
            loan_duration_unit=LoanDurationUnit.MONTHLY
        )
        self.application_submission = ApplicationSubmissionFactory(axiata_customer_data=self.axiata_customer_data)
        self.customer = CustomerFactory(nik='1234561212000001')
        self.merchant = MerchantFactory(customer=self.customer)
        self.workflow = WorkflowFactory(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)

    def generate_application_data(self):
        return {
            'account_number': 'partner_app_id',
            'partner_merchant_code': 'merchant_code',
            'owner_name': 'owner name',
            'email': 'email@testing.com',
            'address_street_num': 'test address',
            'phone_number': '6281234567890',
            'ktp': self.customer.nik,
            'type_of_business': 'test type_of_business',
            'brand_name': 'test shop_name',
            'distributor': 1,
            'origination_fee': 10,
            'interest_rate': 10,
            'admin_fee': 1000,
            'loan_amount': 100000,
            'monthly_installment': 100000,
            'loan_duration': 1,
            'loan_duration_unit': LoanDurationUnit.MONTHLY,
            'date_of_establishment': '2021-09-09',
            'selfie_image': '',
            'ktp_image': '',
            'shops_number': 1,
        }

    @patch('juloserver.merchant_financing.services.PartnerApplicationService.process_image')
    @patch('juloserver.merchant_financing.services.loan_lender_approval_process_task')
    @patch('juloserver.merchant_financing.services.process_application_status_change')
    def test_min_approve_application_flow(self, mock_process_application_status_change,
            mock_loan_lender_approval_process_task, mock_process_image):
        """
        Integration test
        TODO: need to remove PartnerApplicationService.process_image mock
        """
        application_data = self.generate_application_data()
        (application, loan) = PartnerApplicationService.approve_application_flow(
            application_data, self.axiata_customer_data, self.partner)

        mock_process_application_status_change.assert_called_once_with(
            application.id, ApplicationStatusCodes.LOC_APPROVED,
            change_reason='Axiata Approved by script')
        mock_loan_lender_approval_process_task.assert_called_once_with(loan.id)
        mock_process_image.assert_called_once_with(self.axiata_customer_data)
        self.assertIsNotNone(application)
        self.assertEqual(application_data['email'], application.email)
        self.assertIsNotNone(loan)


class BankAccountTest(TestCase):
    @patch('juloserver.merchant_financing.services.XfersService.validate')
    def test_success_inquiry_bank_account(self, mock_validate):
        bank_account_number = '111222333'
        bank_code = 'bca'
        name_in_bank = 'jhon'
        bank_account = BankAccount()
        mock_response_validate = {
            'status': NameBankValidationStatus.SUCCESS,
            'id': '1234',
            'validated_name': name_in_bank,
            'reason': 'success',
            'error_message': None,
            'account_no': bank_account_number,
            'bank_abbrev': bank_code,
        }

        mock_validate.return_value = mock_response_validate
        response = bank_account.inquiry_bank_account(
            bank_account_number=bank_account_number, bank_code=bank_code,
            phone_number='085123456', name_in_bank=name_in_bank
        )
        self.assertEqual(response.get('status'), NameBankValidationStatus.SUCCESS)
        name_bank_validation = NameBankValidation.objects.filter(
            validation_id=response.get('id'),
            validated_name=response.get('validated_name'),
            account_number=response.get('account_no'),
            validation_status=NameBankValidationStatus.SUCCESS
        ).exists()
        self.assertTrue(name_bank_validation)
        bank_name_validation_log = BankNameValidationLog.objects.filter(
            validation_id=response.get('id'),
            validated_name=response.get('validated_name'),
            account_number=response.get('account_no')
        ).exists()
        self.assertTrue(bank_name_validation_log)


class TestAccountPaymentService(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        user = AuthUserFactory(username='testpartner')
        self.client.force_login(user)
        partner = PartnerFactory(user=user)
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor ab',
            address='jakarta',
            email='testdistributorab@gmail.com',
            phone_number='08123152321',
            type_of_business='warung',
            npwp='123040410292312',
            nib='223040410292912',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=123956,
        )
        self.status_lookup = StatusLookupFactory()
        self.merchant_1 = MerchantFactory(
            nik='3283020101910011',
            shop_name='merchant 9',
            distributor=self.distributor,
            merchant_xid=2594367997,
            business_rules_score=0.5
        )
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        self.customer = CustomerFactory(user=user)
        self.application_xid = 2554397666
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            merchant=self.merchant_1,
            partner=self.distributor.partner,
            application_xid=self.application_xid,
        )
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='Merchant Financing',
            payment_frequency='weekly'
        )

        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.account = self.account
        self.application.application_status_id = 190
        self.application.save()
        today = timezone.localtime(timezone.now()).date()
        self.start_date = today - relativedelta(days=3)
        self.end_date = today + relativedelta(days=50)
        self.start_date1 = today + relativedelta(days=30)
        self.end_date1 = today - relativedelta(days=5)
        self.is_paid_off_true = True
        self.is_paid_off_false = False
        self.filter_type = 'due_date'
        self.filter_type1 = 'cdate'
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id=330
        self.account_payment.save()
        payment_method_code = '123'
        payment_method_name = 'Bank BCA 1'
        GlobalPaymentMethodFactory(
            feature_name='BCA', is_active=True, is_priority=True, impacted_type='Primary',
            payment_method_code=payment_method_code, payment_method_name=payment_method_name)
        self.bank_name1 = 'BCA'
        self.bank_name2 = ''
        self.payment_method_name = 'PERMATA'
        self.payment_method_code = PaymentMethodCodes.PERMATA
        self.payment_method_name1 = 'BCA'
        self.payment_method_code1 = PaymentMethodCodes.BCA
        self.payment_method_name2 = 'PERMATA'
        self.payment_method_code2 = PaymentMethodCodes.PERMATA1


    def test_get_account_payments_and_virtual_accounts(self):
        data = {
            "application_xid": self.application_xid,
            "is_paid_off": self.is_paid_off_false,
            "filter_type": self.filter_type,
            "start_date": self.start_date,
            "end_date": self.end_date
        }

        data1 = {
            "application_xid": self.application_xid,
            "is_paid_off": self.is_paid_off_true,
            "filter_type": self.filter_type,
            "start_date": self.start_date,
            "end_date": self.end_date
        }
        account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(self.application_xid, data1)
        self.assertIsNotNone(account_payments)


        account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(self.application_xid, data)
        self.assertIsNotNone(account_payments)
        self.assertIsNotNone(virtual_accounts)

        self.account_payment.status_id = 310
        self.account_payment.save()
        self.loan = LoanFactory(customer=self.customer, application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.payment.account_payment = self.account_payment
        self.payment.save()
        account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(self.application_xid, data)
        self.assertIsNotNone(account_payments)
        self.assertIsNotNone(virtual_accounts)

        data = {
            "application_xid": self.application_xid,
            "is_paid_off": self.is_paid_off_false,
            "filter_type": self.filter_type1,
            "start_date": self.start_date,
            "end_date": self.end_date
        }
        account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(self.application_xid, data)
        self.assertIsNotNone(account_payments)
        self.assertIsNotNone(virtual_accounts)

        data = {
            "application_xid": self.application_xid,
            "is_paid_off": self.is_paid_off_false,
        }
        account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(self.application_xid, data)
        self.assertIsNotNone(account_payments)
        self.assertIsNotNone(virtual_accounts)

    def test_get_payment_methods(self):
        self.loan = LoanFactory(customer=self.customer, application=self.application)
        PaymentMethodLookupFactory(code=self.payment_method_code, name=self.payment_method_name)
        PaymentMethodFactory(
            loan=self.loan,
            payment_method_name=self.payment_method_name,
            payment_method_code=self.payment_method_code,
            customer=self.customer)
        list_method_lookups = get_payment_methods(self.application, self.bank_name2)
        self.assertIsNotNone(list_method_lookups)
        PaymentMethodLookupFactory(code=self.payment_method_code1, name=self.payment_method_name1)
        PaymentMethodFactory(
            loan=self.loan,
            payment_method_name=self.payment_method_name1,
            payment_method_code=self.payment_method_code1,
            bank_code=BankCodes.BCA,
            customer=self.customer)
        list_method_lookups = get_payment_methods(self.application, self.bank_name1)
        self.assertIsNotNone(list_method_lookups)
        PaymentMethodLookupFactory(code=self.payment_method_code2, name=self.payment_method_name2)
        PaymentMethodFactory(
            loan=self.loan,
            payment_method_name=self.payment_method_name2,
            payment_method_code=self.payment_method_code2,
            customer=self.customer)
        list_method_lookups = get_payment_methods(self.application, self.bank_name1)
        self.assertIsNotNone(list_method_lookups)
        PaymentMethodFactory(
            loan=self.loan,
            payment_method_name=self.payment_method_name1,
            payment_method_code=self.payment_method_code1,
            bank_code=BankCodes.PERMATA,
            customer=self.customer)
        list_method_lookups = get_payment_methods(self.application, self.bank_name2)
        self.assertIsNotNone(list_method_lookups)
        PaymentMethodFactory(
            loan=self.loan,
            payment_method_name=self.payment_method_name2,
            payment_method_code=self.payment_method_code2,
            bank_code=BankCodes.PERMATA,
            customer=self.customer)
        list_method_lookups = get_payment_methods(self.application, self.bank_name2)
        self.assertIsNotNone(list_method_lookups)


class LoanMerchantFinancingServices(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        user = AuthUserFactory(username='testpartner1')
        self.client.force_login(user)
        partner = PartnerFactory(user=user)
        self.distributor = DistributorFactory(
            partner=partner,
            user=partner.user,
            distributor_category=MerchantDistributorCategoryFactory(),
            name='distributor ab',
            address='jakarta',
            email='testingdistributorab@gmail.com',
            phone_number='08183152321',
            type_of_business='warung',
            npwp='123050410292312',
            nib='223050410292912',
            bank_account_name='distributor',
            bank_account_number='123456',
            bank_name='abc',
            distributor_xid=128956,
        )
        self.status_lookup = StatusLookupFactory()
        self.merchant_1 = MerchantFactory(
            nik='3283020101910011',
            shop_name='merchant 19',
            distributor=self.distributor,
            merchant_xid=2594387997,
            business_rules_score=0.5
        )
        workflow = WorkflowFactory(
            name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
            handler='MerchantFinancingWorkflowHandler'
        )
        self.customer = CustomerFactory(user=user)
        self.application_xid = 2594398666
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=workflow,
            merchant=self.merchant_1,
            partner=self.distributor.partner,
            application_xid=self.application_xid,
        )
        self.account_lookup = AccountLookupFactory(
            workflow=workflow,
            name='Merchant Financing',
            payment_frequency='weekly'
        )

        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application.account = self.account
        self.application.save()
        self.loan_amount_request = 5500000
        self.partnership_type = PartnershipTypeFactory(partner_type_name='Merchant financing')
        self.partnership_config = PartnershipConfigFactory(
            partner=self.distributor.partner,
            partnership_type=self.partnership_type,
            loan_duration=[3, 7, 14, 30]
        )


    def test_get_range_loan_amount(self):
        with self.assertRaises(JuloException):
            LoanMerchantFinancing.get_range_loan_amount(self.application)

        self.account_limit = AccountLimitFactory(account=self.account,
                                                 available_limit=4770000)
        self.product_line = ProductLineFactory()
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line,
            interest_rate=0.10,
            origination_fee_pct=0.30,
            late_fee_pct=0.05,
        )
        self.master_partner_config_product_lookup = MasterPartnerConfigProductLookupFactory(
            partner=self.distributor.partner,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        self.historical_partner_config_product_lookup = HistoricalPartnerConfigProductLookupFactory(
            master_partner_config_product_lookup=self.master_partner_config_product_lookup,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        res = LoanMerchantFinancing.get_range_loan_amount(self.application)
        self.assertIsNotNone(res)


    def test_get_loan_duration(self):

        with self.assertRaises(JuloException):
            LoanMerchantFinancing.get_loan_duration(self.application, self.loan_amount_request)

        self.account_limit = AccountLimitFactory(account=self.account,
                                                 available_limit=9500000)
        self.product_line = ProductLineFactory()
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line,
            interest_rate=0.10,
            origination_fee_pct=0.30,
            late_fee_pct=0.05,
        )
        self.master_partner_config_product_lookup = MasterPartnerConfigProductLookupFactory(
            partner=self.distributor.partner,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )
        self.historical_partner_config_product_lookup = HistoricalPartnerConfigProductLookupFactory(
            master_partner_config_product_lookup=self.master_partner_config_product_lookup,
            minimum_score=0.30,
            maximum_score=1,
            product_lookup=self.product_lookup
        )

        res = LoanMerchantFinancing.get_loan_duration(self.application, self.loan_amount_request)
        self.assertIsNotNone(res)


class TestEncryptedXidService(TestCase):
    def test_generate_encrypted_application_xid(self):
        application_xid = 1001009189
        xid = generate_encrypted_application_xid(application_xid)
        self.assertIsNotNone(xid)

        xid = generate_encrypted_application_xid(application_xid, MERCHANT_FINANCING_PREFIX)
        self.assertIsNotNone(xid)


class TestAxiataDailyReportService(TestCase):
    def setUp(self):
        DocumentFactory(
            document_source=20220101,
            document_type=AxiataReportType.DISBURSEMENT,
            service='oss'
        )
        DocumentFactory(
            document_source=20220101,
            document_type=AxiataReportType.REPAYMENT,
            service='oss'
        )

    @patch('juloserver.merchant_financing.services.shorten_url')
    def test_get_url_repayment(self, mock_shorten_url):
        dummy_shorten_url = 'https://www.julo.co.id/'
        mock_shorten_url.return_value = dummy_shorten_url
        url = get_urls_axiata_report('2022-01-01', AxiataReportType.REPAYMENT)
        self.assertEqual(url['axiata_repayment_report_url'], dummy_shorten_url)
        self.assertTrue('axiata_disbursement_report_url' not in url)

    @patch('juloserver.merchant_financing.services.shorten_url')
    def test_get_url_disbursement(self, mock_shorten_url):
        dummy_shorten_url = 'https://www.julo.co.id/'
        mock_shorten_url.return_value = dummy_shorten_url
        url = get_urls_axiata_report('2022-01-01', AxiataReportType.DISBURSEMENT)
        self.assertEqual(url['axiata_disbursement_report_url'], dummy_shorten_url)
        self.assertTrue('axiata_repayment_report_url' not in url)

    @patch('juloserver.merchant_financing.services.shorten_url')
    def test_get_url_repayment_and_disbursment(self, mock_shorten_url):
        dummy_shorten_url = 'https://www.julo.co.id/'
        mock_shorten_url.return_value = dummy_shorten_url
        url = get_urls_axiata_report('2022-01-01')
        self.assertEqual(url['axiata_disbursement_report_url'], dummy_shorten_url)
        self.assertEqual(url['axiata_repayment_report_url'], dummy_shorten_url)

    def test_get_url_not_found(self):
        url = get_urls_axiata_report('2022-01-02')
        self.assertIsNone(url)


class TestMFBankValidation(TestCase):
    def setUp(self) -> None:
        self.partner_user = AuthUserFactory(username='rabando')
        self.customer = CustomerFactory(user=self.partner_user)
        self.account = AccountFactory(customer=self.customer,
                                      status=StatusLookupFactory(status_code=420))
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_xid=9999999880,
        )
        self.data_to_validate = {
            'bank_name': 'BANK CENTRAL ASIA, Tbk (BCA)',
            'account_number': '5846244804',
            'name_in_bank': 'test',
            'name_bank_validation_id': None,
            'mobile_phone': '08110000008',
            'application': self.application
        }
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='5846244804',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='success',
            mobile_phone='08110000008'
        )
        self.application.name_bank_validation = self.name_bank_validation
        self.application.save()

    @patch('juloserver.merchant_financing.services.trigger_name_in_bank_validation')
    def test_process_mf_customer_validate_bank_failed(self, mock_trigger_validation) -> None:
        validation_process = MagicMock()
        validation_process.get_id.return_value = None
        validation_process.validate.return_value = True
        validation_process.get_data.return_value = {
            'account_number': '5846244804',
            'validated_name': 'failed',
            'method': 'XFERS'
        }
        validation_process.is_success.return_value = False
        validation_process.is_failed.return_value = True
        mock_trigger_validation.return_value = validation_process
        is_success, note = process_mf_customer_validate_bank(self.data_to_validate, self.application)
        self.assertEqual(is_success, False)
        self.assertEqual(note, 'Name in Bank Validation Failed via XFERS')

    @patch('juloserver.merchant_financing.services.trigger_name_in_bank_validation')
    def test_process_mf_customer_validate_bank_success(self, mock_trigger_validation) -> None:
        validation_process = MagicMock()
        validation_process.get_id.return_value = self.name_bank_validation.id
        validation_process.validate.return_value = True
        validation_process.get_data.return_value = {
            'account_number': '5846244804',
            'validated_name': 'success',
            'method': 'XFERS'
        }
        validation_process.is_success.return_value = True
        mock_trigger_validation.return_value = validation_process
        is_success, note = process_mf_customer_validate_bank(self.data_to_validate, self.application)
        self.assertEqual(is_success, True)
        self.assertEqual(note, 'Name in Bank Validation Success via XFERS')
