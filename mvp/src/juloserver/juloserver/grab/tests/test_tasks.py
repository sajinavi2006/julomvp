import random
from http import HTTPStatus
import mock
import pytest
import requests
import responses
from requests import PreparedRequest
from requests.models import Response
from freezegun import freeze_time

from juloserver.account.tests.factories import (AccountFactory, AccountLookupFactory,
                                                AccountTransactionFactory)
from juloserver.account_payment.tasks import update_account_payment_status_subtask
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.disbursement.tests.factories import DisbursementFactory, NameBankValidationFactory
from juloserver.grab.constants import (
    GrabErrorMessage,
    GrabSMSTemplateCodes,
    GrabEmailTemplateCodes,
    GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE,
    ApplicationStatus
)
from juloserver.grab.services.loan_halt_resume_services import \
    update_loan_payments_for_loan_resume_v2, update_loan_payments_for_loan_halt_v2, \
    update_loan_halt_and_resume_date
from juloserver.grab.tasks import *
from django.test import TestCase
from django.test.utils import override_settings
from juloserver.grab.tests.factories import (GrabLoanInquiryFactory, GrabCustomerDataFactory,GrabLoanDataFactory,
                                             GrabProgramFeatureSettingFactory, GrabAPILogFactory, GrabLoanOfferFactory,
                                             GrabPaymentPlansFactory, EmergencyContactApprovalLinkFactory)
from juloserver.grab.models import (
    GrabAPILog, GrabPaymentPlans, EmergencyContactApprovalLink, FDCCheckManualApproval
)
from juloserver.julo.models import StatusLookup, PaybackTransaction
from juloserver.julo.tasks import update_payment_status_subtask
from juloserver.julo.tests.factories import (CustomerFactory, ApplicationFactory, PartnerFactory,
                                             StatusLookupFactory, WorkflowFactory,
                                             FeatureSettingFactory, PaymentFactory, AuthUserFactory,
                                             LoanFactory, ProductLookupFactory, LenderFactory,
                                             ProductLineFactory, CreditMatrixFactory,
                                             PaybackTransactionFactory, BankFactory,
                                             ApplicationHistoryFactory, SmsHistoryFactory,
                                             EmailHistoryFactory, FDCInquiryFactory)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory, WorkflowStatusNodeFactory
from juloserver.account.tests.factories import AccountLimitFactory
from datetime import date
from past.utils import old_div
from rest_framework.test import APIClient
from unittest.mock import MagicMock, call
from django.conf import settings
from requests.exceptions import Timeout
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.loan.tasks.lender_related import grab_disbursement_trigger_task
from juloserver.followthemoney.factories import LenderBalanceCurrentFactory
from faker import Faker
from juloserver.core.utils import JuloFakerProvider
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.julo_financing.constants import JFinancingStatus
from juloserver.julo_financing.tests.factories import (
    JFinancingCheckoutFactory,
    JFinancingProductFactory,
    JFinancingVerificationFactory,
)

fake = Faker()
fake.add_provider(JuloFakerProvider)


class MockedResponse(requests.Response):
    request = mock.MagicMock(spec=PreparedRequest)


class TestGrabTasks(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='GrabWorkflow', handler='GrabWorkflowHandler')
        self.workflow_status_node = WorkflowStatusNodeFactory(
            status_node=106, workflow=self.workflow,
            handler='Grab106Handler')
        self.workflow_status_node.save()
        self.workflow.save()
        self.application = ApplicationFactory(
            customer=self.customer, workflow=self.workflow)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data)
        self.grab_loan_data = GrabLoanDataFactory(
            grab_loan_inquiry=self.grab_loan_inquiry)
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=106,
            workflow=self.workflow,
            is_active=True
        )

    def test_mark_expiry_application_grab(self) -> None:
        self.application.application_status = StatusLookupFactory(
            status_code=100)
        self.application.workflow = self.workflow
        self.application.cdate = timezone.localtime(timezone.now() - relativedelta(days=14))
        self.application.save()
        self.application.application_status.save()
        mark_form_partial_expired_grab_subtask(
            application_id=self.application.id,
            created_date=self.application.cdate,
            application_status_id=self.application.application_status.status_code
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status.status_code, 106)

        self.application.application_status = StatusLookupFactory(status_code=100)
        self.application.cdate = timezone.localtime(timezone.now())
        self.application.save()
        self.application.application_status.save()
        mark_form_partial_expired_grab_subtask(
            application_id=self.application.id,
            created_date=self.application.cdate,
            application_status_id=self.application.application_status.status_code
        )
        self.application.refresh_from_db()
        self.assertNotEqual(self.application.application_status.status_code, 106)
        self.assertEqual(self.application.application_status.status_code, 100)


class TestTriggerDeductionMainFunction(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='GrabWorkflow', handler='GrabWorkflowHandler')
        self.account_lookup = AccountLookupFactory(partner=self.partner, workflow=self.workflow)
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = Loan.objects.create(
            customer=self.customer,
            application=self.application,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() + timedelta(days=3),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.batch_id = "batch-0 2022-09-24 04:00"
        self.batch_id_2 = "batch-1 2022-09-25 01:00"
        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_1DPD)
        installment = old_div(self.loan.loan_amount, self.loan.loan_duration)
        interest_amount = installment * 0.1
        principal_amount = installment - interest_amount
        self.pending_payment = PaymentFactory(
            loan=self.loan,
            due_date=date.today() - timedelta(days=1),
            due_amount=old_div(self.loan.loan_amount, self.loan.loan_duration),
            installment_interest=interest_amount,
            installment_principal=principal_amount,
            payment_number=5,
            payment_status=payment_status
        )
        self.pending_payment.account_payment = self.account_payment
        self.pending_payment.save()

    @mock.patch('juloserver.grab.tasks.trigger_deduction_api_cron.delay')
    def test_deduction_feature_setting_not_active(self, mock_trigger_deduction_api_cron):
        trigger_deduction_main_function(self.batch_id)
        self.assertEqual(mock_trigger_deduction_api_cron.called, False)

    @mock.patch('juloserver.grab.tasks.trigger_deduction_api_cron.delay')
    def test_success_trigger_deduction_main_function(self, mock_trigger_deduction_api_cron):
        self.deduction_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE,
            parameters={
                "schedule": ["01:00", "04:00", "07:00", "09:00", "10:00", "12:00", "14:00", "16:00", "18:00", "22:00"],
                "complete_rollover": False
            }
        )
        self.grab_feature_setting = GrabProgramFeatureSettingFactory(feature_setting=self.deduction_feature_setting)
        trigger_deduction_main_function(self.batch_id)
        self.assertEqual(mock_trigger_deduction_api_cron.called, True)

    @mock.patch('juloserver.grab.tasks.trigger_deduction_api_cron.delay')
    def test_success_trigger_deduction_main_function_with_complete_rollover(self, mock_trigger_deduction_api_cron):
        self.deduction_feature_setting_complete_rollover = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE,
            parameters={
                "schedule": ["01:00", "04:00", "07:00", "09:00", "10:00", "12:00", "14:00", "16:00", "18:00", "22:00"],
                "complete_rollover": True
            }
        )
        self.grab_feature_setting_complete_rollover = GrabProgramFeatureSettingFactory(
            feature_setting=self.deduction_feature_setting_complete_rollover)
        trigger_deduction_main_function(self.batch_id_2)
        self.assertEqual(mock_trigger_deduction_api_cron.called, True)


class TestGrabNewRepaymentSubTask(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.loan = LoanFactory(account=self.account, customer=self.customer)
        self.batch = 'batch-0 2023-02-21 11:23'
        self.response_data = {'status': 'ok'}

    @responses.activate
    def test_deduction_sub_repayment_task_success(self):
        responses.add(
            'POST',
            url=f'{settings.GRAB_API_URL}/lendingPartner/external/v1/julo-deduction',
            status=200,
            json=self.response_data,
        )
        trigger_deduction_api_cron(self.loan.id, self.batch)
        self.assertFalse(
            GrabAPILog.objects.filter(
                loan_id=self.loan.id,
                query_params='/lendingPartner/external/v1/julo-deduction',
                http_status_code=200,
            ).exists()
        )
        self.assertTrue(
            GrabTransactions.objects.filter(
                loan_id=self.loan.id, grab_api_log_id__isnull=True
            ).exists()
        )

    @responses.activate
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    def test_deduction_sub_repayment_task_failed_4xx(self, mocked_message):
        responses.add(
            'POST',
            url=f'{settings.GRAB_API_URL}/lendingPartner/external/v1/julo-deduction',
            status=400,
            json=self.response_data,
        )
        mocked_message.return_value = None
        trigger_deduction_api_cron(self.loan.id, self.batch)
        self.assertTrue(
            GrabAPILog.objects.filter(
                loan_id=self.loan.id,
                query_params='/lendingPartner/external/v1/julo-deduction',
                http_status_code=400,
            ).exists()
        )
        grab_api_log = GrabAPILog.objects.filter(
            loan_id=self.loan.id,
            query_params='/lendingPartner/external/v1/julo-deduction',
            http_status_code=400,
        ).last()
        self.assertTrue(
            GrabTransactions.objects.filter(
                loan_id=self.loan.id,
                grab_api_log_id=grab_api_log.id,
            ).exists()
        )
        mocked_message.assert_called()

    @responses.activate
    def test_deduction_sub_repayment_task_failed_5xx(self):
        responses.add(
            'POST',
            url=f'{settings.GRAB_API_URL}/lendingPartner/external/v1/julo-deduction',
            status=500,
            json=self.response_data,
        )
        with self.assertRaises(Timeout) as context:
            trigger_deduction_api_cron(self.loan.id, self.batch)
        self.assertTrue(
            GrabAPILog.objects.filter(
                loan_id=self.loan.id,
                query_params='/lendingPartner/external/v1/julo-deduction',
                http_status_code=500,
            ).exists()
        )
        self.assertTrue(
            GrabTransactions.objects.filter(
                loan_id=self.loan.id, grab_api_log_id__isnull=True
            ).exists()
        )


class TestNewRepaymentFlow(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.response_data = {'status': 'ok'}
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = Loan.objects.create(
            customer=self.customer,
            application=self.application,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() + timedelta(days=3),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.deduction_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE,
            parameters={
                "schedule": ["01:00", "04:00", "07:00", "09:00", "10:00", "12:00", "14:00", "16:00", "18:00", "22:00"],
                "complete_rollover": False
            }
        )
        self.batch_id = "batch-0 2022-09-24 04:00"
        self.batch_id_2 = "batch-1 2022-09-25 01:00"
        self.grab_feature_setting = GrabProgramFeatureSettingFactory(feature_setting=self.deduction_feature_setting)
        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_1DPD)
        installment = old_div(self.loan.loan_amount, self.loan.loan_duration)
        interest_amount = installment * 0.1
        principal_amount = installment - interest_amount
        self.pending_payment = PaymentFactory(
            loan=self.loan,
            due_date=date.today() - timedelta(days=1),
            due_amount=old_div(self.loan.loan_amount, self.loan.loan_duration),
            installment_interest=interest_amount,
            installment_principal=principal_amount,
            payment_number=5,
            payment_status=payment_status
        )
        self.pending_payment.account_payment = self.account_payment
        self.pending_payment.save()

    @responses.activate
    @mock.patch('juloserver.grab.services.grab_payment_flow.AccountTransaction.objects')
    @mock.patch('juloserver.grab.services.grab_payment_flow.PaymentEvent.account_transaction')
    def test_success_partial_paid_repayment(self, mock_account_transaction: MagicMock, mock_payment_event: MagicMock):
        responses.add(
            'POST',
            url=f'{settings.GRAB_API_URL}/lendingPartner/external/v1/julo-deduction',
            status=200,
            json=self.response_data,
        )
        trigger_deduction_api_cron(self.loan.id, self.batch_id)
        self.grab_txn = GrabTransactions.objects.get(batch=self.batch_id, loan_id=self.loan.id)
        self.assertEqual(self.grab_txn.status, GrabTransactions.IN_PROGRESS)
        data = {
            'application_xid': self.application.application_xid,
            'loan_xid': self.loan.loan_xid,
            "event_date": "2021-08-24T12:00:00Z",
            'deduction_reference_id': 'test-deduction-0',
            'deduction_amount': 1000,
            'txn_id': self.grab_txn.id
        }

        # hit our repayment
        response = self.client.post('/api/partner/grab/repayment', data=data, format='json')
        self.assertEqual(200, response.status_code, response.content)
        self.grab_txn.refresh_from_db()
        self.assertEqual(self.grab_txn.status, GrabTransactions.SUCCESS)

    @responses.activate
    @mock.patch('juloserver.grab.services.grab_payment_flow.AccountTransaction.objects')
    @mock.patch('juloserver.grab.services.grab_payment_flow.PaymentEvent.account_transaction')
    def test_success_full_paid_repayment(self, mock_account_transaction: MagicMock, mock_payment_event: MagicMock):
        responses.add(
            'POST',
            url=f'{settings.GRAB_API_URL}/lendingPartner/external/v1/julo-deduction',
            status=200,
            json=self.response_data,
        )
        trigger_deduction_api_cron(self.loan.id, self.batch_id)
        self.grab_txn = GrabTransactions.objects.get(batch=self.batch_id, loan_id=self.loan.id)
        self.assertEqual(self.grab_txn.status, GrabTransactions.IN_PROGRESS)
        data = {
            'application_xid': self.application.application_xid,
            'loan_xid': self.loan.loan_xid,
            "event_date": "2021-09-24T12:00:00Z",
            'deduction_reference_id': 'test-deduction-full',
            'deduction_amount': self.loan.loan_amount,
            'txn_id': self.grab_txn.id
        }

        # hit our repayment
        response = self.client.post('/api/partner/grab/repayment', data=data, format='json')
        self.assertEqual(200, response.status_code, response.content)
        self.grab_txn.refresh_from_db()
        self.assertEqual(self.grab_txn.status, GrabTransactions.SUCCESS)

        # check payment not paid
        payment_not_paid = []
        payments = Payment.objects.filter(loan=self.loan).only("id", "paid_date")
        payment_set = set(payments)
        for payment in payment_set:
            if payment.paid_date == None:
                payment_not_paid.append(payment)
        self.assertEqual(0, len(payment_not_paid))

    @responses.activate
    @mock.patch('juloserver.grab.services.grab_payment_flow.AccountTransaction.objects')
    @mock.patch('juloserver.grab.services.grab_payment_flow.PaymentEvent.account_transaction')
    def test_failed_repayment_with_different_loan_xid(self, mock_account_transaction: MagicMock, mock_payment_event: MagicMock):
        responses.add(
            'POST',
            url=f'{settings.GRAB_API_URL}/lendingPartner/external/v1/julo-deduction',
            status=200,
            json=self.response_data,
        )
        trigger_deduction_api_cron(self.loan.id, self.batch_id)
        self.grab_txn = GrabTransactions.objects.get(batch=self.batch_id, loan_id=self.loan.id)
        self.assertEqual(self.grab_txn.status, GrabTransactions.IN_PROGRESS)
        data = {
            'application_xid': self.application.application_xid,
            'loan_xid': 123456,
            "event_date": "2021-08-24T12:00:00Z",
            'deduction_reference_id': 'test-deduction-0',
            'deduction_amount': 1000,
            'txn_id': self.grab_txn.id
        }

        # hit our repayment
        response = self.client.post('/api/partner/grab/repayment', data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json()['errors'][0], f'No Active Loan found for xid {data.get("loan_xid")}')
        self.grab_txn.refresh_from_db()
        self.assertEqual(self.grab_txn.status, GrabTransactions.IN_PROGRESS)


    @responses.activate
    @mock.patch('juloserver.grab.services.grab_payment_flow.AccountTransaction.objects')
    @mock.patch('juloserver.grab.services.grab_payment_flow.PaymentEvent.account_transaction')
    def test_failed_repayment_with_different_app_xid(self, mock_account_transaction: MagicMock, mock_payment_event: MagicMock):
        responses.add(
            'POST',
            url=f'{settings.GRAB_API_URL}/lendingPartner/external/v1/julo-deduction',
            status=200,
            json=self.response_data,
        )
        trigger_deduction_api_cron(self.loan.id, self.batch_id)
        self.grab_txn = GrabTransactions.objects.get(batch=self.batch_id, loan_id=self.loan.id)
        self.assertEqual(self.grab_txn.status, GrabTransactions.IN_PROGRESS)
        data = {
            'application_xid': 123456,
            'loan_xid': self.loan.loan_xid,
            "event_date": "2021-08-24T12:00:00Z",
            'deduction_reference_id': 'test-deduction-0',
            'deduction_amount': 1000,
            'txn_id': self.grab_txn.id
        }

        # hit our repayment
        response = self.client.post('/api/partner/grab/repayment', data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json()['errors'][0], f'Application not found for xid {data.get("application_xid")}')
        self.grab_txn.refresh_from_db()
        self.assertEqual(self.grab_txn.status, GrabTransactions.IN_PROGRESS)

    @mock.patch('juloserver.grab.services.repayment.send_grab_failed_deduction_slack.delay')
    def test_failed_repayment_due_missing_txn_id(self, mocked_slack):
        self.customer_1 = CustomerFactory()
        self.account_1 = AccountFactory(customer=self.customer_1)
        self.loan_1 = LoanFactory(account=self.account, customer=self.customer_1)
        self.grab_customer_data_1 = GrabCustomerDataFactory(customer=self.customer_1)
        self.application_1 = ApplicationFactory(account=self.account,
                                                customer=self.customer_1)
        self.application_1.application_xid = random.randint(3200000000, 7500000000)
        self.application_1.save()
        self.loan_1.loan_xid = random.randint(3200000000, 7500000000)
        self.loan_1.save()
        mocked_slack.return_value = None
        data = {
            'application_xid': self.application_1.application_xid,
            'loan_xid': self.loan_1.loan_xid,
            "event_date": "2021-08-24T12:00:00Z",
            'deduction_reference_id': 'test-deduction-1000',
            'deduction_amount': 1000,
            'txn_id': "some_random_txn_id"
        }
        response = self.client.post('/api/partner/grab/repayment', data=data, format='json')
        self.assertEqual(HTTPStatus.BAD_REQUEST, response.status_code, response.content)
        self.assertEqual(response.json()['errors'][0], 'Txn_id is not found')
        mocked_slack.assert_called()


class TestUpdateGrabTransactionToExpired(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = Loan.objects.create(
            customer=self.customer,
            application=self.application,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() + timedelta(days=3),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.deduction_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE,
            parameters={
                "schedule": ["01:00", "04:00", "07:00", "09:00", "10:00", "12:00", "14:00", "16:00", "18:00",
                             "22:00"],
                "complete_rollover": False
            }
        )
        self.batch_id = "batch-0 2022-09-24 04:00"
        self.batch_id_2 = "batch-1 2022-09-25 01:00"
        self.grab_feature_setting = GrabProgramFeatureSettingFactory(feature_setting=self.deduction_feature_setting)
        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_1DPD)
        installment = old_div(self.loan.loan_amount, self.loan.loan_duration)
        interest_amount = installment * 0.1
        principal_amount = installment - interest_amount
        self.pending_payment = PaymentFactory(
            loan=self.loan,
            due_date=date.today() - timedelta(days=1),
            due_amount=old_div(self.loan.loan_amount, self.loan.loan_duration),
            installment_interest=interest_amount,
            installment_principal=principal_amount,
            payment_number=5,
            payment_status=payment_status
        )
        self.pending_payment.account_payment = self.account_payment
        self.pending_payment.save()

    def test_success_update_grab_transaction_to_expired(self):
        self.old_grab_txn = GrabTransactions.objects.create(
            loan_id=self.loan.id, status=GrabTransactions.IN_PROGRESS, batch=self.batch_id_2
        )
        today = timezone.localtime(timezone.now())
        twentyfour_hours_ago = today - timedelta(hours=24)
        self.old_grab_txn.cdate = twentyfour_hours_ago
        self.old_grab_txn.save()
        # call the expired func
        update_failed_grab_transaction_status()
        self.old_grab_txn.refresh_from_db()
        self.assertEqual(self.old_grab_txn.status, GrabTransactions.EXPIRED)

    def test_failed_update_grab_transaction_to_expired(self):
        self.success_grab_txn = GrabTransactions.objects.create(
            loan_id=self.loan.id, status=GrabTransactions.SUCCESS, batch=self.batch_id_2
        )
        # call the expired func
        update_failed_grab_transaction_status()
        self.success_grab_txn.refresh_from_db()
        self.assertEqual(self.success_grab_txn.status, GrabTransactions.SUCCESS)


class TestUpdateGrabExcludedOldRepaymentLoan(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = Loan.objects.create(
            customer=self.customer,
            application=self.application,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() + timedelta(days=3),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account
        )

        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.deduction_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE,
            parameters={
                "schedule": ["01:00", "04:00", "07:00", "09:00", "10:00", "12:00", "14:00", "16:00", "18:00",
                             "22:00"],
                "complete_rollover": False
            }
        )
        self.batch_id = "batch-0 2022-09-24 04:00"
        self.batch_id_2 = "batch-1 2022-09-25 01:00"
        self.grab_feature_setting = GrabProgramFeatureSettingFactory(feature_setting=self.deduction_feature_setting)
        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_1DPD)
        installment = old_div(self.loan.loan_amount, self.loan.loan_duration)
        interest_amount = installment * 0.1
        principal_amount = installment - interest_amount
        self.pending_payment = PaymentFactory(
            loan=self.loan,
            due_date=date.today() - timedelta(days=1),
            due_amount=old_div(self.loan.loan_amount, self.loan.loan_duration),
            installment_interest=interest_amount,
            installment_principal=principal_amount,
            payment_number=5,
            payment_status=payment_status
        )
        self.pending_payment.account_payment = self.account_payment
        self.pending_payment.save()

    def test_update_grab_excluded_old_repayment_loan(self):
        async_update_grab_excluded_old_repayment_loan()
        grab_excluded_repayment_loan = GrabExcludedOldRepaymentLoan.objects.get(loan=self.loan)
        self.assertEqual(grab_excluded_repayment_loan.loan_id, self.loan.id)


