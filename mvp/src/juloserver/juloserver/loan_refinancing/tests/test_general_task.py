import mock
from django.utils import timezone
from mock import patch
from django.test import TestCase

from juloserver.julo.tests.factories import PaymentMethodFactory
from juloserver.loan_refinancing.models import LoanRefinancingMainReason, LoanRefinancingSubReason
from juloserver.loan_refinancing.tasks.general_tasks import upload_addendum_pdf_to_oss
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory, \
    LoanRefinancingFactory


class TestCovidLoanRefinancingGeneralTask(TestCase):
    def setUp(self):
        self.loan_ref_req = LoanRefinancingRequestFactory(product_type="R4")
        PaymentMethodFactory(customer=self.loan_ref_req.loan.application.customer,
                             is_primary=True,
                             loan=self.loan_ref_req.loan)
        LoanRefinancingFactory(loan=self.loan_ref_req.loan,
                               refinancing_request_date=timezone.now().date(),
                               refinancing_active_date=timezone.now().date(),
                               loan_refinancing_main_reason=LoanRefinancingMainReason.objects.last(),
                               loan_refinancing_sub_reason=LoanRefinancingSubReason.objects.last()
                               )

    @patch('juloserver.julo.tasks.upload_document')
    @patch('juloserver.loan_refinancing.tasks.general_tasks.pisa.CreatePDF')
    def test_upload_addendum_pdf_to_oss(self, mock_upload, mocked_create_pdf):
        mocked_create_pdf.retur_value = 'test'
        with patch('juloserver.loan_refinancing.tasks.general_tasks.open',
                   mock.mock_open(), create=True):
            upload_addendum_pdf_to_oss(self.loan_ref_req.loan.id)
