import mock
import tempfile
import os
from django.test.testcases import TestCase

from django.conf import settings
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory
from juloserver.disbursement.tests.factories import DisbursementFactory
from juloserver.education.services.tasks_related import (
    get_education_invoice_template,
    generate_education_invoice,
    send_email_education_invoice,
    get_education_invoice_attachment,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    DocumentFactory,
)
from juloserver.education.constants import EducationConst
from juloserver.education.tests.factories import (
    StudentRegisterFactory,
    LoanStudentRegisterFactory,
)
from juloserver.loan.tests.factories import TransactionMethodFactory
from juloserver.payment_point.constants import TransactionMethodCode


class TestEducationServicesViewsRelated(TestCase):
    def setUp(self):
        self.student_register = StudentRegisterFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.disbursement = DisbursementFactory(
            reference_id='contract_0b797cb8f5984e0e89eb802a009fa5f4'
        )
        self.education_transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.EDUCATION.code,
            method=TransactionMethodCode.EDUCATION.name,
            fe_display_name='Biaya Pendidikan',
        )
        self.loan = LoanFactory(
            fund_transfer_ts=timezone.now(),
            customer=self.customer,
            account=self.account,
            disbursement_id=self.disbursement.id,
            transaction_method=self.education_transaction_method,
        )
        self.education_transaction = LoanStudentRegisterFactory(
            loan=self.loan, student_register=self.student_register
        )
        self.filename = 'invoice_{}{}.pdf'.format(
            self.student_register.school_id, self.loan.loan_xid
        )
        self.document = DocumentFactory(
            document_source=self.loan.id,
            document_type=EducationConst.DOCUMENT_TYPE,
            filename=self.filename,
            loan_xid=self.loan.loan_xid,
        )

    def test_get_education_invoice_template(self):
        self._test_get_education_invoice_template(template_name='invoice_pdf.html')
        self._test_get_education_invoice_template(
            template_name='invoice_email.html', is_for_email=True
        )

    def _test_get_education_invoice_template(self, template_name, is_for_email=False):
        self.assertRaises(
            Exception,
            get_education_invoice_template,
            education_transaction=None,
            template=EducationConst.TEMPLATE_PATH + template_name,
        )

        # test show note
        education_invoice_html = get_education_invoice_template(
            self.education_transaction,
            EducationConst.TEMPLATE_PATH + template_name,
            is_for_email=is_for_email,
        )
        self.assertIsNotNone(education_invoice_html)
        self.assertIn('Keterangan', education_invoice_html)

        # test greeting exist in email
        if is_for_email:
            self.assertIn(
                'Halo {}!'.format(self.education_transaction.loan.customer.fullname),
                education_invoice_html,
            )

        self.assertIn(self.education_transaction_method.fe_display_name, education_invoice_html)

        # test hide note
        old_note = self.student_register.note
        self.student_register.note = ''
        self.student_register.save()
        education_invoice_html = get_education_invoice_template(
            self.education_transaction,
            EducationConst.TEMPLATE_PATH + template_name,
        )
        self.assertIsNotNone(education_invoice_html)
        self.assertNotIn('Keterangan', education_invoice_html)
        self.student_register.note = old_note
        self.student_register.save()

    @mock.patch('pdfkit.from_string')
    def test_generate_education_invoice(self, mock_pdf_kit):
        self.assertRaises(Exception, generate_education_invoice, education_transaction=None)

        mock_pdf_kit.return_value = True
        local_path = os.path.join(tempfile.gettempdir(), self.filename)
        with open(local_path, 'w') as f:
            f.write("PDF file")
        self.assertIsNone(generate_education_invoice(self.education_transaction))

    def test_send_email_education_invoice(self):
        self.assertRaises(Exception, send_email_education_invoice, education_transaction=None)

    def test_get_education_invoice_attachment(self):
        self.assertRaises(Exception, get_education_invoice_attachment, education_transaction=None)