class TestSubmitGrabDisbursalCreationTask(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.product = ProductLookupFactory()
        self.disbursement = DisbursementFactory()
        self.application = Application.objects.create(
            customer=self.customer,
            account=self.account
        )
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = Loan.objects.create(
            customer=self.customer,
            application=self.application,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() + timedelta(days=3),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account,
            disbursement_id=self.disbursement.id,
            product=self.product
        )
        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_1DPD)
        installment = old_div(self.loan.loan_amount, self.loan.loan_duration)
        interest_amount = installment * 0.1
        principal_amount = installment - interest_amount
        self.pending_payment = PaymentFactory(
            loan=self.loan,
            due_date=date.today() - timedelta(days=1),
            due_amount=old_div(self.loan.loan_amount, self.loan.loan_duration),
            installment_interest=interest_amount,
            installment_principal=principal_amount,
            payment_number=5,
            payment_status=payment_status
        )
        self.pending_payment.account_payment = self.account_payment
        self.pending_payment.save()
        self.response_data = {
            "msg_id": "aa116b4db02940a49fa32e0000521f9f",
            "success": "false",
            "error": {
                "code": "4001",
                "message": "Invalid Request"
            }
        }

    @mock.patch('juloserver.grab.tasks.send_grab_api_timeout_alert_slack.delay')
    def test_trigger_task_failed_loan_not_found(self, mock_timeout_slack_alert):
        trigger_submit_grab_disbursal_creation.apply(loan_id=1234)
        self.assertEqual(mock_timeout_slack_alert.called, False)

    @responses.activate
    @mock.patch('juloserver.grab.tasks.trigger_submit_grab_disbursal_creation.retry')
    def test_trigger_task_success_retried(self, mock_retry):
        import celery
        responses.add(
            'POST',
            url=f'{settings.GRAB_API_URL}/lendingPartner/external/v1/capture',
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            json=self.response_data,
        )
        mock_retry.side_effect = celery.exceptions.Retry
        with pytest.raises(celery.exceptions.Retry):
            trigger_submit_grab_disbursal_creation(loan_id=self.loan.id)

        self.assertTrue(mock_retry.called)


class TestGrabLoanSyncAPI(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.response_data = {'status': 'ok'}
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB, handler='GrabWorkflowHandler')
        self.account_lookup = AccountLookupFactory(partner=self.partner, workflow=self.workflow)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            application_status=StatusLookupFactory(status_code=190),
            workflow=self.workflow
        )
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() + timedelta(days=3),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account
        )
        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.workflow_path = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=211, status_next=216, workflow=self.workflow_path)
        WorkflowStatusPathFactory(status_previous=220, status_next=230, workflow=self.workflow_path)

    @mock.patch('juloserver.loan.services.loan_related.'
                'trigger_grab_loan_sync_api_async_task.apply_async')
    def test_loan_sync_api_success(self, mocked_trigger):
        self.loan.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.loan.save()
        new_status_code = StatusLookup.LOAN_1DPD_CODE
        update_loan_status_and_loan_history(
            self.loan.id, new_status_code, None, "test_loan_sync_api")
        mocked_trigger.assert_called()

    @mock.patch('juloserver.loan.services.loan_related.'
                'trigger_grab_loan_sync_api_async_task.apply_async')
    def test_loan_sync_api_success_1(self, mocked_trigger):
        self.loan.loan_status = StatusLookupFactory(status_code=StatusLookup.LENDER_APPROVAL)
        self.loan.save()
        new_status_code = StatusLookup.CANCELLED_BY_CUSTOMER
        update_loan_status_and_loan_history(
            self.loan.id, new_status_code, None, "test_loan_sync_api")
        mocked_trigger.assert_not_called()

    @mock.patch('juloserver.grab.clients.clients.add_grab_api_log')
    @mock.patch('requests.put')
    def test_trigger_grab_loan_sync_api_async_task_success(
            self, mocked_response, mocked_add_log):
        mocked_response_obj = mock.MagicMock()
        mocked_response_obj.status_code = 200
        mocked_response_obj.content = {"message": "Loan Received", "status": 202}
        mocked_response.return_value = mocked_response_obj
        self.loan.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.application.application_status_id = 190
        self.loan.save()
        self.application.save()

        trigger_grab_loan_sync_api_async_task(self.loan.id)
        mocked_response.assert_called()
        mocked_add_log.assert_not_called()

    @mock.patch('juloserver.grab.clients.clients.add_grab_api_log')
    @mock.patch('requests.put')
    def test_trigger_grab_loan_sync_api_async_task_failed(
            self, mocked_response, mocked_add_log
    ):
        mocked_response_obj = mock.MagicMock()
        mocked_response_obj.status_code = 502
        mocked_response_obj.content = {"message": "Failed", "status": 202}
        mocked_response_obj_2 = mock.MagicMock()
        mocked_response_obj_2.status_code = 200
        mocked_response_obj_2.content = {"message": "Loan Received", "status": 202}

        mocked_response.side_effect = [mocked_response_obj, mocked_response_obj_2]
        mocked_add_log.return_value = None
        self.loan.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.application.application_status_id = 190
        self.loan.save()
        self.application.save()
        trigger_grab_loan_sync_api_async_task(self.loan.id)
        mocked_response.assert_called()
        mocked_add_log.assert_called()


class TestGrabDisbursementProcess(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user, name='grab')
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.account_limit = AccountLimitFactory(account=self.account)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            application_status=StatusLookupFactory(status_code=190),
            workflow=self.workflow
        )
        self.lender = LenderFactory(lender_name='ska', user=self.partner.user)
        self.lender_balance = LenderBalanceCurrentFactory(
            available_balance=1000000000, lender=self.lender)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.grab_loan_inquiry = GrabLoanInquiryFactory(
            grab_customer_data=self.grab_customer_data)
        self.loan = LoanFactory(
            customer=self.customer,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() + timedelta(days=3),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            account=self.account,
            lender=self.lender
        )
        self.grab_loan_data = GrabLoanDataFactory(
            grab_loan_inquiry=self.grab_loan_inquiry, loan=self.loan)
        self.workflow_path = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=211, status_next=214, workflow=self.workflow_path)
        WorkflowStatusPathFactory(status_previous=211, status_next=219, workflow=self.workflow_path)

    @mock.patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    @mock.patch('juloserver.loan.tasks.lender_related.GrabClient.submit_loan_creation')
    def test_grab_disbursement_trigger_task_success(self, mocked_response, mocked_j1_disburse):
        loan_status = StatusLookupFactory(
            status_code=StatusLookup.LENDER_APPROVAL)
        self.loan.loan_status = loan_status
        self.loan.save()
        GrabAPILogFactory(
            customer_id=self.loan.customer.id,
            loan_id=self.loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        )
        magic_mock = mock.MagicMock()
        magic_mock.status_code = 200
        mocked_response.return_value = magic_mock
        mocked_j1_disburse.return_value = None
        grab_disbursement_trigger_task(self.loan.id)
        mocked_j1_disburse.assert_called()

    @mock.patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    @mock.patch('juloserver.loan.tasks.lender_related.GrabClient.submit_loan_creation')
    def test_grab_disbursement_trigger_task_failure_1(self, mocked_response, mocked_j1_disburse):
        loan_status = StatusLookupFactory(
            status_code=StatusLookup.LENDER_APPROVAL)
        self.loan.loan_status = loan_status
        self.loan.save()

        magic_mock = mock.MagicMock()
        magic_mock.status_code = 400
        mocked_response.return_value = magic_mock
        mocked_j1_disburse.return_value = None
        with self.assertRaises(JuloException):
            grab_disbursement_trigger_task(self.loan.id)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 219)
        mocked_j1_disburse.assert_not_called()

    @mock.patch('juloserver.loan.tasks.lender_related.grab_disbursement_trigger_task.apply_async')
    @mock.patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    @mock.patch('juloserver.loan.tasks.lender_related.GrabClient.submit_loan_creation')
    def test_grab_disbursement_trigger_task_failure_2(
            self, mocked_response, mocked_j1_disburse, mocked_grab_disbursement):
        loan_status = StatusLookupFactory(
            status_code=StatusLookup.LENDER_APPROVAL)
        self.loan.loan_status = loan_status
        self.loan.save()

        magic_mock = mock.MagicMock()
        magic_mock.status_code = 500
        mocked_response.return_value = magic_mock
        mocked_j1_disburse.return_value = None
        mocked_grab_disbursement.return_value = None
        with self.assertRaises(JuloException):
            grab_disbursement_trigger_task(self.loan.id)
        self.loan.refresh_from_db()
        mocked_j1_disburse.assert_not_called()

    @mock.patch('juloserver.loan.tasks.lender_related.grab_disbursement_trigger_task.apply_async')
    @mock.patch('juloserver.loan.services.lender_related.julo_one_disbursement_process')
    @mock.patch('juloserver.loan.tasks.lender_related.GrabClient.submit_loan_creation')
    def test_grab_disbursement_trigger_task_failure_3(
            self, mocked_response, mocked_j1_disburse, mocked_grab_disbursement):
        loan_status = StatusLookupFactory(
            status_code=StatusLookup.LENDER_APPROVAL)
        self.loan.loan_status = loan_status
        self.loan.save()

        magic_mock = mock.MagicMock()
        magic_mock.status_code = 500
        mocked_response.return_value = magic_mock
        mocked_j1_disburse.return_value = None
        mocked_grab_disbursement.return_value = None
        with self.assertRaises(JuloException):
            grab_disbursement_trigger_task(self.loan.id, 4)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, 219)
        mocked_j1_disburse.assert_not_called()
        mocked_grab_disbursement.assert_not_called()


