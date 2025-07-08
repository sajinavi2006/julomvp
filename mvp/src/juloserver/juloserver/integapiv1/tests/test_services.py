from django.test import TestCase
from types import SimpleNamespace
from django.utils import timezone

from juloserver.grab.tests.factories import PaymentGatewayCustomerDataFactory
from juloserver.integapiv1.services import (
    AyoconnectBeneficiaryCallbackService,
    create_transaction_data_bni,
    create_or_update_transaction_data_bni,
    create_transaction_va_snap_data,
)
from juloserver.grab.models import (
    PaymentGatewayVendor,
    PaymentGatewayCustomerData,
    PaymentGatewayCustomerDataHistory
)
from juloserver.account.tests.factories import (AccountFactory, AccountLookupFactory,
                                                AccountLimitFactory)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLookupFactory,
    ProductLineFactory,
    PaymentMethodFactory,
    FeatureSettingFactory,
    EscrowPaymentMethodFactory,
    EscrowPaymentMethodLookupFactory,
)
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
)
from juloserver.account.constants import AccountConstant
from juloserver.disbursement.constants import (
    AyoconnectBeneficiaryStatus,
    AyoconnectConst
)
from juloserver.julo.constants import LoanStatusCodes, WorkflowConst
from unittest.mock import patch
from mock import MagicMock
from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import Loan
from juloserver.disbursement.models import PaymentGatewayCustomerDataLoan
from juloserver.julo.banks import BankCodes
from juloserver.julo.models import FeatureNameConst
from juloserver.integapiv1.services import (
    is_payment_method_prohibited,
    construct_transaction_data,
    get_due_amount,
)
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
    CheckoutRequestFactory,
)
from juloserver.account_payment.constants import CheckoutRequestCons
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.statuses import PaymentStatusCodes


