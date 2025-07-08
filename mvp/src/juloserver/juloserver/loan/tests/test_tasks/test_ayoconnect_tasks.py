import warnings

from mock import patch, MagicMock
from factory.django import mute_signals
from django.db.models.signals import post_save
from django.db import connection
from django.test import TestCase
from datetime import datetime

from juloserver.grab.tests.factories import PaymentGatewayCustomerDataFactory
from juloserver.loan.tasks.lender_related import (
    retry_ayoconnect_loan_stuck_at_212_task,
    retry_disbursement_worker,
    julo_one_disbursement_trigger_task,
    ayoconnect_loan_disbursement_retry,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLookupFactory,
    BankFactory,
    LenderFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    CreditScoreFactory,
    ProductLineFactory,
    ApplicationJ1Factory,
    SepulsaProductFactory,
    FeatureSettingFactory,
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountLimitFactory,
    AffordabilityHistoryFactory,
    AccountTransactionFactory,
)
from juloserver.account.constants import AccountConstant
from juloserver.julo.statuses import LoanStatusCodes
from unittest.mock import patch
from juloserver.disbursement.tests.factories import (
    DisbursementFactory,
    NameBankValidationFactory,
    PaymentGatewayCustomerDataLoanFactory,
)
from juloserver.disbursement.constants import (
    DisbursementStatus,
    DisbursementVendors,
    AyoconnectBeneficiaryStatus,
    AyoconnectConst,
    PaymentGatewayVendorConst,
    AyoconnectErrorCodes,
    NameBankValidationStatus,
    AyoconnectFailoverXfersConst,
)
from juloserver.followthemoney.factories import (
    LenderBalanceCurrentFactory,
    LenderCurrentFactory,
)
from juloserver.grab.models import (
    PaymentGatewayVendor,
    PaymentGatewayCustomerData,
    PaymentGatewayBankCode,
)
from juloserver.julo.models import Loan, Disbursement, FeatureSetting
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.loan import utils
from juloserver.julo.models import Loan
from juloserver.disbursement.models import Disbursement
from juloserver.payment_point.constants import TransactionMethodCode, XfersEWalletConst
from juloserver.customer_module.tests.factories import (
    BankAccountDestinationFactory,
    BankAccountCategoryFactory,
)
from juloserver.portal.object.product_profile.tests.test_product_profile_services import (
    ProductProfileFactory,
)
from unittest import skip
from django.test.utils import override_settings
from faker import Faker
from juloserver.core.utils import JuloFakerProvider
from juloserver.julo.constants import FeatureNameConst
from juloserver.disbursement.services import (
    PaymentGatewayDisbursementProcess,
    trigger_name_in_bank_validation,
)
from juloserver.payment_point.tests.factories import (
    XfersEWalletTransactionFactory,
    XfersProductFactory,
)
from juloserver.customer_module.models import BankAccountDestination
from juloserver.payment_point.services.ewallet_related import (
    validate_xfers_ewallet_bank_name_validation,
    xfers_ewallet_disbursement_process,
)
from juloserver.disbursement.exceptions import XfersApiError

fake = Faker()
fake.add_provider(JuloFakerProvider)

warnings.filterwarnings('ignore')