class TestGrabLoanHaltResumeV2(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user)
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='GrabWorkflow', handler='GrabWorkflowHandler')
        self.account_lookup = AccountLookupFactory(name='GRAB', partner=self.partner,
                                                   workflow=self.workflow)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.loan_status = StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            application_status=StatusLookupFactory(status_code=190),
            product_line=self.product_line,
            workflow=self.workflow,
        )
        self.product = ProductLookupFactory()
        self.loan = Loan.objects.create(
            customer=self.customer,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=4,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() + timedelta(days=3),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account,
            disbursement_id=None,
            product=self.product
        )
        self.workflow_path = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=220, status_next=241, workflow=self.workflow_path)

        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        for i in range(1, self.loan.loan_duration + 1):
            due_date = self.loan.fund_transfer_ts + relativedelta(months=i)
            installment = old_div(self.loan.loan_amount, self.loan.loan_duration)
            interest_amount = installment * 0.1
            principal_amount = installment - interest_amount
            PaymentFactory(
                loan=self.loan,
                due_date=due_date,
                due_amount=installment,
                installment_interest=interest_amount,
                installment_principal=principal_amount,
                payment_number=i,
                payment_status=payment_status,
                account_payment=self.account_payment
            )
        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.application.update_safely(application_status_id=190)

        self.customer_1 = CustomerFactory()
        self.account_1 = AccountFactory(customer=self.customer_1, account_lookup=self.account_lookup)
        self.account_limit_1 = AccountLimitFactory(account=self.account_1)
        self.application_1 = ApplicationFactory(
            customer=self.customer_1, account=self.account_1,
            application_status=StatusLookupFactory(status_code=190),
            product_line=self.product_line,
            workflow=self.workflow,
        )
        self.loan_1 = Loan.objects.create(
            customer=self.customer_1,
            partner=self.partner,
            loan_amount=9000000,
            loan_duration=30,
            installment_amount=old_div(900000, 4),
            first_installment_amount=old_div(900000, 4) + 5000,
            cashback_earned_total=0,
            initial_cashback=0,
            loan_disbursement_amount=0,
            fund_transfer_ts=date.today() - timedelta(days=150),
            julo_bank_name="CIMB NIAGA",
            julo_bank_branch="TEBET",
            julo_bank_account_number="12345678",
            cycle_day=13,
            cycle_day_change_date=None,
            cycle_day_requested=None,
            cycle_day_requested_date=None,
            loan_status=self.loan_status,
            account=self.account_1,
            disbursement_id=None,
            product=self.product
        )

        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        for i in range(1, self.loan_1.loan_duration + 1):
            due_date = self.loan_1.fund_transfer_ts + relativedelta(days=i + 3)
            installment = old_div(self.loan.loan_amount, self.loan.loan_duration)
            interest_amount = installment * 0.1
            principal_amount = installment - interest_amount
            account_payment = AccountPaymentFactory(
                account=self.account_1,
                due_date=due_date,
                is_restructured=False
            )
            PaymentFactory(
                loan=self.loan_1,
                due_date=due_date,
                due_amount=installment,
                installment_interest=interest_amount,
                installment_principal=principal_amount,
                payment_number=i,
                payment_status=payment_status,
                account_payment=account_payment,
                is_restructured=False
            )
        self.grab_loan_data_1 = GrabLoanDataFactory(loan=self.loan_1)
        self.application.update_safely(application_status_id=190)

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.grab.tasks.update_grab_payment_data_for_halt_resume_v2.apply_async')
    def test_success_halt_loan(self, mock_update_grab_payment_for_halted_loan):
        today = timezone.localtime(timezone.now())
        next_4_days = today + timedelta(days=4)
        trigger_grab_loan_halt_v2(loan_halt_date=today, loan_resume_date=next_4_days)

        self.loan.refresh_from_db()
        self.grab_loan_data.refresh_from_db()

        app_note_halted = ApplicationNote.objects.filter(
            application_id=self.application.id,
            note_text='Account has been Halted. Halt-date: ({})'.format(today)
        )

        halted_status_lookup = StatusLookup.objects.get_or_none(status_code=LoanStatusCodes.HALT)

        mock_update_grab_payment_for_halted_loan.assert_called()
        self.assertEqual(self.loan.loan_status, halted_status_lookup)
        self.assertIsNotNone(self.grab_loan_data.account_halt_info)
        self.assertEqual(self.grab_loan_data.account_halt_status, AccountHaltStatus.HALTED)
        self.assertIsNotNone(self.grab_loan_data.loan_halt_date)
        self.assertTrue(app_note_halted.exists())

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.grab.services.services.update_loan_status_and_loan_history')
    def test_success_resume_halted_loan(self, mock_update_loan_status_and_loan_history: MagicMock):
        today = timezone.localtime(timezone.now())
        next_4_days = today + timedelta(days=4)
        trigger_grab_loan_halt_v2(loan_halt_date=today, loan_resume_date=next_4_days)

        self.loan.refresh_from_db()
        self.grab_loan_data.refresh_from_db()

        trigger_grab_loan_resume_v2()

        self.loan.refresh_from_db()
        self.grab_loan_data.refresh_from_db()

        app_note_resumed = ApplicationNote.objects.filter(
            application_id=self.application.id,
            note_text='Account has been Updated to Resume. Resume-date: ({})'.format(
                next_4_days.strftime("%Y-%m-%d"))
        )

        halted_status_lookup = StatusLookup.objects.get_or_none(status_code=LoanStatusCodes.HALT)

        self.assertEqual(self.loan.loan_status, halted_status_lookup)
        self.assertIsNotNone(self.grab_loan_data.account_halt_info)
        self.assertEqual(self.grab_loan_data.account_halt_status,
                         AccountHaltStatus.HALTED_UPDATED_RESUME_LOGIC)
        self.assertIsNotNone(self.grab_loan_data.loan_resume_date)
        self.assertTrue(app_note_resumed.exists())

        trigger_loan_resume_final_task_v2()
        self.grab_loan_data.refresh_from_db()

        self.assertEqual(self.grab_loan_data.account_halt_status, AccountHaltStatus.RESUMED)

    def test_update_loan_halt_and_resume_date(self):
        halt_date = timezone.localtime(timezone.now())
        resume_date = halt_date + timedelta(days=4)
        update_loan_halt_and_resume_date(self.grab_loan_data, halt_date, resume_date)
        self.grab_loan_data.refresh_from_db()

        account_halt_info = self.grab_loan_data.account_halt_info
        loaded_account_halt_info = account_halt_info[0]
        self.assertIsNotNone(self.grab_loan_data.account_halt_info)
        self.assertEqual(loaded_account_halt_info.get('account_halt_date'),
                         halt_date.strftime('%Y-%m-%d'))
        self.assertEqual(loaded_account_halt_info.get('account_resume_date'),
                         resume_date.strftime('%Y-%m-%d'))

    def test_update_grab_payment_data_for_halt_resume_v2(self):
        update_grab_payment_data_for_halt_resume_v2(self.loan.id)
        self.loan.refresh_from_db()

        grab_payment_data = GrabPaymentData.objects.filter(loan_id=self.loan.id)
        total_payment = self.loan.payment_set.count()
        self.assertIsNotNone(grab_payment_data.exists())
        self.assertEqual(grab_payment_data.count(), total_payment)

    def test_failed_halted_loan_invalid_account(self):
        halt_date = timezone.localtime(timezone.now())
        random_account_id = fake.numerify(text="#%#%#%")
        with pytest.raises(GrabHaltResumeError) as e:
            trigger_loan_halt_sub_task_v2(random_account_id, halt_date)
        self.assertEqual(str(e.value), "Invalid AccountID: {}".format(random_account_id))

    def test_failed_halted_loan_missing_grab_loan_data(self):
        halt_date = timezone.localtime(timezone.now())
        self.grab_loan_data.update_safely(loan=None)
        with pytest.raises(GrabHaltResumeError) as e:
            update_loan_payments_for_loan_halt_v2(self.loan, halt_date)
        self.assertEqual(str(e.value), "Grab Loan Data not found")

    def test_failed_resume_loan_invalid_account(self):
        random_account_id = fake.numerify(text="#%#%#%")
        with pytest.raises(GrabHaltResumeError) as e:
            trigger_loan_resume_sub_task_v2(random_account_id)
        self.assertEqual(str(e.value), "Invalid AccountID: {}".format(random_account_id))

    def test_failed_resume_loan_missing_grab_loan_data(self):
        halt_date = timezone.localtime(timezone.now())
        resume_date = halt_date + timedelta(days=4)
        self.grab_loan_data.update_safely(loan=None)
        with pytest.raises(GrabHaltResumeError) as e:
            update_loan_payments_for_loan_resume_v2(self.loan, resume_date, halt_date)
        self.assertEqual(str(e.value), "Grab Loan Data not found")

    @pytest.mark.skip(reason="Flaky test")
    @mock.patch('juloserver.account_payment.tasks.update_account_payment_status_subtask.delay')
    def test_payment_status_code_update(self, mocked_account_payment_subtask):
        halt_date = timezone.localtime(timezone.now())
        resume_date = halt_date + timedelta(days=4)
        update_loan_halt_and_resume_date(self.grab_loan_data_1, halt_date, resume_date)
        self.grab_loan_data_1.refresh_from_db()

        account_halt_info = self.grab_loan_data_1.account_halt_info
        loaded_account_halt_info = account_halt_info[0]
        self.assertIsNotNone(self.grab_loan_data_1.account_halt_info)
        self.assertEqual(loaded_account_halt_info.get('account_halt_date'),
                         halt_date.strftime('%Y-%m-%d'))
        self.assertEqual(loaded_account_halt_info.get('account_resume_date'),
                         resume_date.strftime('%Y-%m-%d'))

        mocked_account_payment_subtask.return_value = None

        for payment in self.loan_1.payment_set.all():
            update_payment_status_subtask(payment.id)
            update_account_payment_status_subtask(payment.account_payment.id)
            payment.refresh_from_db()
            payment.account_payment.refresh_from_db()
            assert payment.payment_status_id == payment.account_payment.status_id
        mocked_account_payment_subtask.assert_called()


