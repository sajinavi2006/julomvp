from django.test import TestCase
from unittest.mock import patch, MagicMock
from juloserver.digisign.constants import LoanAgreementSignature, DocumentType, SigningStatus
from juloserver.digisign.tests.factories import DigisignDocumentFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.digisign.tasks import (
    initial_record_digisign_document,
    get_agreement_template,
    generate_filename,
    get_signature_position,
    prepare_request_structs,
    sign_document,
)
from juloserver.julo.tests.factories import LoanFactory, AuthUserFactory, CustomerFactory, \
    StatusLookupFactory, WorkflowFactory, ProductLineFactory, ApplicationFactory


class TestSignDocumentFunctions(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.loan = LoanFactory(application=self.application, account=self.account)

    @patch('juloserver.digisign.tasks.DigisignDocument.objects.create')
    def test_create_digisign_document(self, mock_create):
        mock_create.return_value = MagicMock()
        document = initial_record_digisign_document(1)
        self.assertIsNotNone(document)
        mock_create.assert_called_once_with(
            document_source=1, document_type='loan_agreement_borrower', signing_status='processing'
        )

    @patch('juloserver.digisign.tasks.get_julo_loan_agreement_template')
    def test_get_agreement_template(self, mock_get_template):
        mock_get_template.return_value = ('template_body',)
        body = get_agreement_template(1)
        self.assertEqual(body, 'template_body')
        mock_get_template.assert_called_once_with(1, is_new_digisign=True)

    def test_generate_filename(self):
        self.application.fullname = 'John Doe'
        self.application.save()
        self.loan.update_safely(loan_xid='12345')
        filename = generate_filename(self.loan)
        self.assertIn('John Doe_12345', filename)

    def test_get_signature_position(self):
        pos = get_signature_position(self.application)
        self.assertEqual(pos, LoanAgreementSignature.j1())

    def test_create_document_detail(self):
        self.digisign_document = DigisignDocumentFactory(
            document_type=DocumentType.LOAN_AGREEMENT_BORROWER,
            document_source=12345,
        )
        detail = prepare_request_structs(
            self.digisign_document, 'filename.pdf', 100, 200, 1
        )
        self.assertEqual(
            detail['digisign_document_id'],
            '{}_loan_agreement_borrower'.format(self.digisign_document.id)
        )
        self.assertEqual(detail['file_name'], 'filename.pdf')
        self.assertEqual(detail['sign_positions'][0]['pos_x'], "100")
        self.assertEqual(detail['sign_positions'][0]['pos_y'], "200")
        self.assertEqual(detail['sign_positions'][0]['sign_page'], "1")

    @patch('juloserver.digisign.tasks.get_agreement_template')
    @patch('juloserver.digisign.tasks.sign_with_digisign')
    @patch('juloserver.digisign.tasks.generate_filename')
    def test_sign_document_success(self, mock_generate_filename, mock_sign, mock_get_template):
        mock_get_template.return_value = '<p>template_body</p>'
        mock_generate_filename.return_value = 'file5.pdf'
        mock_sign.return_value = (
            True, {
                'status': 'processing',
                'document_token': 'b3e4fcb305434a2232b4751700919',
                'reference_number': 'b3e4ffcb307348d2a2232b4751700919',
                'file_name': 'file5.pdf'
            }
        )
        self.status = StatusLookupFactory()
        self.status.status_code = 210
        self.status.save()
        loan = LoanFactory(loan_status=self.status, account=self.account)
        digisign = DigisignDocumentFactory(
            document_type=DocumentType.LOAN_AGREEMENT_BORROWER,
            document_source=loan.id,
            signing_status=SigningStatus.PROCESSING
        )
        sign_document(digisign.id)
        mock_get_template.assert_called_once_with(loan.id)
        mock_generate_filename.assert_called_once()
        mock_sign.assert_called_once()
        expected_response = {
            'status': 'processing',
            'document_token': 'b3e4fcb305434a2232b4751700919',
            'reference_number': 'b3e4ffcb307348d2a2232b4751700919',
        }
        digisign.refresh_from_db()
        self.assertEqual(expected_response, {
            'status': digisign.signing_status,
            'document_token': digisign.document_token,
            'reference_number': digisign.reference_number,
        })
