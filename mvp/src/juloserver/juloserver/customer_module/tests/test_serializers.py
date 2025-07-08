from io import BytesIO

from django.core.files.uploadedfile import (
    InMemoryUploadedFile,
    SimpleUploadedFile,
)
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from juloserver.account.tests.factories import AddressFactory
from juloserver.customer_module.models import CustomerDataChangeRequest
from juloserver.customer_module.serializers import (
    CustomerDataChangeRequestApprovalSerializer,
    CustomerDataChangeRequestCompareSerializer,
    CustomerDataChangeRequestCRMSerializer,
    CustomerDataChangeRequestListSerializer,
    CustomerDataChangeRequestSerializer,
)
from juloserver.customer_module.services.customer_related import (
    CustomerDataChangeRequestHandler,
)
from juloserver.customer_module.tests.factories import (
    CustomerDataChangeRequestFactory,
    CXDocumentFactory,
)
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    FeatureSettingFactory,
    ImageFactory,
    StatusLookupFactory,
)


class TestCustomerDataChangeRequestSerializer(TestCase):
    def setUp(self):
        self.change_request = CustomerDataChangeRequestFactory(
            address=AddressFactory(
                latitude=1.2,
                longitude=3.4,
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos=12140,
                detail='Jl. Gandaria I No. 1',
            ),
            job_type='karyawan',
            job_industry='perbankan',
            job_description='mengelola uang',
            company_name='PT. Bank Julo',
            company_phone_number='0211234567',
            payday=15,
            monthly_income=10000000,
            monthly_expenses=5000000,
            monthly_housing_cost=2000000,
            total_current_debt=1000000,
            last_education="S1",
            address_transfer_certificate_image=ImageFactory(
                url='address_transfer_certificate_image.jpg',
            ),
            company_proof_image=ImageFactory(
                url='company_proof_image.jpg',
            ),
            paystub_image=ImageFactory(
                url='paystub_image.jpg',
            ),
            payday_change_reason="lainnya",
            payday_change_proof_image_id=CXDocumentFactory(
                url='payday_change_proof_image.jpg',
            ).id,
        )

    def test_serializer_data(self):
        serializer = CustomerDataChangeRequestSerializer(self.change_request)
        expected_data = {
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'address_latitude': 1.2,
            'address_longitude': 3.4,
            'job_type': 'karyawan',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'last_education': 'S1',
            'payday_change_reason': 'lainnya',
        }
        expected_paystub_image_url = (
            'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/paystub_image.jpg'
        )
        expected_company_proof_image_url = (
            'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg'
        )
        expected_address_transfer_certificate_image_url = 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/address_transfer_certificate_image.jpg'
        expected_payday_change_proof_image_url = 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/payday_change_proof_image.jpg'

        ret_val = serializer.data
        self.assertIn(expected_paystub_image_url, ret_val.pop('paystub_image_url'))
        self.assertIn(expected_company_proof_image_url, ret_val.pop('company_proof_image_url'))
        self.assertIn(
            expected_payday_change_proof_image_url,
            ret_val.pop('payday_change_proof_image_url'),
        )
        self.assertIn(
            expected_address_transfer_certificate_image_url,
            ret_val.pop('address_transfer_certificate_image_url'),
        )
        self.assertEqual(expected_data, ret_val)

    def test_serializer_data_empty_model(self):
        change_request = CustomerDataChangeRequest()
        serializer = CustomerDataChangeRequestSerializer(change_request)
        expected_data = {
            'address_street_num': None,
            'address_provinsi': None,
            'address_kabupaten': None,
            'address_kecamatan': None,
            'address_kelurahan': None,
            'address_kodepos': None,
            'address_latitude': None,
            'address_longitude': None,
            'job_type': None,
            'job_industry': None,
            'job_description': None,
            'company_name': None,
            'company_phone_number': None,
            'payday': None,
            'monthly_income': None,
            'monthly_expenses': None,
            'monthly_housing_cost': None,
            'total_current_debt': None,
            'last_education': None,
            'paystub_image_url': None,
            'company_proof_image_url': None,
            'address_transfer_certificate_image_url': None,
            'payday_change_reason': None,
            'payday_change_proof_image_url': "",
        }
        self.assertEqual(expected_data, serializer.data)

    def construct_submit_data(self, **kwargs):
        data = {
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'address_latitude': 1.2,
            'address_longitude': 3.4,
            'job_type': 'Pegawai negeri',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'last_education': 'S1',
            'app_version': '1.0.0',
            'android_id': '1234567890',
            'latitude': 1.0,
            'longitude': 2.0,
        }
        data.update(**kwargs)
        return data

    def test_is_valid_check_paystub_image_id(self):
        image = ImageFactory(image_source='1', image_type='paystub')
        incorrect_image = ImageFactory(image_source='1', image_type='not-paystub')
        data = self.construct_submit_data(
            paystub_image_id=image.id,
        )

        # Using other image
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 2})
        self.assertFalse(serializer.is_valid())
        self.assertIn('paystub_image_id', serializer.errors)

        # Using correct image
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 1})
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Using incorrect image
        data['paystub_image_id'] = incorrect_image.id
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 1})
        self.assertFalse(serializer.is_valid())
        self.assertIn('paystub_image_id', serializer.errors)

    def test_is_valid_check_company_proof_image_id(self):
        image = ImageFactory(image_source='1', image_type='company_proof')
        incorrect_image = ImageFactory(image_source='1', image_type='not-company_proof')
        data = self.construct_submit_data(
            company_proof_image_id=image.id,
        )

        # Using other image
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 2})
        self.assertFalse(serializer.is_valid())
        self.assertIn('company_proof_image_id', serializer.errors)

        # Using correct image
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 1})
        self.assertTrue(serializer.is_valid(), serializer.errors)

        # Using incorrect image
        data['company_proof_image_id'] = incorrect_image.id
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 1})
        self.assertFalse(serializer.is_valid())
        self.assertIn('company_proof_image_id', serializer.errors)

    def test_paystub_image_is_required(self):
        data = self.construct_submit_data(monthly_income=11000, paystub_image_id=None)
        change_request = CustomerDataChangeRequestFactory(monthly_income=10000)
        serializer = CustomerDataChangeRequestSerializer(
            data=data,
            context={
                'previous_change_request': change_request,
            },
        )
        serializer.is_valid()
        self.assertIn('paystub_image_id', serializer.errors)

    def test_paystub_image_is_required_threshold(self):
        change_request = CustomerDataChangeRequestFactory(monthly_income=10000)

        # The requested change is less than 20% of the previous change request
        data = self.construct_submit_data(monthly_income=11000, paystub_image_id=None)
        serializer = CustomerDataChangeRequestSerializer(
            data=data,
            context={
                'previous_change_request': change_request,
                'payslip_income_multiplier': 1.2,
            },
        )
        serializer.is_valid()
        self.assertNotIn('paystub_image_id', serializer.errors)

        # The requested change is less than the previous change request
        data = self.construct_submit_data(monthly_income=9000, paystub_image_id=None)
        serializer = CustomerDataChangeRequestSerializer(
            data=data,
            context={
                'previous_change_request': change_request,
                'payslip_income_multiplier': 1.2,
            },
        )
        serializer.is_valid()
        self.assertNotIn('paystub_image_id', serializer.errors)

        # The requested change is more than 20% of the previous change request
        data = self.construct_submit_data(monthly_income=12000, paystub_image_id=None)
        serializer = CustomerDataChangeRequestSerializer(
            data=data,
            context={
                'previous_change_request': change_request,
                'payslip_income_multiplier': 1.2,
            },
        )
        serializer.is_valid()
        self.assertIn('paystub_image_id', serializer.errors)

    def test_company_proof_image_is_not_required(self):
        data = self.construct_submit_data(company_name='Old', company_proof_image_id=None)
        change_request = CustomerDataChangeRequestFactory(
            job_type='Job Type',
            job_industry='Job Industry',
            job_description='Job Description',
            company_name='PT. Julo',
            company_phone_number='0211234567',
            payday=15,
        )
        serializer = CustomerDataChangeRequestSerializer(
            data=data,
            context={
                'previous_change_request': change_request,
            },
        )
        serializer.is_valid()
        self.assertNotIn('company_proof_image_id', serializer.errors)

    def test_is_valid_no_change_data(self):
        data = self.construct_submit_data()
        change_request = CustomerDataChangeRequestFactory(
            address=AddressFactory(
                detail=data['address_street_num'],
                provinsi=data['address_provinsi'],
                kabupaten=data['address_kabupaten'],
                kecamatan=data['address_kecamatan'],
                kelurahan=data['address_kelurahan'],
                kodepos=data['address_kodepos'],
                latitude=123,
                longitude=1,
            ),
            job_type=data['job_type'],
            job_industry=data['job_industry'],
            job_description=data['job_description'],
            company_name=data['company_name'],
            company_phone_number=data['company_phone_number'],
            payday=data['payday'],
            monthly_income=data['monthly_income'],
            monthly_expenses=data['monthly_expenses'],
            monthly_housing_cost=data['monthly_housing_cost'],
            total_current_debt=data['total_current_debt'],
            last_education=data['last_education'],
            app_version=data['app_version'],
            android_id=data['android_id'],
            latitude=data['latitude'],
            longitude=data['longitude'],
        )
        serializer = CustomerDataChangeRequestSerializer(
            data=data,
            context={
                'previous_change_request': change_request,
            },
        )
        ret_val = serializer.is_valid()
        self.assertFalse(ret_val)

    def test_job_type_required_field(self):
        data = self.construct_submit_data(
            job_type='Pegawai Swasta',
            job_industry=None,
            job_description=None,
            company_name=None,
            payday=0,
        )
        change_request = CustomerDataChangeRequestFactory(
            address=AddressFactory(
                detail=data['address_street_num'],
                provinsi=data['address_provinsi'],
                kabupaten=data['address_kabupaten'],
                kecamatan=data['address_kecamatan'],
                kelurahan=data['address_kelurahan'],
                kodepos=data['address_kodepos'],
                latitude=data['address_latitude'],
                longitude=data['address_longitude'],
            ),
            job_type=data['job_type'],
            job_industry="Job Industry",
            job_description="Job Description",
            company_name="PT. Julo",
            company_phone_number=data['company_phone_number'],
            payday=1,
            monthly_income=data['monthly_income'],
            monthly_expenses=data['monthly_expenses'],
            monthly_housing_cost=data['monthly_housing_cost'],
            total_current_debt=data['total_current_debt'],
            app_version=data['app_version'],
            android_id=data['android_id'],
            latitude=data['latitude'],
            longitude=data['longitude'],
        )
        serializer = CustomerDataChangeRequestSerializer(
            data=data,
            context={
                'previous_change_request': change_request,
            },
        )
        ret_val = serializer.is_valid()
        self.assertFalse(ret_val, serializer.errors)
        self.assertNotIn('job_industry', serializer.errors)
        self.assertNotIn('job_description', serializer.errors)
        self.assertNotIn('company_name', serializer.errors)
        self.assertNotIn('company_phone_number', serializer.errors)
        self.assertNotIn('payday', serializer.errors)

    def test_job_type_no_payday(self):
        job_types = ('Ibu rumah tangga', 'Mahasiswa', 'Tidak bekerja')
        for job_type in job_types:
            data = self.construct_submit_data(
                job_type=job_type,
                job_industry='',
                job_description='',
                company_name='',
                company_phone_number='',
                payday=0,
            )
            change_request = CustomerDataChangeRequestFactory(
                address=AddressFactory(
                    detail=data['address_street_num'],
                    provinsi=data['address_provinsi'],
                    kabupaten=data['address_kabupaten'],
                    kecamatan=data['address_kecamatan'],
                    kelurahan=data['address_kelurahan'],
                    kodepos=data['address_kodepos'],
                    latitude=data['address_latitude'],
                    longitude=data['address_longitude'],
                ),
                job_type=data['job_type'],
                job_industry="Job Industry",
                job_description="Job Description",
                company_name="PT. Julo",
                company_phone_number=data['company_phone_number'],
                payday=1,
                monthly_income=data['monthly_income'],
                monthly_expenses=data['monthly_expenses'],
                monthly_housing_cost=data['monthly_housing_cost'],
                total_current_debt=data['total_current_debt'],
                app_version=data['app_version'],
                android_id=data['android_id'],
                latitude=data['latitude'],
                longitude=data['longitude'],
            )
            serializer = CustomerDataChangeRequestSerializer(
                data=data,
                context={
                    'previous_change_request': change_request,
                },
            )
            ret_val = serializer.is_valid()
            self.assertTrue(ret_val, serializer.errors)

    def test_job_type_household(self):
        data = self.construct_submit_data(
            job_type='Staf rumah tangga',
            job_industry='Staf rumah tangga',
            job_description=None,
            company_name=None,
            payday=None,
        )
        change_request = CustomerDataChangeRequestFactory(
            address=AddressFactory(
                detail=data['address_street_num'],
                provinsi=data['address_provinsi'],
                kabupaten=data['address_kabupaten'],
                kecamatan=data['address_kecamatan'],
                kelurahan=data['address_kelurahan'],
                kodepos=data['address_kodepos'],
                latitude=data['address_latitude'],
                longitude=data['address_longitude'],
            ),
            job_type=data['job_type'],
            job_industry="Job Industry",
            job_description="Job Description",
            company_name="PT. Julo",
            company_phone_number=data['company_phone_number'],
            payday=1,
            monthly_income=data['monthly_income'],
            monthly_expenses=data['monthly_expenses'],
            monthly_housing_cost=data['monthly_housing_cost'],
            total_current_debt=data['total_current_debt'],
            app_version=data['app_version'],
            android_id=data['android_id'],
            latitude=data['latitude'],
            longitude=data['longitude'],
        )
        serializer = CustomerDataChangeRequestSerializer(
            data=data,
            context={
                'previous_change_request': change_request,
            },
        )
        ret_val = serializer.is_valid()
        self.assertTrue(ret_val, serializer.errors)

    def test_invalid_payday(self):
        data = self.construct_submit_data(payday=0)
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 2})
        self.assertFalse(serializer.is_valid(), serializer.errors)
        self.assertIn('payday', serializer.errors)

    def test_valid_app_version_format(self):
        valid_versions = [
            '1.0.0',
            '1.0',
            '1.0.0-v',
            '1.0.0-V',
            '1.0.0+v',
            '1.0.0+V',
            '1.0.0-p',
            '1.0.0-P',
            '8.17.0',
            '8.17.0+v',
            '8.17+v',
            '8.18',
            '8.18.9',
            '8.18.69',
        ]
        for version in valid_versions:
            data = self.construct_submit_data(app_version=version)
            serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 2})
            self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_invalid_app_version_format(self):
        invalid_versions = ['1.0.0a', '1:0:0', "1.0.0'; DROP TABLE ops.customers; --'", "1.0.0xx"]
        for version in invalid_versions:
            data = self.construct_submit_data(app_version=version)
            serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 2})
            self.assertFalse(serializer.is_valid(), serializer.errors)
            self.assertIn('app_version', serializer.errors)

    def test_allowed_special_characters(self):
        allowed_special_characters = "@./- "
        data = self.construct_submit_data(address_street_num=allowed_special_characters)
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 2})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_disallowed_special_characters(self):
        disallowed_special_character = "!"
        data = self.construct_submit_data(address_street_num=disallowed_special_character)
        serializer = CustomerDataChangeRequestSerializer(data=data, context={'customer_id': 2})
        self.assertFalse(serializer.is_valid(), serializer.errors)
        self.assertIn('address_street_num', serializer.errors)