class TestGrabFileTransfer(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)

        self.product_lookup = ProductLookupFactory(product_line=self.product_line)
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)

        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                application=self.application,
                                loan_amount=10000000, loan_xid=1000003456,
                                product=self.product_lookup)
        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        self.grab_file_transfer_call_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_FILE_TRANSFER_CALL,
            is_active=True,
            parameters={"loan_per_file": 1000, "transaction_per_file": 25000,
                        "populate_loan_schedule": "21:30", "populate_daily_txn_schedule": "21:30"}
        )

    @mock.patch('juloserver.grab.tasks.logger.info')
    @mock.patch('juloserver.grab.tasks.send_grab_failed_deduction_slack.delay')
    def test_failed_grab_file_transfer_feature_setting_not_active(self, mock_slack_alert,
                                                                  mock_logger):
        self.grab_file_transfer_call_feature_setting.update_safely(is_active=False)
        cron_trigger_grab_file_transfer()
        mock_slack_alert.assert_called()
        mock_logger.assert_called_with({
            "action": "cron_trigger_grab_file_transfer",
            "message": "grab file transfer feature setting doesn't exist or inactive"
        })

    @mock.patch('juloserver.grab.tasks.logger.info')
    @mock.patch('juloserver.grab.tasks.send_grab_failed_deduction_slack.delay')
    def test_failed_grab_file_transfer_feature_setting_missing_all_parameters(self,
                                                                              mock_slack_alert,
                                                                              mock_logger):
        self.grab_file_transfer_call_feature_setting.update_safely(parameters={})
        cron_trigger_grab_file_transfer()
        mock_slack_alert.assert_called()
        mock_logger.assert_called_with({
            "action": "cron_trigger_grab_file_transfer",
            "message": "grab file transfer feature setting doesn't have parameters"
        })

    @mock.patch('juloserver.grab.tasks.logger.info')
    @mock.patch('juloserver.grab.tasks.send_grab_failed_deduction_slack.delay')
    def test_failed_grab_file_transfer_feature_setting_missing_required_parameters(self,
                                                                                   mock_slack_alert,
                                                                                   mock_logger):
        missing_key = 'loan_per_file'
        new_parameters = self.grab_file_transfer_call_feature_setting.parameters.copy()
        new_parameters.pop(missing_key)
        self.grab_file_transfer_call_feature_setting.update_safely(parameters=new_parameters)
        cron_trigger_grab_file_transfer()
        mock_slack_alert.assert_called()
        mock_logger.assert_called_with({
            "action": "cron_trigger_grab_file_transfer",
            "message": "grab file transfer feature setting parameter {} doesn't exist".format(
                missing_key)
        })

    @mock.patch('juloserver.grab.tasks.logger.info')
    @mock.patch('juloserver.grab.tasks.send_grab_failed_deduction_slack.delay')
    @mock.patch('juloserver.grab.tasks.cron_trigger_populate_grab_file_transfer.delay')
    def test_success_trigger_populate_data(self, mock_trigger_populate, mock_slack_alert,
                                           mock_logger):
        cron_trigger_grab_file_transfer()
        self.assertEqual(mock_trigger_populate.call_count, 2)
        mock_slack_alert.asset_not_called()
        mock_logger.assert_not_called()

    @mock.patch('juloserver.grab.services.services.upload_file_to_oss')
    @mock.patch('juloserver.grab.tasks.send_grab_failed_deduction_slack.delay')
    @mock.patch('juloserver.grab.tasks.populate_files_to_oss_task.delay')
    def test_success_populate_loan_data(self, mock_populate, mock_slack_alert,
                                        mock_upload_to_oss: MagicMock):
        limit = self.grab_file_transfer_call_feature_setting.parameters.get(FeatureSettingParameters.LOAN_PER_FILE)
        start_index = 0
        end_index = limit

        populate_active_loan_to_oss_main()
        mock_populate.assert_called_once()
        mock_slack_alert.assert_called_once()

        grab_async_audit = GrabAsyncAuditCron.objects.first()
        self.assertEqual(grab_async_audit.cron_status, GrabAsyncAuditCron.INITIATED)

        populate_files_to_oss_task(
            start_index,
            end_index,
            grab_async_audit.cron_file_name,
            grab_async_audit.cron_file_type
        )
        grab_async_audit.refresh_from_db()
        self.assertEqual(grab_async_audit.cron_status, GrabAsyncAuditCron.COMPLETED)

    @mock.patch('juloserver.grab.services.services.upload_file_to_oss')
    @mock.patch('juloserver.grab.tasks.send_grab_failed_deduction_slack.delay')
    @mock.patch('juloserver.grab.tasks.populate_files_to_oss_task.delay')
    def test_success_populate_daily_transaction_data(self, mock_populate, mock_slack_alert,
                                                     mock_upload_to_oss: MagicMock):
        today = timezone.localtime(timezone.now().replace(hour=19, minute=0, second=0, tzinfo=None))
        PaybackTransactionFactory.create_batch(3, payback_service='grab')
        payback_transactions = PaybackTransaction.objects.all()
        for payback_transaction in payback_transactions:
            payback_transaction.update_safely(cdate=today)
            AccountTransactionFactory(payback_transaction=payback_transaction)

        start_index = 0
        end_index = 999

        populate_daily_transaction_to_oss_main()
        mock_populate.assert_called_once()
        mock_slack_alert.assert_called_once()

        grab_async_audit = GrabAsyncAuditCron.objects.first()
        self.assertEqual(grab_async_audit.cron_status, GrabAsyncAuditCron.INITIATED)

        populate_files_to_oss_task(
            start_index,
            end_index,
            grab_async_audit.cron_file_name,
            grab_async_audit.cron_file_type
        )
        grab_async_audit.refresh_from_db()
        self.assertEqual(grab_async_audit.cron_status, GrabAsyncAuditCron.COMPLETED)

    @mock.patch('juloserver.grab.services.services.upload_file_to_oss')
    @mock.patch('juloserver.grab.tasks.send_grab_failed_deduction_slack.delay')
    @mock.patch('juloserver.grab.tasks.populate_files_to_oss_task.delay')
    def test_success_update_limit_loan_data_per_file(self, mock_populate, mock_slack_alert,
                                                     mock_upload_to_oss: MagicMock):
        LoanFactory.create_batch(2, loan_amount=10000000, loan_duration=12,
                                 product=self.product_lookup)
        start_index = 0
        custom_limit = 1
        end_index = start_index + custom_limit
        updated_key = 'loan_per_file'
        new_parameters = self.grab_file_transfer_call_feature_setting.parameters.copy()
        new_parameters[updated_key] = custom_limit
        self.grab_file_transfer_call_feature_setting.update_safely(parameters=new_parameters)

        populate_active_loan_to_oss_main()
        self.assertEqual(mock_populate.call_count, 3)
        mock_slack_alert.assert_called_once()

        grab_async_audit = GrabAsyncAuditCron.objects.all()
        self.assertEqual(grab_async_audit.count(), 3)
        for element in grab_async_audit:
            self.assertEqual(element.cron_status, GrabAsyncAuditCron.INITIATED)
            populate_files_to_oss_task(
                start_index,
                end_index,
                element.cron_file_name
            )
            start_index += 1
            end_index += start_index + custom_limit
            element.refresh_from_db()
            self.assertEqual(element.cron_status, GrabAsyncAuditCron.COMPLETED)

    @mock.patch('juloserver.grab.services.services.upload_file_to_oss')
    @mock.patch('juloserver.grab.tasks.send_grab_failed_deduction_slack.delay')
    @mock.patch('juloserver.grab.tasks.populate_files_to_oss_task.delay')
    def test_success_update_limit_daily_transaction_data_per_file(self, mock_populate,
                                                                  mock_slack_alert,
                                                                  mock_upload_to_oss: MagicMock):
        today = timezone.localtime(timezone.now().replace(hour=19, minute=0, second=0, tzinfo=None))
        PaybackTransactionFactory.create_batch(3, payback_service='grab')
        payback_transactions = PaybackTransaction.objects.all()
        for payback_transaction in payback_transactions:
            payback_transaction.update_safely(cdate=today)
            AccountTransactionFactory(payback_transaction=payback_transaction)

        start_index = 0
        custom_limit = 1
        end_index = start_index + custom_limit
        updated_key = 'transaction_per_file'
        new_parameters = self.grab_file_transfer_call_feature_setting.parameters.copy()
        new_parameters[updated_key] = custom_limit
        self.grab_file_transfer_call_feature_setting.update_safely(parameters=new_parameters)

        populate_daily_transaction_to_oss_main()
        self.assertEqual(mock_populate.call_count, 3)
        mock_slack_alert.assert_called_once()

        grab_async_audit = GrabAsyncAuditCron.objects.all()
        self.assertEqual(grab_async_audit.count(), 3)
        for element in grab_async_audit:
            self.assertEqual(element.cron_status, GrabAsyncAuditCron.INITIATED)
            populate_files_to_oss_task(
                start_index,
                end_index,
                element.cron_file_name,
                element.cron_file_type
            )
            start_index += 1
            end_index += start_index + custom_limit
            element.refresh_from_db()
            self.assertEqual(element.cron_status, GrabAsyncAuditCron.COMPLETED)