@override_settings(CELERY_ALWAYS_EAGER=True)
class TestAyoconnectRetryLoanStuckAt212(TestCase):
    def create_loans(self):
        for i in range(self.n_data):
            user = AuthUserFactory()
            customer = CustomerFactory(user=user)

            account = AccountFactory(
                customer=customer,
                status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
            )

            application = ApplicationFactory(
                customer=customer,
                workflow=self.workflow,
                product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
                account=account,
            )
            account.account_lookup = AccountLookupFactory(workflow=application.workflow)
            account.save()

            affordability_history = AffordabilityHistoryFactory(application=application)

            product_lookup = ProductLookupFactory()
            credit_matrix = CreditMatrixFactory(product=product_lookup)

            CreditMatrixProductLineFactory(
                credit_matrix=credit_matrix,
                product=application.product_line,
                max_duration=8,
                min_duration=1,
            )

            credit_score = CreditScoreFactory(
                application_id=application.id, score=u'A-', credit_matrix_id=credit_matrix.id
            )

            AccountLimitFactory(
                account=account,
                max_limit=10000000,
                set_limit=10000000,
                available_limit=10000000,
                latest_affordability_history=affordability_history,
                latest_credit_score=credit_score,
            )

            beneficiary_id = "test123"
            external_customer_id = "JULO-XXI"

            PaymentGatewayCustomerData.objects.create(
                customer_id=customer.id,
                payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
                beneficiary_id=beneficiary_id,
                external_customer_id=external_customer_id,
            )

            with patch('juloserver.julo.models.XidLookup.get_new_xid') as mock_get_new_xid:
                mock_get_new_xid.return_value = "100{}".format(i)
                validation_id = 100 + i
                bank_validation = NameBankValidationFactory(
                    validation_id=validation_id,
                    method=DisbursementVendors.AYOCONNECT,
                    account_number=account.id,
                    name_in_bank=self.bank_name,
                    bank_code=self.bank_code,
                )

                disbursement = DisbursementFactory(
                    name_bank_validation=bank_validation,
                    disburse_status=DisbursementStatus.PENDING,
                    reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
                    method=DisbursementVendors.AYOCONNECT,
                    disbursement_type='loan_one',
                    step=2,
                    external_id=123 + i,
                )
                self.disbursements.append(disbursement)

                loan = LoanFactory(
                    account=account,
                    customer=customer,
                    loan_status=StatusLookupFactory(
                        status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING
                    ),
                    disbursement_id=disbursement.id,
                    name_bank_validation_id=bank_validation.id,
                    lender=self.lender,
                    loan_xid=123 + i,
                    application=application,
                    application_id2=application.id,
                )
                self.loans.append(loan)

    def setUp(self):
        self.user_auth = AuthUserFactory()

        self.bank_name = 'test-bank-name'
        self.bank_code = 'test-bank-code-{}'.format(datetime.now().strftime('%s'))
        self.bank = BankFactory(
            bank_code='666',
            bank_name=self.bank_name,
            xendit_bank_code=self.bank_code,
            swift_bank_code=self.bank_code,
            xfers_bank_code=self.bank_code,
        )

        self.lender = LenderFactory(
            lender_name='ska',
            user=self.user_auth,
            lender_status='active',
            xfers_token='123',
        )

        LenderBalanceCurrentFactory(lender=self.lender, available_balance=100000000)

        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name=PaymentGatewayVendorConst.AYOCONNECT
        )

        PaymentGatewayBankCode.objects.create(
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            bank_id=self.bank.id,
            swift_bank_code=self.bank.swift_bank_code,
        )

        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.loans = []
        self.disbursements = []
        self.n_data = 10
        self.create_loans()

    @patch('juloserver.loan.services.lender_related.ayoconnect_loan_disbursement_failed')
    @patch('juloserver.loan.tasks.lender_related.retry_disbursement_stuck_212')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_balance')
    @patch('juloserver.loan.services.lender_related.generate_account_payment_for_payments')
    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.create_disbursement')
    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_beneficiary')
    def test_retry_loan_stuck_at_212_ayoconnect(
        self,
        mock_check_beneficiary,
        mock_get_token,
        mock_create_disbursement,
        mock_generate_account_payment,
        mock_check_balance,
        mock_retry_disbursement_stuck_212,
        mock_ayoconnect_loan_disbursement_failed,
    ):
        mock_check_beneficiary.return_value = True, AyoconnectBeneficiaryStatus.ACTIVE
        mock_get_token.return_value = {'accessToken': 'testing token'}
        mock_create_disbursement.return_value = {
            'transaction': {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_PROCESSING,
                'amount': 100000,
                'referenceNumber': None,
            },
            'transactionId': 123,
        }
        mock_check_balance.return_value = DisbursementStatus.SUFFICIENT_BALANCE, True, 0

        mock_retry_disbursement_stuck_212.return_value = True, False

        # retry
        with mute_signals(post_save):
            result = retry_ayoconnect_loan_stuck_at_212_task()
            n_data = result.get('n_loan')
            self.assertEqual(n_data, self.n_data)
            self.assertEqual(mock_ayoconnect_loan_disbursement_failed.call_count, 0)

    @patch('juloserver.loan.services.lender_related.ayoconnect_loan_disbursement_failed')
    @patch('juloserver.loan.tasks.lender_related.retry_disbursement_stuck_212')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_balance')
    @patch('juloserver.loan.services.lender_related.generate_account_payment_for_payments')
    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.create_disbursement')
    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_beneficiary')
    def test_retry_loan_stuck_at_212_ayoconnect_failed(
        self,
        mock_check_beneficiary,
        mock_get_token,
        mock_create_disbursement,
        mock_generate_account_payment,
        mock_check_balance,
        mock_retry_disbursement_stuck_212,
        mock_ayoconnect_loan_disbursement_failed,
    ):
        mock_check_beneficiary.return_value = True, AyoconnectBeneficiaryStatus.INACTIVE
        mock_get_token.return_value = {'accessToken': 'testing token'}
        mock_create_disbursement.return_value = {
            'transaction': {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_SUCCESS,
                'amount': 100000,
                'referenceNumber': None,
            },
            'transactionId': 123,
        }
        mock_check_balance.return_value = DisbursementStatus.SUFFICIENT_BALANCE, True, 0

        mock_retry_disbursement_stuck_212.return_value = True, True

        with mute_signals(post_save):
            result = retry_ayoconnect_loan_stuck_at_212_task()
            self.assertEqual(result.get('n_loan'), self.n_data)
            self.assertEqual(
                mock_ayoconnect_loan_disbursement_failed.call_count, result.get('n_loan')
            )

    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_balance')
    @patch('juloserver.loan.services.lender_related.generate_account_payment_for_payments')
    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.create_disbursement')
    @patch('juloserver.disbursement.clients.ayoconnect.AyoconnectClient.get_token')
    @patch('juloserver.disbursement.services.ayoconnect.AyoconnectService.check_beneficiary')
    def test_retry_loan_stuck_at_212_ayoconnect_insufficient_balance(
        self,
        mock_check_beneficiary,
        mock_get_token,
        mock_create_disbursement,
        mock_generate_account_payment,
        mock_check_balance,
    ):
        mock_check_beneficiary.return_value = True, AyoconnectBeneficiaryStatus.ACTIVE
        mock_get_token.return_value = {'accessToken': 'testing token'}
        mock_create_disbursement.return_value = {
            'transaction': {
                'status': AyoconnectConst.DISBURSEMENT_STATUS_PROCESSING,
                'amount': 100000,
                'referenceNumber': None,
            },
            'transactionId': 123,
        }
        mock_check_balance.return_value = DisbursementStatus.INSUFICIENT_BALANCE, False, 0

        for loan, disbursement in zip(self.loans, self.disbursements):
            self.assertEqual(loan.status, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
            self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)

        # retry
        with mute_signals(post_save):
            result = retry_ayoconnect_loan_stuck_at_212_task()
            n_data = result.get('n_loan')
            self.assertEqual(n_data, 0)

        for loan, disbursement in zip(self.loans, self.disbursements):
            loan.refresh_from_db()
            disbursement.refresh_from_db()

            self.assertEqual(loan.status, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
            self.assertEqual(disbursement.disburse_status, DisbursementStatus.PENDING)
            self.assertEqual(disbursement.reason, AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE)

        mock_check_beneficiary.assert_not_called()
        mock_get_token.assert_not_called()
        mock_create_disbursement.assert_not_called()
        mock_generate_account_payment.assert_not_called()

    def test_generate_query_for_get_loan_and_disbursement(self):
        batch_size = 100
        query = utils.generate_query_for_get_loan_and_disbursement(
            batch_size=batch_size,
            last_id=0,
            loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            disburse_status=DisbursementStatus.PENDING,
            disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
        )
        self.assertIsNotNone(query)
        self.assertTrue('limit {}'.format(batch_size) in query.lower())
        self.assertFalse('d.disbursement_id <' in query.lower())

        query = utils.generate_query_for_get_loan_and_disbursement(
            batch_size=batch_size,
            last_id=123,
            loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            disburse_status=DisbursementStatus.PENDING,
            disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
        )
        self.assertIsNotNone(query)
        self.assertTrue('limit {}'.format(batch_size) in query.lower())
        self.assertTrue(
            'd.disbursement_id < 123 order by d.disbursement_id desc limit {}'.format(batch_size)
            in query.lower()
        )

    @patch("juloserver.loan.tasks.lender_related.retry_ayoconnect_stuck_212_disbursement")
    def test_retry_disbursement_worker(self, mock_retry_disburse):
        query = utils.generate_query_for_get_loan_and_disbursement(
            batch_size=2,
            last_id=0,
            loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            disburse_status=DisbursementStatus.PENDING,
            disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
        )
        loan_fields = utils.get_table_fields(Loan._meta.db_table)
        disbursement_fields = utils.get_table_fields(Disbursement._meta.db_table)
        with connection.cursor() as cursor:
            result = retry_disbursement_worker(cursor, query, loan_fields, disbursement_fields)
            row_count, last_id = result.get('row_count'), result.get('last_id')

            self.assertEqual(row_count, 2)
            self.assertNotEqual(last_id, 0)

    @patch("juloserver.loan.tasks.lender_related.retry_ayoconnect_stuck_212_disbursement")
    def test_retry_disbursement_worker_no_data(self, mock_retry_disburse):
        # lets just update the data to make it not fill the criteria of retryment
        Disbursement.objects.filter(id__in=[d.id for d in self.disbursements]).update(
            disburse_status=DisbursementStatus.FAILED
        )

        query = utils.generate_query_for_get_loan_and_disbursement(
            batch_size=2,
            last_id=0,
            loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            disburse_status=DisbursementStatus.PENDING,
            disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
        )
        loan_fields = utils.get_table_fields(Loan._meta.db_table)
        disbursement_fields = utils.get_table_fields(Disbursement._meta.db_table)
        with connection.cursor() as cursor:
            result = retry_disbursement_worker(cursor, query, loan_fields, disbursement_fields)
            row_count, last_id = result.get('row_count'), result.get('last_id')

            self.assertEqual(row_count, 0)
            self.assertTrue(last_id == 0)

    @patch("juloserver.loan.tasks.lender_related.retry_ayoconnect_stuck_212_disbursement")
    def test_retry_disbursement_worker_invalid_query(self, mock_retry_disburse):
        query = "hahahahah"
        loan_fields = utils.get_table_fields(Loan._meta.db_table)
        disbursement_fields = utils.get_table_fields(Disbursement._meta.db_table)
        with connection.cursor() as cursor:
            result = retry_disbursement_worker(cursor, query, loan_fields, disbursement_fields)
            row_count, last_id = result.get('row_count'), result.get('last_id')

            self.assertEqual(row_count, 0)
            self.assertTrue(last_id == 0)

        mock_retry_disburse.assert_not_called()

    @patch("juloserver.loan.tasks.lender_related.retry_ayoconnect_stuck_212_disbursement")
    def test_retry_disbursement_worker_invalid_loan_data(self, mock_retry_disburse):
        query = utils.generate_query_for_get_loan_and_disbursement(
            batch_size=2,
            last_id=0,
            loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            disburse_status=DisbursementStatus.PENDING,
            disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
        )
        loan_fields = utils.get_table_fields('hehe')
        disbursement_fields = utils.get_table_fields(Disbursement._meta.db_table)
        with connection.cursor() as cursor:
            result = retry_disbursement_worker(cursor, query, loan_fields, disbursement_fields)
            row_count, last_id = result.get('row_count'), result.get('last_id')
            self.assertEqual(row_count, 0)
            self.assertTrue(last_id == 0)

        mock_retry_disburse.assert_not_called()

    @patch("juloserver.loan.tasks.lender_related.retry_ayoconnect_stuck_212_disbursement")
    def test_retry_disbursement_worker_invalid_disbursement_data(self, mock_retry_disburse):
        query = utils.generate_query_for_get_loan_and_disbursement(
            batch_size=2,
            last_id=0,
            loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            disburse_status=DisbursementStatus.PENDING,
            disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
        )
        loan_fields = utils.get_table_fields(Loan._meta.db_table)
        disbursement_fields = utils.get_table_fields("yow")
        with connection.cursor() as cursor:
            result = retry_disbursement_worker(cursor, query, loan_fields, disbursement_fields)
            row_count, last_id = result.get('row_count'), result.get('last_id')
            self.assertEqual(row_count, 0)
            self.assertTrue(last_id == 0)

        mock_retry_disburse.assert_not_called()

    def test_parse_loan_and_disbursement(self):
        loan_fields = utils.get_table_fields(Loan._meta.db_table)
        n_loan_fields = len(loan_fields)
        disbursement_fields = utils.get_table_fields(Disbursement._meta.db_table)

        # the reason why i put 50 instead of 10 is to make sure the query return 10
        # if the query return more than 10, it will raise index error
        query = utils.generate_query_for_get_loan_and_disbursement(
            batch_size=50,
            last_id=0,
            loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            disburse_status=DisbursementStatus.PENDING,
            disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
        )

        last_disbursement_id = 0
        counter = 0
        with connection.cursor() as cursor:
            cursor.execute(query)
            for _, row in enumerate(cursor.fetchall()):
                counter += 1
                loan_obj = utils.parse_loan(row[:n_loan_fields], loan_fields)
                disbursement_obj = utils.parse_disbursement(
                    row[n_loan_fields:], disbursement_fields
                )
                self.assertTrue(isinstance(loan_obj, Loan))
                self.assertTrue(isinstance(disbursement_obj, Disbursement))

                if last_disbursement_id > 0:
                    self.assertTrue(disbursement_obj.id < last_disbursement_id)
                last_disbursement_id = disbursement_obj.id

        self.assertNotEqual(counter, 0)

    def test_parse_loan_invalid_partner_and_product_lookup(self):
        loan_fields = utils.get_table_fields(Loan._meta.db_table)
        n_loan_fields = len(loan_fields)
        query = utils.generate_query_for_get_loan_and_disbursement(
            batch_size=1,
            last_id=0,
            loan_status=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
            disburse_status=DisbursementStatus.PENDING,
            disburse_reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
        )
        with connection.cursor() as cursor:
            cursor.execute(query)
            for row in cursor.fetchall():
                for value in [None, "", "hehe"]:
                    temp = utils.to_dict(row[:n_loan_fields], loan_fields)
                    temp['partner'] = value
                    temp['product_code'] = value
                    with patch('juloserver.loan.utils.to_dict') as mock_to_dict:
                        mock_to_dict.return_value = temp
                        utils.parse_loan(row[:n_loan_fields], loan_fields)


class TestDisbursementTriggerTaskAYC(TestCase):
    def setUp(self):
        self.j1_product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1, product_profile=ProductProfileFactory()
        )
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='XFERS',
            validation_status='SUCCESS',
            mobile_phone='08674734',
            attempt=0,
        )
        self.application = ApplicationJ1Factory(
            account=self.account, customer=self.customer, name_bank_validation=name_bank_validation
        )
        self.lender = LenderCurrentFactory(lender_name='test-lender')
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            transaction_method_id=TransactionMethodCode.SELF.code,
            lender=self.lender,
        )
        self.lender_balance_current = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=self.loan.loan_amount
        )
        bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        bank = BankFactory(
            bank_code='012', bank_name='BCA', xendit_bank_code='BCA', swift_bank_code='01'
        )
        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=bank,
            name_bank_validation=name_bank_validation,
            account_number='12345',
            is_deleted=False,
        )
        self.loan.name_bank_validation_id = name_bank_validation.id
        self.loan.transaction_method_id = TransactionMethodCode.SELF.code
        self.loan.bank_account_destination = bank_account_destination
        self.loan.save()
        self.disbursement = DisbursementFactory(
            name_bank_validation=name_bank_validation,
            disburse_status=DisbursementStatus.PENDING,
            reason=AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE,
            method=DisbursementVendors.AYOCONNECT,
            disbursement_type='loan_one',
            step=2,
            external_id=123,
        )

    @patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    def test_julo_one_disbursement_trigger_task_ayc_success(
        self, mock_julo_one_disbursement_process
    ):
        self.loan.disbursement_id = self.disbursement.id
        self.loan.product.product_line_id = ProductLineCodes.J1
        self.loan.save()
        self.loan.product.save()
        julo_one_disbursement_trigger_task(self.loan.id)
        mock_julo_one_disbursement_process.assert_called_once()

    @patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    def test_julo_one_disbursement_trigger_task_ayc_not_triggered(
        self, mock_julo_one_disbursement_process
    ):
        julo_one_disbursement_trigger_task(self.loan.id)
        mock_julo_one_disbursement_process.assert_not_called()


