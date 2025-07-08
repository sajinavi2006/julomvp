from django.test.testcases import TestCase

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    PartnerFactory,
    PartnershipCustomerDataFactory,
    ProductLineFactory,
    WorkflowFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.merchant_financing.web_app.crm.serializers import (
    MFWebAppUploadRegisterSerializer,
)
from juloserver.partnership.models import PartnershipFlowFlag
from juloserver.partnership.constants import PartnershipFlag


class TestMFWebAppUploadRegisterSerializer(TestCase):
    def setUp(self) -> None:
        self.data = {
            "nik_number": "2339860101912711",
            "email_borrower": "prod+testaxiataupload10322@julofinance.com",
            "customer_name": "Jaka Cakrawala 1",
            "date_of_birth": "01/01/1997",
            "place_of_birth": "Denpasar",
            "zipcode": "23611",
            "marital_status": "Menikah",
            "handphone_number": "082218021557",
            "company_name": "PT YAYA INDONESIA",
            "address": "tes",
            "provinsi": "JAWA BARAT",
            "kabupaten": "Bogor",
            "education": "DIPLOMA",
            "total_revenue_per_year": "5000000",
            "gender": "Wanita",
            "business_category": "Advertising",
            "proposed_limit": "50000000",
            "product_line": "",
            "nib_number": "1234567891111"
        }
        self.partner = PartnerFactory(is_active=True, name="Axiata Web")
        self.partnership_flow_flag = PartnershipFlowFlag.objects.create(
            partner=self.partner,
            name=PartnershipFlag.FIELD_CONFIGURATION,
            configs={
                'fields': {
                    'user_type': False,
                    'kin_name': False,
                    'kin_mobile_phone': False,
                    'home_status': False,
                    'certificate_number': False,
                    'certificate_date': False,
                    'npwp': False,
                },
                'perorangan': [
                    'home_status',
                    'kin_name',
                    'kin_mobile_phone',
                ],
                'lembaga': [
                    'certificate_number',
                    'certificate_date',
                    'npwp',
                    'kin_name',
                    'kin_mobile_phone',
                ],
            },
        )
        self.configs = self.partnership_flow_flag.configs

    def test_valid_data(self):
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        self.assertTrue(serializer.is_valid())
    
    def test_invalid_nib_number(self):
        self.data['nib_number'] = "121"
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'nib_number': ['NIB tidak valid, NIB harus menggunakan 13 digit angka']},
            serializer.errors
        )
    
    def test_invalid_date_of_birth(self):
        self.data['date_of_birth'] = "28/04/1997"
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {
                'date_of_birth': [
                    'tanggal akta tidak valid, hanya boleh isi tanggal sesuai format MM/DD/YYYY'
                ]
            },
            serializer.errors,
        )

    def test_invalid_gender(self):
        self.data['gender'] = "Woman"
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'gender': ['Gender tidak sesuai']},
            serializer.errors
        )

    def test_invalid_business_category(self):
        self.data['business_category'] = "Advertising1"
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'business_category': ['Kategori bisnis data tidak valid']},
            serializer.errors
        )

    def test_invalid_provinsi(self):
        self.data['provinsi'] = "JAWA"
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'provinsi': ['Provinsi data tidak valid']},
            serializer.errors
        )

    def test_invalid_kabupaten(self):
        self.data['kabupaten'] = "BGR"
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'kabupaten': ['Kabupaten data tidak valid']},
            serializer.errors
        )

    def test_invalid_nik(self):
        workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.AXIATA_WEB)

        application = ApplicationFactory(
            workflow=workflow,
            partner=self.partner,
            product_line=product_line,
        )

        partnership_customer_data = PartnershipCustomerDataFactory(
            nik=self.data["nik_number"],
            application=application,
        )

        # NIK Already use
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'nik_number': ['NIK Anda sudah terdaftar']},
            serializer.errors
        )

        # Invalid NIK
        self.data["nik_number"] = '233986010'
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'nik_number': ['NIK Tidak Valid']},
            serializer.errors
        )

    def test_invalid_email_borrower(self):
        workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.AXIATA_WEB)

        application = ApplicationFactory(
            workflow=workflow,
            partner=self.partner,
            product_line=product_line,
        )

        partnership_customer_data = PartnershipCustomerDataFactory(
            email=self.data["email_borrower"],
            application=application,
        )

        # Email Already use
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'email_borrower': ['Email Anda sudah terdaftar']},
            serializer.errors
        )

        # Invalid Email Format
        self.data["email_borrower"] = '233986010'
        serializer = MFWebAppUploadRegisterSerializer(
            data=self.data, context={'field_configs': self.configs}
        )
        serializer.is_valid()
        self.assertEqual(
            {'email_borrower': ['Email data tidak valid']},
            serializer.errors
        )
