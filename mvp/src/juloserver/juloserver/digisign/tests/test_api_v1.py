from unittest.mock import patch
from django.test.utils import override_settings
from rest_framework.test import APIClient
from django.test.testcases import TestCase
from juloserver.application_flow.authentication import OnboardingInternalAuthentication
from juloserver.digisign.constants import DocumentType, SigningStatus
from juloserver.digisign.models import DigisignDocument
from juloserver.digisign.tests.factories import DigisignDocumentFactory
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    StatusLookupFactory,
)
from juloserver.julo.constants import (
    FeatureNameConst,
)


class TestDigisign(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        FeatureSettingFactory(
            feature_name=FeatureNameConst.DIGISIGN,
            is_active=True,
            parameters={},
        )

    def test_get_consent_page(self):
        url = '/api/digisign/v1/get_consent_page'
        response = self.client.get(url)
        self.assertEqual(
            response.json(),
            {'success': True, 'data': {}, 'errors': []}
        )


class TestSignDocumentCallback(TestCase):
    def setUp(self):
        """Set up test environment before each test."""
        self.client = APIClient()
        self.test_token = "test_token_12345"
        self.status = StatusLookupFactory()
        self.status.status_code = 210
        self.status.save()
        self.loan = LoanFactory(loan_status=self.status)
        self.digisign_document = DigisignDocumentFactory(
            document_type=DocumentType.LOAN_AGREEMENT_BORROWER,
            document_source=self.loan.id,
            signing_status='processing',
            document_token='b3e4fcb305434a2232b4751700919',
            reference_number='b3e4ffcb307348d2a2232b4751700919',
        )
        self.data = {
            "status": "completed",
            "reference_number": "b3e4ffcb307348d2a2232b4751700919" ,
            "signed_document": "data:application/pdf;base64, SGVsbG8sIFdvcmxkIQ==",
        }

    @patch('juloserver.digisign.services.digisign_document_services.accept_julo_sphp')
    @patch('juloserver.digisign.services.digisign_document_services.upload_signed_document_to_oss')
    @override_settings(JWT_SECRET_KEY="secret-jwt")
    def test_valid_request_successful_processing(self, mock_upload, mock_accept_julo_sphp):
        """Test successful processing of a valid request."""
        mock_upload.return_value = 'remote_path_mock'
        self.token = 'Bearer ' + OnboardingInternalAuthentication.generate_token('digital-signature')
        self.client.credentials(HTTP_AUTHORIZATION=self.token)
        url = '/api/digisign/v1/sign_document/callback'
        # Make request
        response = self.client.post(
            path=url,
            data=self.data,
            format='json',
        )
        # Assert the response
        self.assertEqual(response.status_code, 200)
        dsd = DigisignDocument.objects.get(document_source=self.loan.id)
        expected_response = {
            'document_source': self.loan.id,
            'document_type': 'loan_agreement_borrower',
            'document_url': 'remote_path_mock',
            'service': 'oss',
            'signing_status': 'completed',
            'document_token': 'b3e4fcb305434a2232b4751700919',
            'reference_number': 'b3e4ffcb307348d2a2232b4751700919'
        }
        self.assertEqual(expected_response, {
            'document_source': self.loan.id,
            'document_type': dsd.document_type,
            'document_url': dsd.document_url,
            'service': dsd.service,
            'signing_status': dsd.signing_status,
            'document_token': dsd.document_token,
            'reference_number': dsd.reference_number
        })

    @patch('juloserver.digisign.services.digisign_document_services.accept_julo_sphp')
    @patch('juloserver.digisign.services.digisign_document_services.upload_signed_document_to_oss')
    @override_settings(JWT_SECRET_KEY="secret-jwt")
    def test_internal_timeout_when_loan_not_inactive(self, mock_upload, mock_accept_julo_sphp):
        """Test that document status is set to INTERNAL_TIMEOUT when loan is not in INACTIVE status."""
        # Set loan status to something other than INACTIVE
        active_status = StatusLookupFactory(status_code=220)  # Assuming 220 is not INACTIVE
        self.loan.loan_status = active_status
        self.loan.save()

        self.token = 'Bearer ' + OnboardingInternalAuthentication.generate_token(
            'digital-signature')
        self.client.credentials(HTTP_AUTHORIZATION=self.token)
        url = '/api/digisign/v1/sign_document/callback'

        response = self.client.post(
            path=url,
            data=self.data,
            format='json',
        )

        # Verify response
        self.assertEqual(response.status_code, 200)

        # Verify document status was updated correctly
        dsd = DigisignDocument.objects.get(document_source=self.loan.id)
        # because loan already changed to 220, that mean we ignore everything update from callback
        self.assertEqual(dsd.signing_status, SigningStatus.PROCESSING)

        mock_upload.assert_not_called()
        mock_accept_julo_sphp.assert_not_called()

    @patch('juloserver.digisign.services.digisign_document_services.accept_julo_sphp')
    @patch('juloserver.digisign.services.digisign_document_services.upload_signed_document_to_oss')
    @override_settings(JWT_SECRET_KEY="secret-jwt")
    def test_internal_timeout_when_loan_inactive(self, mock_upload, mock_accept_julo_sphp):
        """Test that document status is set to INTERNAL_TIMEOUT when loan is not in INACTIVE status."""
        # Set loan status to something other than INACTIVE
        mock_upload.return_value = 'cust_1000168473/application_loan_agreement_borrower/signed_document2024-11-12-18-09.pdf'
        active_status = StatusLookupFactory(status_code=210)  # loan status  = 210
        self.loan.loan_status = active_status
        self.loan.save()

        self.token = 'Bearer ' + OnboardingInternalAuthentication.generate_token(
            'digital-signature')
        self.client.credentials(HTTP_AUTHORIZATION=self.token)
        url = '/api/digisign/v1/sign_document/callback'

        response = self.client.post(
            path=url,
            data=self.data,
            format='json',
        )

        # Verify response
        self.assertEqual(response.status_code, 200)

        # Verify document status was updated correctly
        dsd = DigisignDocument.objects.get(document_source=self.loan.id)
        # because loan still 210, that mean we need update from callback
        self.assertEqual(dsd.signing_status, SigningStatus.COMPLETED)

        mock_upload.assert_called()
        mock_accept_julo_sphp.assert_called()

    @patch('juloserver.digisign.services.digisign_document_services.logger')
    @patch('juloserver.digisign.services.digisign_document_services.accept_julo_sphp')
    @override_settings(JWT_SECRET_KEY="secret-jwt")
    def test_internal_timeout_logs_error(self, mock_accept_julo_sphp, mock_logger):
        """Test that appropriate error is logged when an internal timeout occurs."""
        # Set loan status to something other than INACTIVE
        active_status = StatusLookupFactory(status_code=220)
        self.loan.loan_status = active_status
        self.loan.save()

        self.token = 'Bearer ' + OnboardingInternalAuthentication.generate_token(
            'digital-signature')
        self.client.credentials(HTTP_AUTHORIZATION=self.token)
        url = '/api/digisign/v1/sign_document/callback'

        self.client.post(
            path=url,
            data=self.data,
            format='json',
        )
        mock_logger.error.assert_called_with({
            'action': 'process_callback_digisign',
            'reference_number': 'b3e4ffcb307348d2a2232b4751700919',
            'status': 'completed',
            'based64': 'data:application/pdf;base64, SGVsbG8sIFdvcmxkIQ==',
            'message': 'Loan already changed by task trigger_waiting_callback_timeout'
        })
