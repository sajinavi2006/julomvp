from builtins import str
import mock
from mock import patch
from django.test.utils import override_settings

from rest_framework import status
from rest_framework.test import APITestCase
from juloserver.api_token.models import ExpiryToken as Token
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    ProductLineFactory,
    LenderBalanceFactory,
    LenderServiceRateFactory,
    WorkflowFactory,
    ProductLookupFactory
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import CustomerFactory, LoanFactory, PartnerFactory
from .factories import NameBankValidationFactory, DisbursementFactory
from juloserver.julo.constants import ProductLineCodes, WorkflowConst
from juloserver.disbursement.serializers import PaymentGatewayCallbackSerializer
from juloserver.disbursement.constants import DisbursementStatus
from juloserver.disbursement.services import (
    get_disbursement_by_obj,
    PaymentGatewayDisbursementProcess
)


class TestXenditNameValidateEventCallbackView(APITestCase):

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 150
        self.application.save()
        self.token, _created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.validation_id = 100
        self.bank_validation = NameBankValidationFactory(
            validation_id=self.validation_id,
            method='Xendit',
            account_number=123,
            name_in_bank='test')
        self.loan = LoanFactory(
            name_bank_validation_id=self.bank_validation.id,
            application=self.application)

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_xendit_name_validate_event_callback_view_case_0(self, mock_change_status):
        data = {
            'id': self.validation_id,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'bank_account_holder_name': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_name_validate',
            data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_xendit_name_validate_event_callback_view(self, mock_change_status):
        data = {
            'id': 223,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'bank_account_holder_name': 'abc'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_name_validate',
            data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_xendit_name_validate_event_callback_view_case_2(self, mock_change_status):
        data = {
            'id': self.validation_id,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'Fail',
            'updated': 1,
            'bank_account_holder_name': 'abc',
            'failure_reason': 'test',
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_name_validate',
            data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_xendit_name_validate_event_callback_view_case_3(self, mock_change_status):
        self.bank_validation.validation_status = 'SUCCESS'
        self.bank_validation.save()
        data = {
            'id': self.validation_id,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'bank_account_holder_name': 'abc'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_name_validate',
            data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_xendit_name_validate_event_callback_view_case_4(self, mock_change_status):
        data = {
            'id': self.validation_id,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'bank_account_holder_name': 'aaa'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_name_validate',
            data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestXenditDisburseEventCallbackView(APITestCase):

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 150
        self.application.save()
        self.token, _created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.validation_id = 100
        self.bank_validation = NameBankValidationFactory(
            validation_id=self.validation_id,
            method='Xendit',
            account_number=123,
            name_in_bank='test',
            bank_code='BCA_SYR')
        self.disbursement = DisbursementFactory(
            name_bank_validation=self.bank_validation,
            disburse_id=123456,
            method='Xendit',
            disbursement_type='loan_one')
        self.loan = LoanFactory(
            name_bank_validation_id=self.bank_validation.id,
            disbursement_id=self.disbursement.id,
            application=self.application)
        self.lender_balance = LenderBalanceFactory(
            partner=self.loan.partner,
            total_deposit=100000000,
            available_balance=100000000
            )
        self.lender_service = LenderServiceRateFactory(partner=self.loan.partner)

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_disburse_event_callback(self, mock_change_status):
        data = {
            'id': self.disbursement.disburse_id,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'account_holder_name': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(XENDIT_DISBURSEMENT_VALIDATION_TOKEN='test')
    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_disburse_event_callback_case_2(self, mock_change_status):
        data = {
            'id': self.disbursement.disburse_id,
            'bank_code': 'BCA_SYR',
            'bank_account_number': 123423,
            'status': 'COMPLETED',
            'updated': 1,
            'account_holder_name': 'test',
            'amount': 1000000,
            'external_id': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(XENDIT_DISBURSEMENT_VALIDATION_TOKEN='test')
    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_disburse_event_callback_case_3(self, mock_change_status):
        data = {
            'id': 911,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'account_holder_name': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(XENDIT_DISBURSEMENT_VALIDATION_TOKEN='test')
    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_disburse_event_callback_case_4(self, mock_change_status):
        self.disbursement.disburse_status = 'COMPLETED'
        self.disbursement.save()
        data = {
            'id': self.disbursement.disburse_id,
            'bank_code': 'BCA_SYR',
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'account_holder_name': 'test',
            'amount': 1000000,
            'external_id': 'test'
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xendit_disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(XENDIT_DISBURSEMENT_VALIDATION_TOKEN='test')
    @patch('juloserver.disbursement.views.views_api_v1.application_bulk_disbursement_tasks')
    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_disburse_event_callback_case_5(self, mock_change_status, mock_task):
        self.disbursement.disbursement_type='bulk'
        self.disbursement.save()
        data = {
            'id': self.disbursement.disburse_id,
            'bank_code': 'BCA_SYR',
            'bank_account_number': 123423,
            'status': 'FAILED',
            'updated': 1,
            'account_holder_name': 'test',
            'amount': 1000000,
            'external_id': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/xendit_disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestXfersDisburseEventCallbackView(APITestCase):

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name='test')
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer, partner=self.partner)
        self.application.application_status_id = 150
        self.application.save()
        self.token, _created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
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

    def test_xfers_callback(self):
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test'
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xfers-disburse?step=1',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)

        #status success
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'success',
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xfers-disburse?step=1',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)


class TestXfersDisburseEventCallbackGrabView(APITestCase):

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name='test')
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer,
        )
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.workflow_grab = WorkflowFactory(name=WorkflowConst.GRAB)
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            partner=self.partner,
            product_line=self.product_line,
            account=self.account,
            workflow=self.workflow_grab
        )
        self.application.application_status_id = 190
        self.application.save()
        self.token, _created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
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
            application=self.application,
            account=self.account
        )

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_callback_from_xfers_partner')
    def test_xfers_callback(self, _mock_process_callback_from_xfers_partner):
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test'
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xfers-disburse?step=1',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        _mock_process_callback_from_xfers_partner.delay.assert_called()
        #status success
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'success',
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xfers-disburse?step=1',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_mock_process_callback_from_xfers_partner.delay.call_count, 2)

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_callback_from_xfers')
    def test_process_callback_from_xfers_j1(self, _mock_process_callback_from_xfers):
        self.application.product_line = self.product_line_j1
        self.application.workflow = self.workflow_j1
        self.application.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test'
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xfers-disburse?step=1',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        _mock_process_callback_from_xfers.delay.assert_called()
        #status success
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'success',
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xfers-disburse?step=1',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_mock_process_callback_from_xfers.delay.call_count, 2)

    def test_xfers_callback_j1(self):
        self.loan.disbursement_id = None
        self.loan.save()
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'failed',
            'failure_reason': 'test'
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xfers-disburse?step=1',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)

        #status success
        data = {
            'idempotency_id': str(self.disbursement.disburse_id),
            'status': 'success',
        }
        response = self.client.post(
            '/api/disbursement/callbacks/xfers-disburse?step=1',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)


class TestInstamoneyDisburseEventCallbackView(APITestCase):

    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 150
        self.application.save()
        self.token, _created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.validation_id = 100
        self.bank_validation = NameBankValidationFactory(
            validation_id=self.validation_id,
            method='Instamoney',
            account_number=123,
            name_in_bank='test',
            bank_code='BCA_SYR')
        self.disbursement = DisbursementFactory(
            name_bank_validation=self.bank_validation,
            disburse_id=123456,
            method='Instamoney',
            disbursement_type='loan_one')
        self.loan = LoanFactory(
            name_bank_validation_id=self.bank_validation.id,
            disbursement_id=self.disbursement.id,
            application=self.application)
        self.lender_balance = LenderBalanceFactory(
            partner=self.loan.partner,
            total_deposit=100000000,
            available_balance=100000000
            )
        self.lender_service = LenderServiceRateFactory(partner=self.loan.partner)

    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_instamoney_disburse_event_callback(self, mock_change_status):
        data = {
            'id': self.disbursement.disburse_id,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'account_holder_name': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/instamoney-disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(INSTAMONEY_API_TOKEN='test')
    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_instamoney_disburse_event_callback_case_2(self, mock_change_status):
        data = {
            'id': self.disbursement.disburse_id,
            'bank_code': 'BCA_SYR',
            'bank_account_number': 123423,
            'status': 'COMPLETED',
            'updated': 1,
            'account_holder_name': 'test',
            'amount': 1000000,
            'external_id': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/instamoney-disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(INSTAMONEY_API_TOKEN='test')
    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_instamoney_disburse_event_callback_case_3(self, mock_change_status):
        data = {
            'id': 911,
            'bank_code': 14564,
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'account_holder_name': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/instamoney-disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(INSTAMONEY_API_TOKEN='test')
    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_instamoney_disburse_event_callback_case_4(self, mock_change_status):
        self.disbursement.disburse_status = 'COMPLETED'
        self.disbursement.save()
        data = {
            'id': self.disbursement.disburse_id,
            'bank_code': 'BCA_SYR',
            'bank_account_number': 123423,
            'status': 'SUCCESS',
            'updated': 1,
            'account_holder_name': 'test',
            'amount': 1000000,
            'external_id': 'test'
        }
        response = self.client.post(
            '/api/disbursement/callbacks/instamoney-disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(INSTAMONEY_API_TOKEN='test')
    @patch('juloserver.disbursement.views.views_api_v1.application_bulk_disbursement_tasks')
    @mock.patch('juloserver.disbursement.views.views_api_v1.process_application_status_change')
    def test_instamoney_disburse_event_callback_case_5(self, mock_change_status, mock_task):
        self.disbursement.disbursement_type = 'bulk'
        self.disbursement.save()
        data = {
            'id': self.disbursement.disburse_id,
            'bank_code': 'BCA_SYR',
            'bank_account_number': 123423,
            'status': 'FAILED',
            'updated': 1,
            'account_holder_name': 'test',
            'amount': 1000000,
            'external_id': 'test'
        }

        response = self.client.post(
            '/api/disbursement/callbacks/instamoney-disburse',
            data=data, HTTP_X_CALLBACK_TOKEN='test')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestPaymentGatewayDisburseEventCallbackView(APITestCase):
    @mock.patch('juloserver.julo.models.XidLookup.get_new_xid')
    def setUp(self, mock_get_new_xid):
        self.path = '/api/disbursement/callbacks/v1/payment-gateway-disburse'
        self.loan_xid = 1221
        mock_get_new_xid.return_value = self.loan_xid

        product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        product = ProductLookupFactory(product_line=product_line)
        self.user_auth = AuthUserFactory()
        self.partner = PartnerFactory(name='test')
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer, partner=self.partner)
        self.application.application_status_id = 150
        self.application.save()
        self.token, _created = Token.objects.get_or_create(user=self.user_auth)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.validation_id = 100
        self.bank_validation = NameBankValidationFactory(
            validation_id=self.validation_id,
            method='PG',
            account_number=123,
            name_in_bank='test',
            bank_code='BCA_SYR')
        self.disbursement = DisbursementFactory(
            name_bank_validation=self.bank_validation,
            disburse_id=123456,
            method='PG',
            disbursement_type='loan_one',
            step=2,
            original_amount=1000000,
            external_id=self.loan_xid)
        self.loan = LoanFactory(
            name_bank_validation_id=self.bank_validation.id,
            disbursement_id=self.disbursement.id,
            application=self.application,
            product=product)

    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_payment_gateway_callback_success(self):
        self.assertEqual(
            self.disbursement.disburse_status,
            DisbursementStatus.INITIATED
        )
        data = {
            'transaction_id': self.disbursement.disburse_id,
            'object_transfer_id': 'transfer_{}'.format(
                self.disbursement.disburse_id),
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
        response = self.client.post(
            '/api/disbursement/callbacks/v1/payment-gateway-disburse',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.disbursement.refresh_from_db()
        self.assertEqual(
            self.disbursement.disburse_status,
            DisbursementStatus.COMPLETED
        )
        disbursement_procces = get_disbursement_by_obj(self.disbursement)
        self.assertTrue(isinstance(
            disbursement_procces,
            PaymentGatewayDisbursementProcess
        ))
        self.assertTrue(disbursement_procces.is_grab_loan(
            self.disbursement.external_id)
        )

    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_payment_gateway_callback_failed(self):
        self.assertEqual(
            self.disbursement.disburse_status,
            DisbursementStatus.INITIATED
        )
        data = {
            'transaction_id': self.disbursement.disburse_id,
            'object_transfer_id': 'transfer_{}'.format(
                self.disbursement.disburse_id),
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
        response = self.client.post(
            '/api/disbursement/callbacks/v1/payment-gateway-disburse',
            data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.disbursement.refresh_from_db()
        self.assertEqual(
            self.disbursement.disburse_status,
            DisbursementStatus.FAILED
        )
        disbursement_procces = get_disbursement_by_obj(self.disbursement)
        self.assertTrue(isinstance(disbursement_procces, PaymentGatewayDisbursementProcess))
        self.assertTrue(disbursement_procces.is_grab_loan(self.disbursement.external_id))

    def test_serializer_invalid_params(self):
        # Prepare invalid data
        invalid_data = {
            # Missing or incorrect fields
            'transaction_id': 'not_an_integer',
            'object_transfer_id': '',
        }

        response = self.client.post(self.path, data=invalid_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('juloserver.disbursement.views.views_api_v1.process_disbursement_payment_gateway')
    def test_successful_callback(self, mock_process_disbursement):
        # Prepare valid data
        valid_data = {
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
        response = self.client.post(self.path, data=valid_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_serializer_validation(self):
        # Test individual serializer validations
        test_cases = [
            # Test valid data
            (
                {
                    'transaction_id': 123,
                    'object_transfer_id': 'transfer_123',
                    'object_transfer_type': 'payout',
                    'transaction_date': '2024-02-07',
                    'status': 'completed',
                    'amount': '100.00',
                    'bank_id': 456,
                    'bank_account': '1234567890',
                    'bank_account_name': 'John Doe',
                    'bank_code': 'BANK001',
                    'preferred_pg': 'stripe',
                    'can_retry': False,
                },
                True,
            ),
            # Test missing required fields
            (
                {
                    'transaction_id': 123,
                    # Missing critical fields
                },
                False,
            ),
            # Test invalid field types
            (
                {
                    'transaction_id': 'not_an_integer',
                    'object_transfer_id': 123,  # Wrong type
                    'bank_id': 'not_an_integer',
                    'can_retry': 'not_a_boolean',
                },
                False,
            ),
        ]

        for data, expected_validity in test_cases:
            serializer = PaymentGatewayCallbackSerializer(data=data)
            assert serializer.is_valid() == expected_validity, "Failed for data: {}".format(data)

    @override_settings(CELERY_ALWAYS_EAGER=True)
    @mock.patch('juloserver.loan.services.lender_related.update_loan_status_and_loan_history')
    def test_payment_gateway_callback_failed_grab_app(self, mock_update_loan_status):
        self.application.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB
        )
        self.application.save()

        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.INITIATED)
        data = {
            'transaction_id': self.disbursement.disburse_id,
            'object_transfer_id': 'transfer_{}'.format(
                self.disbursement.disburse_id),
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
        response = self.client.post(
            '/api/disbursement/callbacks/v1/payment-gateway-disburse', data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.disbursement.refresh_from_db()
        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.FAILED)
        disbursement_procces = get_disbursement_by_obj(self.disbursement)
        self.assertTrue(isinstance(disbursement_procces, PaymentGatewayDisbursementProcess))
        self.assertTrue(disbursement_procces.is_grab_loan(self.disbursement.external_id))
        mock_update_loan_status.assert_called_with(
            self.loan.id,
            change_reason='PG Service disbursement failed',
            new_status_code=213
        )

    @override_settings(CELERY_ALWAYS_EAGER=True)
    @mock.patch('juloserver.loan.services.lender_related.update_loan_status_and_loan_history')
    def test_payment_gateway_callback_failed_j1_app(self, mock_update_loan_status):
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        product = ProductLookupFactory(product_line=product_line)
        self.application.workflow = WorkflowFactory(
            name=WorkflowConst.JULO_ONE
        )
        self.application.save()
        self.loan.product = product
        self.loan.save()

        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.INITIATED)
        data = {
            'transaction_id': self.disbursement.disburse_id,
            'object_transfer_id': 'transfer_{}'.format(
                self.disbursement.disburse_id),
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
        response = self.client.post(
            '/api/disbursement/callbacks/v1/payment-gateway-disburse', data=data, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.disbursement.refresh_from_db()
        self.assertEqual(self.disbursement.disburse_status, DisbursementStatus.FAILED)
        disbursement_procces = get_disbursement_by_obj(self.disbursement)
        self.assertTrue(isinstance(disbursement_procces, PaymentGatewayDisbursementProcess))
        self.assertFalse(disbursement_procces.is_grab_loan(self.disbursement.external_id))
        mock_update_loan_status.assert_called_with(
            self.loan.id,
            change_reason='Disbursement failed',
            new_status_code=215
        )