class TestMoveAuthTasks(TestCase):
    def setUp(self) -> None:
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)

        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line)

        self.customer = CustomerFactory()
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(customer=self.customer,
                                      account_lookup=self.account_lookup)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account)

    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_success(self, mocked_auth_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow
        )

        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 200
        mocked_auth_response.content = json.dumps({
            "msg_id": "e3c936af0f3648d3a3417dd89110abe9",
            "success": True, "version": "1.0"})
        mocked_auth_call.return_value = mocked_auth_response
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        ).exists())

    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_no_response(self, mocked_auth_call, mocked_retry):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()
        GrabLoanDataFactory(loan=loan)
        mocked_auth_response = None
        mocked_auth_call.return_value = mocked_auth_response
        mocked_retry.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertFalse(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        ).exists())
        mocked_retry.assert_called()

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4001(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()
        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48750", "success": False,
            "error": {"code": "4001", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_4001
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4002(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow,)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "4002", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_4002
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_6001(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow,)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "6001", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_API_ERROR
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4xx_no_error_code(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow,)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason="Grab API Failure"
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4006(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "4006", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_4006
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4008(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "4008", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_4008
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4011(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "4011", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_4011
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4014(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "4014", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_4014
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4015(
            self, mocked_auth_call, mocked_slack_call):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "4015", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_4015
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.tasks.trigger_application_creation_grab_api.apply_async')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_4025(
            self, mocked_auth_call, mocked_slack_call, mocked_app_trigger):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 400
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "4025", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_app_trigger.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=400
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_4025
        ))
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)
        mocked_app_trigger.assert_called()

    @mock.patch('juloserver.grab.tasks.send_grab_api_timeout_alert_slack.delay')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_5001_last_attempt(
            self, mocked_auth_call, mocked_slack_call, mocked_alert):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "5001", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_alert.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=500
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_5001
        ).exists())
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.tasks.send_grab_api_timeout_alert_slack.delay')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_5xx_last_attempt(
            self, mocked_auth_call, mocked_slack_call, mocked_alert):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_alert.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=500
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason="Grab API Failure"
        ).exists())
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.tasks.send_grab_api_timeout_alert_slack.delay')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_5002_last_attempt(
            self, mocked_auth_call, mocked_slack_call, mocked_alert):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "5002", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_auth_call.return_value.request.url = "URL"

        mocked_auth_call.request = mock.MagicMock()
        mocked_slack_call.return_value = None
        mocked_alert.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=500
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_5002
        ).exists())
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.tasks.send_grab_api_timeout_alert_slack.delay')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_no_response_last_attempt(
            self, mocked_auth_call, mocked_slack_call, mocked_alert):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_call.return_value = None
        mocked_slack_call.return_value = None
        mocked_alert.return_value = None
        with self.assertRaises(GrabLogicException):
            trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason="Grab API Error"
        ).exists())
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.tasks.send_grab_api_timeout_alert_slack.delay')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_5002_last_attempt(
            self, mocked_auth_call, mocked_slack_call, mocked_alert):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "5002", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_auth_call.return_value.request.url = "URL"

        mocked_auth_call.request = mock.MagicMock()
        mocked_slack_call.return_value = None
        mocked_alert.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=500
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_5002
        ).exists())
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.tasks.send_grab_api_timeout_alert_slack.delay')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_8002_last_attempt(
            self, mocked_auth_call, mocked_slack_call, mocked_alert):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "8002", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_auth_call.return_value.request.url = "URL"

        mocked_auth_call.request = mock.MagicMock()
        mocked_slack_call.return_value = None
        mocked_alert.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=500
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_8002
        ).exists())
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.tasks.send_grab_api_timeout_alert_slack.delay')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_application_creation_missing_last_attempt(
            self, mocked_auth_call, mocked_slack_call, mocked_alert):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "5002", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_auth_call.return_value.request.url = "URL"

        mocked_auth_call.request = mock.MagicMock()
        mocked_slack_call.return_value = None
        mocked_alert.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
        self.assertTrue(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=500
        ).exists())
        self.assertTrue(LoanHistory.objects.filter(
            loan=loan,
            status_new=219,
            change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_5002
        ).exists())
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_5002_retry(
            self, mocked_auth_call, mocked_slack_call, mocked_retry):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "5002", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_retry.return_value = None
        for i in list(range(6)):
            trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=i)
            self.assertTrue(GrabAPILog.objects.filter(
                loan_id=loan.id,
                query_params=GrabPaths.LOAN_CREATION,
                http_status_code=500
            ).exists())
            mocked_retry.assert_called_with((
                loan.id, i + 1), eta=mock.ANY)
            mocked_retry.reset_mock()

    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_8002_retry(
            self, mocked_auth_call, mocked_slack_call, mocked_retry):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "8002", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_retry.return_value = None
        for i in list(range(6)):
            trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=i)
            self.assertTrue(GrabAPILog.objects.filter(
                loan_id=loan.id,
                query_params=GrabPaths.LOAN_CREATION,
                http_status_code=500
            ).exists())
            mocked_retry.assert_called_with((
                loan.id, i + 1), eta=mock.ANY)
            mocked_retry.reset_mock()


    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_5xx_retry(
            self, mocked_auth_call, mocked_slack_call, mocked_retry):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_retry.return_value = None
        for i in list(range(6)):
            trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=i)
            self.assertTrue(GrabAPILog.objects.filter(
                loan_id=loan.id,
                query_params=GrabPaths.LOAN_CREATION,
                http_status_code=500
            ).exists())
            mocked_retry.assert_called_with((
                loan.id, i + 1), eta=mock.ANY)
            mocked_retry.reset_mock()

    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_no_response_retry(
            self, mocked_auth_call, mocked_slack_call, mocked_retry):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_call.return_value = None
        mocked_slack_call.return_value = None
        mocked_retry.return_value = None
        for i in list(range(6)):
            trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=i)
            mocked_retry.assert_called_with((
                loan.id, i + 1), eta=mock.ANY)
            mocked_retry.reset_mock()

    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=MockedResponse)
    def test_trigger_auth_call_for_loan_creation_error_5001_retry(
            self, mocked_auth_call, mocked_slack_call, mocked_retry):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=MockedResponse)
        mocked_auth_response.status_code = 500
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "5001", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_retry.return_value = None
        for i in list(range(6)):
            trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=i)
            self.assertTrue(GrabAPILog.objects.filter(
                loan_id=loan.id,
                query_params=GrabPaths.LOAN_CREATION,
                http_status_code=500
            ).exists())
            mocked_retry.assert_called_with((
                loan.id, i + 1), eta=mock.ANY)
            mocked_retry.reset_mock()

    @mock.patch("juloserver.grab.clients.clients.GrabClient.submit_loan_creation")
    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_failed_not_reached_180(
        self,
        mocked_auth_call,
        mocked_retry,
        mock_submit_loan_creation,
    ):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()
        mocked_retry.return_value = None
        GrabLoanDataFactory(loan=loan)
        mock_responses = [
            {
                "status_code": None,
                "response": None
            },
            {
                "status_code": 400,
                "response": {
                    "msg_id": "9e8c2ddcfb2f465586f21633fcc48750", "success": False,
                    "error": {"code": "4001", "message": "Invalid Request"}
                }
            },
            {
                "status_code": 400,
                "response": {
                    "msg_id": "9e8c2ddcfb2f465586f21633fcc48750", "success": False,
                    "error": {"message": "Invalid Request"}
                }
            },
            {
                "status_code": 500,
                "response": {
                    "msg_id": "9e8c2ddcfb2f465586f21633fcc48750", "success": False,
                    "error": {"code": "5001", "message": "Invalid Request"}
                }
            }
        ]
        for resp in mock_responses:
            status_code = resp.get("status_code", None)
            if status_code is None:
                mocked_auth_response = None
                mocked_auth_call.return_value = mocked_auth_response
                mock_submit_loan_creation.return_value = mocked_auth_response
            else:
                mocked_auth_response = requests.Response()
                mocked_auth_response.status_code = status_code
                mocked_auth_response._content = json.dumps(resp.get("response"))
                if status_code == 500:
                    mocked_auth_response.request = requests.Request()
                mocked_auth_call.return_value = mocked_auth_response
                mock_submit_loan_creation.return_value = mocked_auth_response

            if status_code is None:
                with self.assertRaises(GrabLogicException):
                    trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
                    self.assertFalse(GrabAPILog.objects.filter(
                        loan_id=loan.id,
                        query_params=GrabPaths.LOAN_CREATION,
                        http_status_code=200
                    ).exists())
                    mocked_retry.assert_called()
            else:
                trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
                self.assertFalse(GrabAPILog.objects.filter(
                    loan_id=loan.id,
                    query_params=GrabPaths.LOAN_CREATION,
                    http_status_code=200
                ).exists())
                mocked_retry.assert_not_called()
            loan_history = LoanHistory.objects.filter(loan_id=loan.id).last()
            self.assertNotEqual(
                loan_history.change_reason,
                GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE
            )
            loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
            loan.save()
            mocked_auth_call.reset_mock()
            mock_submit_loan_creation.reset_mock()

    @mock.patch("juloserver.grab.tasks.is_application_reached_180_before")
    @mock.patch("juloserver.grab.clients.clients.GrabClient.submit_loan_creation")
    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_failed_reached_180(
        self,
        mocked_auth_call,
        mocked_retry,
        mock_submit_loan_creation,
        mock_reached_180
    ):
        mock_reached_180.return_value  = True
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()
        mocked_retry.return_value = None
        GrabLoanDataFactory(loan=loan)
        mock_responses = [
            {
                "status_code": None,
                "response": None
            },
            {
                "status_code": 400,
                "response": {
                    "msg_id": "9e8c2ddcfb2f465586f21633fcc48750", "success": False,
                    "error": {"code": "4001", "message": "Invalid Request"}
                }
            },
            {
                "status_code": 400,
                "response": {
                    "msg_id": "9e8c2ddcfb2f465586f21633fcc48750", "success": False,
                    "error": {"message": "Invalid Request"}
                }
            },
            {
                "status_code": 500,
                "response": {
                    "msg_id": "9e8c2ddcfb2f465586f21633fcc48750", "success": False,
                    "error": {"code": "5001", "message": "Invalid Request"}
                }
            }
        ]
        for resp in mock_responses:
            status_code = resp.get("status_code", None)
            if status_code is None:
                mocked_auth_response = None
                mocked_auth_call.return_value = mocked_auth_response
                mock_submit_loan_creation.return_value = mocked_auth_response
            else:
                mocked_auth_response = requests.Response()
                mocked_auth_response.status_code = status_code
                mocked_auth_response._content = json.dumps(resp.get("response"))
                if status_code == 500:
                    mocked_auth_response.request = requests.Request()
                mocked_auth_call.return_value = mocked_auth_response
                mock_submit_loan_creation.return_value = mocked_auth_response

            if status_code is None:
                with self.assertRaises(GrabLogicException):
                    trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
                    self.assertFalse(GrabAPILog.objects.filter(
                        loan_id=loan.id,
                        query_params=GrabPaths.LOAN_CREATION,
                        http_status_code=200
                    ).exists())
                    mocked_retry.assert_called()
            else:
                trigger_auth_call_for_loan_creation(loan_id=loan.id, retry_attempt=7)
                self.assertFalse(GrabAPILog.objects.filter(
                    loan_id=loan.id,
                    query_params=GrabPaths.LOAN_CREATION,
                    http_status_code=200
                ).exists())
                mocked_retry.assert_not_called()
            loan_history = LoanHistory.objects.filter(loan_id=loan.id).last()
            self.assertEqual(
                loan_history.change_reason,
                GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE
            )
            loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
            loan.save()
            mocked_auth_call.reset_mock()
            mock_submit_loan_creation.reset_mock()

    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_application_190_missing(
            self, mocked_auth_call, mocked_slack_call, mocked_retry):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_DENIED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 200
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "5001", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_retry.return_value = None
        with self.assertRaises(GrabLogicException):
            trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertFalse(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        ).exists())

    @mock.patch('juloserver.grab.tasks.trigger_application_creation_grab_api.apply_async')
    @mock.patch('juloserver.grab.tasks.trigger_auth_call_for_loan_creation.apply_async')
    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_application_log_missing(
            self, mocked_auth_call, mocked_slack_call, mocked_retry, mocked_app_creation):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow)
        GrabLoanDataFactory(loan=loan)
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 200
        mocked_auth_response.content = json.dumps({
            "msg_id": "9e8c2ddcfb2f465586f21633fcc48751", "success": False,
            "error": {"code": "5001", "message": "Invalid Request"}})
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        mocked_retry.return_value = None
        mocked_app_creation.return_value = None
        with self.assertRaises(GrabLogicException):
            trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertFalse(GrabAPILog.objects.filter(
            loan_id=loan.id,
            query_params=GrabPaths.LOAN_CREATION,
            http_status_code=200
        ).exists())
        mocked_retry.assery_called()
        mocked_app_creation.assert_called()

    @mock.patch("juloserver.grab.tasks.is_application_reached_180_before")
    @mock.patch("juloserver.grab.tasks.send_sms_to_dax_pass_3_max_creditors")
    @mock.patch("juloserver.grab.tasks.GrabClient.submit_loan_creation")
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_success_reached_180_before(
        self, mocked_auth_call, mock_submit_loan_creation, mock_send_sms,
        mock_is_application_reached_180_before
        ):
        mock_response = requests.Response()
        mock_response.status_code = HTTPStatus.OK
        mock_submit_loan_creation.return_value = mock_response
        mock_is_application_reached_180_before.return_value = True

        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow
        )

        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 200
        mocked_auth_response.content = json.dumps({
            "msg_id": "e3c936af0f3648d3a3417dd89110abe9",
            "success": True, "version": "1.0"})
        mocked_auth_call.return_value = mocked_auth_response
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        mock_send_sms.assert_called()

    @mock.patch("juloserver.grab.utils.is_application_reached_180_before")
    @mock.patch("juloserver.grab.utils.send_sms_to_dax_pass_3_max_creditors")
    @mock.patch("juloserver.grab.tasks.GrabClient.submit_loan_creation")
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_success_not_reached_180_before(
        self, mocked_auth_call, mock_submit_loan_creation, mock_send_sms,
        mock_is_application_reached_180_before
        ):
        mock_response = requests.Response()
        mock_response.status_code = HTTPStatus.OK
        mock_submit_loan_creation.return_value = mock_response
        mock_is_application_reached_180_before.return_value = False

        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(account=account, loan_status=loan_status,
                           name_bank_validation_id=name_bank_validation.id,
                           customer=customer)
        application = ApplicationFactory(
            customer=customer, account=account, workflow=self.workflow
        )

        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 200
        mocked_auth_response.content = json.dumps({
            "msg_id": "e3c936af0f3648d3a3417dd89110abe9",
            "success": True, "version": "1.0"})
        mocked_auth_call.return_value = mocked_auth_response
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        mock_send_sms.assert_not_called()

    @mock.patch('juloserver.grab.clients.clients.send_message_normal_format')
    @mock.patch('requests.post', spec=requests.Response)
    def test_trigger_auth_call_for_loan_creation_error_422_CRS_failed_validation(
        self, mocked_auth_call, mocked_slack_call
    ):
        customer = CustomerFactory()
        GrabCustomerDataFactory(customer=customer)
        account = AccountFactory(customer=customer, account_lookup=self.account_lookup)
        AccountLimitFactory(account=account)
        loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        name_bank_validation = NameBankValidationFactory(bank_code='AUTHCALL')
        loan = LoanFactory(
            account=account,
            loan_status=loan_status,
            name_bank_validation_id=name_bank_validation.id,
            customer=customer,
        )
        application = ApplicationFactory(
            customer=customer,
            account=account,
            workflow=self.workflow,
        )
        GrabLoanDataFactory(loan=loan)
        GrabAPILogFactory(
            customer_id=loan.customer.id,
            application_id=application.id,
            query_params=GrabPaths.APPLICATION_CREATION,
            http_status_code=200,
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        application.save()

        mocked_auth_response = mock.MagicMock(spec=requests.Response)
        mocked_auth_response.status_code = 422
        mocked_auth_response.content = json.dumps(
            {
                "msg_id": "afe90e0711fc41f88193e857ea909bbf",
                "success": False,
                "error": {"code": "5022", "message": "PFO Error: ErrorCrsFailedValidation"},
            }
        )
        mocked_auth_call.return_value = mocked_auth_response
        mocked_slack_call.return_value = None
        trigger_auth_call_for_loan_creation(loan_id=loan.id)
        self.assertTrue(
            GrabAPILog.objects.filter(
                loan_id=loan.id, query_params=GrabPaths.LOAN_CREATION, http_status_code=422
            ).exists()
        )
        self.assertTrue(
            LoanHistory.objects.filter(
                loan=loan,
                status_new=219,
                change_reason=GrabErrorMessage.AUTH_ERROR_MESSAGE_API_ERROR,
            )
        )
        loan.refresh_from_db()
        self.assertEqual(loan.loan_status_id, 219)

class TestClearGrabLoanOffer(TestCase):

    @freeze_time("2024-03-20")
    def setUp(self):
        self.n_grab_loan_offer = 10
        self.grab_loans_offer_id = []
        for i in range(self.n_grab_loan_offer):
            loan_offer = GrabLoanOfferFactory()
            self.grab_loans_offer_id.append(loan_offer.id)

        current_month = timezone.now().month
        if current_month == 1:
            last_month = timezone.now().replace(month=12, year=timezone.now().year - 1)
        else:
            last_month = timezone.now().replace(month=current_month-1)

        with connection.cursor() as cursor:
            update_query = "update {} set udate='{}' where grab_loan_offer_id in ({})".format(
                GrabLoanOffer._meta.db_table,
                last_month.strftime("%Y-%m-%d"),
                ', '.join([str(i) for i in self.grab_loans_offer_id])
            )
            cursor.execute(update_query)

    def test_clear_grab_loan_offer_data(self):
        self.assertEqual(
            GrabLoanOffer.objects.filter(id__in=self.grab_loans_offer_id).count(),
            self.n_grab_loan_offer
        )
        n_deleted = clear_grab_loan_offer_data()
        self.assertEqual(
            GrabLoanOffer.objects.filter(id__in=self.grab_loans_offer_id).count(),
            self.n_grab_loan_offer - n_deleted
        )


class TestGrabAutoApplyLoan(TestCase):
    @mock.patch('juloserver.julo.models.XidLookup.get_new_xid')
    def setUp(self, mock_get_new_xid):
        mock_get_new_xid.return_value = "121212"
        self.mobile_phone = '6281245789865'
        self.token = '906d4e43a3446cecb4841cf41c10c91c9610c8a5519437c913ab9144b71054f915752a69d' \
                     '0220619666ac3fc1f27f7b4934a6a4b2baa2f85b6533c663ca6d98f976328625f756e79a7cc' \
                     '543770b6945c1a5aaafd066ceed10204bf85c07c2fae81118d990d7c5fafcb98f8708f540d6d' \
                     '8971764c12b9fb912c7d1c3b1db1f931'
        self.hashed_phone_number = '7358b08205b13f3ec8967ea7f1c331a40cefdeda0cef8bf8b9ca7acefd9564a2'
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(phone=self.mobile_phone)
        self.grab_customer_data = GrabCustomerDataFactory(
            phone_number=self.mobile_phone,
            customer=self.customer,
            grab_validation_status=True,
            otp_status='VERIFIED',
            token=self.token,
            hashed_phone_number=self.hashed_phone_number
        )
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.account = AccountFactory(
            account_lookup=self.account_lookup,
            customer=self.customer
        )
        self.account_limit = AccountLimitFactory(account=self.account)

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.name_bank_validation = NameBankValidationFactory(bank_code='HELLOQWE')
        self.bank = BankFactory(xfers_bank_code='HELLOQWE')
        self.application_status_code = StatusLookupFactory(code=190)
        self.partner = PartnerFactory(name="grab")
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.product_line,
            application_status=self.application_status_code,
            mobile_phone_1=self.mobile_phone,
            bank_name='bank_test',
            name_in_bank='name_in_bank'
        )
        self.program_id = 'test-program-id'
        self.loan_amount = 1000000
        self.tenure = 30

    @mock.patch('requests.post')
    @mock.patch('juloserver.grab.services.services.GrabLoanService.parse_loan_offer')
    @mock.patch('juloserver.grab.tasks.GrabClient')
    @mock.patch('juloserver.grab.tasks.grab_auto_apply_loan_task_subtask.apply_async')
    def test_grab_auto_apply_loan_task_no_grab_loan_offer_data(
        self,
        mock_grab_auto_apply_loan_task_subtask,
        mock_client,
        mock_parse_loan_offer,
        mock_request,
    ):
        mock_loan_creation_request_response = {"success": True, "data": None, "errors": []}
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = mock_loan_creation_request_response
        mock_client.get_loan_offer.return_value = {
            "msg_id": "7eab2027d4be41ef86a98ff60c542c9d",
            "success": True,
            "version": "1",
            "data": [
                {
                    "program_id": "DAX_ID_CL02",
                    "max_loan_amount": "1000000",
                    "min_loan_amount": "500000",
                    "weekly_installment_amount": "1000000",
                    "loan_duration": 180,
                    "min_tenure": 60,
                    "tenure_interval": 30,
                    "frequency_type": "DAILY",
                    "fee_type": "FLAT",
                    "fee_value": "40000",
                    "interest_type": "SIMPLE_INTEREST",
                    "interest_value": "3",
                    "penalty_type": "FLAT",
                    "penalty_value": "2000000",
                }
            ],
        }
        grab_auto_apply_loan_task(self.customer.id, self.program_id, self.application.id)
        mock_grab_auto_apply_loan_task_subtask.assert_called_with(
            args=(self.customer.id, self.program_id, self.application.id)
        )
        grab_auto_apply_loan_task_subtask(self.customer.id, self.program_id, self.application.id)
        mock_request.assert_called_with(
            url="{}/api/partner/grab/loan-creation-request".format(settings.GRAB_SERVICE_BASE_URL),
            headers={'Authorization': 'Token ' + self.customer.user.auth_expiry_token.key},
            json={
                'program_id': 'test-program-id',
                'application_id': self.application.id,
            },
        )

    @mock.patch('requests.post')
    @mock.patch('juloserver.grab.services.services.GrabLoanService.get_grab_loan_offer_data')
    @mock.patch('juloserver.grab.services.services.GrabLoanService.parse_loan_offer')
    @mock.patch('juloserver.grab.tasks.GrabClient')
    @mock.patch('juloserver.grab.tasks.grab_auto_apply_loan_task_subtask.apply_async')
    def test_grab_auto_apply_loan_task_have_grab_loan_offer_data(
        self,
        mock_grab_auto_apply_loan_task_subtask,
        mock_client,
        mock_parse_loan_offer,
        mock_get_grab_loan_offer_data,
        mock_request,
    ):
        mock_get_grab_loan_offer_data = {"message": "hello world!"}
        mock_loan_creation_request_response = {"success": True, "data": None, "errors": []}
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = mock_loan_creation_request_response
        grab_auto_apply_loan_task(self.customer.id, self.program_id, self.application.id)
        mock_client.assert_not_called()
        mock_parse_loan_offer.assert_not_called()
        mock_grab_auto_apply_loan_task_subtask.assert_called_with(
            args=(self.customer.id, self.program_id, self.application.id)
        )
        grab_auto_apply_loan_task_subtask(self.customer.id, self.program_id, self.application.id)
        mock_request.assert_called_with(
            url="{}/api/partner/grab/loan-creation-request".format(settings.GRAB_SERVICE_BASE_URL),
            headers={'Authorization': 'Token ' + self.customer.user.auth_expiry_token.key},
            json={
                'program_id': 'test-program-id',
                'application_id': self.application.id,
            },
        )