class TestAyoconnectTasks(TestCase):
    def setUp(self) -> None:
        self.user_auth = AuthUserFactory()

        self.bank_name = 'test-bank-name'
        self.bank_code = 'test-bank-code-{}'.format(datetime.now().strftime('%s'))
        self.bank = BankFactory(
            bank_code='666',
            bank_name=self.bank_name,
            xendit_bank_code=self.bank_code,
            swift_bank_code=self.bank_code,
            xfers_bank_code=self.bank_code,
        )

        self.lender = LenderFactory(
            lender_name='ska',
            user=self.user_auth,
            lender_status='active',
            xfers_token='123',
        )

        self.workflow = WorkflowFactory(name='GrabWorkflow')

        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.failover_feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_AYOCONNECT_XFERS_FAILOVER, is_active=True
        )

    def fake_PG_disburse(self):
        return True

    @patch('juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task')
    def test_ayoconnect_loan_disbursement_retry(self, mock_julo_one_disbursement_trigger_task):
        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            account=self.account,
        )
        bank_validation = NameBankValidationFactory(
            validation_id=fake.numerify(text="#%#%#%"),
            method=DisbursementVendors.AYOCONNECT,
            account_number=fake.numerify(text="#%#%#%"),
            name_in_bank=self.bank_name,
            bank_code=self.bank_code,
        )

        disbursement = DisbursementFactory(
            name_bank_validation=bank_validation,
            disburse_status=DisbursementStatus.FAILED,
            method=DisbursementVendors.AYOCONNECT,
            disbursement_type='loan_one',
            step=2,
            external_id=fake.numerify(text="#%#%#%"),
        )

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED),
            disbursement_id=disbursement.id,
            name_bank_validation_id=bank_validation.id,
            lender=self.lender,
            loan_xid=fake.numerify(text="#%#%#%"),
            application=application,
            application_id2=application.id,
        )

        grab_disbursement_retry_ft = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_DISBURSEMENT_RETRY,
            is_active=True,
            category='grab',
            description='configuration for GRAB disbursement retry',
            parameters={'max_retry_times': 3, 'delay_in_min': 5},
        )

        disbursement_retry_times = disbursement.retry_times
        ayoconnect_loan_disbursement_retry(
            loan.id, max_retries=grab_disbursement_retry_ft.parameters.get('max_retry_times')
        )
        disbursement.refresh_from_db()
        mock_julo_one_disbursement_trigger_task.assert_called_once()
        self.assertEqual(disbursement.retry_times, disbursement_retry_times + 1)

    @patch.object(PaymentGatewayDisbursementProcess, 'disburse_grab', fake_PG_disburse)
    @patch('juloserver.loan.services.lender_related.update_committed_amount_for_lender_balance')
    @patch('juloserver.grab.services.loan_related.check_grab_auth_success')
    def test_ayoconnect_grab_loan_disbursement_retry_with_failover_to_pg_service(
        self, mock_check_grab_auth_success, mock_commit_lender_balance
    ):
        mock_check_grab_auth_success.return_value = True
        mock_commit_lender_balance.return_value = True
        lender_balance_current = LenderBalanceCurrentFactory(lender=self.lender)
        account_limit = AccountLimitFactory(account=self.account, set_limit=1000000)
        bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        bank = BankFactory(
            bank_code='012', bank_name='BCA', xendit_bank_code='BCA', swift_bank_code='01'
        )

        bank_validation = NameBankValidationFactory(
            validation_id=fake.numerify(text="#%#%#%"),
            method=DisbursementVendors.AYOCONNECT,
            account_number=fake.numerify(text="#%#%#%"),
            name_in_bank=self.bank_name,
            bank_code=self.bank_code,
            validation_status=NameBankValidationStatus.SUCCESS,
            bank=bank,
        )

        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            account=self.account,
            name_bank_validation=bank_validation,
        )

        bank_account_destination = BankAccountDestinationFactory(
            bank_account_category=bank_account_category,
            customer=self.customer,
            bank=bank,
            name_bank_validation=bank_validation,
            account_number='12345',
            is_deleted=False,
        )

        disbursement = DisbursementFactory(
            name_bank_validation=bank_validation,
            disburse_status=DisbursementStatus.FAILED,
            method=DisbursementVendors.AYOCONNECT,
            disbursement_type='loan_one',
            retry_times=3,
            step=2,
            external_id=fake.numerify(text="#%#%#%"),
        )

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED),
            disbursement_id=disbursement.id,
            name_bank_validation_id=bank_validation.id,
            lender=self.lender,
            loan_xid=disbursement.external_id,
            application=application,
            application_id2=application.id,
            bank_account_destination=bank_account_destination,
        )

        ayoconnect_loan_disbursement_retry(loan.id, max_retries=3)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.method, DisbursementVendors.PG)
        self.assertEqual(disbursement.retry_times, 0)

    @patch('juloserver.loan.services.lender_related.ayoconnect_loan_disbursement_failed')
    def test_ayoconnect_loan_disbursement_retry_redirect_to_213(
        self, mock_ayoconnect_loan_disbursement_failed
    ):
        self.failover_feature_setting.update_safely(is_active=False)
        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB),
            account=self.account,
        )
        bank_validation = NameBankValidationFactory(
            validation_id=fake.numerify(text="#%#%#%"),
            method=DisbursementVendors.AYOCONNECT,
            account_number=fake.numerify(text="#%#%#%"),
            name_in_bank=self.bank_name,
            bank_code=self.bank_code,
        )

        disbursement = DisbursementFactory(
            name_bank_validation=bank_validation,
            disburse_status=DisbursementStatus.FAILED,
            method=DisbursementVendors.AYOCONNECT,
            disbursement_type='loan_one',
            retry_times=3,
            step=2,
            external_id=fake.numerify(text="#%#%#%"),
        )

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED),
            disbursement_id=disbursement.id,
            name_bank_validation_id=bank_validation.id,
            lender=self.lender,
            loan_xid=fake.numerify(text="#%#%#%"),
            application=application,
            application_id2=application.id,
        )

        ayoconnect_loan_disbursement_retry(loan.id, max_retries=3)
        disbursement.refresh_from_db()
        mock_ayoconnect_loan_disbursement_failed.assert_called_once()
        mock_ayoconnect_loan_disbursement_failed.assert_called_with(loan, force_failed=True)