class TestCreateTransactionBNISnap(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=410)
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.payment_method = PaymentMethodFactory(
            customer=self.customer,
            virtual_account=9881236315000686,
            payment_method_name='Bank BNI',
            bank_code=BankCodes.BNI,
            payment_method_code=9881236315
        )
        self.account_payment = AccountPaymentFactory(account=self.account)

    @patch('juloserver.integapiv1.clients.FaspaySnapClient.create_transaction_va_data')
    def test_create_transaction_va_snap_data_success(self, create_transaction_va_data: MagicMock):
        create_transaction_va_data.return_value = {
            'responseCode': '2002700',
            'responseMessage': 'Success',
            'virtualAccountData': {
                'partnerServiceId': str(self.payment_method.payment_method_code),
                'customerNo': '99241669',
                'virtualAccountNo': str(self.payment_method.virtual_account),
                'virtualAccountName': 'prod only',
                'virtualAccountEmail': 'test+integration5641830862@julo.co.id',
                'virtualAccountPhone': '628664183628629',
                'trxId': str(self.payment_method.virtual_account),
                'totalAmount': {
                    'value': str(self.account_payment.due_amount),
                    'currency': 'IDR'
                },
                'expiredDate': '2034-04-27T12:29:57+07:00',
                'additionalInfo': {
                'billDate': '2024-04-29T12:29:57+07:00',
                'channelCode': '801',
                'billDescription': 'JULO BNI Faspay',
                'redirectUrl': 'https://debit-sandbox.faspay.co.id/pws/100003/0830000010100000/1fd022c9aec27c648fe9b7c239eaf75ec2ba1ca4?trx_id=1714368599241669&merchant_id=31932&bill_no=9881236315000686'
                }
            }
        }, None

        response, error = create_transaction_va_snap_data(
            self.payment_method,
            self.payment_method.virtual_account,
            str(self.account_payment.due_amount),
            self.application,
            "test-data"
        )
        self.assertIsNone(error)

    @patch('juloserver.integapiv1.services.create_transaction_va_snap_data')
    def test_create_transaction_data_bni_success(self, create_transaction_va_snap_data: MagicMock):
        create_transaction_va_snap_data.return_value = {
            'responseCode': '2002700',
            'responseMessage': 'Success',
            'virtualAccountData': {
                'partnerServiceId': str(self.payment_method.payment_method_code),
                'customerNo': '99241669',
                'virtualAccountNo': str(self.payment_method.virtual_account),
                'virtualAccountName': 'prod only',
                'virtualAccountEmail': 'test+integration5641830862@julo.co.id',
                'virtualAccountPhone': '628664183628629',
                'trxId': str(self.payment_method.virtual_account),
                'totalAmount': {
                    'value': str(self.account_payment.due_amount),
                    'currency': 'IDR'
                },
                'expiredDate': '2034-04-27T12:29:57+07:00',
                'additionalInfo': {
                'billDate': '2024-04-29T12:29:57+07:00',
                'channelCode': '801',
                'billDescription': 'JULO BNI Faspay',
                'redirectUrl': 'https://debit-sandbox.faspay.co.id/pws/100003/0830000010100000/1fd022c9aec27c648fe9b7c239eaf75ec2ba1ca4?trx_id=1714368599241669&merchant_id=31932&bill_no=9881236315000686'
                }
            }
        }, None

        response, error = create_transaction_data_bni(self.account, "testing-create")
        self.assertIsNone(error)
        self.assertEqual(response['responseCode'], '2002700')
        self.assertEqual(response['virtualAccountData']['partnerServiceId'], str(self.payment_method.payment_method_code))
        self.assertEqual(response['virtualAccountData']['virtualAccountNo'], str(self.payment_method.virtual_account))
        self.assertEqual(response['virtualAccountData']['totalAmount']['value'], str(self.account_payment.due_amount))


    @patch('juloserver.integapiv1.services.update_transaction_data')
    def test_update_transaction_data_bni_success(self, update_transaction_data: MagicMock):
        update_transaction_data.return_value = {
            'response_code': '00',
            'response_desc': 'Successfully to update transaction'
        }, None

        response, error = create_or_update_transaction_data_bni(self.account, "testing-create")
        self.assertIsNone(error)
        self.assertEqual(response['response_code'], '00')


    @patch('juloserver.integapiv1.services.update_transaction_data')
    @patch('juloserver.integapiv1.services.create_transaction_va_snap_data')
    def test_create_or_update_transaction_data_bni_success(self, create_transaction_va_snap_data: MagicMock, update_transaction_data: MagicMock):
        update_transaction_data.return_value = {
            'response_code': '01',
            'response_desc': 'Transaction not found'
        }, 'Transaction not found'

        create_transaction_va_snap_data.return_value = {
            'responseCode': '2002700',
            'responseMessage': 'Success',
            'virtualAccountData': {
                'partnerServiceId': str(self.payment_method.payment_method_code),
                'customerNo': '99241669',
                'virtualAccountNo': str(self.payment_method.virtual_account),
                'virtualAccountName': 'prod only',
                'virtualAccountEmail': 'test+integration5641830862@julo.co.id',
                'virtualAccountPhone': '628664183628629',
                'trxId': str(self.payment_method.virtual_account),
                'totalAmount': {
                    'value': str(self.account_payment.due_amount),
                    'currency': 'IDR'
                },
                'expiredDate': '2034-04-27T12:29:57+07:00',
                'additionalInfo': {
                'billDate': '2024-04-29T12:29:57+07:00',
                'channelCode': '801',
                'billDescription': 'JULO BNI Faspay',
                'redirectUrl': 'https://debit-sandbox.faspay.co.id/pws/100003/0830000010100000/1fd022c9aec27c648fe9b7c239eaf75ec2ba1ca4?trx_id=1714368599241669&merchant_id=31932&bill_no=9881236315000686'
                }
            }
        }, None

        response, error = create_or_update_transaction_data_bni(self.account, "testing-create")
        self.assertIsNone(error)
        self.assertEqual(response['responseCode'], '2002700')
        self.assertEqual(response['virtualAccountData']['partnerServiceId'], str(self.payment_method.payment_method_code))
        self.assertEqual(response['virtualAccountData']['virtualAccountNo'], str(self.payment_method.virtual_account))
        self.assertEqual(response['virtualAccountData']['totalAmount']['value'], str(self.account_payment.due_amount))