class TestUpdatePaymentStatusCode(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.grab_customer_data = GrabCustomerDataFactory(customer=self.customer)
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=GRAB_ACCOUNT_LOOKUP_NAME)
        self.account = AccountFactory(customer=self.customer,
                                      account_lookup=self.account_lookup)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account)

    def test_payment_due_amount_zero(self):
        loan = LoanFactory(customer=self.customer, account=self.account)
        loan.loan_status = StatusLookupFactory(status_code=220)
        loan.save()
        payments = Payment.objects.filter(loan=loan)
        payment_set = set(payments)
        for payment in payment_set:
            payment.due_amount = 0
            payment.payment_status = StatusLookupFactory(status_code=310)
            payment.is_restructured = False
            payment.save()
        update_status_for_paid_off_payment_grab(loan.id)
        loan = Loan.objects.filter(id=loan.id).last()
        self.assertEqual(loan.loan_status_id, LoanStatusCodes.PAID_OFF)

    def test_payment_due_amount_non_zero(self):
        loan = LoanFactory(customer=self.customer, account=self.account)
        loan.loan_status = StatusLookupFactory(status_code=220)
        loan.save()
        payments = Payment.objects.filter(loan=loan)
        payment_set = set(payments)
        for payment in payment_set:
            payment.due_amount = 100
            payment.payment_status = StatusLookupFactory(status_code=310)
            payment.is_restructured = False
            payment.save()
        update_status_for_paid_off_payment_grab(loan.id)
        loan = Loan.objects.filter(id=loan.id).last()
        self.assertNotEqual(loan.loan_status_id, LoanStatusCodes.PAID_OFF)

    def test_payment_due_amount_update_payment(self):
        loan = LoanFactory(customer=self.customer, account=self.account)
        loan.loan_status = StatusLookupFactory(status_code=220)
        loan.save()
        payments = Payment.objects.filter(loan=loan)
        payment_set = set(payments)
        for payment in payment_set:
            payment.due_amount = 100
            payment.payment_status = StatusLookupFactory(status_code=310)
            payment.is_restructured = False
            payment.save()

        payment_zero = list(payment_set)[0]
        payment_zero.due_amount = 0
        payment_zero.payment_status = StatusLookupFactory(status_code=310)
        payment_zero.save()

        update_status_for_paid_off_payment_grab(loan.id)
        payment_zero = Payment.objects.filter(id=payment_zero.id).last()
        loan = Loan.objects.filter(id=loan.id).last()
        self.assertTrue(payment_zero.payment_status_id >= PaymentStatusCodes.PAID_ON_TIME)
        self.assertNotEqual(loan.loan_status_id, 250)

    def test_payment_due_amount_update_loan(self):
        loan = LoanFactory(customer=self.customer, account=self.account)
        GrabLoanDataFactory(loan=loan)
        loan.loan_status = StatusLookupFactory(status_code=220)
        loan.save()
        payments = Payment.objects.filter(loan=loan).order_by('due_date')
        payment_set = list(payments)
        for idx, payment in enumerate(payment_set):
            payment.due_amount = 100
            payment.payment_status = StatusLookupFactory(status_code=310)
            payment.is_restructured = False
            payment.due_date = timezone.localtime(timezone.now() - timedelta(days=(idx + 90)))
            payment.save()
            update_payment_status_subtask(payment.id)
            payment = Payment.objects.filter(id=payment.id).last()

        update_status_for_paid_off_payment_grab(loan.id)
        loan = Loan.objects.filter(id=loan.id).last()
        self.assertTrue(loan.loan_status_id >= LoanStatusCodes.LOAN_90DPD)
        self.assertNotEqual(loan.loan_status_id, LoanStatusCodes.PAID_OFF)

    def test_task_update_payment_status_to_paid_off(self):
        loan = LoanFactory(customer=self.customer, account=self.account)
        loan.loan_status = StatusLookupFactory(status_code=220)
        loan.save()
        payments = Payment.objects.filter(loan=loan)
        payment_set = set(payments)
        for payment in payment_set:
            payment.due_amount = 0
            payment.payment_status = StatusLookupFactory(status_code=310)
            payment.is_restructured = False
            payment.save()
        data = GrabSqlUtility.run_sql_query_for_paid_off_payment_invalid_status(
            GRAB_ACCOUNT_LOOKUP_NAME)
        loan_ids_set = set()
        for (loan_id,) in data:
            loan_ids_set.add(loan_id)
        self.assertIn(loan.id, loan_ids_set)


class TestGrabAppStatusChangesSMS(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account,
            mobile_phone_1='6281245789865'
        )
        now = timezone.localtime(timezone.now())
        self.product_lookup = ProductLookupFactory(product_line=self.product_line)
        self.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                application=self.application,
                                loan_amount=10000000, loan_xid=1000003456,
                                product=self.product_lookup,
                                loan_status=self.loan_status)

        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=ApplicationStatusCodes.FORM_CREATED)

    @mock.patch(
        'juloserver.grab.tasks.'
        'send_grab_sms_based_on_template_code')
    @mock.patch(
        'juloserver.grab.tasks.'
        'send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task1.delay')
    def test_send_sms_to_user_at_100_and_will_expire_in_1_day(
            self,
            mock_send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task,
            mock_send_grab_sms_based_on_template_code
    ):

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL)

        self.application.save()
        send_sms_to_user_at_100_and_will_expire_in_1_day()
        self.assertEqual(mock_send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task.called, False)

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)

        self.application.save()
        send_sms_to_user_at_100_and_will_expire_in_1_day()
        self.assertEqual(mock_send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task.called, True)

        SmsHistoryFactory(application=self.application,
                          template_code=GrabSMSTemplateCodes.GRAB_SMS_APP_100_EXPIRE_IN_ONE_DAY)
        send_sms_to_user_at_100_and_will_expire_in_1_day()
        self.assertEqual(mock_send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task.called, True)
        mock_send_grab_sms_based_on_template_code.assert_not_called()


    @mock.patch(
        'juloserver.grab.tasks.'
        'send_grab_sms_based_on_template_code')
    @mock.patch(
        'juloserver.grab.tasks.'
        'send_sms_to_user_at_131_for_24_hour_sub_task1.delay')
    def test_send_sms_to_user_at_131_for_24_hour(
            self,
            mock_send_sms_to_user_at_131_for_24_hour_sub_task,
            mock_send_grab_sms_based_on_template_code
    ):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL)

        self.application.save()
        send_sms_to_user_at_131_for_24_hour()
        self.assertEqual(mock_send_sms_to_user_at_131_for_24_hour_sub_task.called, False)

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED)

        self.application.save()
        send_sms_to_user_at_131_for_24_hour()
        self.assertEqual(mock_send_sms_to_user_at_131_for_24_hour_sub_task.called, True)
        SmsHistoryFactory(application=self.application,
                          template_code=GrabSMSTemplateCodes.GRAB_SMS_APP_AT_131_FOR_24_HOUR)
        send_sms_to_user_at_131_for_24_hour()
        self.assertEqual(mock_send_sms_to_user_at_131_for_24_hour_sub_task.called, True)
        mock_send_grab_sms_based_on_template_code.assert_not_called()


    @mock.patch(
        'juloserver.grab.tasks.get_julo_sms_client')
    @mock.patch(
        'juloserver.grab.tasks.'
        'send_grab_sms_based_on_template_code')
    def test_trigger_sms_to_submit_digisign(
            self,
            mock_send_grab_sms_based_on_template_code,
            mock_get_julo_sms_client,
    ):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED)

        self.application.save()
        data = trigger_sms_to_submit_digisign(self.loan.id)
        self.assertIsNone(data)

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)

        self.application.save()
        data = trigger_sms_to_submit_digisign(self.loan.id)
        self.assertIsNone(data)
        mock_send_grab_sms_based_on_template_code.assert_called()

        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=ApplicationStatusCodes.LOC_APPROVED,
            status_old=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
        )
        data = trigger_sms_to_submit_digisign(self.loan.id)
        mock_send_grab_sms_based_on_template_code.assert_called()


class TestMarkLoanExpirationGrab(TestCase):
    def setUp(self):
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=GRAB_ACCOUNT_LOOKUP_NAME)
        self.customer = CustomerFactory()
        self.account = AccountFactory(account_lookup=self.account_lookup, customer=self.customer)
        self.application = ApplicationFactory(account=self.account)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory(product_line=self.product_line)
        self.loan = LoanFactory(
            account=self.account,
            sphp_exp_date=date.today() + timedelta(days=3),
            product=self.product_lookup
        )

    @mock.patch('juloserver.grab.tasks.mark_sphp_expired_grab_subtask.delay')
    def test_trigger_mark_grab_expiration_status_210(self, mocked_subtask):
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.save()
        mark_sphp_expired_grab()
        mocked_subtask.assert_called_with([self.loan.id])

    @mock.patch('juloserver.grab.tasks.mark_sphp_expired_grab_subtask.delay')
    def test_trigger_mark_grab_expiration_status_217(self, mocked_subtask):
        self.loan.loan_status = StatusLookupFactory(status_code=217)
        self.loan.save()
        mark_sphp_expired_grab()
        mocked_subtask.assert_not_called()

    @mock.patch('juloserver.grab.tasks.mark_sphp_expired_grab_subtask.delay')
    def test_trigger_mark_grab_expiration_status_220(self, mocked_subtask):
        self.loan.loan_status = StatusLookupFactory(status_code=220)
        self.loan.save()
        mark_sphp_expired_grab()
        mocked_subtask.assert_not_called()

    def test_mark_trigger_mark_grab_subtask_status_210_expired(self):
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.sphp_exp_date = timezone.localtime(timezone.now() - timedelta(days=1))
        self.loan.save()
        mark_sphp_expired_grab_subtask([self.loan.id])
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.SPHP_EXPIRED)

    def test_mark_trigger_mark_grab_subtask_status_210_not_expired(self):
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.sphp_exp_date = timezone.localtime(timezone.now() + timedelta(days=1))
        self.loan.save()
        mark_sphp_expired_grab_subtask([self.loan.id])
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.INACTIVE)

    def test_mark_trigger_mark_grab_subtask_status_220_expired(self):
        self.loan.loan_status = StatusLookupFactory(status_code=220)
        self.loan.sphp_exp_date = timezone.localtime(timezone.now() - timedelta(days=1))
        self.loan.save()
        mark_sphp_expired_grab_subtask([self.loan.id])
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.CURRENT)

    @mock.patch('juloserver.julo.tasks.mark_sphp_expired_julo_one_subtask.delay')
    def test_triggering_main_julo_one_function_exclude_grab(self, mocked_subtask):
        from juloserver.julo.tasks import mark_sphp_expired_julo_one
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.save()
        mark_sphp_expired_julo_one()
        mocked_subtask.assert_not_called()

    @mock.patch('juloserver.julo.tasks.mark_sphp_expired_julo_one_subtask.delay')
    def test_triggering_main_julo_one_function_non_grab_loan(self, mocked_subtask):
        from juloserver.julo.tasks import mark_sphp_expired_julo_one
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        product_lookup = ProductLookupFactory(product_line=product_line)
        self.loan.product = product_lookup
        self.loan.save()
        mark_sphp_expired_julo_one()
        mocked_subtask.assert_called_with(self.loan.id)

    @mock.patch('juloserver.julo.tasks.mark_sphp_expired_julo_one_subtask.delay')
    def test_triggering_main_julo_one_exclude_jfinancing(self, mocked_subtask):
        from juloserver.julo.tasks import mark_sphp_expired_julo_one

        product = JFinancingProductFactory(quantity=10)
        checkout_info = {
            "address": "test",
            "address_detail": "test",
            "full_name": "test",
            "phone_number": "08321321321",
        }
        checkout = JFinancingCheckoutFactory(
            customer=self.customer, additional_info=checkout_info, j_financing_product=product
        )
        verification = JFinancingVerificationFactory(
            j_financing_checkout=checkout,
            loan=self.loan,
            validation_status=JFinancingStatus.INITIAL,
        )

        self.loan.loan_status = StatusLookupFactory(status_code=209)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        product_lookup = ProductLookupFactory(product_line=product_line)
        self.loan.product = product_lookup
        self.loan.transaction_method_id = TransactionMethodCode.JFINANCING.code
        self.loan.save()
        mark_sphp_expired_julo_one()
        mocked_subtask.assert_called()
        mocked_subtask.reset_mock()

        # exclude on_review status
        verification.validation_status = JFinancingStatus.ON_REVIEW
        verification.save()
        mark_sphp_expired_julo_one()
        mocked_subtask.assert_not_called()

    @mock.patch('juloserver.julo.tasks.update_loan_status_and_loan_history')
    def test_mark_sphp_expired_julo_one_subtask_with_x216_loan_status(self, mock_loan_status):
        from juloserver.julo.tasks import mark_sphp_expired_julo_one_subtask
        self.loan.loan_status = StatusLookupFactory(status_code=216)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        product_lookup = ProductLookupFactory(product_line=product_line)
        self.loan.product = product_lookup
        self.loan.save()
        mark_sphp_expired_julo_one_subtask(self.loan.pk)
        mock_loan_status.assert_not_called()

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.grab.tasks.mark_sphp_expired_grab_subtask.delay')
    def test_triggering_main_grab_function_greater_than_batch_size(self, mocked_subtask):
        batch_size = 12
        loan_list = []
        for idx in list(range(batch_size)):
            loan = LoanFactory(account=self.account)
            loan.loan_status = StatusLookupFactory(status_code=210)
            loan.sphp_exp_date = timezone.localtime(timezone.now() - timedelta(days=1))
            loan.save()
            loan_list.append(loan.id)
        loan_list = sorted(loan_list, reverse=True)
        mark_sphp_expired_grab()
        calls = [
            call(loan_list[:10]),
            call(loan_list[10:])
        ]
        mocked_subtask.assert_has_calls(calls)

    def test_triggering_sub_grab_function_batch_size(self):
        batch_size = 10
        loan_list = []
        for idx in list(range(batch_size)):
            loan = LoanFactory(account=self.account)
            loan.loan_status = StatusLookupFactory(status_code=210)
            loan.sphp_exp_date = timezone.localtime(timezone.now() - timedelta(days=1))
            loan.save()
            loan_list.append(loan.id)
        loan_list = sorted(loan_list, reverse=True)
        mark_sphp_expired_grab_subtask(loan_list)
        for loan_id in loan_list:
            loan = Loan.objects.get(id=loan_id)
            self.assertEqual(loan.loan_status_id, LoanStatusCodes.SPHP_EXPIRED)

    def test_triggering_sub_grab_function_batch_size_mixed_case(self):
        batch_size = 10
        loan_list = []
        invalid_list = []
        for idx in list(range(batch_size)):
            loan = LoanFactory(account=self.account)
            if idx not in {0, 1}:
                loan.loan_status = StatusLookupFactory(status_code=210)
            else:
                loan.loan_status = StatusLookupFactory(status_code=220)
                invalid_list.append(loan.id)
            loan.sphp_exp_date = timezone.localtime(timezone.now() - timedelta(days=1))
            loan.save()
            loan_list.append(loan.id)
        loan_list = sorted(loan_list, reverse=True)
        mark_sphp_expired_grab_subtask(loan_list)
        for loan_id in loan_list:
            loan = Loan.objects.filter(id=loan_id).last()
            if loan.id not in invalid_list:
                self.assertEqual(loan.loan_status_id, LoanStatusCodes.SPHP_EXPIRED)
            else:
                self.assertEqual(loan.loan_status_id, LoanStatusCodes.CURRENT)


class TestGrabUpdatePaymentStatusSubtask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=GRAB_ACCOUNT_LOOKUP_NAME)
        self.account = AccountFactory(customer=self.customer,
                                      account_lookup=self.account_lookup)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.grab_customer_data = GrabCustomerDataFactory()
        status_code = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_INVALIDATED)
        self.loan = LoanFactory(customer=self.customer, status=status_code,
                                account=self.account)
        self.loan.save()
        self.grab_loan_data = GrabLoanDataFactory(loan=self.loan)
        payments = Payment.objects.filter(loan=self.loan).order_by('due_date')
        payment_set = list(payments)
        for idx, payment in enumerate(payment_set):
            payment.due_amount = 100
            payment.payment_status = StatusLookupFactory(status_code=310)
            payment.is_restructured = False
            payment.due_date = timezone.localtime(timezone.now() - timedelta(days=(idx + 90)))
            payment.save()

    def test_update_payment_subtask_invalidated(self):
        payment = Payment.objects.filter(loan=self.loan).order_by('due_date').first()
        status_code = StatusLookupFactory(
            status_code=LoanStatusCodes.LOAN_INVALIDATED)
        self.loan.loan_status = status_code
        self.loan.save()
        update_payment_status_subtask(payment_id=payment.id)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.LOAN_INVALIDATED)

    def test_update_payment_status_subtask_active(self):
        payment = Payment.objects.filter(loan=self.loan).order_by('due_date').first()
        status_code = StatusLookupFactory(
            status_code=LoanStatusCodes.CURRENT)
        self.loan.loan_status = status_code
        update_payment_status_subtask(payment_id=payment.id)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.LOAN_90DPD)


