import io
import os

import pytest
from django.conf import settings
import mock
from PIL import Image
from unittest.mock import MagicMock

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    PartnerFactory,
    WorkflowFactory,
    ProductLineFactory,
    PartnershipCustomerDataFactory,
    PartnershipApplicationDataFactory,
    CustomerFactory,
    ApplicationFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.merchant_financing.constants import MFComplianceRegisterUpload
from juloserver.merchant_financing.utils import (
    download_pdf_from_restricted_url,
    download_image_from_restricted_url,
)
from juloserver.merchant_financing.web_app.services import (
    mf_register_merchant_upload_csv,
    upload_merchant_financing_onboarding_document,
)
from juloserver.partnership.models import (
    PartnershipDistributor,
    PartnershipApplicationData,
    PartnershipImage,
    PartnershipCustomerData,
    PartnershipDocument,
)


class TestMfRegisterMerchantUploadCsvService(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.agent = AgentFactory(user=self.user_auth)

        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)

        self.partnership_distributor = PartnershipDistributor.objects.create(
            distributor_id="320240520006",
            distributor_name="PT Forward Backward",
            distributor_bank_account_number="2589991995",
            distributor_bank_account_name="PROD ONLY",
            bank_code="14",
            bank_name="BANK CENTRAL ASIA, Tbk (BCA)",
            partner=self.partner,
            is_deleted=False,
        )

        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        self.merchant_data = {
            "proposed_limit": "20000000",
            "distributor_code": self.partnership_distributor.distributor_id,
            "fullname": "Prod merchant",
            "mobile_phone_1": "087850835001",
            "marital_status": "Menikah",
            "gender": "Pria",
            "birth_place": "Jakarta",
            "dob": "1963-04-28",
            "home_status": "Milik sendiri, lunas",
            "spouse_name": "istri Prod merchant",
            "spouse_mobile_phone": "087850835002",
            "kin_name": "ibu Prod merchant",
            "kin_mobile_phone": "087850835003",
            "address_provinsi": "KOTA DENPASAR",
            "address_kabupaten": "PEGUYANGAN KAJA",
            "address_kelurahan": "PEGUYANGAN KAJA",
            "address_kecamatan": "DENPASAR UTARA",
            "address_kodepos": "80115",
            "address_street_num": "JL TUNJUNG TUTUR II NO 4 DENPASAR",
            "bank_name": "BANK CENTRAL ASIA, Tbk (BCA)",
            "bank_account_number": "2589991995",
            "loan_purpose": "Modal Usaha",
            "monthly_income": "148750000",
            "monthly_expenses": "99166667",
            "pegawai": "1",
            "business_type": "Budidaya Ikan",
            "ktp": "5171042804630001",
            "last_education": "S1",
            "npwp": "",
            "email": "prod.only@julofinance.com",
        }

    def test_success_register_merchant(self):
        is_success, message = mf_register_merchant_upload_csv(
            self.merchant_data, self.partner, self.user_auth.id
        )
        self.assertTrue(is_success)
        self.assertEqual("Success register merchant application", message)

    def test_failed_merchant_exists(self):
        customer = CustomerFactory(user=self.user_auth)
        PartnershipCustomerDataFactory(
            customer=customer, email='prod.only@julofinance.com', partner=self.partner
        )

        is_success, message = mf_register_merchant_upload_csv(
            self.merchant_data, self.partner, self.user_auth.id
        )
        self.assertFalse(is_success)
        self.assertEqual("No KTP/Alamat email/No HP Borrower sudah terdaftar", message)

    @staticmethod
    def create_image(image_path, size=(100, 100)):
        image = Image.new('RGB', size, color='red')
        image.save(image_path)

    @staticmethod
    def create_document(pdf_path):
        c = canvas.Canvas(pdf_path, pagesize=letter)
        c.drawString(100, 750, "Hello, this is a PDF file.")
        c.save()

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.merchant_financing.web_app.services.process_application_status_change')
    @mock.patch('juloserver.merchant_financing.web_app.utils.upload_file_to_oss')
    def test_success_file_upload_is_active(self, mock_upload_file_to_oss, mock_status_change):
        mock_upload_file_to_oss.return_value = True
        mock_status_change.return_value = True
        self.merchant_data['file_upload'] = 'aktif'

        dummy_image_path = os.path.join(settings.MEDIA_ROOT, 'image.png')
        self.create_image(dummy_image_path)
        self.merchant_data['ktp_image'] = dummy_image_path
        self.merchant_data['selfie_ktp_image'] = dummy_image_path
        self.merchant_data['agent_merchant_image'] = dummy_image_path
        is_success, message = mf_register_merchant_upload_csv(
            self.merchant_data, self.partner, self.user_auth.id
        )
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            nik=self.merchant_data.get('ktp')
        ).last()
        application_id = partnership_customer_data.application_id
        partnership_images = PartnershipImage.objects.filter(
            application_image_source=application_id
        )
        self.assertTrue(is_success)
        self.assertEqual("Success register merchant application", message)
        self.assertEqual(len(partnership_images), 3)

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.merchant_financing.web_app.services.process_application_status_change')
    @mock.patch('juloserver.merchant_financing.web_app.utils.upload_file_to_oss')
    def test_success_file_upload_is_active_with_cahsflow_report(
        self, mock_upload_file_to_oss, mock_status_change
    ):
        mock_upload_file_to_oss.return_value = True
        mock_status_change.return_value = True
        self.merchant_data['file_upload'] = 'aktif'

        dummy_image_path = os.path.join(settings.MEDIA_ROOT, 'image.png')
        self.create_image(dummy_image_path)
        self.merchant_data['ktp_image'] = dummy_image_path
        self.merchant_data['selfie_ktp_image'] = dummy_image_path
        self.merchant_data['agent_merchant_image'] = dummy_image_path
        pdf_path = os.path.join(settings.MEDIA_ROOT, 'document.pdf')
        self.create_document(pdf_path)
        self.merchant_data['cashflow_report'] = pdf_path
        is_success, message = mf_register_merchant_upload_csv(
            self.merchant_data, self.partner, self.user_auth.id
        )
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            nik=self.merchant_data.get('ktp')
        ).last()
        application_id = partnership_customer_data.application_id
        partnership_images = PartnershipImage.objects.filter(
            application_image_source=application_id
        )
        partnership_document = PartnershipDocument.objects.filter(document_source=application_id)
        self.assertTrue(is_success)
        self.assertEqual("Success register merchant application", message)
        self.assertEqual(len(partnership_images), 3)
        self.assertEqual(len(partnership_document), 1)

    def test_failed_file_upload_is_active_with_no_document(self):
        self.merchant_data['file_upload'] = 'aktif'
        is_success, message = mf_register_merchant_upload_csv(
            self.merchant_data, self.partner, self.user_auth.id
        )
        self.assertFalse(is_success)
        self.assertEqual("Failed register merchant application", message)


