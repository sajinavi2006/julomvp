from datetime import date
from django.http import HttpResponse
from django.test.testcases import TestCase
from mock import MagicMock, patch
from rest_framework import status
from rest_framework.test import APIClient

from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.dana.constants import DanaErrorMessage
from juloserver.dana.loan.services import dana_generate_hashed_loan_xid
from juloserver.dana.tests.factories import DanaCustomerDataFactory, DanaLoanReferenceFactory
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.models import Partner, Application
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    DocumentFactory,
    LoanFactory,
    PartnerFactory,
    StatusLookupFactory,
    WorkflowFactory,
    FeatureSettingFactory,
)
from juloserver.partnership.tests.factories import PartnerLoanRequestFactory
from juloserver.pusdafil.services import validate_pusdafil_customer_data


class TestDanaAgreementContentView(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.user_partner = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_partner, name="dana")

        self.status_lookup = StatusLookupFactory()

        workflow = WorkflowFactory(name=WorkflowConst.DANA, handler='DanaWorkflowHandler')
        customer = CustomerFactory(user=user)
        self.application = ApplicationFactory(
            customer=customer, workflow=workflow, partner=self.partner
        )
        self.account_lookup = AccountLookupFactory(
            workflow=workflow, name='Dana', payment_frequency='weekly'
        )
        self.account = AccountFactory(
            customer=customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=customer,
            partner=self.partner,
            dana_customer_identifier="12345679237",
            dob=date(2023, 1, 1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=customer,
            application=self.application,
            loan_amount=10000000,
        )
        self.partner_loan = PartnerLoanRequestFactory(
            loan=self.loan,
            partner=self.partner,
            loan_amount=self.loan.loan_amount,
            loan_disbursement_amount=self.loan.loan_disbursement_amount,
        )
        loan_xid_encoded = dana_generate_hashed_loan_xid(self.loan.loan_xid)
        self.endpoint = '/v1.0/agreement/content/{}'.format(loan_xid_encoded)
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DANA_AGREEMENT_PASSWORD,
            description="Dana Agreement PDF password",
            parameters={},
        )
        self.customer_id = customer.id

    def test_agreement_content_with_invalid_loan_xid(self) -> None:
        self.loan.loan_xid = 23234234
        self.loan.save()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.content:
            self.assertEqual(response.content.decode(), DanaErrorMessage.INVALID_LOAN_XID)

    def test_agreement_content_with_no_document(self) -> None:
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.content:
            self.assertEqual(response.content.decode(), DanaErrorMessage.DOCUMENT_NOT_FOUND)

    @patch('juloserver.dana.loan.views.requests.get')
    @patch('juloserver.julo.models.Document.document_url')
    @patch('juloserver.dana.loan.views.PdfFileReader')
    @patch('juloserver.dana.loan.views.PdfFileWriter')
    def test_agreement_content_success(
        self,
        mock_pdf_writer: MagicMock,
        mock_pdf_reader: MagicMock,
        mock_get_doc_url: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        doc_url = 'https://www.julo.co.id/'
        DocumentFactory(document_type="dana_loan_agreement", loan_xid=self.loan.loan_xid)
        mock_get_doc_url.return_value = doc_url
        mock_request.return_value = HttpResponse(content="")
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_agreement_content_with_loan_not_created(self) -> None:
        self.dana_loan_reference = DanaLoanReferenceFactory(customer_id=self.customer_id)
        reference_id_encoded = dana_generate_hashed_loan_xid(self.dana_loan_reference.id)
        self.endpoint = '/v1.0/agreement/content/{}'.format(reference_id_encoded)
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.content:
            self.assertEqual(response.content.decode(), DanaErrorMessage.AGREEMENT_IN_PROCESS)


class TestDanaValidateCustomerDataView(TestCase):
    """
    check for these case if null or not in the map:
    1. application.gender
    2. application.address_kabupaten
    3. application.address_provinsi
    4. application.address_kodepos
    5. application.marital_status
    6. application.job_type
    7. application.job_industry
    8. application.monthly_income
    """

    def test_validate_pusdafil_customer_data_success(self) -> None:
        application_success = ApplicationFactory(
            gender="Pria",
            address_kabupaten="TANGERANG",
            address_provinsi="JAKARTA",
            address_kodepos="12345",
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        application_success.save()

        application_fail_gender = ApplicationFactory(
            gender="",
            address_kabupaten="TANGERANG",
            address_provinsi="JAKARTA",
            address_kodepos="12345",
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        application_fail_gender.save()

        application_fail_kabupaten = ApplicationFactory(
            gender="Pria",
            address_kabupaten="BUKAN KOTA",
            address_provinsi="JAKARTA",
            address_kodepos="12345",
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        application_fail_kabupaten.save()

        application_fail_provinsi = ApplicationFactory(
            gender="Pria",
            address_kabupaten="TANGERANG",
            address_provinsi="BUKAN PROVINSI",
            address_kodepos="12345",
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        application_fail_provinsi.save()

        application_fail_kodepos = ApplicationFactory(
            gender="Pria",
            address_kabupaten="TANGERANG",
            address_provinsi="JAKARTA",
            address_kodepos="abcde",
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        application_fail_kodepos.save()

        application_fail_kodepos2 = ApplicationFactory(
            gender="Pria",
            address_kabupaten="TANGERANG",
            address_provinsi="JAKARTA",
            address_kodepos=None,
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        application_fail_kodepos2.save()

        application_fail_marital_status = ApplicationFactory(
            gender="Pria",
            address_kabupaten="TANGERANG",
            address_provinsi="JAKARTA",
            address_kodepos="12345",
            marital_status="Tidak Menikah",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        application_fail_marital_status.save()

        application_fail_job_type = ApplicationFactory(
            gender="Pria",
            address_kabupaten="TANGERANG",
            address_provinsi="JAKARTA",
            address_kodepos="12345",
            marital_status="Cerai",
            job_type="Job Type test",
            job_industry="Tidak bekerja",
            monthly_income=1000000,
        )
        application_fail_job_type.save()

        application_fail_job_industry = ApplicationFactory(
            gender="Pria",
            address_kabupaten="TANGERANG",
            address_provinsi="JAKARTA",
            address_kodepos="12345",
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Job Industry Test",
            monthly_income=1000000,
        )
        application_fail_job_industry.save()

        application_fail_monthly_income = ApplicationFactory(
            gender="Pria",
            address_kabupaten="TANGERANG",
            address_provinsi="JAKARTA",
            address_kodepos="12345",
            marital_status="Cerai",
            job_type="Tidak bekerja",
            job_industry="Tidak bekerja",
            monthly_income=None,
        )
        application_fail_monthly_income.save()

        applications = Application.objects.all()

        result = validate_pusdafil_customer_data(applications)
        self.assertEqual(result, [application_success])