class TestGrabAppStatusChangesEmail(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account,
            mobile_phone_1='6281245789865'
        )
        now = timezone.localtime(timezone.now())
        self.product_lookup = ProductLookupFactory(product_line=self.product_line)

        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=ApplicationStatusCodes.FORM_CREATED)

    @mock.patch(
        'juloserver.grab.tasks.'
        'send_grab_email_based_on_template_code')
    @mock.patch(
        'juloserver.grab.tasks.'
        'task_send_email_to_user_131_daily_process_chunk.delay')
    def test_send_email_to_user_at_131_for_24_hour(
            self,
            mock_send_email_to_user_at_131_for_24_hour_sub_task,
            mock_send_grab_email_based_on_template_code
    ):

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)

        self.application.save()
        send_email_to_user_at_131_for_24_hour()
        self.assertEqual(mock_send_email_to_user_at_131_for_24_hour_sub_task.called, False)

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED)

        self.application.save()
        send_email_to_user_at_131_for_24_hour()
        self.assertEqual(mock_send_email_to_user_at_131_for_24_hour_sub_task.called, True)

        EmailHistoryFactory(
            application=self.application,
            customer=self.customer,
            payment=None,
            template_code=GrabEmailTemplateCodes.GRAB_EMAIL_APP_AT_131,
            to_email=self.application.email,
            status='sent_to_provider',
        )
        send_email_to_user_at_131_for_24_hour()
        self.assertEqual(mock_send_email_to_user_at_131_for_24_hour_sub_task.called, True)
        mock_send_grab_email_based_on_template_code.assert_not_called()


    @mock.patch(
        'juloserver.grab.tasks.'
        'send_grab_email_based_on_template_code')
    @mock.patch(
        'juloserver.grab.tasks.'
        'task_send_email_to_user_before_app_expire_process_chunk.delay')
    def test_send_sms_to_user_at_131_for_24_hour(
            self,
            mock_send_email_to_user_before_3hr_of_app_expire_task,
            mock_send_grab_email_based_on_template_code
    ):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL)

        self.application.save()
        send_email_to_user_before_3hr_of_app_expire()
        self.assertEqual(mock_send_email_to_user_before_3hr_of_app_expire_task.called, False)

        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED)

        self.application.save()
        send_email_to_user_before_3hr_of_app_expire()
        self.assertEqual(mock_send_email_to_user_before_3hr_of_app_expire_task.called, True)
        EmailHistoryFactory(
            application=self.application,
            customer=self.customer,
            payment=None,
            template_code=GrabEmailTemplateCodes.GRAB_EMAIL_APP_AT_131,
            to_email=self.application.email,
            status='sent_to_provider',
        )
        send_email_to_user_before_3hr_of_app_expire()
        self.assertEqual(mock_send_email_to_user_before_3hr_of_app_expire_task.called, True)
        mock_send_grab_email_based_on_template_code.assert_not_called()


class TestClearGrabPaymentPlans(TestCase):
    def test_clear_grab_payment_plans_with_old_data(self):
        with freeze_time("2024-01-01"):
            for _ in range(5):
                GrabPaymentPlansFactory()

        self.assertNotEqual(GrabPaymentPlans.objects.all().count(), 0)
        clear_grab_payment_plans()
        self.assertEqual(GrabPaymentPlans.objects.all().count(), 0)

    def test_clear_grab_payment_plans_without_old_data(self):
        for _ in range(5):
            GrabPaymentPlansFactory()

        self.assertNotEqual(GrabPaymentPlans.objects.all().count(), 0)
        clear_grab_payment_plans()
        self.assertNotEqual(GrabPaymentPlans.objects.all().count(), 0)


