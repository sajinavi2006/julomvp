import mock
import tempfile
import os

from django.contrib.contenttypes.models import ContentType
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.account.utils import get_first_12_digits
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.healthcare.models import HealthcareUser
from juloserver.healthcare.services.tasks_related import (
    get_healthcare_invoice_template,
    generate_healthcare_invoice,
    send_email_healthcare_invoice,
)
from juloserver.julo.models import EmailHistory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    DocumentFactory,
)
from juloserver.healthcare.constants import HealthcareConst
from juloserver.healthcare.factories import HealthcareUserFactory
from juloserver.loan.models import AdditionalLoanInformation
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode


class TestHealthcareServicesViewsRelated(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.disbursement = DisbursementFactory(
            reference_id='contract_0b123cb4f5678ee9eb100a109fa5f4'
        )
        self.healthcare_user = HealthcareUserFactory(account=self.account)
        self.healthcare_transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.HEALTHCARE.code,
            method=TransactionMethodCode.HEALTHCARE.name,
            fe_display_name='Biaya Kesehatan',
        )
        self.loan = LoanFactory(
            fund_transfer_ts=timezone.now(),
            customer=self.customer,
            account=self.account,
            disbursement_id=self.disbursement.id,
            transaction_method=self.healthcare_transaction_method,
            bank_account_destination=BankAccountDestinationFactory(customer=self.customer),
        )
        AdditionalLoanInformation.objects.create(
            content_type=ContentType.objects.get_for_model(HealthcareUser),
            object_id=self.healthcare_user.id,
            loan=self.loan,
        )
        self.filename = 'invoice_{}{}.pdf'.format(self.healthcare_user.id, self.loan.loan_xid)
        self.document = DocumentFactory(
            document_source=self.loan.id,
            document_type=HealthcareConst.DOCUMENT_TYPE_INVOICE,
            filename=self.filename,
            loan_xid=self.loan.loan_xid,
        )

    def test_get_healthcare_invoice_template(self):
        self._test_get_healthcare_invoice_template('invoice_pdf.html')
        self._test_get_healthcare_invoice_template('invoice_email.html', is_for_email=True)

    def _test_get_healthcare_invoice_template(self, template_name, is_for_email=False):
        healthcare_invoice_html = get_healthcare_invoice_template(
            self.healthcare_user,
            self.loan,
            template_name,
        )

        # test opening and closing text exist in email
        if is_for_email:
            self.assertIn(
                'Halo {},'.format(self.loan.get_application.fullname_with_title),
                healthcare_invoice_html,
            )

        self.assertIn(
            self.healthcare_transaction_method.foreground_icon_url, healthcare_invoice_html
        )
        self.assertIn(self.healthcare_transaction_method.fe_display_name, healthcare_invoice_html)
        self.assertIn(get_first_12_digits(self.disbursement.reference_id), healthcare_invoice_html)

    @mock.patch('pdfkit.from_string')
    @mock.patch('juloserver.healthcare.services.tasks_related.upload_document')
    def test_generate_healthcare_invoice(self, mock_upload_document, mock_pdf_kit):
        mock_pdf_kit.return_value = True
        mock_upload_document.return_value = True
        self.assertIsNone(generate_healthcare_invoice(self.healthcare_user, self.loan))

    @mock.patch('juloserver.healthcare.services.tasks_related.get_julo_email_client')
    @mock.patch('juloserver.healthcare.services.tasks_related.get_pdf_content_from_html')
    def test_send_email_healthcare_invoice(self, mock_get_pdf_content_from_html, mock_email_client):
        mock_email_client().send_email.return_value = None, None, {'X-Message-Id': 123}
        mock_get_pdf_content_from_html.return_value = ''
        self.assertIsNone(send_email_healthcare_invoice(self.healthcare_user, self.loan))
        self.assertTrue(EmailHistory.objects.filter(customer=self.customer).exists())