class TestAyoconnectLoanDisbursementRetry(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.j1_product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1, product_profile=ProductProfileFactory()
        )
        self.product = ProductLookupFactory(
            product_line=self.j1_product_line,
        )
        self.disbursement = DisbursementFactory(
            disburse_status=DisbursementStatus.FAILED,
            method=DisbursementVendors.AYOCONNECT,
            original_amount=100000,
        )
        self.loan = LoanFactory(
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
            transaction_method_id=TransactionMethodCode.SELF.code,
            disbursement_id=self.disbursement.id,
            customer=self.customer,
            product=self.product,
            lender=LenderFactory(),
        )
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

    @patch('juloserver.loan.services.lender_related.is_disbursement_stuck_less_than_threshold')
    @patch('juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task')
    def test_ayoconnect_loan_disbursement_retry_beneficiary_errors(
        self,
        mock_julo_one_disbursement_trigger_task,
        mock_is_disbursement_stuck_less_than_threshold,
    ):
        # test disbursement API or callback got error that need to change status of beneficiary id
        self.disbursement.reason = AyoconnectErrorCodes.J1_RECREATE_BEN_IDS[0]
        self.disbursement.save()
        mock_is_disbursement_stuck_less_than_threshold.return_value = True
        ayoconnect_loan_disbursement_retry(self.loan.id, max_retries=3)
        mock_julo_one_disbursement_trigger_task.assert_called_once()
        self.pg_customer_data.refresh_from_db()
        self.assertEqual(
            self.pg_customer_data.status,
            AyoconnectBeneficiaryStatus.UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK,
        )
        self.disbursement.refresh_from_db()
        self.assertEqual(self.disbursement.retry_times, 1)

    @patch('juloserver.loan.services.lender_related.is_disbursement_stuck_less_than_threshold')
    @patch('juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task')
    def test_ayoconnect_loan_disbursement_not_retry_beneficiary_errors(
        self,
        mock_julo_one_disbursement_trigger_task,
        mock_is_disbursement_stuck_less_than_threshold,
    ):
        # test disbursement API or callback got error no need to change status of beneficiary id
        self.disbursement.reason = AyoconnectErrorCodes.ERROR_OCCURRED_FROM_BANK
        self.disbursement.save()
        mock_is_disbursement_stuck_less_than_threshold.return_value = True
        ayoconnect_loan_disbursement_retry(self.loan.id, max_retries=3)
        mock_julo_one_disbursement_trigger_task.assert_called_once()
        self.pg_customer_data.refresh_from_db()
        self.assertNotEqual(
            self.pg_customer_data.status,
            AyoconnectBeneficiaryStatus.UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK,
        )
        self.disbursement.refresh_from_db()
        self.assertEqual(self.disbursement.retry_times, 1)

    @patch('juloserver.loan.tasks.lender_related.update_loan_status_and_loan_history')
    @patch('juloserver.loan.services.lender_related.switch_disbursement_to_xfers')
    @patch('juloserver.loan.services.lender_related.is_disbursement_stuck_less_than_threshold')
    @patch('juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task')
    def test_ayoconnect_loan_disbursement_failover_to_xfers(
        self,
        mock_julo_one_disbursement_trigger_task,
        mock_is_disbursement_stuck_less_than_threshold,
        mock_switch_disbursement_to_xfers,
        mock_update_loan_status_and_loan_history,
    ):
        for error_code in AyoconnectErrorCodes.force_switch_to_xfers_error_codes():
            # disbursement reason need to force to use Xfers
            mock_julo_one_disbursement_trigger_task.reset_mock()

            self.disbursement.reason = error_code
            self.disbursement.save()
            ayoconnect_loan_disbursement_retry(self.loan.id, max_retries=3)
            mock_switch_disbursement_to_xfers.assert_called_with(
                disbursement=self.disbursement,
                lender_name=self.loan.lender.lender_name,
                reason=AyoconnectFailoverXfersConst.J1_FORCE_SWITCH_MAPPING[error_code],
            )
            mock_julo_one_disbursement_trigger_task.assert_called()

        # disbursement retry times exceed the limit
        self.disbursement.retry_times = 3
        self.disbursement.reason = AyoconnectErrorCodes.ERROR_OCCURRED_FROM_BANK
        self.disbursement.save()

        mock_julo_one_disbursement_trigger_task.reset_mock()
        mock_switch_disbursement_to_xfers.reset_mock()
        mock_is_disbursement_stuck_less_than_threshold.return_value = True
        ayoconnect_loan_disbursement_retry(self.loan.id, max_retries=3)
        mock_switch_disbursement_to_xfers.assert_called_with(
            disbursement=self.disbursement,
            lender_name=self.loan.lender.lender_name,
            reason=AyoconnectFailoverXfersConst.MAX_RETRIES_EXCEEDED,
        )
        mock_julo_one_disbursement_trigger_task.assert_called()

        mock_julo_one_disbursement_trigger_task.reset_mock()
        mock_is_disbursement_stuck_less_than_threshold.return_value = False
        ayoconnect_loan_disbursement_retry(self.loan.id, max_retries=3)
        mock_update_loan_status_and_loan_history.assert_called_with(
            loan_id=self.loan.id,
            new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
        )
        mock_julo_one_disbursement_trigger_task.assert_not_called()

    @patch('juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task')
    def test_ayoconnect_loan_disbursement_not_retry_unhandled_errors(
        self, mock_julo_one_disbursement_trigger_task
    ):
        self.disbursement.reason = '1234'
        self.disbursement.save()
        ayoconnect_loan_disbursement_retry(self.loan.id, max_retries=3)
        mock_julo_one_disbursement_trigger_task.assert_not_called()

    @patch('juloserver.loan.tasks.lender_related.update_loan_status_and_loan_history')
    @patch('juloserver.loan.services.lender_related.switch_disbursement_to_xfers')
    @patch('juloserver.loan.services.lender_related.is_disbursement_stuck_less_than_threshold')
    @patch('juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task')
    def test_ayoconnect_ewallet_loan_disbursement_failed_and_cancel(
        self,
        mock_julo_one_disbursement_trigger_task,
        mock_is_disbursement_stuck_less_than_threshold,
        mock_switch_disbursement_to_xfers,
        mock_update_loan_status_and_loan_history,
    ):
        # don't allow AYC E-Wallet transaction switch to Xfers
        # disbursement retry times exceed the limit
        self.disbursement.retry_times = 3
        self.disbursement.reason = AyoconnectErrorCodes.ERROR_OCCURRED_FROM_BANK
        self.disbursement.save()
        self.loan.transaction_method_id = TransactionMethodCode.DOMPET_DIGITAL.code
        self.loan.save()

        mock_julo_one_disbursement_trigger_task.reset_mock()
        mock_is_disbursement_stuck_less_than_threshold.return_value = True
        ayoconnect_loan_disbursement_retry(self.loan.id, max_retries=3)

        mock_switch_disbursement_to_xfers.assert_not_called()
        mock_update_loan_status_and_loan_history.assert_called_with(
            loan_id=self.loan.id,
            new_status_code=LoanStatusCodes.TRANSACTION_FAILED,
        )
        mock_julo_one_disbursement_trigger_task.assert_not_called()

    @patch('juloserver.loan.services.lender_related.switch_disbursement_to_xfers')
    @patch('juloserver.loan.services.lender_related.is_disbursement_stuck_less_than_threshold')
    @patch('juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task')
    def test_ayoconnect_loan_disbursement_failover_to_xfers_with_feature_setting(
        self,
        mock_julo_one_disbursement_trigger_task,
        mock_is_disbursement_stuck_less_than_threshold,
        mock_switch_disbursement_to_xfers,
    ):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY,
            parameters=dict(
                ayc_configuration={
                    "error_code_types": {
                        "force_switch_to_xfers": AyoconnectErrorCodes.J1_FORCE_SWITCH_TO_XFERS,
                        "all": AyoconnectErrorCodes.J1_DISBURSE_RETRY_ERROR_CODES,
                    },
                }
            ),
            is_active=True,
        )

        for error_code in AyoconnectErrorCodes.force_switch_to_xfers_error_codes():
            # disbursement reason need to force to use Xfers
            mock_julo_one_disbursement_trigger_task.reset_mock()

            self.disbursement.reason = error_code
            self.disbursement.save()
            ayoconnect_loan_disbursement_retry(self.loan.id, max_retries=3)
            mock_switch_disbursement_to_xfers.assert_called_with(
                disbursement=self.disbursement,
                lender_name=self.loan.lender.lender_name,
                reason=AyoconnectFailoverXfersConst.J1_FORCE_SWITCH_MAPPING[error_code],
            )
            mock_julo_one_disbursement_trigger_task.assert_called()