class TestCustomerDataChangeRequestListSerializer(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(fullname='John Doe')
        self.application = ApplicationJ1Factory(customer=self.customer)

    def test_serializer(self):
        change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            application=self.application,
            source='app',
            status='approved',
            approval_note='Approval note',
        )
        serializer = CustomerDataChangeRequestListSerializer(change_request)
        expected_data = {
            'id': change_request.id,
            'customer_id': self.customer.id,
            'application_id': self.application.id,
            'fullname': self.customer.fullname,
            'status': change_request.status,
            'source': change_request.source,
            'approval_note': change_request.approval_note,
            'cdate': change_request.cdate.isoformat().replace('+00:00', 'Z'),
            'udate': change_request.udate.isoformat().replace('+00:00', 'Z'),
        }
        self.assertEqual(serializer.data, expected_data)


class TestCustomerDataChangeRequestApprovalSerializer(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(fullname='John Doe')
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.setting = FeatureSettingFactory(
            feature_name='customer_data_change_request',
            is_active=True,
        )
        self.change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            application=self.application,
            source='app',
            status='submitted',
            approval_note=None,
            address=AddressFactory(
                latitude=1.2,
                longitude=3.4,
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos=12140,
                detail='Jl. Gandaria I No. 1',
            ),
            job_type='karyawan',
            job_industry='perbankan',
            job_description='mengelola uang',
            company_name='PT. Bank Julo',
            company_phone_number='0211234567',
            payday=15,
            monthly_income=10000000,
            monthly_expenses=5000000,
            monthly_housing_cost=2000000,
            total_current_debt=1000000,
            last_education="S1",
            address_transfer_certificate_image=ImageFactory(
                url='address_transfer_certificate_image.jpg',
            ),
            company_proof_image=ImageFactory(
                url='company_proof_image.jpg',
            ),
            paystub_image=ImageFactory(
                url='paystub_image.jpg',
            ),
            payday_change_reason="lainnya",
            payday_change_proof_image_id=CXDocumentFactory(
                url='payday_change_proof_image.jpg',
            ).id,
        )

    def test_save(self):
        serializer = CustomerDataChangeRequestApprovalSerializer(
            self.change_request,
            data={
                'status': 'approved',
                'approval_note': 'Approval note',
            },
            context={'user': self.customer.user},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self.change_request.refresh_from_db()
        self.assertEqual(self.change_request.status, 'approved')
        self.assertEqual(self.change_request.approval_note, 'Approval note')
        self.assertEqual(self.change_request.approval_user_id, self.customer.user_id)

    def test_save_with_invalid_status(self):
        serializer = CustomerDataChangeRequestApprovalSerializer(
            self.change_request,
            data={
                'status': 'invalid',
                'approval_note': 'Approval note',
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            serializer.is_valid(raise_exception=True)

        self.assertIn('status', ctx.exception.detail, str(ctx.exception))

    def test_save_with_approved_request(self):
        self.change_request.update_safely(status='approved')
        serializer = CustomerDataChangeRequestApprovalSerializer(
            self.change_request,
            data={
                'status': 'rejected',
                'approval_note': 'Approval note',
            },
        )
        with self.assertRaises(ValidationError) as ctx:
            serializer.is_valid(raise_exception=True)
            serializer.save()

        self.change_request.refresh_from_db()
        self.assertIn('status', ctx.exception.detail, str(ctx.exception))
        self.assertEqual(
            ['Status is already approved'],
            ctx.exception.detail['status'],
            str(ctx.exception),
        )
        self.assertEqual(self.change_request.status, 'approved')


class TestCustomerDataChangeRequestCompareSerializer(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(fullname='John Doe')
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            application=self.application,
            source='app',
            status='submitted',
            approval_note=None,
            address=AddressFactory(
                latitude=1.2,
                longitude=3.4,
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos='12140',
                detail='Jl. Gandaria I No. 1',
            ),
            job_type='karyawan',
            job_industry='perbankan',
            job_description='mengelola uang',
            company_name='PT. Bank Julo',
            company_phone_number='0211234567',
            payday=15,
            monthly_income=10000000,
            monthly_expenses=5000000,
            monthly_housing_cost=2000000,
            total_current_debt=1000000,
            payday_change_reason="lainnya",
            payday_change_proof_image_id=CXDocumentFactory(
                url='payday_change_proof_image.jpg',
            ).id,
        )

    def test_serialize_data(self):
        data = CustomerDataChangeRequestCompareSerializer(instance=self.change_request).data

        self.assertEqual('karyawan', data['job_type'])
        self.assertEqual('perbankan', data['job_industry'])
        self.assertEqual('mengelola uang', data['job_description'])
        self.assertEqual('PT. Bank Julo', data['company_name'])
        self.assertEqual('0211234567', data['company_phone_number'])
        self.assertEqual(15, data['payday'])
        self.assertEqual('Rp 10.000.000', data['monthly_income'])
        self.assertEqual('Rp 5.000.000', data['monthly_expenses'])
        self.assertEqual('Rp 2.000.000', data['monthly_housing_cost'])
        self.assertEqual('Rp 1.000.000', data['total_current_debt'])
        self.assertEqual(
            (
                'Jl. Gandaria I No. 1, Gandaria Utara, Kebayoran Baru, '
                'Jakarta Selatan, DKI Jakarta, 12140'
            ),
            data['address'],
        )

    def test_empty_data(self):
        change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            application=self.application,
            source='app',
            status='submitted',
            approval_note=None,
            address=None,
            job_type=None,
            job_industry=None,
            job_description=None,
            company_name=None,
            company_phone_number=None,
            payday=None,
            monthly_income=None,
            monthly_expenses=None,
            monthly_housing_cost=None,
            total_current_debt=None,
        )
        data = CustomerDataChangeRequestCompareSerializer(instance=change_request).data

        self.assertIsNone(data['job_type'])
        self.assertIsNone(data['job_industry'])
        self.assertIsNone(data['job_description'])
        self.assertIsNone(data['company_name'])
        self.assertIsNone(data['company_phone_number'])
        self.assertIsNone(data['payday'])
        self.assertIsNone(data['monthly_income'])
        self.assertIsNone(data['monthly_expenses'])
        self.assertIsNone(data['monthly_housing_cost'])
        self.assertIsNone(data['total_current_debt'])
        self.assertIsNone(data['address'])


class TestCustomerDataChangeRequestCRMSerializer(TestCase):
    IMAGE_DATA = (
        b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x00\x00\x00\x21\xf9\x04'
        b'\x01\x0a\x00\x01\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02'
        b'\x02\x4c\x01\x00\x3b'
    )
    PDF_DATA = b'pdf string'

    def setUp(self):
        self.customer = CustomerFactory(fullname='John Doe')
        self.first_application = ApplicationJ1Factory(
            customer=self.customer,
            application_status=StatusLookupFactory(status_code=175),
        )
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.setting = FeatureSettingFactory(
            feature_name='customer_data_change_request',
            is_active=True,
        )
        self.change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            application=self.application,
            source='app',
            status='submitted',
            approval_note=None,
            address=AddressFactory(
                latitude=1.2,
                longitude=3.4,
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos=12140,
                detail='Jl. Gandaria I No. 1',
            ),
            job_type='karyawan',
            job_industry='perbankan',
            job_description='mengelola uang',
            company_name='PT. Bank Julo',
            company_phone_number='0211234567',
            payday=15,
            monthly_income=10000000,
            monthly_expenses=5000000,
            monthly_housing_cost=2000000,
            total_current_debt=1000000,
            address_transfer_certificate_image=ImageFactory(
                url='address_transfer_certificate_image.jpg',
            ),
            company_proof_image=ImageFactory(
                url='company_proof_image.jpg',
            ),
            paystub_image=ImageFactory(
                url='paystub_image.jpg',
            ),
            payday_change_reason="lainnya",
            payday_change_proof_image_id=CXDocumentFactory(
                url='payday_change_proof_image.jpg',
            ).id,
        )

    def construct_submit_data(self, **kwargs):
        data = {
            'customer_id': self.customer.id,
            'application_id': self.application.id,
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'job_type': 'Pegawai negeri',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'last_education': 'S1',
        }
        data.update(**kwargs)
        return data

    def test_save(self):
        handler = CustomerDataChangeRequestHandler(self.customer)
        serializer = CustomerDataChangeRequestCRMSerializer(
            self.change_request,
            data=self.construct_submit_data(
                address_transfer_certificate_image=SimpleUploadedFile(
                    "address_transfer_certificate_image.png",
                    self.IMAGE_DATA,
                    content_type="image/png",
                ),
                company_proof_image=SimpleUploadedFile(
                    "company_proof_image.png",
                    self.IMAGE_DATA,
                    content_type="image/png",
                ),
                paystub_image=SimpleUploadedFile(
                    "paystub.png",
                    self.IMAGE_DATA,
                    content_type="image/png",
                ),
            ),
            context={
                "change_request_handler": handler,
                "previous_change_request": handler.convert_application_data_to_change_request(),
            },
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        change_request = serializer.save(source='source')
        self.assertEqual(self.customer, self.change_request.customer)
        self.assertEqual(self.application, self.change_request.application)
        self.assertEqual('source', change_request.source)
        self.assertEqual('submitted', change_request.status)
        self.assertEqual('DKI Jakarta', change_request.address.provinsi)
        self.assertEqual('Jakarta Selatan', change_request.address.kabupaten)
        self.assertEqual('Kebayoran Baru', change_request.address.kecamatan)
        self.assertEqual('Gandaria Utara', change_request.address.kelurahan)
        self.assertEqual('12140', change_request.address.kodepos)
        self.assertEqual('Pegawai negeri', change_request.job_type)
        self.assertEqual('perbankan', change_request.job_industry)
        self.assertEqual('mengelola uang', change_request.job_description)
        self.assertEqual('PT. Bank Julo', change_request.company_name)
        self.assertEqual('0211234567', change_request.company_phone_number)
        self.assertEqual(15, change_request.payday)
        self.assertEqual(10000000, change_request.monthly_income)
        self.assertEqual(5000000, change_request.monthly_expenses)
        self.assertEqual(2000000, change_request.monthly_housing_cost)
        self.assertEqual(1000000, change_request.total_current_debt)
        self.assertIsNotNone(change_request.address_transfer_certificate_image)
        self.assertIsNotNone(change_request.company_proof_image)
        self.assertIsNotNone(change_request.paystub_image)

    def test_is_valid_not_latest_application(self):
        handler = CustomerDataChangeRequestHandler(self.customer)
        serializer = CustomerDataChangeRequestCRMSerializer(
            self.change_request,
            data=self.construct_submit_data(
                application_id=self.first_application.id,
            ),
            context={
                "change_request_handler": handler,
                "previous_change_request": handler.convert_application_data_to_change_request(),
            },
        )
        self.assertFalse(serializer.is_valid(), serializer.errors)
        self.assertIn('application_id', serializer.errors)
        self.assertEqual('Application ID is not the latest', serializer.errors['application_id'][0])

    def test_is_valid_not_active_application(self):
        self.application.update_safely(application_status_id=120)
        handler = CustomerDataChangeRequestHandler(self.customer)
        serializer = CustomerDataChangeRequestCRMSerializer(
            self.change_request,
            data=self.construct_submit_data(
                application_id=self.application.id,
            ),
            context={
                "change_request_handler": handler,
                "previous_change_request": handler.convert_application_data_to_change_request(),
            },
        )
        self.assertFalse(serializer.is_valid(), serializer.errors)
        self.assertIn('application_id', serializer.errors)
        self.assertEqual('Application is not active', serializer.errors['application_id'][0])

    def test_submit_pdf_file(self):
        handler = CustomerDataChangeRequestHandler(self.customer)
        serializer = CustomerDataChangeRequestCRMSerializer(
            self.change_request,
            data=self.construct_submit_data(
                address_transfer_certificate_image=SimpleUploadedFile(
                    "address_transfer_certificate_image.pdf",
                    self.PDF_DATA,
                    content_type="application/pdf",
                ),
                company_proof_image=SimpleUploadedFile(
                    "company_proof_image.pdf",
                    self.PDF_DATA,
                    content_type="application/pdf",
                ),
                paystub_image=SimpleUploadedFile(
                    "paystub.pdf",
                    self.PDF_DATA,
                    content_type="application/pdf",
                ),
            ),
            context={
                "change_request_handler": handler,
                "previous_change_request": handler.convert_application_data_to_change_request(),
            },
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        change_request = serializer.save(source='source')
        self.assertEqual(self.customer, self.change_request.customer)
        self.assertEqual(self.application, self.change_request.application)
        self.assertEqual('source', change_request.source)
        self.assertEqual('submitted', change_request.status)
        self.assertEqual('DKI Jakarta', change_request.address.provinsi)
        self.assertEqual('Jakarta Selatan', change_request.address.kabupaten)
        self.assertEqual('Kebayoran Baru', change_request.address.kecamatan)
        self.assertEqual('Gandaria Utara', change_request.address.kelurahan)
        self.assertEqual('12140', change_request.address.kodepos)
        self.assertEqual('Pegawai negeri', change_request.job_type)
        self.assertEqual('perbankan', change_request.job_industry)
        self.assertEqual('mengelola uang', change_request.job_description)
        self.assertEqual('PT. Bank Julo', change_request.company_name)
        self.assertEqual('0211234567', change_request.company_phone_number)
        self.assertEqual(15, change_request.payday)
        self.assertEqual(10000000, change_request.monthly_income)
        self.assertEqual(5000000, change_request.monthly_expenses)
        self.assertEqual(2000000, change_request.monthly_housing_cost)
        self.assertEqual(1000000, change_request.total_current_debt)
        self.assertIsNotNone(change_request.address_transfer_certificate_image)
        self.assertIsNotNone(change_request.company_proof_image)
        self.assertIsNotNone(change_request.paystub_image)

    def test_invalid_file_type(self):
        handler = CustomerDataChangeRequestHandler(self.customer)
        serializer = CustomerDataChangeRequestCRMSerializer(
            self.change_request,
            data=self.construct_submit_data(
                address_transfer_certificate_image=SimpleUploadedFile(
                    "address_transfer_certificate_image.txt",
                    self.PDF_DATA,
                    content_type="text/plain",
                ),
                company_proof_image=SimpleUploadedFile(
                    "company_proof_image.txt",
                    self.PDF_DATA,
                    content_type="text/plain",
                ),
                paystub_image=InMemoryUploadedFile(
                    file=BytesIO(self.PDF_DATA),
                    field_name=None,
                    name="paystub.pdf",
                    content_type="application/pdf",
                    size=6000000,
                    charset=None,
                ),
            ),
            context={
                "change_request_handler": handler,
                "previous_change_request": handler.convert_application_data_to_change_request(),
            },
        )
        expected_error_message = (
            'Pastikan file yang diupload memiliki format png, jpg, atau pdf dan tidak melebihi 5MB'
        )
        self.assertFalse(serializer.is_valid(), serializer.errors)
        self.assertIn('address_transfer_certificate_image', serializer.errors)
        self.assertIn('company_proof_image', serializer.errors)
        self.assertIn('paystub_image', serializer.errors)
        self.assertEqual(
            expected_error_message, serializer.errors['address_transfer_certificate_image'][0]
        )
        self.assertEqual(expected_error_message, serializer.errors['company_proof_image'][0])
        self.assertEqual(expected_error_message, serializer.errors['paystub_image'][0])