class TestEmergencyContactTasks(TestCase):
    @mock.patch("juloserver.grab.tasks.sleep", return_value=None)
    @mock.patch("juloserver.grab.tasks.delete_old_ec_approval_link.delay")
    @mock.patch("juloserver.grab.tasks.sending_sms_to_emergency_contact.delay")
    @mock.patch("juloserver.grab.tasks.emergency_contact_auto_reject.delay")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    def test_task_emergency_contact_no_feature_settings(
        self,
        mock_get_feature_settings_parameters,
        mock_emergency_contact_auto_reject,
        mock_sending_sms_to_emergency_contact,
        mock_delete_old_ec_approval_link,
        mock_sleep
    ):
        mock_get_feature_settings_parameters.return_value = None

        task_emergency_contact()

        mock_emergency_contact_auto_reject.assert_not_called()
        mock_sending_sms_to_emergency_contact.assert_not_called()
        mock_delete_old_ec_approval_link.assert_not_called()

    @mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact.delay")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    def test_task_emergency_contact_resend_sms_no_feature_settings(
        self,
        mock_get_feature_settings_parameters,
        mock_resend_sms_to_emergency_contact
    ):
        mock_get_feature_settings_parameters.return_value = None

        task_emergency_contact_resend_sms()

        mock_resend_sms_to_emergency_contact.assert_not_called()

    @freeze_time("2024-01-01T20:00:00+07:00")
    @mock.patch("juloserver.grab.tasks.delete_old_ec_approval_link")
    @mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact")
    @mock.patch("juloserver.grab.tasks.sending_sms_to_emergency_contact")
    @mock.patch("juloserver.grab.tasks.emergency_contact_auto_reject")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    def test_task_emergency_contact_time_not_match(
        self,
        mock_get_feature_settings_parameters,
        mock_emergency_contact_auto_reject,
        mock_sending_sms_to_emergency_contact,
        mock_resend_sms_to_emergency_contact,
        mock_delete_old_ec_approval_link,
    ):
        mock_get_feature_settings_parameters.return_value = {
            'sms_cron_send_time': 19
        }

        task_emergency_contact()

        mock_emergency_contact_auto_reject.delay.assert_called()
        mock_sending_sms_to_emergency_contact.delay.assert_not_called()
        mock_resend_sms_to_emergency_contact.delay.assert_not_called()
        mock_delete_old_ec_approval_link.delay.asset_called()

    @freeze_time("2024-01-01T20:00:00+07:00")
    @mock.patch("juloserver.grab.tasks.delete_old_ec_approval_link")
    @mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact")
    @mock.patch("juloserver.grab.tasks.sending_sms_to_emergency_contact")
    @mock.patch("juloserver.grab.tasks.emergency_contact_auto_reject")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    def test_task_emergency_contact_time_match(
        self,
        mock_get_feature_settings_parameters,
        mock_emergency_contact_auto_reject,
        mock_sending_sms_to_emergency_contact,
        mock_resend_sms_to_emergency_contact,
        mock_delete_old_ec_approval_link
    ):
        mock_get_feature_settings_parameters.return_value = {
            'sms_cron_send_time': 20
        }

        task_emergency_contact()

        mock_emergency_contact_auto_reject.delay.assert_called()
        mock_sending_sms_to_emergency_contact.assert_called()
        mock_resend_sms_to_emergency_contact.assert_not_called()
        mock_delete_old_ec_approval_link.delay.assert_called()

    @freeze_time("2024-01-01T20:00:00+07:00")
    @mock.patch("juloserver.grab.tasks.delete_old_ec_approval_link")
    @mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact")
    @mock.patch("juloserver.grab.tasks.sending_sms_to_emergency_contact")
    @mock.patch("juloserver.grab.tasks.emergency_contact_auto_reject")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    def test_task_emergency_contact_resend_sms_time_match(
        self,
        mock_get_feature_settings_parameters,
        mock_emergency_contact_auto_reject,
        mock_sending_sms_to_emergency_contact,
        mock_resend_sms_to_emergency_contact,
        mock_delete_old_ec_approval_link
    ):
        mock_get_feature_settings_parameters.return_value = {
            'sms_cron_send_time': 20
        }

        task_emergency_contact_resend_sms()

        mock_emergency_contact_auto_reject.delay.assert_not_called()
        mock_sending_sms_to_emergency_contact.assert_not_called()
        mock_resend_sms_to_emergency_contact.assert_not_called()
        mock_delete_old_ec_approval_link.delay.assert_not_called()

    @freeze_time("2024-01-01T20:00:00+07:00")
    @mock.patch("juloserver.grab.tasks.delete_old_ec_approval_link")
    @mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact")
    @mock.patch("juloserver.grab.tasks.sending_sms_to_emergency_contact")
    @mock.patch("juloserver.grab.tasks.emergency_contact_auto_reject")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    def test_task_emergency_contact_resend_sms_time_added_one_hour(
        self,
        mock_get_feature_settings_parameters,
        mock_emergency_contact_auto_reject,
        mock_sending_sms_to_emergency_contact,
        mock_resend_sms_to_emergency_contact,
        mock_delete_old_ec_approval_link
    ):
        mock_get_feature_settings_parameters.return_value = {
            'sms_cron_send_time': 19
        }

        task_emergency_contact_resend_sms()

        mock_emergency_contact_auto_reject.delay.assert_not_called()
        mock_sending_sms_to_emergency_contact.assert_not_called()
        mock_resend_sms_to_emergency_contact.assert_called()
        mock_delete_old_ec_approval_link.delay.assert_not_called()

    @mock.patch("juloserver.grab.services.services.EmergencyContactService.auto_reject_ec_consent")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_expired_emergency_approval_link_queryset")
    def test_emergency_contact_auto_reject(
        self,
        mock_get_expired_emergency_approval_link_queryset,
        mock_auto_reject_ec_consent):
        class MockQuerySet(object):
            def exists(self):
                return True
        mock_get_expired_emergency_approval_link_queryset.return_value = MockQuerySet()
        emergency_contact_auto_reject()
        mock_auto_reject_ec_consent.assert_called()

    @mock.patch("juloserver.grab.services.services.EmergencyContactService.auto_reject_ec_consent")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_expired_emergency_approval_link_queryset")
    def test_emergency_contact_auto_reject_not_expired_approval_link(
        self,
        mock_get_expired_emergency_approval_link_queryset,
        mock_auto_reject_ec_consent):
        class MockQuerySet(object):
            def exists(self):
                return False
        mock_get_expired_emergency_approval_link_queryset.return_value = MockQuerySet()
        emergency_contact_auto_reject()
        mock_auto_reject_ec_consent.assert_not_called()

    @mock.patch("juloserver.grab.services.services.get_redis_client")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.pop_application_ids_from_redis")
    @mock.patch("juloserver.julo.clients.get_julo_sms_client")
    @mock.patch("juloserver.grab.tasks.sending_sms_to_emergency_contact_worker")
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters")
    def test_sending_sms_to_emergency_contact(
        self,
        mock_get_feature_settings_parameters,
        mock_sending_sms_to_emergency_contact_worker,
        mock_get_julo_sms_client,
        mock_pop_application_ids_from_redis,
        mock_get_redis_client
    ):
        class MockRedisClient(object):
            def sadd(self, key, data):
                pass

        mock_get_feature_settings_parameters.return_value = {
            'opt_out_in_hour': 48,
            'sms_cron_send_time': 19
        }
        mock_get_julo_sms_client.return_value = None
        mock_get_redis_client.return_value = MockRedisClient()

        application_ids = []
        for _ in range(5):
            app = ApplicationFactory()
            application_ids.append(app.id)

        mock_pop_application_ids_from_redis.return_value = application_ids

        sending_sms_to_emergency_contact()

        mock_sending_sms_to_emergency_contact_worker.assert_called()
        mock_sending_sms_to_emergency_contact_worker.assert_called_with(
            application_ids,
            {
                'opt_out_in_hour': 48,
                'sms_cron_send_time': 19
            }
        )

    @freeze_time("2024-01-01T00:00:00")
    @mock.patch("juloserver.grab.services.services.get_redis_client")
    @mock.patch("juloserver.grab.tasks.sending_sms_async_worker")
    @mock.patch("juloserver.grab.tasks.get_julo_sms_client")
    @mock.patch("juloserver.grab.services.services.shorten_url")
    def test_sending_sms_to_emergency_contact_worker(
        self,
        mock_shorten_url,
        mock_get_julo_sms_client,
        mock_sending_sms_async_worker,
        mock_get_redis_client
    ):
        class MockSmsClient(object):
            def send_sms(self, phone, message):
                return message, {
                    "messages": [
                        {
                            "to": "666",
                            "message": "message",
                            "status": 1,
                            "julo_sms_vendor": "whatsapp_service",
                            "message-id": 666
                        }
                    ]
                }

        mock_shorten_url.return_value = "shortened_url"
        mock_get_julo_sms_client.return_value = MockSmsClient()
        mock_get_redis_client.return_value = None

        application_ids = []
        parameters = {'opt_out_in_hour': 48}
        for _ in range(5):
            application = ApplicationFactory()
            application_ids.append(application.id)

        sending_sms_to_emergency_contact_worker(application_ids, parameters)

        for ec_approval_link in EmergencyContactApprovalLink.objects.filter(
            application_id__in=application_ids
        ).iterator():
            self.assertNotEqual(ec_approval_link.expiration_date, timezone.now())
            self.assertFalse(ec_approval_link.is_used)

        self.assertEqual(len(application_ids), EmergencyContactApprovalLink.objects.filter(
            application_id__in=application_ids).count())

        mock_sending_sms_async_worker.delay.assert_called()

    @freeze_time("2024-01-01T00:00:00")
    @mock.patch("juloserver.grab.services.services.get_redis_client")
    @mock.patch("juloserver.grab.tasks.sending_sms_async_worker")
    @mock.patch("juloserver.grab.tasks.get_julo_sms_client")
    @mock.patch("juloserver.grab.services.services.shorten_url")
    def test_sending_sms_to_emergency_contact_worker_ec_received_sms_before(
        self,
        mock_shorten_url,
        mock_get_julo_sms_client,
        mock_sending_sms_async_worker,
        mock_get_redis_client
    ):
        class MockSmsClient(object):
            def send_sms(self, phone, message):
                return message, {
                    "messages": [
                        {
                            "to": "666",
                            "message": "message",
                            "status": 1,
                            "julo_sms_vendor": "whatsapp_service",
                            "message-id": 666
                        }
                    ]
                }

        class MockRedisClient(object):
            def sadd(self, key, data):
                pass

        mock_shorten_url.return_value = "shortened_url"
        mock_get_julo_sms_client.return_value = MockSmsClient()
        mock_get_redis_client.return_value = MockRedisClient()

        customer = CustomerFactory()
        kin_mobile_phone = "+62812233386602"
        app = ApplicationFactory(customer=customer)
        app.kin_mobile_phone = kin_mobile_phone
        app.save()

        SmsHistoryFactory(
            application=app,
            customer=customer,
            to_mobile_phone=kin_mobile_phone,
            template_code="grab_emergency_contact"
        )

        application_ids = []
        parameters = {'opt_out_in_hour': 48}
        for _ in range(5):
            application = ApplicationFactory(customer=customer, kin_mobile_phone=kin_mobile_phone)
            application_ids.append(application.id)

        sending_sms_to_emergency_contact_worker(application_ids, parameters)

        self.assertFalse(EmergencyContactApprovalLink.objects.filter(
            application_id__in=application_ids
        ).exists())

        mock_sending_sms_async_worker.delay.assert_not_called()

    @mock.patch("juloserver.grab.services.services.get_redis_client")
    def test_resend_sms_to_emergency_contact_no_ec_approval_link(self, mock_get_redis_client):
        customer = CustomerFactory()
        kin_mobile_phone = "+62812233386602"

        application = ApplicationFactory(customer=customer)
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        SmsHistoryFactory(
            application=application,
            customer=customer,
            to_mobile_phone=kin_mobile_phone,
            template_code="grab_emergency_contact"
        )

        with mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact_worker") as \
            mock_resend_sms_to_emergency_contact_worker:
            resend_sms_to_emergency_contact()
            mock_resend_sms_to_emergency_contact_worker.assert_not_called()

    @mock.patch("juloserver.grab.services.services.get_redis_client")
    def test_resend_sms_to_emergency_contact(self, mock_redis_client):
        customer = CustomerFactory()
        kin_mobile_phone = "+62812233386602"

        application = ApplicationFactory(customer=customer)
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        with freeze_time("2024-01-01"):
            SmsHistoryFactory(
                application=application,
                customer=customer,
                to_mobile_phone=kin_mobile_phone,
                template_code="grab_emergency_contact"
            )

        with mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact_worker") as \
            mock_resend_sms_to_emergency_contact_worker:
            resend_sms_to_emergency_contact()
            mock_resend_sms_to_emergency_contact_worker.assert_called()


    @mock.patch('juloserver.grab.tasks.get_julo_sms_client')
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.send_sms_to_ec")
    def test_resend_sms_to_emergency_contact_worker(self, mock_send_sms_to_ec, mock_get_julo_sms_client):
        customer = CustomerFactory()
        kin_mobile_phone = "+62812233386602"

        application = ApplicationFactory(customer=customer)
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        with freeze_time("2024-01-01"):
            SmsHistoryFactory(
                application=application,
                customer=customer,
                to_mobile_phone=kin_mobile_phone,
                template_code="grab_emergency_contact"
            )

        ec_approval_link = [{
            'id': 703,
            'application_id': application.id,
            'unique_link': 'test-unique-link'
        }]

        resend_sms_to_emergency_contact_worker(ec_approval_link)
        mock_send_sms_to_ec.assert_called()

    @mock.patch('juloserver.grab.tasks.get_julo_sms_client')
    @mock.patch("juloserver.grab.services.services.EmergencyContactService.send_sms_to_ec")
    def test_resend_sms_to_emergency_contact_worker_received_sms_before(self, mock_send_sms_to_ec, mock_get_julo_sms_client):
        customer = CustomerFactory()
        kin_mobile_phone = "0812233386602"

        application = ApplicationFactory(customer=customer)
        application.kin_mobile_phone = kin_mobile_phone
        application.save()
        unique_link = "test-unique-link"
        ec_approval_link = EmergencyContactApprovalLinkFactory()
        ec_approval_link.unique_link = unique_link
        ec_approval_link.application_id = application.id
        ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
        ec_approval_link.save()

        SmsHistoryFactory(
            application=application,
            customer=customer,
            to_mobile_phone=format_e164_indo_phone_number(kin_mobile_phone),
            template_code="grab_emergency_contact"
        )

        ec_approval_link = [{
            'id': 703,
            'application_id': application.id,
            'unique_link': 'test-unique-link'
        }]

        resend_sms_to_emergency_contact_worker(ec_approval_link)
        mock_send_sms_to_ec.assert_not_called()

    def test_delete_ec_approval_link(self):
        customer = CustomerFactory()
        kin_mobile_phone = "0812233386602"

        application = ApplicationFactory(customer=customer)
        application.kin_mobile_phone = kin_mobile_phone
        application.save()
        unique_link = "test-unique-link"
        with freeze_time("2024-01-01"):
            ec_approval_link = EmergencyContactApprovalLinkFactory()
            ec_approval_link.unique_link = unique_link
            ec_approval_link.application_id = application.id
            ec_approval_link.expiration_date = timezone.localtime(timezone.now() + timedelta(hours=5))
            ec_approval_link.is_used = True
            ec_approval_link.save()

        self.assertTrue(
            EmergencyContactApprovalLink.objects.filter(id=ec_approval_link.id).exists()
        )
        delete_old_ec_approval_link()
        self.assertFalse(
            EmergencyContactApprovalLink.objects.filter(id=ec_approval_link.id).exists()
        )

    @freeze_time("2024-01-01T00:00:00")
    @mock.patch("juloserver.grab.services.services.get_redis_client")
    @mock.patch("juloserver.grab.services.services.create_sms_history")
    @mock.patch("juloserver.grab.tasks.get_julo_sms_client")
    @mock.patch("juloserver.grab.services.services.shorten_url")
    def test_reapply_case_given_consent(
        self,
        mock_shorten_url,
        mock_get_julo_sms_client,
        mock_create_sms_history,
        mock_get_redis_client
    ):
        class MockSmsClient(object):
            def send_sms(self, phone, message):
                return message, {
                    "messages": [
                        {
                            "to": "666",
                            "message": "message",
                            "status": 1,
                            "julo_sms_vendor": "whatsapp_service",
                            "message-id": 666
                        }
                    ]
                }

        class MockRedisClient(object):
            def sadd(self, key, data):
                pass

        mock_shorten_url.return_value = "shortened_url"
        mock_get_julo_sms_client.return_value = MockSmsClient()
        mock_get_redis_client.return_value = MockRedisClient()

        application_ids = []
        parameters = {'opt_out_in_hour': 48}
        customer = CustomerFactory()

        kin_mobile_phone = "081221112221"
        application = ApplicationFactory(customer=customer, kin_mobile_phone=kin_mobile_phone)
        application_ids.append(application.id)

        sending_sms_to_emergency_contact_worker(application_ids, parameters)

        for ec_approval_link in EmergencyContactApprovalLink.objects.filter(
            application_id__in=application_ids
        ).iterator():
            self.assertNotEqual(ec_approval_link.expiration_date, timezone.now())
            self.assertFalse(ec_approval_link.is_used)

        self.assertEqual(len(application_ids), EmergencyContactApprovalLink.objects.filter(
            application_id__in=application_ids).count())

        self.assertEqual(mock_create_sms_history.call_count, 1)

        SmsHistoryFactory(
            application=application,
            customer=customer,
            to_mobile_phone=format_e164_indo_phone_number(kin_mobile_phone),
            template_code="grab_emergency_contact"
        )

        mock_create_sms_history.reset_mock()
        application_ids = []
        application1 = ApplicationFactory(customer=customer, kin_mobile_phone=kin_mobile_phone)
        application_ids.append(application1.id)
        sending_sms_to_emergency_contact_worker(application_ids, parameters)
        self.assertEqual(mock_create_sms_history.call_count, 0)

        with mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters") as mock_get_feature_settings:
            mock_get_feature_settings.return_value = parameters
            with mock.patch("juloserver.grab.services.services.EmergencyContactService.pop_application_ids_from_redis") as mock_pop_app_from_redis:
                from juloserver.grab.services.services import EmergencyContactService
                svc = EmergencyContactService()
                unique_link = svc.generate_unique_link(application1.id, application1.kin_name)
                mock_pop_app_from_redis.return_value = [json.dumps({'application_id': application1.id, 'unique_link': unique_link})]
                with mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact_worker") as mock_worker:
                    resend_sms_to_emergency_contact()
                    ec_approval_link = list(EmergencyContactApprovalLink.objects.filter(
                        application_id=application1.id).values("id", "application_id", "unique_link")
                    )
                    mock_worker.assert_called_with(ec_approval_link)

    @freeze_time("2024-01-01T00:00:00")
    @mock.patch("juloserver.grab.services.services.get_redis_client")
    @mock.patch("juloserver.grab.services.services.create_sms_history")
    @mock.patch("juloserver.grab.tasks.get_julo_sms_client")
    @mock.patch("juloserver.grab.services.services.shorten_url")
    def test_reapply_case_not_given_consent(
        self,
        mock_shorten_url,
        mock_get_julo_sms_client,
        mock_create_sms_history,
        mock_get_redis_client
    ):
        class MockSmsClient(object):
            def send_sms(self, phone, message):
                return message, {
                    "messages": [
                        {
                            "to": "666",
                            "message": "message",
                            "status": 1,
                            "julo_sms_vendor": "whatsapp_service",
                            "message-id": 666
                        }
                    ]
                }

        class MockRedisClient(object):
            def sadd(self, key, data):
                pass

        mock_shorten_url.return_value = "shortened_url"
        mock_get_julo_sms_client.return_value = MockSmsClient()
        mock_get_redis_client.return_value = MockRedisClient()

        application_ids = []
        parameters = {'opt_out_in_hour': 48}
        customer = CustomerFactory()

        kin_mobile_phone = "081221112221"
        application = ApplicationFactory(customer=customer, kin_mobile_phone=kin_mobile_phone)
        application_ids.append(application.id)

        sending_sms_to_emergency_contact_worker(application_ids, parameters)

        for ec_approval_link in EmergencyContactApprovalLink.objects.filter(
            application_id__in=application_ids
        ).iterator():
            self.assertNotEqual(ec_approval_link.expiration_date, timezone.now())
            self.assertFalse(ec_approval_link.is_used)

        self.assertEqual(len(application_ids), EmergencyContactApprovalLink.objects.filter(
            application_id__in=application_ids).count())

        self.assertEqual(mock_create_sms_history.call_count, 1)

        SmsHistoryFactory(
            application=application,
            customer=customer,
            to_mobile_phone=format_e164_indo_phone_number(kin_mobile_phone),
            template_code="grab_emergency_contact"
        )

        mock_create_sms_history.reset_mock()
        application_ids = []
        application1 = ApplicationFactory(customer=customer, kin_mobile_phone=kin_mobile_phone)
        application_ids.append(application1.id)
        sending_sms_to_emergency_contact_worker(application_ids, parameters)
        self.assertEqual(mock_create_sms_history.call_count, 0)

        SmsHistory.objects.filter(application_id=application.id).delete()

        with mock.patch("juloserver.grab.services.services.EmergencyContactService.get_feature_settings_parameters") as mock_get_feature_settings:
            mock_get_feature_settings.return_value = parameters
            with mock.patch("juloserver.grab.services.services.EmergencyContactService.pop_application_ids_from_redis") as mock_pop_application_from_redis:
                from juloserver.grab.services.services import EmergencyContactService
                svc = EmergencyContactService()
                unique_link = svc.generate_unique_link(application1.id, application1.kin_name)
                mock_pop_application_from_redis.return_value = [json.dumps({'application_id': application1.id, 'unique_link': unique_link})]
                with mock.patch("juloserver.grab.tasks.resend_sms_to_emergency_contact_worker") as mock_worker:
                    resend_sms_to_emergency_contact()
                    ec_approval_link = list(EmergencyContactApprovalLink.objects.filter(
                        application_id__in=[application1.id]).
                                            values('id', 'application_id', 'unique_link').order_by('-id')
                    )
                    mock_worker.assert_called_with(ec_approval_link)

        # test resend sms worker, make sure only send sms once
        send_sms_count = 0
        for ec_approval in ec_approval_link:
            with mock.patch("juloserver.grab.services.services.EmergencyContactService.send_sms_to_ec") as mock_send_sms:
                resend_sms_to_emergency_contact_worker([ec_approval])
                temp_app = Application.objects.get(id=ec_approval.get('application_id'))
                SmsHistoryFactory(
                    application=temp_app,
                    customer=temp_app.customer,
                    to_mobile_phone=format_e164_indo_phone_number(temp_app.kin_mobile_phone),
                    template_code="grab_emergency_contact"
                )
                send_sms_count += mock_send_sms.call_count

        self.assertEqual(send_sms_count, 1)


class TestTriggerApplicationCreation(TestCase):
    def mock_response_success(self):
        response = Response()
        response.status_code = HTTPStatus.OK
        response.headers = {"Content-Type": "application/json"},
        response._content = {"message": "success"}
        return response

    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    @mock.patch("juloserver.grab.clients.clients.GrabClient.submit_application_creation")
    def test_trigger_application_creation_grab_api_no_log(self, mock_submit_application_creation):
        mock_submit_application_creation.return_value = self.mock_response_success()

        trigger_application_creation_grab_api(self.application.id)
        mock_submit_application_creation.assert_called()

    @mock.patch("juloserver.grab.clients.clients.GrabClient.fetch_application_submission_log")
    @mock.patch("juloserver.grab.clients.clients.GrabClient.submit_application_creation")
    def test_trigger_application_creation_grab_api_have_log(
        self,
        mock_submit_application_creation,
        mock_fetch_application_submission_log
    ):
        mock_fetch_application_submission_log.return_value = self.mock_response_success()

        trigger_application_creation_grab_api(self.application.id)
        mock_submit_application_creation.assert_not_called()


class TestProcessApplicationChange(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory()
        self.partner = PartnerFactory(user=self.user)
        self.status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL,
        )
        self.workflow = WorkflowFactory(name='GrabWorkflow', handler='GrabWorkflowHandler')
        self.application1 = ApplicationFactory(
            customer=self.customer,
            status=self.status,
            partner=self.partner,
            workflow=self.workflow
        )
        self.application2 = ApplicationFactory(
            customer=self.customer,
            status=self.status,
            partner=self.partner,
            workflow=self.workflow
        )
        self.fdc_check_manual_approval_data = [
            FDCCheckManualApproval(
                application_id=self.application1.id, status=ApplicationStatus.APPROVE,
            ),
            FDCCheckManualApproval(
                application_id=self.application2.id, status=ApplicationStatus.REJECT,
            ),
        ]
        FDCCheckManualApproval.objects.bulk_create(self.fdc_check_manual_approval_data)
        self.fdc_check_manual_approval_data1 = [
            FDCCheckManualApproval(
                application_id=self.application1.id, status="test",
            ),
            FDCCheckManualApproval(
                application_id=self.application2.id, status="test",
            ),
        ]
        FDCCheckManualApproval.objects.bulk_create(self.fdc_check_manual_approval_data1)
        FDCInquiryFactory(
            application_id=self.application2.id, inquiry_status='pending'
        )
    @mock.patch("juloserver.grab.tasks.send_trigger_to_anaserver_status105")
    @mock.patch('juloserver.grab.tasks.call_process_application_status_change')
    def test_process_application_status_change_failure(
        self,
        mock_call_process_application_status_change,
        mock_send_trigger_to_anaserver_status105
    ):
        process_application_status_change(self.fdc_check_manual_approval_data1)
        mock_call_process_application_status_change.assert_not_called()
        mock_send_trigger_to_anaserver_status105.assert_not_called()
    @mock.patch("juloserver.grab.workflows.GrabWorkflowAction.trigger_anaserver_status105")
    @mock.patch("juloserver.grab.workflows.GrabWorkflowAction.update_customer_data")
    @mock.patch('juloserver.julo.services.process_application_status_change')
    def test_process_application_status_change_success(
        self,
        mock_process_application_status_change,
        mock_update_customer_data,
        mock_trigger_anaserver_status105
    ):
        process_application_status_change(self.fdc_check_manual_approval_data)
        mock_process_application_status_change.assert_called_once()
        mock_update_customer_data.assert_called_once()
        mock_trigger_anaserver_status105.assert_called_once()