class TestMFStandardUploadDocumentOnboarding(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.partner_name = "efishery"
        self.partner = PartnerFactory(name=self.partner_name, is_active=True)
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )

    @staticmethod
    def create_image(size=(100, 100), image_format='PNG'):
        data = io.BytesIO()
        Image.new('RGB', size).save(data, image_format)
        data.seek(0)
        return data

    @mock.patch('juloserver.merchant_financing.web_app.services.upload_file_as_bytes_to_oss')
    def test_upload_merchant_financing_onboarding_document_upload_single_file(
        self, mock_upload_to_oss: MagicMock
    ):
        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        application_id = self.application.id
        customer_id = self.customer.id
        customer_data = {
            'application_id': application_id,
            'customer_id': customer_id,
            'created_by_user_id': self.user.id,
        }
        data_image = {'ktp': image_file}
        is_multiple = False
        result_upload, is_success = upload_merchant_financing_onboarding_document(
            data=data_image, customer_data=customer_data, is_multiple=is_multiple
        )
        self.assertIsInstance(result_upload, dict)
        self.assertTrue(is_success)
        mock_upload_to_oss.assert_called_once()

    @mock.patch('juloserver.merchant_financing.web_app.services.upload_file_as_bytes_to_oss')
    def test_upload_merchant_financing_onboarding_document_upload_multiple_file(
        self, mock_upload_to_oss: MagicMock
    ):
        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        application_id = self.application.id
        customer_id = self.customer.id
        customer_data = {
            'application_id': application_id,
            'customer_id': customer_id,
            'created_by_user_id': self.user.id,
        }
        data_image = {'company_photo': [image_file, image_file]}
        is_multiple = True
        result_upload, is_success = upload_merchant_financing_onboarding_document(
            data=data_image, customer_data=customer_data, is_multiple=is_multiple
        )
        self.assertIsInstance(result_upload, list, "The returned value is not a list")
        self.assertTrue(is_success)
        self.assertEqual(mock_upload_to_oss.call_count, 2)