class TestAyoconnectBeneficiaryCallbackService(TestCase):
    def setUp(self):
        self.ayo_service = AyoconnectBeneficiaryCallbackService()
        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.account_lookup = AccountLookupFactory(name='GRAB', workflow=self.workflow)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
            account_lookup=self.account_lookup
        )
        self.account_limit = AccountLimitFactory(account=self.account)

        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")

        self.beneficiary_id = "test123"
        self.external_customer_id = "JULO-XXI"
        self.payment_gateway_customer_data = PaymentGatewayCustomerData.objects.create(
            customer_id=self.customer.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            beneficiary_id=self.beneficiary_id,
            external_customer_id=self.external_customer_id
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        product_lookup = ProductLookupFactory()

    def test_is_customer_data_exists_failed(self):
        svc = AyoconnectBeneficiaryCallbackService()
        self.assertIsNone(svc.is_payment_gateway_customer_data_exists())

    def test_is_customer_data_exists_success(self):
        svc = AyoconnectBeneficiaryCallbackService(
            {
                "beneficiary_id": self.beneficiary_id,
                "customer_id": self.external_customer_id
            }
        )
        self.assertIsNotNone(svc.is_payment_gateway_customer_data_exists())

    def test_update_beneficiary_status_from_inactive_to_active(self):
        svc = AyoconnectBeneficiaryCallbackService({
            "beneficiary_id": self.beneficiary_id,
            "status": AyoconnectBeneficiaryStatus.INACTIVE
        })

        # test, beneficiary is inactive, previous status is none
        svc.update_beneficiary_status(
            self.payment_gateway_customer_data,
            AyoconnectBeneficiaryStatus.INACTIVE
        )
        cust_data = PaymentGatewayCustomerData.objects.get(beneficiary_id=self.beneficiary_id)
        cust_data_history = PaymentGatewayCustomerDataHistory.objects. \
            filter(payment_gateway_customer_data=cust_data).last()
        self.assertEqual(cust_data.status, AyoconnectBeneficiaryStatus.INACTIVE)
        self.assertIsNone(cust_data_history.old_status)

        # beneficiary current status is active, previous is inactive
        svc.update_beneficiary_status(
            self.payment_gateway_customer_data,
            AyoconnectBeneficiaryStatus.ACTIVE
        )
        cust_data = PaymentGatewayCustomerData.objects.filter(
            beneficiary_id=self.beneficiary_id).last()
        cust_data_history = PaymentGatewayCustomerDataHistory.objects. \
            filter(payment_gateway_customer_data=cust_data).last()
        self.assertEqual(cust_data.status, AyoconnectBeneficiaryStatus.ACTIVE)
        self.assertEqual(cust_data_history.old_status, AyoconnectBeneficiaryStatus.INACTIVE)

    @patch("juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary")
    def test_update_beneficiary_status_same_as_before(self, mock_update_beneficiary):
        self.payment_gateway_customer_data.status = AyoconnectBeneficiaryStatus.ACTIVE
        self.payment_gateway_customer_data.save()
        self.payment_gateway_customer_data.refresh_from_db()

        svc = AyoconnectBeneficiaryCallbackService()
        resp = svc.update_beneficiary_status(
            payment_gateway_customer_data=self.payment_gateway_customer_data,
            status=AyoconnectBeneficiaryStatus.ACTIVE
        )
        self.assertEqual(resp, False)
        mock_update_beneficiary.assert_not_called()

    @patch("juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary")
    def test_update_beneficiary_status_not_same_as_before(self, mock_update_beneficiary):
        self.payment_gateway_customer_data.status = AyoconnectBeneficiaryStatus.ACTIVE
        self.payment_gateway_customer_data.save()
        self.payment_gateway_customer_data.refresh_from_db()

        svc = AyoconnectBeneficiaryCallbackService()
        svc.update_beneficiary_status(
            payment_gateway_customer_data=self.payment_gateway_customer_data,
            status=AyoconnectBeneficiaryStatus.BLOCKED
        )
        mock_update_beneficiary.assert_called_once()

    def create_loans(self, n_loan, status):
        for i in range(n_loan):
            with patch('juloserver.julo.models.XidLookup.get_new_xid') as mock_get_new_xid:
                mobile_phone = '628124578918{}'.format(i)
                application_status_code = StatusLookupFactory(code=190)
                self.application = ApplicationFactory(
                    customer=self.customer,
                    account=self.account,
                    product_line=self.product_line,
                    application_status=application_status_code,
                    mobile_phone_1=mobile_phone,
                    bank_name='bank_test',
                    name_in_bank='name_in_bank'
                )
                disbursement = DisbursementFactory(method='Ayoconnect')
                mock_get_new_xid.return_value = "100{}".format(i)
                LoanFactory(
                    account=self.account,
                    customer=self.customer,
                    loan_status=StatusLookupFactory(status_code=status),
                    disbursement_id=disbursement.id
                )

    def test_get_loan_with_status(self):
        n_loan = 1

        self.create_loans(n_loan=n_loan, status=LoanStatusCodes.FUND_DISBURSAL_FAILED)
        svc = AyoconnectBeneficiaryCallbackService({
            "beneficiary_id": self.beneficiary_id,
            "status": AyoconnectBeneficiaryStatus.INACTIVE
        })

        loan = svc.get_loan_with_status(self.customer, LoanStatusCodes.FUND_DISBURSAL_FAILED)

        self.assertIsNotNone(loan)
        self.assertEqual(loan.loan_status.status_code, LoanStatusCodes.FUND_DISBURSAL_FAILED)

    @patch('juloserver.loan.tasks.lender_related.loan_disbursement_retry_task.apply_async')
    @patch(
        "juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status")
    def test_process_beneficiary_status(
            self,
            mock_update_beneficiary_status,
            mock_julo_one_disbursement):
        n_loan = 1
        self.create_loans(n_loan=n_loan, status=LoanStatusCodes.FUND_DISBURSAL_FAILED)
        counter = 1
        for status in [
            AyoconnectBeneficiaryStatus.ACTIVE,
            AyoconnectBeneficiaryStatus.BLOCKED,
            AyoconnectBeneficiaryStatus.INACTIVE]:
            svc = AyoconnectBeneficiaryCallbackService({
                "beneficiary_id": self.beneficiary_id,
                "status": status
            })
            resp, msg = svc.process_beneficiary(self.payment_gateway_customer_data)
            self.assertEqual(resp, True)
            self.assertIsNone(msg)
            self.assertEqual(mock_update_beneficiary_status.call_count, counter)
            mock_update_beneficiary_status.called_once_with(self.payment_gateway_customer_data,
                                                            status)
            self.assertEqual(mock_julo_one_disbursement.call_count, 0)
            counter += 1

    @patch('juloserver.loan.tasks.lender_related.loan_disbursement_retry_task.apply_async')
    @patch(
        "juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status")
    def test_process_beneficiary_status_for_grab_account(
            self, mock_update_beneficiary_status, mock_julo_one_disbursement
    ):
        n_loan = 1
        self.create_loans(n_loan=n_loan, status=LoanStatusCodes.FUND_DISBURSAL_FAILED)
        self.account.account_lookup = AccountLookupFactory(
            name=GRAB_ACCOUNT_LOOKUP_NAME,
            workflow=self.application.workflow
        )
        self.account.save()

        counter = 1
        for status in [
            AyoconnectBeneficiaryStatus.ACTIVE,
            AyoconnectBeneficiaryStatus.BLOCKED,
            AyoconnectBeneficiaryStatus.INACTIVE]:
            svc = AyoconnectBeneficiaryCallbackService({
                "beneficiary_id": self.beneficiary_id,
                "status": status
            })
            resp, _ = svc.process_beneficiary(self.payment_gateway_customer_data)
            self.assertEqual(resp, True)
            self.assertEqual(mock_update_beneficiary_status.call_count, counter)
            mock_update_beneficiary_status.called_once_with(self.payment_gateway_customer_data,
                                                            status)
            self.assertEqual(mock_julo_one_disbursement.call_count, 0)
            counter += 1

    @patch('juloserver.loan.tasks.lender_related.loan_disbursement_retry_task.apply_async')
    @patch(
        "juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status")
    def test_process_beneficiary_status_same_as_before(self, mock_update_beneficiary_status,
                                                       mock_julo_one_disbursement):
        self.payment_gateway_customer_data.status = AyoconnectBeneficiaryStatus.BLOCKED
        svc = AyoconnectBeneficiaryCallbackService({
            "beneficiary_id": self.beneficiary_id,
            "status": AyoconnectBeneficiaryStatus.BLOCKED
        })
        resp, msg = svc.process_beneficiary(self.payment_gateway_customer_data)
        self.assertEqual(resp, True)
        self.assertIsNone(msg)
        self.assertEqual(mock_update_beneficiary_status.call_count, 1)
        mock_update_beneficiary_status.called_once_with(self.payment_gateway_customer_data,
                                                        AyoconnectBeneficiaryStatus.BLOCKED)
        mock_julo_one_disbursement.assert_not_called()

    @patch('juloserver.loan.tasks.lender_related.loan_disbursement_retry_task.apply_async')
    @patch(
        'juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status')
    def test_process_beneficiary_status_no_loans(self, mock_update_beneficiary_status,
                                                 mock_julo_one_disbursement):
        counter = 1
        for status in [AyoconnectBeneficiaryStatus.ACTIVE,
                       AyoconnectBeneficiaryStatus.BLOCKED,
                       AyoconnectBeneficiaryStatus.INACTIVE]:
            svc = AyoconnectBeneficiaryCallbackService({
                "beneficiary_id": self.beneficiary_id,
                "status": status
            })
            resp, msg = svc.process_beneficiary(self.payment_gateway_customer_data)
            self.assertEqual(resp, True)
            self.assertIsNone(msg)
            self.assertEqual(mock_update_beneficiary_status.call_count, counter)
            self.assertEqual(mock_julo_one_disbursement.call_count, 0)
            counter += 1

    @patch('juloserver.integapiv1.services.trigger_create_or_update_ayoconnect_beneficiary.delay')
    @patch(
        'juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status')
    def test_process_beneficiary_status_disabled(
            self,
            mock_update_beneficiary_status,
            mock_trigger_create_or_update_ayoconnect_beneficiary
    ):
        n_loan = 1
        self.create_loans(n_loan=n_loan, status=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        svc = AyoconnectBeneficiaryCallbackService({
            "beneficiary_id": self.beneficiary_id,
            "status": AyoconnectBeneficiaryStatus.DISABLED
        })
        resp, msg = svc.process_beneficiary(self.payment_gateway_customer_data)
        self.assertEqual(resp, True)
        self.assertIsNone(msg)
        self.assertEqual(mock_update_beneficiary_status.call_count, 1)
        mock_trigger_create_or_update_ayoconnect_beneficiary. \
            assert_called_once_with(self.customer.id)

    @patch('juloserver.integapiv1.services.trigger_create_or_update_ayoconnect_beneficiary.delay')
    @patch(
        'juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status')
    def test_process_beneficiary_invalid_status(
            self,
            mock_update_beneficiary_status,
            mock_trigger_create_or_update_ayoconnect_beneficiary
    ):
        n_loan = 1
        self.create_loans(n_loan=n_loan, status=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        svc = AyoconnectBeneficiaryCallbackService({
            "beneficiary_id": self.beneficiary_id,
            "status": 4
        })
        resp, msg = svc.process_beneficiary(self.payment_gateway_customer_data)
        self.assertEqual(resp, False)
        self.assertIsNotNone(msg)
        self.assertEqual(mock_update_beneficiary_status.call_count, 0)
        mock_trigger_create_or_update_ayoconnect_beneficiary.assert_not_called()

    @patch('juloserver.integapiv1.services.trigger_create_or_update_ayoconnect_beneficiary.delay')
    def test_process_unsuccess_callback_failed(self, mock_trigger_create_or_update_beneficiary):
        svc = AyoconnectBeneficiaryCallbackService({
            "beneficiary_id": self.beneficiary_id,
            "status": AyoconnectBeneficiaryStatus.DISABLED
        })
        resp = svc.process_unsuccess_callback(external_customer_id="not-found-external_customer_id")
        self.assertEqual(resp, False)
        mock_trigger_create_or_update_beneficiary.assert_not_called()

    def test_process_unsuccess_callback_success_not_trigger_request_beneficiary(self):
        counter = 0
        n_iteration = 5
        for _ in range(n_iteration):
            pg_cust_data = PaymentGatewayCustomerData.objects.get(
                external_customer_id=self.external_customer_id
            )

            svc = AyoconnectBeneficiaryCallbackService({
                "beneficiary_id": self.beneficiary_id,
                "status": AyoconnectBeneficiaryStatus.DISABLED
            })

            with patch(
                    'juloserver.integapiv1.services.trigger_create_or_update_ayoconnect_beneficiary.apply_async') as \
                    mock_trigger_create_or_update_beneficiary:
                resp = svc.process_unsuccess_callback(
                    external_customer_id=self.external_customer_id
                )

                self.assertEqual(resp, True)

                if not pg_cust_data.beneficiary_request_retry_limit:
                    self.assertEqual(mock_trigger_create_or_update_beneficiary.call_count, 1)
                elif pg_cust_data.beneficiary_request_retry_limit >= AyoconnectConst.BENEFICIARY_RETRY_LIMIT:
                    mock_trigger_create_or_update_beneficiary.assert_not_called()
                else:
                    self.assertEqual(mock_trigger_create_or_update_beneficiary.call_count, 1)

            counter += 1

        self.assertEqual(counter, n_iteration)

    @patch(
        'juloserver.integapiv1.services.trigger_create_or_update_ayoconnect_beneficiary.apply_async')
    def test_process_unsuccess_callback_success(self, mock_trigger_create_or_update_beneficiary):
        svc = AyoconnectBeneficiaryCallbackService({
            "beneficiary_id": self.beneficiary_id,
            "status": AyoconnectBeneficiaryStatus.DISABLED
        })
        resp = svc.process_unsuccess_callback(external_customer_id=self.external_customer_id)
        self.assertEqual(resp, True)
        self.assertEqual(mock_trigger_create_or_update_beneficiary.call_count, 1)

        # test for J1
        customer = CustomerFactory()
        account = AccountFactory(customer=customer)
        ApplicationFactory(
            customer=customer,
            account=account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
        )
        external_customer_id = "JULO-J1"
        payment_gateway_customer_data = PaymentGatewayCustomerDataFactory(
            customer_id=customer.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            beneficiary_id='test1234',
            external_customer_id=external_customer_id,
            status=AyoconnectBeneficiaryStatus.INACTIVE,
        )
        resp = svc.process_unsuccess_callback(external_customer_id=external_customer_id)
        self.assertEqual(resp, True)
        payment_gateway_customer_data.refresh_from_db()
        self.assertEqual(payment_gateway_customer_data.status,
                         AyoconnectBeneficiaryStatus.UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK)

    @patch('juloserver.loan.tasks.lender_related.loan_disbursement_retry_task.apply_async')
    @patch(
        "juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status")
    def test_process_beneficiary_set_retry_request_limit_to_zero(
            self,
            mock_update_beneficiary_status,
            mock_loan_disbursement_retry_task):
        n_loan = 1
        self.create_loans(n_loan=n_loan, status=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        status = AyoconnectBeneficiaryStatus.ACTIVE

        svc = AyoconnectBeneficiaryCallbackService({
            "beneficiary_id": self.beneficiary_id,
            "status": status
        })
        self.payment_gateway_customer_data.beneficiary_request_retry_limit = AyoconnectConst.BENEFICIARY_RETRY_LIMIT
        self.payment_gateway_customer_data.save()

        resp, _ = svc.process_beneficiary(self.payment_gateway_customer_data)
        self.assertEqual(resp, True)
        self.assertEqual(mock_update_beneficiary_status.call_count, 1)
        mock_update_beneficiary_status.called_once_with(self.payment_gateway_customer_data,
                                                        status)
        self.assertEqual(mock_loan_disbursement_retry_task.call_count, 1)

        self.payment_gateway_customer_data.refresh_from_db()
        self.assertEqual(self.payment_gateway_customer_data.beneficiary_request_retry_limit, 0)

    def test_success_callback_for_multiple_beneficiary_data(self):
        beneficiary_id = "test123double"
        external_customer_id = "JULO-XXI-double"

        for index in range(2):
            PaymentGatewayCustomerData.objects.create(
                customer_id=self.customer.id,
                payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
                beneficiary_id=beneficiary_id,
                external_customer_id=external_customer_id
            )

        svc = AyoconnectBeneficiaryCallbackService(
            {
                "beneficiary_id": self.beneficiary_id,
                "customer_id": self.external_customer_id
            }
        )
        self.assertIsNotNone(svc.is_payment_gateway_customer_data_exists())

    @patch('juloserver.loan.tasks.lender_related.julo_one_disbursement_trigger_task')
    @patch(
        "juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status"
    )
    def test_process_beneficiary_status_for_j1_account(
        self, mock_update_beneficiary_status, mock_julo_one_disbursement_trigger_task
    ):
        n_loan = 1
        self.create_loans(n_loan=n_loan, status=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        loans = Loan.objects.all()
        for loan in loans:
            loan.product.product_line_id = ProductLineCodes.J1
            loan.product.save()
            disbursement = DisbursementFactory(method='Ayoconnect')
            loan.disbursement_id = disbursement.id
            loan.save()
            PaymentGatewayCustomerDataLoan.objects.create(
                beneficiary_id=self.beneficiary_id,
                disbursement_id=loan.disbursement_id,
                loan_id=loan.id,
            )

        status = AyoconnectBeneficiaryStatus.ACTIVE

        svc = AyoconnectBeneficiaryCallbackService(
            {"beneficiary_id": self.beneficiary_id, "status": status}
        )
        resp, _ = svc.process_beneficiary(self.payment_gateway_customer_data)
        self.assertEqual(resp, True)
        mock_update_beneficiary_status.called_once_with(self.payment_gateway_customer_data, status)
        mock_julo_one_disbursement_trigger_task.called_once()
        pg_customer_data_history = PaymentGatewayCustomerDataHistory.objects.filter(
            new_beneficiary_id=self.beneficiary_id,
            old_beneficiary_id=self.beneficiary_id,
        ).exists()
        self.assertTrue(pg_customer_data_history)

    @patch('juloserver.integapiv1.services.execute_after_transaction_safely')
    @patch(
        "juloserver.integapiv1.services.AyoconnectBeneficiaryCallbackService.update_beneficiary_status"
    )
    def test_process_beneficiary_j1_account_multiple_loan(
        self, mock_update_beneficiary_status, mock_execute_after_transaction_safely
    ):
        # multiple loan with same  beneficiary_id
        n_loan = 3
        self.create_loans(n_loan=n_loan, status=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        status = AyoconnectBeneficiaryStatus.ACTIVE

        svc = AyoconnectBeneficiaryCallbackService(
            {"beneficiary_id": self.beneficiary_id, "status": status}
        )
        mock_execute_after_transaction_safely.return_value = None
        loans = Loan.objects.all()
        for loan in loans:
            loan.product.product_line_id = ProductLineCodes.J1
            loan.product.save()
            disbursement = DisbursementFactory(method='Ayoconnect')
            loan.disbursement_id = disbursement.id
            loan.save()
            PaymentGatewayCustomerDataLoan.objects.create(
                beneficiary_id=self.beneficiary_id,
                disbursement_id=loan.disbursement_id,
                loan_id=loan.id,
            )

        resp, _ = svc.process_beneficiary(self.payment_gateway_customer_data)
        self.assertEqual(resp, True)
        mock_update_beneficiary_status.called_once_with(self.payment_gateway_customer_data, status)
        self.assertEqual(mock_execute_after_transaction_safely.call_count, n_loan)
        pg_customer_data_loan = PaymentGatewayCustomerDataLoan.objects.filter(processed=True)
        pg_customer_data_history = PaymentGatewayCustomerDataHistory.objects.filter(
            new_beneficiary_id=self.beneficiary_id,
            old_beneficiary_id=self.beneficiary_id,
        ).exists()
        self.assertTrue(pg_customer_data_loan)
        self.assertTrue(pg_customer_data_history)


class TestIsPaymentMethodProhibitedService(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.payment_method = PaymentMethodFactory(
            payment_method_code=123123, customer=self.customer, loan=None
        )
        escrow_payment_method_lookup = EscrowPaymentMethodLookupFactory(payment_method_code=123123)
        self.escrow_payment_method = EscrowPaymentMethodFactory(
            escrow_payment_method_lookup=escrow_payment_method_lookup
        )

    def test_is_payment_method_prohibited_true_payment_method(self):
        FeatureSettingFactory(
            parameters={
                "payment_method_code": [self.payment_method.payment_method_code],
            },
            feature_name=FeatureNameConst.REPAYMENT_PROHIBIT_VA_PAYMENT,
        )

        is_prohibited = is_payment_method_prohibited(self.payment_method)

        self.assertTrue(is_prohibited)

    def test_is_payment_method_prohibited_false_payment_method(self):
        FeatureSettingFactory(
            parameters={
                "payment_method_code": ["999999"],
            },
            feature_name=FeatureNameConst.REPAYMENT_PROHIBIT_VA_PAYMENT,
        )

        is_prohibited = is_payment_method_prohibited(self.payment_method)

        self.assertFalse(is_prohibited)

    def test_is_payment_method_prohibited_true_escrow_payment_method(self):
        FeatureSettingFactory(
            parameters={
                "payment_method_code": [self.payment_method.payment_method_code],
            },
            feature_name=FeatureNameConst.REPAYMENT_PROHIBIT_VA_PAYMENT,
        )

        is_prohibited = is_payment_method_prohibited(self.escrow_payment_method)

        self.assertTrue(is_prohibited)

    def test_is_payment_method_prohibited_false_escrow_payment_method(self):
        FeatureSettingFactory(
            parameters={
                "payment_method_code": ["999999"],
            },
            feature_name=FeatureNameConst.REPAYMENT_PROHIBIT_VA_PAYMENT,
        )

        is_prohibited = is_payment_method_prohibited(self.escrow_payment_method)

        self.assertFalse(is_prohibited)


class TestConstructFaspayTransactionData(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()

    @patch('juloserver.integapiv1.services.detokenize_sync_primary_object_model')
    @patch('juloserver.integapiv1.services.generate_faspay_signature')
    def test_construct_transaction_data(
        self, mock_generate_faspay_signature, mock_detokenize_sync_primary_object_model
    ):
        va = '123412341234'
        due_amount = '1000000'
        result_detokenized = {
            'fullname': 'John Doe',
            'mobile_phone_1': '081234234234',
            'email': 'test@gmail.com',
        }
        mock_detokenize_sync_primary_object_model.return_value = SimpleNamespace(
            **result_detokenized
        )
        mock_generate_faspay_signature.return_value = 'xxxx-xxxx-xxxx-xxxxx'
        result = construct_transaction_data(va, due_amount, self.application)

        self.assertIsNotNone(result)
        self.assertEqual(result_detokenized['fullname'], result['cust_name'])
        self.assertEqual(result_detokenized['mobile_phone_1'], result['msisdn'])
        self.assertEqual(result_detokenized['email'], result['email'])


class TestGetDueAmount(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.today_date = timezone.localtime(timezone.now()).date()
        self.account_payment_1 = AccountPaymentFactory(
            account=self.account, due_date=self.today_date, due_amount=100
        )
        self.account_payment_2 = AccountPaymentFactory(
            account=self.account,
            due_date=self.today_date + timezone.timedelta(days=2),
            due_amount=200,
        )
        self.checkout_request = CheckoutRequestFactory(
            account_id=self.account,
            status=CheckoutRequestCons.ACTIVE,
            expired_date=timezone.now() + timezone.timedelta(days=1),
            total_payments=300,
            account_payment_ids=[self.account_payment_1.id, self.account_payment_2.id],
        )

    def test_returns_due_amount_for_active_checkout_request(self):
        result = get_due_amount(self.account)
        self.assertEqual(result['due_amount'], 300)
        self.assertEqual(result['oldest_unpaid_account_payment'].id, self.account_payment_1.id)

    def test_returns_due_amount_for_unpaid_account_payments(self):
        self.checkout_request.delete()
        result = get_due_amount(self.account)
        self.assertEqual(result['due_amount'], 100)
        self.assertEqual(result['oldest_unpaid_account_payment'].id, self.account_payment_1.id)

    def test_returns_none_for_no_unpaid_account_payments(self):
        self.checkout_request.delete()
        AccountPayment.objects.filter(account=self.account).update(
            status_id=PaymentStatusCodes.PAID_ON_TIME
        )
        result = get_due_amount(self.account)
        self.assertIsNone(result)

    def test_returns_due_amount_for_multiple_unpaid_account_payments(self):
        self.checkout_request.delete()
        self.account_payment_1.update_safely(due_date=self.today_date - timezone.timedelta(days=1))
        self.account_payment_2.update_safely(due_date=self.today_date)
        result = get_due_amount(self.account)
        self.assertEqual(result['due_amount'], 300)
        self.assertEqual(result['oldest_unpaid_account_payment'].id, self.account_payment_1.id)