class TestXfersEwalletDisbursement(TestCase):
    def setUp(self):
        self.j1_product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1, product_profile=ProductProfileFactory()
        )
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.account_limit = AccountLimitFactory(account=self.account)
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='12345',
            name_in_bank='BCA',
            method='Xfers',
            validation_status='SUCCESS',
            mobile_phone='08674734',
            attempt=0,
        )
        self.application = ApplicationJ1Factory(
            account=self.account, customer=self.customer, name_bank_validation=name_bank_validation
        )
        self.lender = LenderCurrentFactory(lender_name='test-lender')
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_APPROVAL),
            transaction_method_id=TransactionMethodCode.DOMPET_DIGITAL.code,
            lender=self.lender,
        )
        self.lender_balance_current = LenderBalanceCurrentFactory(
            lender=self.lender, available_balance=self.loan.loan_amount
        )
        self.bank_account_category = BankAccountCategoryFactory(
            category='e-wallet', display_label='Pribadi', parent_category_id=1
        )
        self.bank = BankFactory(
            bank_code='012',
            bank_name=XfersEWalletConst.PERMATA_BANK_NAME,
            xfers_bank_code="PERMATA",
        )
        self.loan.save()
        self.xfers_product = XfersProductFactory(sepulsa_product=SepulsaProductFactory())

    @patch('juloserver.loan.tasks.lender_related.xfers_ewallet_disbursement_process')
    def test_julo_one_disbursement_trigger_task_success(self, xfers_ewallet_disbursement_process):
        XfersEWalletTransactionFactory(
            loan=self.loan, customer=self.loan.customer, xfers_product=self.xfers_product
        )
        self.loan.product.product_line_id = ProductLineCodes.J1
        self.loan.product.save()
        julo_one_disbursement_trigger_task(self.loan.id)
        xfers_ewallet_disbursement_process.assert_called_once()

    @patch('juloserver.disbursement.clients.xfers.XfersClient.add_bank_account')
    @patch('juloserver.disbursement.clients.xfers.XfersClient.get_user_token')
    def test_validate_name_bank_validation(self, mock_user_token, mock_add_bank_account):
        mock_add_bank_account.return_value = [
            {
                'id': 9601037,
                'status': 'SUCCESS',
                'detected_name': "test",
                'validated_name': 'CACA PITRIADI',
                'reason': 'success',
                'error_message': None,
                'account_no': '123321123',
                'bank_abbrev': 'KESEJAHTERAAN_EKONOMI',
            }
        ]
        data_to_validate = {
            "bank_name": XfersEWalletConst.PERMATA_BANK_NAME,
            "account_number": "123321123",
            "name_in_bank": '',
            "name_bank_validation_id": None,
            "mobile_phone": self.application.mobile_phone_1,
            "application": self.application,
        }

        validation = trigger_name_in_bank_validation(data_to_validate, method="Xfers", new_log=True)
        validation.validate(bypass_name_in_bank=True)
        name_bank_validation = validation.name_bank_validation
        bank_account_destination = BankAccountDestination.objects.create(
            bank_account_category_id=self.bank_account_category.pk,
            customer_id=self.customer.pk,
            bank_id=self.bank.pk,
            account_number=name_bank_validation.account_number,
            name_bank_validation_id=name_bank_validation.pk,
        )
        assert bank_account_destination != None
        assert validation.is_success() == True

    @patch('juloserver.disbursement.clients.xfers.XfersClient.add_bank_account')
    @patch('juloserver.disbursement.clients.xfers.XfersClient.get_user_token')
    def test_validate_xfers_ewallet_bank_name_validation(
        self, mock_user_token, mock_add_bank_account
    ):
        validation_status = 'SUCCESS'
        mock_add_bank_account.return_value = [
            {
                'id': 9601037,
                'status': validation_status,
                'detected_name': "test",
                'validated_name': 'CACA PITRIADI',
                'reason': 'success',
                'error_message': None,
                'account_no': '123321123',
                'bank_abbrev': 'KESEJAHTERAAN_EKONOMI',
            }
        ]
        # add new
        self.loan.bank_account_destination_id = None
        self.loan.save()
        phone_number = '081233213213'
        account_number = XfersEWalletConst.PREFIX_ACCOUNT_NUMBER + phone_number
        XfersEWalletTransactionFactory(
            loan=self.loan,
            customer=self.loan.customer,
            xfers_product=self.xfers_product,
            phone_number=phone_number,
        )
        status = validate_xfers_ewallet_bank_name_validation(self.loan)
        self.loan.refresh_from_db()
        assert status == True
        assert self.loan.bank_account_destination_id != None

        bank_account_destination = self.loan.bank_account_destination
        name_bank_validation = bank_account_destination.name_bank_validation
        assert bank_account_destination.account_number == account_number
        assert name_bank_validation.account_number == account_number
        assert bank_account_destination.bank.bank_name == self.bank.bank_name
        assert (
            bank_account_destination.bank_account_category.category
            == self.bank_account_category.category
        )
        assert name_bank_validation.validation_status == validation_status

        # bank exists
        self.loan.bank_account_destination_id = None
        self.loan.save()
        status = validate_xfers_ewallet_bank_name_validation(self.loan)
        count = BankAccountDestination.objects.filter(customer_id=self.loan.customer_id).count()
        assert count == 1

    @patch('juloserver.disbursement.clients.xfers.XfersClient.add_bank_account')
    @patch('juloserver.disbursement.clients.xfers.XfersClient.get_user_token')
    def test_validate_xfers_ewallet_bank_name_validation_exception(
        self, mock_user_token, mock_add_bank_account
    ):
        mock_add_bank_account.side_effect = XfersApiError("Test")
        # add new
        self.loan.bank_account_destination_id = None
        self.loan.save()
        phone_number = '081233213213'
        account_number = XfersEWalletConst.PREFIX_ACCOUNT_NUMBER + phone_number
        XfersEWalletTransactionFactory(
            loan=self.loan,
            customer=self.loan.customer,
            xfers_product=self.xfers_product,
            phone_number=phone_number,
        )
        status = validate_xfers_ewallet_bank_name_validation(self.loan)
        self.loan.refresh_from_db()
        assert status == False
        assert self.loan.bank_account_destination_id != None
        assert self.loan.bank_account_destination.account_number == account_number

    @patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    @patch(
        'juloserver.payment_point.services.ewallet_related.validate_xfers_ewallet_bank_name_validation'
    )
    def test_xfers_ewallet_disbursement_process(
        self,
        mock_validate_xfers_ewallet_bank_name,
        mock_julo_one_disbursement,
    ):
        mock_validate_xfers_ewallet_bank_name.return_value = True
        self.loan.bank_account_destination_id = None
        self.loan.save()
        xfers_ewallet_disbursement_process(self.loan)
        mock_julo_one_disbursement.assert_called_once()

        mock_julo_one_disbursement.reset_mock()
        mock_validate_xfers_ewallet_bank_name.return_value = False
        xfers_ewallet_disbursement_process(self.loan)
        mock_julo_one_disbursement.assert_not_called()
        self.loan.refresh_from_db()
        assert self.loan.loan_status_id == LoanStatusCodes.TRANSACTION_FAILED
