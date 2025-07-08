import pytz
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import Group
from mock import patch, Mock, MagicMock
from rest_framework.test import APIClient, APITestCase
from datetime import datetime
from babel.dates import format_date
from datetime import timedelta

import juloserver.application_form.tasks.application_task
from juloserver.apiv2.constants import ErrorCode, ErrorMessage
from juloserver.application_form.views.view_v1 import ApplicationUpdate
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    StatusLookup,
    ApplicationStatusCodes,
    AddressGeolocation,
    WorkflowStatusPath,
    ApplicationHistory,
    Application,
    Workflow,
    ApplicationExperiment,
    ApplicationUpgrade,
    ApplicationFieldChange,
    CustomerAppAction,
    CustomerFieldChange,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CityLookupFactory,
    CustomerFactory,
    DeviceFactory,
    DistrictLookupFactory,
    ImageFactory,
    MobileFeatureSettingFactory,
    OnboardingFactory,
    ProductLineFactory,
    ProvinceLookupFactory,
    SubDistrictLookupFactory,
    StatusLookupFactory,
    WorkflowFactory,
    MantriFactory,
    OtpRequestFactory,
    IdfyVideoCallFactory,
    FeatureSettingFactory,
    ExperimentFactory,
    ExperimentTestGroupFactory,
    BankFactory,
    ApplicationUpgradeFactory,
    SmsHistoryFactory,
    OcrKtpResultFactory,
    PartnerFactory,
    AddressGeolocationFactory,
    AgentAssistedWebTokenFactory,
    ApplicationHistoryFactory,
    ApplicationPhoneRecordFactory,
)
from juloserver.application_flow.factories import (
    ApplicationPathTagStatusFactory,
    ApplicationTagFactory,
)
from juloserver.application_form.constants import (
    LabelFieldsIDFyConst,
    ApplicationDirectionConst,
    IDFyAgentOfficeHoursConst,
    GeneralMessageResponseShortForm,
    AgentAssistedSubmissionConst,
)
from juloserver.pin.services import CustomerPinService
from juloserver.julo.constants import (
    OnboardingIdConst,
    MobileFeatureNameConst,
    FeatureNameConst,
    IdentifierKeyHeaderAPI,
    ExperimentConst,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo.models import Image
from juloserver.liveness_detection.tests.factories import (
    ActiveLivenessDetectionFactory,
    ActiveLivenessVendorResultFactory,
    PassiveLivenessDetectionFactory,
    PassiveLivenessVendorResultFactory,
)
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
    ActiveLivenessVendorResult,
    PassiveLivenessVendorResult,
)
from juloserver.apiv3.views import ApplicationUpdateV3
from juloserver.otp.constants import SessionTokenAction
from juloserver.application_form.models import IdfyVideoCall, IdfyCallBackLog
from copy import deepcopy
from juloserver.application_form.models.revive_mtl_request import ReviveMtlRequest
from juloserver.application_form.utils import (
    generate_consent_form_code,
    generate_web_token,
)
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.api_token.models import ExpiryToken
from juloserver.application_form.constants import AgentAssistedSubmissionConst
from juloserver.application_flow.handlers import JuloOne105Handler
from juloserver.new_crm.tests.factories import ApplicationPathTagFactory
from juloserver.julo.tests.factories import AgentAssistedWebTokenFactory, ExperimentSettingFactory
from juloserver.account.models import ExperimentGroup


class TestApplicationUpdate(TestCase):
    url = '/api/application-form/v1/application/{}'

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, nik=None, email=None)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status = StatusLookup.objects.get(status_code=100)
        self.application.save()
        self.device = DeviceFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.data = {
            "application_status": 100,
            "device": self.device.id,
            "application_number": 1,
            "email": 'fathur.rohman+22013107@julofinance.com',
            "ktp": '0220202201310006',
            "fullname": 'Fathur Rohman',
            "dob": '1990-01-01',
            "marital_status": 'Lajang',
            "mother_maiden_name": 'Mama',
            "address_street_num": 'Nomor 12AB',
            "address_provinsi": 'Jawa Barat',
            "address_kabupaten": 'Bogor',
            "address_kecamatan": 'Parung Panjang',
            "address_kelurahan": 'Kabasiran',
            "address_kodepos": '',
            "address_detail": 'address detail what is this',
            "kin_relationship": 'Orang tua',
            "kin_name": 'Bama',
            "kin_mobile_phone": '089677537749',
            "close_kin_name": 'Yuli',
            "close_kin_mobile_phone": '08964447749',
            "spouse_name": 'Andre',
            "spouse_mobile_phone": '089644471119',
            "job_type": 'Pegawai negeri',
            "job_industry": 'Admin Finance/HR',
            "job_description": 'Admin',
            "job_start": '1990-01-02',
            "payday": 30,
            "monthly_income": 15000000,
            "monthly_expenses": 10000000,
            "total_current_debt": 100000,
            "loan_purpose": 'Modal usaha',
            "bank_name": 'BANK CENTRAL ASIA, Tbk (BCA)',
            "bank_account_number": '43985',
            "gender": "Pria",
            "referral_code": "w349876",
            "birth_place": "Jakarta",
        }

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_success_update_application(self, mock_1, mock_2):
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        json = resp.json()
        self.assertEqual(json['status'], self.data['application_status'])
        self.assertEqual(json['device'], self.device.id)
        self.assertEqual(json['application_number'], self.data['application_number'])
        self.assertEqual(json['email'], self.data['email'])
        self.assertEqual(json['ktp'], self.data['ktp'])
        self.assertEqual(json['fullname'], self.data['fullname'])
        self.assertEqual(json['dob'], self.data['dob'])
        self.assertEqual(json['marital_status'], self.data['marital_status'])
        self.assertEqual(json['mother_maiden_name'], 'Mama')
        self.assertEqual(json['address_street_num'], self.data['address_street_num'])
        self.assertEqual(json['address_provinsi'], self.data['address_provinsi'])
        self.assertEqual(json['address_kabupaten'], self.data['address_kabupaten'])
        self.assertEqual(json['address_kecamatan'], self.data['address_kecamatan'])
        self.assertEqual(json['address_kelurahan'], self.data['address_kelurahan'])
        self.assertEqual(json['address_kodepos'], self.data['address_kodepos'])
        self.assertEqual(json['address_detail'], self.data['address_detail'])
        self.assertEqual(json['kin_relationship'], self.data['kin_relationship'])
        self.assertEqual(json['kin_name'], self.data['kin_name'])
        self.assertEqual(json['kin_mobile_phone'], self.data['kin_mobile_phone'])
        self.assertEqual(json['close_kin_name'], self.data['close_kin_name'])
        self.assertEqual(json['close_kin_mobile_phone'], self.data['close_kin_mobile_phone'])
        self.assertEqual(json['spouse_name'], self.data['spouse_name'])
        self.assertEqual(json['spouse_mobile_phone'], self.data['spouse_mobile_phone'])
        self.assertEqual(json['job_type'], self.data['job_type'])
        self.assertEqual(json['job_industry'], self.data['job_industry'])
        self.assertEqual(json['job_description'], self.data['job_description'])
        self.assertEqual(json['job_start'], self.data['job_start'])
        self.assertEqual(json['payday'], self.data['payday'])
        self.assertEqual(json['monthly_income'], self.data['monthly_income'])
        self.assertEqual(json['monthly_expenses'], self.data['monthly_expenses'])
        self.assertEqual(json['total_current_debt'], self.data['total_current_debt'])
        self.assertEqual(json['loan_purpose'], self.data['loan_purpose'])
        self.assertEqual(json['bank_name'], self.data['bank_name'])
        self.assertEqual(json['bank_account_number'], self.data['bank_account_number'])
        self.assertEqual(json['gender'], self.data['gender'])
        self.assertEqual(json['referral_code'], self.data['referral_code'])
        self.assertEqual(json['birth_place'], self.data['birth_place'])

        # Check in database that company_name should be empty string
        self.application.refresh_from_db()
        self.assertEqual(self.application.company_name, '')

    @patch.object(ApplicationUpdate, 'check_liveness', return_value=False)
    def test_missing_liveness(self, mock_check_liveness):
        resp = self.client.patch(
            self.url.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        json = resp.json()
        self.assertFalse(json['success'])
        self.assertEqual(json['errors'][0], 'Cek kembali halaman selfie dan ambil ulang foto kamu')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_company_phone(self, mock_1, mock_2):
        resp = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "company_phone_number": "0213838383"},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

        self.application.refresh_from_db()
        self.assertEqual(self.application.company_phone_number, '0213838383')
        # company phone is a normal mobile phone
        resp = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "company_phone_number": "0852839383838"},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

        self.application.refresh_from_db()
        self.assertEqual(self.application.company_phone_number, '0852839383838')
        # company phone with a different prefix
        self.application.application_status_id = 100
        self.application.save()
        resp = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "company_phone_number": "0352839383838"},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.company_phone_number, '0352839383838')
        # invalid phone number format
        resp = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "company_phone_number": "08528393"},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()['company_phone_number'],
            ["Maaf, nomor yang kamu masukkan tidak valid. Mohon masukkan nomor lainnya"],
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.company_phone_number, '0352839383838')
        # company phone is duplicated with others phone number
        resp = self.client.patch(
            self.url.format(self.application.id),
            data={
                **self.data,
                "company_phone_number": "085283938383",
                "kin_mobile_phone": "085283938383",
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()['detail'], 'Nomor telepon tidak boleh sama dengan nomor yang lain'
        )
        self.application.refresh_from_db()
        self.assertEqual(self.application.company_phone_number, '0352839383838')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_error_company_phone_gsm(self, mock_1, mock_2):
        resp = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "company_phone_number": self.data['kin_mobile_phone']},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    # new rule on card RUS1-1011, can not submit form without company phone
    # @patch('juloserver.apiv2.views.process_application_status_change')
    # @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    # def test_success_without_company_phone(
    #     self, mock_process_application_status_change, mock_check_liveness
    # ):
    #     resp = self.client.patch(
    #         self.url.format(self.application.id),
    #         data={**self.data, "company_phone_number": ""},
    #         format='json',
    #     )
    #
    #     self.assertEqual(resp.status_code, 200)
    #
    #     self.application.refresh_from_db()
    #     self.assertEqual(self.application.company_phone_number, '')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_titleize_staff_rumah_tangga(self, mock_1, mock_2):
        resp = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "job_industry": "Staf rumah tangga"},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        json = resp.json()
        self.assertEqual(json['job_industry'], "Staf Rumah Tangga")

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_invalid_nik(self, mock_1, mock_2):
        self.customer.nik = '0020020201900000'
        self.customer.save()

        resp = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, 'ktp': '0020020201900000'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_failed_customer_claim_should_not_raise_error(self, mock_1, mock_2):
        nik = '0220202201310006'

        # Create fake customer that has nik
        CustomerFactory(nik=nik)

        self.customer.nik = '0220020201900001'
        self.customer.save()

        resp = self.client.patch(
            self.url.format(self.application.id), data={**self.data, 'ktp': nik}, format='json'
        )
        self.assertEqual(resp.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.nik, '0220020201900001')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_submit_application_with_data_contains_code(
        self, mock_check_liveness, mock_submit_selfie, mock_status_change
    ):
        sample_value = '<script src="https://julo.co.id/"></script>'
        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()
        self.data['address_detail'] = sample_value

        # hit endpoint submission
        response = self.client.patch(
            self.url.format(self.application.id), data={**self.data}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_submit_application_with_data_contains_code_mother_maiden_name(
        self, mock_check_liveness, mock_submit_selfie, mock_status_change
    ):
        sample_value = '<script src="https://julo.co.id/"></script>'
        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()
        self.data['mother_maiden_name'] = sample_value

        # hit endpoint submission
        response = self.client.patch(
            self.url.format(self.application.id), data={**self.data}, format='json'
        )
        self.assertEqual(response.status_code, 400)

        # case success for mother maiden name
        self.data['mother_maiden_name'] = 'Ibunda'

        # hit endpoint submission
        response = self.client.patch(
            self.url.format(self.application.id), data={**self.data}, format='json'
        )
        self.customer.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.customer.mother_maiden_name, 'Ibunda')
        self.assertEqual(response.json()['mother_maiden_name'], 'Ibunda')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdate, 'check_liveness', return_value=True)
    def test_otp_validation_view(self, mock_check_liveness, mock_submit_selfie, mock_status_change):
        phone_number = '081234567890'
        self.otp_token = '111123'

        MobileFeatureSettingFactory(
            feature_name='compulsory_otp_setting',
            is_active=True,
            parameters={
                "otp_max_request": 30,
                "otp_resend_time": 30,
                "otp_max_validate": 30,
                "wait_time_seconds": 12000,
            },
        )

        OtpRequestFactory(
            customer=self.customer,
            otp_token=self.otp_token,
            phone_number=phone_number,
            is_used=True,
            action_type=SessionTokenAction.VERIFY_PHONE_NUMBER,
        )

        # Case number not changed
        response = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "mobile_phone_1": phone_number},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        # case phone number changed
        submitted_phone_number = '081234567999'
        response = self.client.patch(
            self.url.format(self.application.id),
            data={**self.data, "mobile_phone_1": submitted_phone_number},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(ErrorMessage.PHONE_NUMBER_MISMATCH, response.json()['errors'])


class TestCheckRegion(APITestCase):
    url = '/api/application-form/v1/regions/check'

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_get_complete(self):
        province = ProvinceLookupFactory(province='Jawa Barat')
        city = CityLookupFactory(city='Bogor', province=province)
        district = DistrictLookupFactory(district='Parung Panjang', city=city)
        SubDistrictLookupFactory(sub_district='Kabasiran', zipcode='12345', district=district)

        resp = self.client.get(
            self.url,
            {
                'province': 'jawa barat',
                'city': 'bogor',
                'district': 'parung panjang',
                'sub-district': 'kabasiran',
            },
        )

        json = resp.json()
        data = json['data']
        self.assertEqual(data['province'], 'Jawa Barat')
        self.assertEqual(data['city'], 'Bogor')
        self.assertEqual(data['district'], 'Parung Panjang')
        self.assertEqual(data['sub_district'], 'Kabasiran')
        self.assertEqual(data['zipcode'], '12345')

    def test_without_sub_district(self):
        province = ProvinceLookupFactory(province='Jawa Barat')
        city = CityLookupFactory(city='Bogor', province=province)
        DistrictLookupFactory(district='Parung Panjang', city=city)

        resp = self.client.get(
            self.url,
            {
                'province': 'jawa barat',
                'city': 'bogor',
                'district': 'parung panjang',
                'sub-district': 'kabasiran',
            },
        )

        json = resp.json()
        data = json['data']
        self.assertEqual(data['province'], 'Jawa Barat')
        self.assertEqual(data['city'], 'Bogor')
        self.assertEqual(data['district'], 'Parung Panjang')
        self.assertEqual(data['sub_district'], '')
        self.assertEqual(data['zipcode'], '')

    def test_without_district(self):
        province = ProvinceLookupFactory(province='Jawa Barat')
        city = CityLookupFactory(city='Bogor', province=province)

        resp = self.client.get(
            self.url,
            {
                'province': 'jawa barat',
                'city': 'bogor',
                'district': 'parung panjang',
                'sub-district': 'kabasiran',
            },
        )

        json = resp.json()
        data = json['data']
        self.assertEqual(data['province'], 'Jawa Barat')
        self.assertEqual(data['city'], 'Bogor')
        self.assertEqual(data['district'], '')
        self.assertEqual(data['sub_district'], '')
        self.assertEqual(data['zipcode'], '')

    def test_without_city(self):
        ProvinceLookupFactory(province='Jawa Barat')

        resp = self.client.get(
            self.url,
            {
                'province': 'jawa barat',
                'city': 'bogor',
                'district': 'parung panjang',
                'sub-district': 'kabasiran',
            },
        )

        json = resp.json()
        data = json['data']
        self.assertEqual(data['province'], 'Jawa Barat')
        self.assertEqual(data['city'], '')
        self.assertEqual(data['district'], '')
        self.assertEqual(data['sub_district'], '')
        self.assertEqual(data['zipcode'], '')

    def test_without_province(self):
        resp = self.client.get(
            self.url,
            {
                'province': 'jawa barat',
                'city': 'bogor',
                'district': 'parung panjang',
                'sub-district': 'kabasiran',
            },
        )

        json = resp.json()
        data = json['data']
        self.assertEqual(data['province'], '')
        self.assertEqual(data['city'], '')
        self.assertEqual(data['district'], '')
        self.assertEqual(data['sub_district'], '')
        self.assertEqual(data['zipcode'], '')

    def test_sub_district_correct_but_others_not(self):
        province = ProvinceLookupFactory(province='Jawa Barat')
        city = CityLookupFactory(city='Bogor', province=province)
        district = DistrictLookupFactory(district='Parung Panjang', city=city)
        SubDistrictLookupFactory(sub_district='Kabasiran', zipcode='12345', district=district)

        resp = self.client.get(
            self.url,
            {
                'province': 'jawa tengah',
                'city': 'jepara',
                'district': 'kedung',
                'sub-district': 'kabasiran',
            },
        )

        json = resp.json()
        data = json['data']
        self.assertEqual(data['province'], 'Jawa Barat')
        self.assertEqual(data['city'], 'Bogor')
        self.assertEqual(data['district'], 'Parung Panjang')
        self.assertEqual(data['sub_district'], 'Kabasiran')
        self.assertEqual(data['zipcode'], '12345')

    def test_double_sub_disrict(self):
        province = ProvinceLookupFactory(province='Jawa Barat')
        city = CityLookupFactory(city='Bogor', province=province)
        district = DistrictLookupFactory(district='Parung Panjang', city=city)
        SubDistrictLookupFactory(sub_district='Kabasiran', zipcode='12345', district=district)

        province = ProvinceLookupFactory(province='Jawa Tengah')
        city = CityLookupFactory(city='Demak', province=province)
        district = DistrictLookupFactory(district='Kali Banji', city=city)
        SubDistrictLookupFactory(sub_district='Kabasiran', zipcode='34837', district=district)

        resp = self.client.get(
            self.url,
            {
                'province': 'jawa barat',
                'city': 'bogor',
                'district': 'parung panjang',
                'sub-district': 'kabasiran',
            },
        )

        json = resp.json()
        data = json['data']
        self.assertEqual(data['province'], 'Jawa Barat')
        self.assertEqual(data['city'], 'Bogor')
        self.assertEqual(data['district'], 'Parung Panjang')
        self.assertEqual(data['sub_district'], 'Kabasiran')
        self.assertEqual(data['zipcode'], '12345')


class ReapplyApiClient(APIClient):
    def precheck(self):
        url = '/api/application-form/v1/precheck-reapply'
        return self.get(url)

    def reapply(self, data, header={}):
        url = '/api/application-form/v1/reapply'
        return self.post(url, data, **header)


class TestReapplyApplication(TestCase):
    def setUp(self):
        self.client = ReapplyApiClient()
        self.user = AuthUserFactory()
        self.expiry_token = ExpiryToken.objects.filter(user=self.user).last()
        self.expiry_token.update_safely(is_active=True)

        customer_pin_service = CustomerPinService()
        customer_pin_service.init_customer_pin(self.user)

        self.customer = CustomerFactory(user=self.user)
        self.customer.can_reapply = True
        self.customer.save()

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.workflow_j1_ios = WorkflowFactory(name=WorkflowConst.JULO_ONE_IOS)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)

        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status = StatusLookup.objects.get(status_code=106)
        self.application.address_street_num = 1
        self.application.last_education = 'SLTA'
        self.application.save()

        self.image = ImageFactory(image_type='ktp_self', image_source=self.application.id)

        self.device = DeviceFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.mfs = MobileFeatureSettingFactory()
        self.mfs.feature_name = 'application_reapply_setting'
        self.mfs.parameters['editable'] = {'ktp': True}
        self.mfs.save()
        self.data = {
            "ktp": '0000000101920000',
            "device_id": self.device.id,
            "app_version": '7.0.0',
            "user": self.user,
        }
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.PARTNER_ACCOUNTS_FORCE_LOGOUT,
            is_active=True,
            parameters=[
                'Dagangan',
            ],
        )

        self.ios_id = 'E78E234E-4981-4BB7-833B-2B6CEC2F56DF'
        self.new_device_header = {
            IdentifierKeyHeaderAPI.X_DEVICE_ID: self.ios_id,
            IdentifierKeyHeaderAPI.X_PLATFORM: 'iOS',
            IdentifierKeyHeaderAPI.X_PLATFORM_VERSION: '18.0.1',
        }

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_success_reapply_editable_ktp(self, mock_status_change, mock_store):
        resp = self.client.reapply(self.data)
        json = resp.json()

        self.assertEqual(resp.status_code, 200)
        application = Application.objects.filter(pk=resp.data['content']['id']).last()
        self.assertEqual(application.workflow.name, WorkflowConst.JULO_ONE)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_success_reapply_onboarding_id_9(self, mock_status_change, mock_store):
        self.application.update_safely(onboarding_id=9, refresh=True)
        resp = self.client.reapply(self.data)
        json = resp.json()

        self.assertEqual(resp.status_code, 200)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    @patch('juloserver.application_form.views.view_v1.get_application_reapply_setting')
    def test_success_reapply_uneditable_ktp(self, mock_status_change, mock_store, mock_mfs):
        mock_mfs.return_value = False
        resp = self.client.reapply(self.data)
        json = resp.json()

        self.assertEqual(resp.status_code, 200)

    def test_cant_reapply(self):
        self.customer.can_reapply = False
        self.customer.save()

        resp = self.client.reapply(self.data)

        self.assertEqual(resp.data['error_code'], ErrorCode.CUSTOMER_REAPPLY)
        self.assertEqual(resp.data['error_message'], ErrorMessage.CUSTOMER_REAPPLY)

    @patch('juloserver.application_form.views.view_v1.does_user_have_pin')
    def test_user_has_no_pin(self, mocking_pin):
        mocking_pin.return_value = None
        resp = self.client.reapply(self.data)

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['message'], 'This customer is not available')

    def test_no_last_application_reapply(self):
        self.application.delete()
        resp = self.client.reapply(self.data)

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data['message'], 'customer has no application')

    def test_failed_reapply(self):
        resp = self.client.reapply(self.data)

        self.assertEqual(resp.data['error_code'], ErrorCode.CUSTOMER_REAPPLY)
        self.assertEqual(resp.data['error_message'], ErrorMessage.GENERAL)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_existing_data_reapply(self, mock_status_change, mock_store):
        """
        Case with data response include with data below:
        occupied_since
        home_status
        dependent
        last_education
        monthly_housing_cost

        Refer to the ticket:
        https://juloprojects.atlassian.net/browse/RUS1-1268
        """

        home_status = 'Kontrak'
        last_education = 'SLTA'
        occupied_since = '2014-02-01'
        dependent = 0
        monthly_housing_cost = 500000

        application_update = {
            "home_status": home_status,
            "last_education": last_education,
            "occupied_since": occupied_since,
            "dependent": dependent,
            "monthly_housing_cost": monthly_housing_cost,
        }

        self.application.update_safely(**application_update)

        # hit endpoint Reapply proces
        resp = self.client.reapply(self.data)

        # make sure data is same with data saved on the application data
        application = Application.objects.filter(pk=resp.data['content']['id']).last()
        self.assertEqual(application.workflow.name, WorkflowConst.JULO_ONE)
        self.assertEqual(resp.data['content']['home_status'], home_status)
        self.assertEqual(resp.data['content']['last_education'], last_education)
        self.assertEqual(resp.data['content']['dependent'], dependent)
        self.assertEqual(resp.data['content']['occupied_since'], occupied_since)
        self.assertEqual(resp.data['content']['monthly_housing_cost'], monthly_housing_cost)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_have_x190_to_prevent_reapply(self, mock_status_change, mock_store):
        """
        Prevent customer if have x190 status do reapply
        """

        self.application.update_safely(application_status_id=190)

        # hit endpoint Reapply proces
        resp = self.client.reapply(self.data)
        self.assertEqual(resp.status_code, 400)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_have_partner_with_list_not_allowed(self, mock_status_change, mock_store):
        """
        Set expired if customer have partner listed
        """

        self.application.update_safely(
            application_status_id=106, partner=PartnerFactory(name='dagangan')
        )
        # hit endpoint Reapply proces
        resp = self.client.reapply(self.data)
        self.assertEqual(resp.status_code, 401)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_have_partner_with_list_allowed(self, mock_status_change, mock_store):
        """
        Prevent customer if have x190 status do reapply
        """

        self.application.update_safely(
            application_status_id=106, partner=PartnerFactory(name='non-listed')
        )

        # hit endpoint Reapply proces
        resp = self.client.reapply(self.data)
        self.assertEqual(resp.status_code, 200)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_have_partner_with_empty_partner(self, mock_status_change, mock_store):
        """
        Prevent customer if have x190 status do reapply
        """

        self.application.update_safely(
            application_status_id=106, partner=PartnerFactory(name='dagangan')
        )
        self.application.update_safely(
            partner=None,
        )
        # hit endpoint Reapply proces
        resp = self.client.reapply(self.data)
        self.assertEqual(resp.status_code, 200)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_reapply_with_ios_device(self, mock_status_change, mock_store):
        """
        Reapply from iOS Device
        """

        home_status = 'Kontrak'
        last_education = 'SLTA'
        occupied_since = '2014-02-01'
        dependent = 0
        monthly_housing_cost = 500000

        application_update = {
            "home_status": home_status,
            "last_education": last_education,
            "occupied_since": occupied_since,
            "dependent": dependent,
            "monthly_housing_cost": monthly_housing_cost,
        }
        self.application.update_safely(**application_update)

        # hit endpoint Reapply proces
        resp = self.client.reapply(self.data, self.new_device_header)

        response_json = resp.json()
        # make sure data is same with data saved on the application data
        application = Application.objects.filter(pk=response_json['content']['id']).last()
        self.assertEqual(application.workflow.name, WorkflowConst.JULO_ONE_IOS)
        self.assertEqual(application.home_status, home_status)
        self.assertEqual(application.last_education, last_education)
        self.assertEqual(application.dependent, dependent)
        self.assertEqual(application.monthly_housing_cost, monthly_housing_cost)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_reapply_to_ios_with_empty_onboarding_id(self, mock_status_change, mock_store):
        """
        Reapply from iOS Device
        """

        home_status = 'Kontrak'
        last_education = 'SLTA'
        occupied_since = '2014-02-01'
        dependent = 0
        monthly_housing_cost = 500000

        application_update = {
            "home_status": home_status,
            "last_education": last_education,
            "occupied_since": occupied_since,
            "dependent": dependent,
            "monthly_housing_cost": monthly_housing_cost,
            "onboarding_id": None,
        }
        self.application.update_safely(**application_update)

        # hit endpoint Reapply proces
        resp = self.client.reapply(self.data, self.new_device_header)

        response_json = resp.json()
        # make sure data is same with data saved on the application data
        application = Application.objects.filter(pk=response_json['content']['id']).last()
        self.assertEqual(application.workflow.name, WorkflowConst.JULO_ONE_IOS)
        self.assertEqual(application.home_status, home_status)
        self.assertEqual(application.last_education, last_education)
        self.assertEqual(application.dependent, dependent)
        self.assertEqual(application.monthly_housing_cost, monthly_housing_cost)
        self.assertEqual(application.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)

    @patch('juloserver.application_form.views.view_v1.process_application_status_change')
    @patch('juloserver.application_form.views.view_v1.store_application_to_experiment_table')
    def test_reapply_for_mother_maiden_name(self, mock_status_change, mock_store):

        experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.MOTHER_NAME_VALIDATION,
            start_date=datetime.now() - timedelta(days=1),
            end_date=datetime.now() + timedelta(days=50),
            is_active=True,
            criteria={
                "app_version": ">=9.1.0",
                "app_id": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
                "improper_names": [
                    "MAMAH",
                ],
            },
        )
        self.application.update_safely(
            application_status_id=106,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        header = {
            'HTTP_X_APP_VERSION': '9.1.0',
        }
        # hit endpoint Reapply proces
        resp = self.client.reapply(self.data, header)
        self.assertEqual(resp.status_code, 200)
        is_exists = ExperimentGroup.objects.filter(
            application_id=resp.json()['content']['id'],
            experiment_setting=experiment_setting,
            group='experiment',
        ).exists()
        self.assertTrue(is_exists)


class TestApplicationCancelation(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = CustomerFactory()

        self.workflow_j1 = WorkflowFactory(name='JuloStarterWorkflow')
        self.product_line_j1 = ProductLineFactory(product_line_code=2)
        self.work_flow_status_path_j1 = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=137,
            type='happy',
            is_active=True,
            workflow=self.workflow_j1,
        )
        self.workflow_jturbo = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_line_jturbo = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )

        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow_j1)
        self.application.onboarding_id = 3
        self.application.application_status_id = 100
        self.application.product_line = self.product_line_j1
        self.application.save()

        self.device = DeviceFactory(customer=self.customer)
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.customer.user.auth_expiry_token.key
        )

    @patch('juloserver.julo.workflows.send_email_status_change_task')
    def test_success_cancel_application(self, mock_send_email_status_change_task):
        form_data = {
            "application_status": 100,
            "ktp": "5638450801956915",
            "fullname": "",
            "email": "rizal.zaenal+bak935@julofinance.com",
            "birth_place": "",
            "dob": "",
            "gender": "",
            "mother_maiden_name": "",
            "mobile_phone_1": "",
            "mobile_phone_2": "",
            "address_street_num": "",
            "address_provinsi": "",
            "address_kabupaten": "",
            "address_kecamatan": "",
            "address_kelurahan": "",
            "address_kodepos": "",
            "occupied_since": "",
            "home_status": "",
            "marital_status": "",
            "dependent": 0,
            "kin_name": "",
            "kin_mobile_phone": "",
            "spouse_name": "",
            "spouse_mobile_phone": "",
            "close_kin_name": "",
            "kin_relationship": "",
            "close_kin_mobile_phone": "",
            "close_kin_relationship": "",
            "job_type": "",
            "job_industry": "",
            "job_description": "",
            "company_name": "",
            "company_phone_number": "",
            "job_start": "",
            "payday": 0,
            "last_education": "",
            "monthly_income": -1,
            "monthly_expenses": -1,
            "monthly_housing_cost": -1,
            "total_current_debt": -1,
            "bank_name": "",
            "bank_account_number": "",
            "loan_purpose": "",
            "loan_purpose_desc": "",
            "marketing_source": "",
            "referral_code": "",
            "is_term_accepted": True,
            "is_verification_agreed": True,
            "onboarding_id": 3,
        }

        resp = self.client.post('/api/application-form/v1/cancel', data=form_data)
        self.assertEqual(resp.status_code, 200)

        form_data = {
            "fullname": "Aselole",
            "dob": "1999-01-13",
            "payday": 0,
            "monthly_income": 9999999,
            "monthly_expenses": 4444444,
            "mobile_phone_2": "085932223382",
            "mother_maiden_name": "Asmaul Husna",
            "last_education": "S1",
            'device': -1,
            "birth_place": '123',
        }
        resp = self.client.post('/api/application-form/v1/cancel', data=form_data)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.application.application_status_id, 100)

        last_application = Application.objects.get(id=self.application.id)
        self.assertEqual(last_application.fullname, form_data['fullname'])
        self.assertEqual(
            last_application.dob, datetime.strptime(form_data['dob'], "%Y-%m-%d").date()
        )
        self.assertEqual(last_application.monthly_income, form_data['monthly_income'])
        self.assertEqual(last_application.monthly_expenses, form_data['monthly_expenses'])
        self.assertEqual(last_application.mobile_phone_2, form_data['mobile_phone_2'])
        self.assertEqual(last_application.last_education, form_data['last_education'])
        self.assertNotEqual(last_application.device.id, form_data['device'])
        self.assertNotEqual(last_application.payday, form_data['payday'])

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.mother_maiden_name, form_data['mother_maiden_name'])

        # case user want to modify immutable fields
        form_data["application_status"] = 190
        form_data['email'] = 'changed_email@julofinance.co.id'
        form_data['ktp'] = '9638450801956999'
        form_data['onboarding_id'] = 99

        initial_email = last_application.email
        initial_ktp = last_application.ktp
        initial_onboarding_id = 3

        resp = self.client.post('/api/application-form/v1/cancel', data=form_data)
        self.assertEqual(resp.status_code, 200)

        last_application = Application.objects.filter(customer=self.customer).last()

        self.assertEqual(last_application.application_status_id, 100)
        self.assertEqual(last_application.email, initial_email)
        self.assertEqual(last_application.ktp, initial_ktp)
        self.assertEqual(last_application.onboarding_id, initial_onboarding_id)

        # case user is only have half finished form, only save values that passed validation

        initial_fullname = last_application.fullname
        initial_company_phone = last_application.company_phone_number
        initial_mother_maiden_name = self.customer.mother_maiden_name
        initial_mobile_phone_1 = last_application.mobile_phone_1
        initial_birth_place = last_application.birth_place

        form_data = {
            "fullname": "Ahay",
            "payday": 0,
            "mobile_phone_1": "085932",
            'company_phone_number': '9999999999999999999999999999999999999999999999',
            "mother_maiden_name": "Asmaul Husni",
            "birth_place": '123',
        }

        resp = self.client.post('/api/application-form/v1/cancel', data=form_data)

        self.assertEqual(resp.status_code, 200)
        last_application = Application.objects.filter(customer=self.customer).last()

        self.assertEqual(last_application.company_phone_number, initial_company_phone)
        self.assertEqual(last_application.mobile_phone_1, initial_mobile_phone_1)
        self.assertEqual(last_application.birth_place, initial_birth_place)
        self.assertEqual(last_application.fullname, form_data['fullname'])

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.mother_maiden_name, form_data['mother_maiden_name'])

    @patch(
        'juloserver.application_form.services.julo_starter_service.process_application_status_change'
    )
    @patch('juloserver.julo.workflows.send_email_status_change_task')
    def test_failed_cancel_application(
        self, mock_send_email_status_change_task, mock_application_change_status
    ):
        # wrong application status
        self.application.application_status_id = 105
        self.application.onboarding_id = 7
        self.application.save()
        resp = self.client.post('/api/application-form/v1/cancel')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['errors'], ['Application not found'])

        # allow for Julo One
        self.application.application_status_id = 100
        self.application.onboarding_id = 1
        self.application.save()
        resp = self.client.post('/api/application-form/v1/cancel')
        self.assertEqual(resp.status_code, 200)

        # allow for Julo Turbo / JStarter
        self.application.application_status_id = 100
        self.application.onboarding_id = 7
        self.application.workflow = self.workflow_jturbo
        self.application.product_line = self.product_line_jturbo
        self.application.save()
        resp = self.client.post('/api/application-form/v1/cancel')
        self.assertEqual(resp.status_code, 200)

        # success
        self.application.onboarding_id = 7
        self.application.save()
        resp = self.client.post('/api/application-form/v1/cancel')
        self.assertEqual(resp.status_code, 200)

        # case if not define application workflow / product line
        self.application.workflow = None
        self.application.product_line = None
        self.application.save()
        resp = self.client.post('/api/application-form/v1/cancel')
        self.assertEqual(resp.status_code, 403)

        # case if customer not have application
        self.application.delete()
        resp = self.client.post('/api/application-form/v1/cancel')
        self.assertEqual(resp.status_code, 404)


class TestChooseProductPicker(TestCase):
    @patch('juloserver.pii_vault.services.detokenize_pii_data_by_client')
    def setUp(self, mock_detokenize_pii_data_by_client) -> None:
        mock_detokenize_pii_data_by_client.return_value = {}
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.endpoint = '/api/application-form/v1/product-picker'
        self.expiry_token = ExpiryToken.objects.filter(user=self.user).last()
        self.expiry_token.update_safely(is_active=True)
        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)

        # JuloStarter
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_line_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )

        self.application_form_created = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )

        self.onboarding_lfs = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.onboarding_julostarter = OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_ID)
        self.onboarding_j1_j360 = OnboardingFactory(id=OnboardingIdConst.JULO_360_J1_ID)
        self.onboarding_jturbo_j360 = OnboardingFactory(id=OnboardingIdConst.JULO_360_TURBO_ID)

        # For J1
        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow_j1,
        )

        # For JuloStarter
        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow_jstarter,
        )

        self.payload = {
            "onboarding_id": OnboardingIdConst.LONGFORM_SHORTENED_ID,
            "customer_id": self.customer.id,
            "is_rooted_device": False,
            "is_suspicious_ip": False,
            "latitude": 0.0,
            "longitude": 0.0,
        }

        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
            HTTP_X_APP_VERSION='7.10.0',
        )

        self.experiment = ExperimentFactory(code='ExperimentUwOverhaul')
        self.experiment_test_group = ExperimentTestGroupFactory(
            experiment=self.experiment,
            type='application',
            value='#nth:-1:1,2,3,4,5,6,7,8,9,0',
        )
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.PARTNER_ACCOUNTS_FORCE_LOGOUT,
            is_active=True,
            parameters=[
                'Dagangan',
            ],
        )

    @patch(
        'juloserver.application_form.services.product_picker_service.check_latitude_longitude',
        return_value=True,
    )
    def test_picker_product_j1(self, mocking_check_latitude_longitude):
        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.LONGFORM_SHORTENED_ID,
        )
        application_id = response.json()['data']['applications'][0]['id']
        create_address = AddressGeolocation.objects.filter(application_id=application_id).exists()
        self.assertTrue(create_address)

        # case if not send latitude or longitude as optional
        self.payload.pop('latitude')
        self.payload.pop('longitude')
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 200)

    def test_picker_product_jstarter(self):
        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.JULO_STARTER_ID,
        )

    def test_picker_product_miss_data(self):
        self.payload = {"onboarding_id": 0, "customer_id": 222222}
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

    def test_picker_product_with_status_updated(self):
        """
        Should be updated status
        """

        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['status'],
            ApplicationStatusCodes.FORM_CREATED,
        )

    @patch('juloserver.application_flow.services.still_in_experiment', return_value=True)
    def test_picker_product_with_switch_workflow(self, mock_experiment_duration):
        """
        Should be updated status
        """

        # create first app with jturbo condition
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_line_jstarter
        self.application.onboarding_id = OnboardingIdConst.JULO_STARTER_ID
        self.application.save()

        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client.post(self.endpoint, self.payload)
        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 200)

        # make sure not create other application id but return same application
        application_data = response.json()['data']['applications'][0]
        self.assertEqual(application_data['id'], self.application.id)
        self.assertEqual(
            application_data['onboarding_id'],
            OnboardingIdConst.JULO_STARTER_ID,
        )
        self.assertEqual(
            application_data['customer_mother_maiden_name'],
            self.customer.mother_maiden_name,
        )
        self.assertEqual(application_data['onboarding_id'], OnboardingIdConst.JULO_STARTER_ID)
        self.assertEqual(self.application.workflow.name, WorkflowConst.JULO_STARTER)
        self.assertEqual(
            self.application.product_line.product_line_code, ProductLineCodes.JULO_STARTER
        )
        self.assertEqual(self.application.onboarding_id, OnboardingIdConst.JULO_STARTER_ID)
        turbo_apps = Application.objects.filter(
            customer_id=self.customer.id, onboarding_id=OnboardingIdConst.JULO_STARTER_ID
        ).count()
        self.assertEqual(turbo_apps, 1)

        # case if customer request different onboarding_id
        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.application.refresh_from_db()

        application_data = response.json()['data']['applications'][0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application_data['id'], self.application.id)
        self.assertEqual(application_data['onboarding_id'], OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.assertEqual(self.application.workflow.name, WorkflowConst.JULO_ONE)
        self.assertEqual(self.application.product_line.product_line_code, ProductLineCodes.J1)
        self.assertEqual(self.application.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)
        j1_apps = Application.objects.filter(
            customer_id=self.customer.id, onboarding_id=OnboardingIdConst.LONGFORM_SHORTENED_ID
        ).count()
        self.assertEqual(j1_apps, 1)
        # have experiment UW or not
        is_exists = ApplicationExperiment.objects.filter(
            application=self.application,
            experiment=self.experiment,
        ).exists()
        self.assertTrue(is_exists)

    def test_picker_product_with_multiple_app_case_x107(self):
        """
        Test case multiple app with case x107
        """

        # setup for application jstarter
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = ApplicationStatusCodes.OFFER_REGULAR
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_line_jstarter
        self.application.save()

        # set mother maiden name
        self.customer.mother_maiden_name = 'Jane'
        self.customer.save()

        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        response_app = response.json()['data']['applications'][0]

        # make sure the onboarding should be J1 / LFS
        self.assertEqual(response_app['onboarding_id'], OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.assertEqual(response_app['status'], ApplicationStatusCodes.FORM_CREATED)
        self.assertEqual(response_app['product_line_code'], ProductLineCodes.J1)
        # self.assertIsNone(response_app['customer_mother_maiden_name'])

    def test_picker_product_with_multiple_app_case_jturbo_x137(self):
        """
        Test case multiple app with case x107
        """

        # setup for application jstarter
        # previous is jturbo application in x137
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = (
            ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER
        )
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_line_jstarter
        self.application.save()

        # set mother maiden name
        self.customer.mother_maiden_name = 'Jane'
        self.customer.save()

        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        response_app = response.json()['data']['applications'][0]

        self.assertEqual(response_app['onboarding_id'], OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.assertEqual(response_app['status'], ApplicationStatusCodes.FORM_CREATED)
        self.assertEqual(response_app['product_line_code'], ProductLineCodes.J1)
        # self.assertIsNone(response_app['customer_mother_maiden_name'])

    def test_picker_product_with_multiple_app_case_j1_x137(self):
        """
        Test case multiple app with case x107
        """

        # previous is j1 application in x137
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = (
            ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER
        )
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_line_j1
        self.application.save()

        # set mother maiden name
        self.customer.mother_maiden_name = 'Jane'
        self.customer.save()

        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        response_app = response.json()['data']['applications'][0]

        self.assertEqual(response_app['onboarding_id'], OnboardingIdConst.JULO_STARTER_ID)
        self.assertEqual(response_app['status'], ApplicationStatusCodes.FORM_CREATED)
        self.assertEqual(response_app['product_line_code'], ProductLineCodes.JULO_STARTER)
        # self.assertIsNone(response_app['customer_mother_maiden_name'])

    @patch(
        'juloserver.moengage.services.use_cases.send_user_attributes_to_moengage_for_customer_reminder_vkyc.apply_async'
    )
    def test_product_picker_with_reminder_for_kyc(self, mock_reminder):
        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        mock_reminder.assert_called()

    def test_product_picker_have_existing_app(self):
        """
        For case testing use existing the application_id
        """

        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        response_app = response.json()['data']['applications'][0]
        self.assertEqual(str(response_app['status']), str(ApplicationStatusCodes.FORM_CREATED))

        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 200)
        response_app = response.json()['data']['applications'][0]
        app_jturbo = response_app['id']
        self.assertEqual(str(response_app['status']), str(ApplicationStatusCodes.FORM_CREATED))

        # should be not created new application
        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['applications'][0]['id'], app_jturbo)

        # check have 1 application in x100
        applications_db = Application.objects.filter(customer=self.customer)
        self.assertEqual(applications_db.count(), 1)
        self.assertEqual(applications_db.last().workflow.name, WorkflowConst.JULO_STARTER)

        # case hit with onboarding_id 9 request should response onboarding_id = 3
        OnboardingFactory(id=OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT)
        self.payload['onboarding_id'] = OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 200)
        response_app = response.json()['data']['applications'][0]
        response_app['onboarding_id'] = OnboardingIdConst.LONGFORM_SHORTENED_ID

    def test_if_customer_already_have_status_x190(self):
        """
        Test if customer cannot create other application if have status x190
        """

        # create simulation for app already x190 in J1
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = ApplicationStatusCodes.LOC_APPROVED

        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_line_j1
        self.application.save()

        # try to set can_reapply True should be cannot create application
        self.customer.update_safely(can_reapply=True)
        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

        # try to set can_reapply false should be cannot create application
        self.customer.update_safely(can_reapply=False)
        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

    def test_if_customer_already_have_upgrade_flow_and_reapply(self):

        # create application for JTurbo
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        self.application_turbo = ApplicationFactory(customer=self.customer)
        self.application_turbo.application_status_id = (
            ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE
        )
        self.application_turbo.workflow = self.workflow_jstarter
        self.application_turbo.product_line = self.product_line_jstarter
        self.application_turbo.onboarding_id = OnboardingIdConst.JULO_STARTER_ID
        self.application_turbo.save()

        # create application for J1
        self.application_j1 = ApplicationFactory(customer=self.customer)
        self.application_j1.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application_j1.workflow = self.workflow_j1
        self.application_j1.product_line = self.product_line_j1
        self.application_j1.onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID
        self.application_j1.save()

        # create application upgrade data
        ApplicationUpgradeFactory(
            application_id=self.application_j1.id,
            application_id_first_approval=self.application_turbo.id,
            is_upgrade=1,
        )

        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        response_json = response.json()['data']['applications'][0]
        upgrade_data = ApplicationUpgrade.objects.filter(
            application_id_first_approval=self.application_turbo.id,
            is_upgrade=1,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(upgrade_data.count(), 2)
        self.assertEqual(upgrade_data.last().application_id, response_json['id'])

    def test_reapply_customer_switch_product(self):
        OnboardingFactory(id=OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT)
        self.old_application = ApplicationFactory(
            customer=self.customer, application_number=1, onboarding=self.onboarding_lfs
        )
        self.old_application.update_safely(
            application_status_id=ApplicationStatusCodes.APPLICATION_DENIED,
            refresh=True,
        )

        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        # reapply with product picker FE send ob id 9
        self.customer.update_safely(can_reapply=True)
        self.payload["onboarding_id"] = OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
        response = self.client.post(self.endpoint, self.payload)
        response_app = response.json()['data']['applications'][0]
        self.assertEqual(response_app['onboarding_id'], OnboardingIdConst.LONGFORM_SHORTENED_ID)

        # change to jturbo
        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client.post(self.endpoint, self.payload)
        response_app = response.json()['data']['applications'][0]
        self.assertEqual(response_app['onboarding_id'], OnboardingIdConst.JULO_STARTER_ID)

        # change back to LFS with FE request ob_id = 9
        self.payload["onboarding_id"] = OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
        response = self.client.post(self.endpoint, self.payload)
        response_app = response.json()['data']['applications'][0]
        self.assertEqual(response_app['onboarding_id'], OnboardingIdConst.LONGFORM_SHORTENED_ID)

    def test_if_customer_have_partner_not_allowed_reapply(self):
        """
        Test if customer not allowed reapply
        """

        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 106
        self.application.workflow = self.workflow_j1
        self.application.partner = PartnerFactory(name='dagangan')
        self.application.product_line = self.product_line_j1
        self.application.save()

        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id
        self.assertIsNotNone(self.application.partner_id)
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 401)

    def test_if_customer_have_partner_is_empty(self):
        """
        Test if customer not allowed reapply
        """

        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 106
        self.application.workflow = self.workflow_j1
        self.application.partner = PartnerFactory(name='dagangan')
        self.application.product_line = self.product_line_j1
        self.application.save()
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id
        self.assertIsNotNone(self.application.partner_id)
        self.application.update_safely(partner=None)
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 201)

    def test_if_customer_have_partner_allowed_reapply(self):
        """
        Test if customer allowed reapply
        """

        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 106
        self.application.workflow = self.workflow_j1
        self.application.partner = PartnerFactory(name='non-listed')
        self.application.product_line = self.product_line_j1
        self.application.save()

        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id
        self.assertIsNotNone(self.application.partner_id)
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 201)

    @patch(
        'juloserver.application_form.services.product_picker_service.generate_address_from_geolocation_async.delay'
    )
    @patch(
        'juloserver.application_form.services.product_picker_service.check_latitude_longitude',
        return_value=True,
    )
    def test_picker_product_j1_with_latitude_longitude(
        self, mocking_check_latitude_longitude, mocking_generate_address
    ):
        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.LONGFORM_SHORTENED_ID,
        )
        application_id = response.json()['data']['applications'][0]['id']
        create_address = AddressGeolocation.objects.filter(application_id=application_id).exists()
        self.assertTrue(create_address)
        self.assertTrue(mocking_generate_address.called)

    @patch(
        'juloserver.application_form.services.product_picker_service.generate_address_from_geolocation_async.delay'
    )
    def test_picker_product_j1_without_latitude_longitude(self, mocking_check_latitude_longitude):

        # case if not send latitude or longitude as optional
        self.payload.pop('latitude')
        self.payload.pop('longitude')
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertFalse(mocking_check_latitude_longitude.called)

    @patch(
        'juloserver.application_form.services.product_picker_service.generate_address_from_geolocation_async.delay'
    )
    def test_picker_product_j1_without_latitude_longitude_set_none(
        self, mocking_check_latitude_longitude
    ):
        # case if not send latitude or longitude as optional
        self.payload['latitude'] = None
        self.payload['longitude'] = None
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(mocking_check_latitude_longitude.called)

    @patch(
        'juloserver.application_form.services.product_picker_service.generate_address_from_geolocation_async.delay'
    )
    def test_picker_product_j1_without_latitude_longitude_set_empty_string(
        self, mocking_check_latitude_longitude
    ):
        # case if not send latitude or longitude as optional
        self.payload['latitude'] = ""
        self.payload['longitude'] = ""
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(mocking_check_latitude_longitude.called)

    def test_if_customer_have_x107_but_choose_jturbo(self):
        """
        Test if customer allowed reapply
        """

        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 107
        self.application.workflow = self.workflow_jstarter
        self.application.product_line = self.product_line_jstarter
        self.application.onboarding_id = OnboardingIdConst.JULO_STARTER_ID
        self.application.save()

        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.LONGFORM_SHORTENED_ID,
        )

    @patch(
        'juloserver.application_form.services.product_picker_service.check_latitude_longitude',
        return_value=True,
    )
    def test_picker_product_j1_j360(self, mocking_check_latitude_longitude):
        self.payload["onboarding_id"] = OnboardingIdConst.JULO_360_J1_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.JULO_360_J1_ID,
        )
        application_id = response.json()['data']['applications'][0]['id']
        create_address = AddressGeolocation.objects.filter(application_id=application_id).exists()
        self.assertTrue(create_address)

        # case if not send latitude or longitude as optional
        self.payload.pop('latitude')
        self.payload.pop('longitude')
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 200)

    @patch(
        'juloserver.application_form.services.product_picker_service.check_latitude_longitude',
        return_value=True,
    )
    def test_picker_product_jturbo_j360(self, mocking_check_latitude_longitude):
        self.payload["onboarding_id"] = OnboardingIdConst.JULO_360_TURBO_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.JULO_360_TURBO_ID,
        )
        application_id = response.json()['data']['applications'][0]['id']
        application = Application.objects.filter(pk=application_id).last()
        workflow = Workflow.objects.filter(id=application.workflow_id).last()
        self.assertEqual(workflow.name, WorkflowConst.JULO_STARTER)
        create_address = AddressGeolocation.objects.filter(application_id=application_id).exists()
        self.assertTrue(create_address)

        # case if not send latitude or longitude as optional
        self.payload.pop('latitude')
        self.payload.pop('longitude')
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 200)

    def test_if_customer_have_x107_but_choose_jturbo_after_creating_j1_app(self):
        # Case last_app = 105 J1, should return J1 LFS
        self.j1_application = ApplicationFactory(customer=self.customer)
        self.j1_application.application_status_id = 100
        self.j1_application.workflow = self.workflow_j1
        self.j1_application.product_line = self.product_line_j1
        self.j1_application.onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID
        self.j1_application.save()

        response = self.client.post(self.endpoint, self.payload, format='json')

        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.LONGFORM_SHORTENED_ID,
        )

        # Case have x107 Julo Turbo and x135 but can_reapply = True, should return new Turbo App
        self.j1_application.application_status_id = 135
        self.j1_application.save()

        self.customer.can_reapply = True
        self.customer.save()

        self.payload["onboarding_id"] = OnboardingIdConst.JULO_STARTER_ID
        response = self.client.post(self.endpoint, self.payload, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.JULO_STARTER_ID,
        )

    def test_logic_reroute_onboarding_2_to_3(self):
        """
        Test if customer allowed create new application for onboarding ID 2
        """

        self.onboarding_shortform = OnboardingFactory(id=OnboardingIdConst.SHORTFORM_ID)

        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 106
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_line_j1
        self.application.onboarding_id = OnboardingIdConst.SHORTFORM_ID
        self.application.save()
        self.payload["onboarding_id"] = OnboardingIdConst.SHORTFORM_ID
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        response = self.client.post(self.endpoint, self.payload, format='json')
        response_json = response.json()['data']
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response_json['applications'][0]['onboarding_id'],
            OnboardingIdConst.LONGFORM_SHORTENED_ID,
        )
        self.assertIsNotNone(self.application.ktp)
        self.assertIsNotNone(self.application.email)
        new_application = Application.objects.filter(
            id=response.json()['data']['applications'][0]['id']
        ).last()
        self.assertEqual(new_application.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)

        # delete application
        new_application.delete()
        self.customer.update_safely(can_reapply=True)

        # hit endpoint product picker
        response = self.client.post(self.endpoint, self.payload, format='json')
        response_json = response.json()['data']
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response_json['applications'][0]['onboarding_id'],
            OnboardingIdConst.LONGFORM_SHORTENED_ID,
        )
        self.assertIsNotNone(self.application.ktp)
        self.assertIsNotNone(self.application.email)
        new_application = Application.objects.filter(
            id=response.json()['data']['applications'][0]['id']
        ).last()
        self.assertEqual(new_application.onboarding_id, OnboardingIdConst.LONGFORM_SHORTENED_ID)

    def test_logic_not_allowed_reroute_onboarding_2_to_3(self):
        """
        Test if customer not allowed create new application for onboarding ID 2
        """

        self.onboarding_shortform = OnboardingFactory(id=OnboardingIdConst.SHORTFORM_ID)

        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 106
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_line_j1
        self.application.onboarding_id = OnboardingIdConst.SHORTFORM_ID
        self.application.save()
        self.payload["onboarding_id"] = OnboardingIdConst.SHORTFORM_ID
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        self.application.update_safely(ktp=None)
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0],
            GeneralMessageResponseShortForm.message_not_allowed_reapply_for_shortform,
        )

    def test_logic_not_allowed_for_user_have_last_application_x105(self):

        # last application x105
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 105
        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_line_j1
        self.application.onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID
        self.application.save()

        self.payload["onboarding_id"] = OnboardingIdConst.LONGFORM_SHORTENED_ID
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)

    @patch(
        'juloserver.application_form.services.product_picker_service.check_latitude_longitude',
        return_value=True,
    )
    def test_picker_product_j1_j360(self, mocking_check_latitude_longitude):
        self.payload["onboarding_id"] = OnboardingIdConst.JULO_360_J1_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.JULO_360_J1_ID,
        )
        application_id = response.json()['data']['applications'][0]['id']
        create_address = AddressGeolocation.objects.filter(application_id=application_id).exists()
        self.assertTrue(create_address)

        # case if not send latitude or longitude as optional
        self.payload.pop('latitude')
        self.payload.pop('longitude')
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 200)

    @patch(
        'juloserver.application_form.services.product_picker_service.check_latitude_longitude',
        return_value=True,
    )
    def test_picker_product_jturbo_j360(self, mocking_check_latitude_longitude):
        self.payload["onboarding_id"] = OnboardingIdConst.JULO_360_TURBO_ID
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()['data']['applications'][0]['onboarding_id'],
            OnboardingIdConst.JULO_360_TURBO_ID,
        )
        application_id = response.json()['data']['applications'][0]['id']
        create_address = AddressGeolocation.objects.filter(application_id=application_id).exists()
        self.assertTrue(create_address)

        # case if not send latitude or longitude as optional
        self.payload.pop('latitude')
        self.payload.pop('longitude')
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 200)

    def test_julo_360_mobile_phone_pick_product(self):
        self.application = ApplicationFactory(customer=self.customer)
        self.application.onboarding_id = self.onboarding_j1_j360
        self.application.save()

        customer_phone = '08111122223333'
        self.customer.phone = customer_phone
        self.customer.save()

        self.payload["onboarding_id"] = 10
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 201)

        new_application = Application.objects.filter(
            id=response.json()['data']['applications'][0]['id']
        ).last()
        self.assertEqual(new_application.onboarding_id, 10)
        self.assertEqual(new_application.mobile_phone_1, customer_phone)

    def test_julo_360_mobile_phone_pick_product(self):
        self.application = ApplicationFactory(customer=self.customer)
        self.application.onboarding_id = self.onboarding_j1_j360
        self.application.save()

        customer_phone = '08111122223333'
        self.customer.phone = customer_phone
        self.customer.save()

        self.payload["onboarding_id"] = 10
        self.device = DeviceFactory(customer=self.customer)
        self.payload['device_id'] = self.device.id

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 201)

        new_application = Application.objects.filter(
            id=response.json()['data']['applications'][0]['id']
        ).last()
        self.assertEqual(new_application.onboarding_id, 10)
        self.assertEqual(new_application.mobile_phone_1, customer_phone)


class TestGetProductPickers(TestCase):
    url = '/api/application-form/v1/product-picker'

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.setting = MobileFeatureSettingFactory(
            feature_name='dynamic_product_picker',
            parameters=[{'title': 'J1'}, {'title': 'Turbo'}],
            is_active=True,
        )

    def test_try_to_get_without_authentication(self):
        response = self.client.get(self.url)
        response_json = response.json()

        self.assertEqual(
            response_json['errors'][0], 'Authentication credentials were not provided.'
        )
        self.assertEqual(response.status_code, 401)

    def test_setting_not_active(self):
        self.setting.is_active = False
        self.setting.save()
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
            HTTP_X_APP_VERSION='7.10.0',
        )
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        errors = response.json()['errors']
        self.assertEqual(errors[0], 'Feature setting not found.')

    def test_success(self):
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
            HTTP_X_APP_VERSION='7.10.0',
        )
        response = self.client.get(self.url)
        data = response.json()['data']

        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['title'], 'J1')
        self.assertEqual(data[1]['title'], 'Turbo')


class TestApplicationUpgrade(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)

        self.endpoint = '/api/application-form/v1/application-upgrade'

        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)

        # JuloStarter
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_line_jstarter = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )
        self.application_form_created = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED
        )
        self.onboarding_lfs = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.onboarding_julostarter = OnboardingFactory(id=OnboardingIdConst.JULO_STARTER_ID)
        self.device = DeviceFactory(customer=self.customer)

        code_referral = "referralcode90"
        self.mantri = MantriFactory(code=code_referral)

        # data submit Julo Turbo to x105
        self.data = {
            "fullname": "Tony Teo",
            "device": self.device,
            "dob": "1991-01-01",
            "gender": "Pria",
            "ktp": "4555560402199712",
            "email": "testingpurpose@julofinance.com",
            "mobile_phone_1": "0833226695",
            "address_street_num": "Jalan Bakung Sari",
            "address_provinsi": "Bali",
            "address_kabupaten": "Kab.Badung",
            "address_kecamatan": "Kuta",
            "address_kelurahan": "Kuta",
            "address_kodepos": "80361",
            "bank_name": "BANK CENTRAL ASIA, Tbk (BCA)",
            "bank_account_number": "34676464346",
            "referral_code": code_referral,
            "onboarding_id": OnboardingIdConst.JULO_STARTER_ID,
            "kin_dob": "1999-09-09",
            "kin_name": "Kin name",
            "kin_gender": "Pria",
            "kin_mobile_phone": "839382928393",
            "kin_relationship": "Kin",
        }

        self.application = ApplicationFactory(
            customer=self.customer,
            onboarding=self.onboarding_julostarter,
            workflow=self.workflow_jstarter,
            product_line=self.product_line_jstarter,
            mantri_id=self.mantri.id,
        )

        # For J1
        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow_j1,
        )

        self.payload = {
            "onboarding_id": OnboardingIdConst.LONGFORM_SHORTENED_ID,
            "customer_id": self.customer.id,
            "device_id": self.device.id,
            "is_rooted_device": False,
            "is_suspicious_ip": False,
            "android_id": "c32d6eee0040052a",
            "gcm_reg_id": "djP4BDXjQe6oZ_nYhIHp9V",
            "manufacturer": "docomo",
            "model": "SO-02J",
            "latitude": 0.0,
            "longitude": 0.0,
        }

        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
            HTTP_X_APP_VERSION='7.10.0',
        )

    def save_image_app(self):
        target_type_images = ('ktp_self', 'selfie', 'crop_selfie')
        for image in target_type_images:
            ImageFactory(image_type=image, image_source=self.application.id)

    def mandatory_case_success(self):
        # update the data
        self.application.update_safely(**self.data)
        self.save_image_app()

    def move_to_loan_approved_status(self):
        self.application.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )

    def create_data_active_liveness(self, total_rows):
        for row in range(total_rows):
            vendor = ActiveLivenessVendorResultFactory()
            ActiveLivenessDetectionFactory(
                application=self.application,
                customer=self.customer,
                liveness_vendor_result=vendor,
            )

    def create_data_passive_liveness(self, total_rows):
        vendor_passive_case = PassiveLivenessVendorResultFactory()
        PassiveLivenessDetectionFactory(
            application=self.application,
            customer=self.customer,
            liveness_vendor_result=vendor_passive_case,
        )

    def test_success_application_upgrade(self):
        """
        To test all case success
        """

        self.mandatory_case_success()
        self.move_to_loan_approved_status()

        # save if is exist mother maiden name
        mother_maiden_name = 'Ibunda'
        self.customer.update_safely(mother_maiden_name=mother_maiden_name)

        WorkflowStatusPathFactory(
            status_previous=190,
            status_next=191,
            type='happy',
            is_active=True,
            workflow=self.workflow_jstarter,
        )

        # hit endpoint to copy data
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(response.json()['data']['device_id'])
        response_json = response.json()['data']['applications'][0]

        self.assertNotEqual(response_json['application_xid'], self.application.application_xid)
        self.assertEqual(response_json['status'], ApplicationStatusCodes.FORM_CREATED)
        self.assertEqual(response_json['fullname'], self.data['fullname'])
        self.assertEqual(response_json['dob'], self.data['dob'])
        self.assertEqual(response_json['ktp'], self.data['ktp'])
        self.assertEqual(response_json['email'], self.data['email'])
        self.assertEqual(response_json['mobile_phone_1'], self.data['mobile_phone_1'])
        self.assertEqual(response_json['address_street_num'], self.data['address_street_num'])
        self.assertEqual(response_json['address_provinsi'], self.data['address_provinsi'])
        self.assertEqual(response_json['address_kabupaten'], self.data['address_kabupaten'])
        self.assertEqual(response_json['address_kecamatan'], self.data['address_kecamatan'])
        self.assertEqual(response_json['address_kelurahan'], self.data['address_kelurahan'])
        self.assertEqual(response_json['address_kodepos'], self.data['address_kodepos'])
        self.assertEqual(response_json['bank_name'], self.data['bank_name'])
        self.assertEqual(response_json['bank_account_number'], self.data['bank_account_number'])
        self.assertEqual(response_json['referral_code'], self.data['referral_code'])
        self.assertEqual(response_json['kin_name'], self.data['kin_name'])
        self.assertEqual(response_json['kin_dob'], self.data['kin_dob'])
        self.assertEqual(response_json['kin_mobile_phone'], self.data['kin_mobile_phone'])
        self.assertEqual(response_json['kin_gender'], self.data['kin_gender'])
        self.assertEqual(response_json['kin_relationship'], self.data['kin_relationship'])

        # make sure data will get onboarding_id LFS
        self.assertEqual(response_json['onboarding_id'], OnboardingIdConst.LONGFORM_SHORTENED_ID)

        # make sure mother_maiden_name is not empty when upgrade application (if exists)
        self.assertEqual(response_json['customer_mother_maiden_name'], mother_maiden_name)

        # make sure the duplication process is success
        images_new_app = Image.objects.filter(image_source=response_json['id']).exists()
        self.assertTrue(images_new_app)
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 191)
        application_j1 = Application.objects.filter(pk=response_json['id']).last()
        self.assertIsNotNone(application_j1.device_id)

    def test_for_onboarding_only_allow_for_lfs(self):
        """
        To test onboarding only allow for LFS
        """

        self.payload['onboarding_id'] = OnboardingIdConst.JULO_STARTER_ID
        self.mandatory_case_success()

        # hit endpoint to copy data
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

    def test_for_onboarding_allow_for_lfs_split_emergency_contact(self):
        # case for Onboarding_id = 9, should be success but changed to LFS

        mother_maiden_name = 'Ibunda'
        self.customer.update_safely(mother_maiden_name=mother_maiden_name)

        WorkflowStatusPathFactory(
            status_previous=190,
            status_next=191,
            type='happy',
            is_active=True,
            workflow=self.workflow_jstarter,
        )

        self.payload['onboarding_id'] = OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT
        self.mandatory_case_success()
        self.move_to_loan_approved_status()

        # hit endpoint to copy data
        response = self.client.post(self.endpoint, self.payload)
        response_json = response.json()['data']['applications'][0]

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response_json['onboarding_id'], OnboardingIdConst.LONGFORM_SHORTENED_ID)

    def test_for_not_found_device_id_param(self):
        """
        To test mandatory to send device_id from FE
        """

        self.payload.pop('device_id')
        self.mandatory_case_success()

        # hit endpoint to copy data
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

    def test_application_upgrade_only_allow_for_jturbo(self):
        """
        Allow only for JTurbo application
        """

        self.application.workflow = self.workflow_j1
        self.application.product_line = self.product_line_j1
        self.application.onboarding_id = OnboardingIdConst.LONGFORM_SHORTENED_ID
        self.application.save()

        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

    def test_application_upgrade_only_for_jturbo_190(self):
        """
        Not allowed other status, only allow for x190
        """

        self.application.application_status = self.application_form_created
        self.application.save()

        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

    def test_copy_liveness_detection(self):
        """
        To test liveness detection
        """
        WorkflowStatusPathFactory(
            status_previous=190,
            status_next=191,
            type='happy',
            is_active=True,
            workflow=self.workflow_jstarter,
        )

        self.mandatory_case_success()
        self.move_to_loan_approved_status()

        # save if is exist mother maiden name
        mother_maiden_name = 'Ibunda'
        self.customer.update_safely(mother_maiden_name=mother_maiden_name)

        target_rows = 3
        target_rows_passive = 1
        customer_rows = 2 * target_rows
        self.create_data_active_liveness(target_rows)
        self.create_data_passive_liveness(target_rows_passive)

        # hit endpoint to copy data
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)
        response_json = response.json()['data']['applications'][0]

        count_active_data_app = ActiveLivenessDetection.objects.filter(
            application_id=response_json['id']
        ).count()
        # make sure only 1 row for copy the data
        self.assertEqual(count_active_data_app, target_rows)

        count_active_data_cust = ActiveLivenessDetection.objects.filter(
            customer_id=self.customer.id
        ).count()
        self.assertEqual(count_active_data_cust, customer_rows)

        count_vendor_active = ActiveLivenessVendorResult.objects.all().count()
        self.assertEqual(count_vendor_active, customer_rows)

        count_passive_data_app = PassiveLivenessDetection.objects.filter(
            application_id=response_json['id']
        ).count()
        # make sure only 1 row for copy the data
        self.assertEqual(count_passive_data_app, target_rows_passive)

        count_passive_data_cust = PassiveLivenessDetection.objects.filter(
            customer_id=self.customer.id
        ).count()
        self.assertEqual(count_passive_data_cust, 2)

        count_vendor_passive = PassiveLivenessVendorResult.objects.all().count()
        self.assertEqual(count_vendor_passive, 2)

    def test_application_not_allowed(self):
        self.application.workflow = self.workflow_j1
        self.application.save()

        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

    def test_have_application_in_x100(self):
        # create application in x100
        application_x100 = ApplicationFactory(
            application_status=StatusLookupFactory(status_code=100), customer=self.customer
        )

        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 400)

    @patch(
        'juloserver.application_form.services.product_picker_service.check_latitude_longitude',
        return_value=True,
    )
    def test_checker_latitude_longitude(self, mock_checker_latitude_longitude):
        self.mandatory_case_success()
        self.move_to_loan_approved_status()

        # save if is exist mother maiden name
        mother_maiden_name = 'Ibunda'
        self.customer.update_safely(mother_maiden_name=mother_maiden_name)

        WorkflowStatusPathFactory(
            status_previous=190,
            status_next=191,
            type='happy',
            is_active=True,
            workflow=self.workflow_jstarter,
        )

        # hit endpoint to copy data
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)

        # check data address_location already generate
        response_json = response.json()['data']['applications'][0]
        create_address = AddressGeolocation.objects.filter(
            application_id=response_json['id']
        ).exists()
        self.assertTrue(create_address)

    @patch(
        'juloserver.application_form.services.product_picker_service.check_latitude_longitude',
        return_value=True,
    )
    def test_checker_latitude_longitude_empty(self, mock_checker_latitude_longitude):
        self.mandatory_case_success()
        self.move_to_loan_approved_status()

        # save if is exist mother maiden name
        mother_maiden_name = 'Ibunda'
        self.customer.update_safely(mother_maiden_name=mother_maiden_name)

        WorkflowStatusPathFactory(
            status_previous=190,
            status_next=191,
            type='happy',
            is_active=True,
            workflow=self.workflow_jstarter,
        )

        # for case not have latitude or longitude
        self.payload.pop('latitude')
        self.payload.pop('longitude')

        # hit endpoint to copy data
        response = self.client.post(self.endpoint, self.payload)
        self.assertEqual(response.status_code, 201)


class TestCreateProfile(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(id=7, name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
        )
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.url = '/api/application-form/v1/create-profile'
        self.setting = FeatureSettingFactory(
            feature_name='idfy_config_id',
            parameters={'config_id': 'test'},
            is_active=True,
        )
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
            is_active=True,
            parameters={
                'weekdays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 0,
                    },
                },
                'holidays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 30,
                    },
                },
            },
        )

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_create_profile_view(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "capture_expires_at": None,
            "capture_link": "https://capture.kyc.idfy.com/captures?t=test",
            "profile_id": "TestIDfy",
        }
        mock_http_request.return_value = mock_response

        response = self.client.get(self.url)
        response_data = response.json().get('data')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response_data['video_call_url'], "https://capture.kyc.idfy.com/captures?t=test"
        )
        self.assertEqual(response_data['profile_id'], "TestIDfy")

        mock_response = Mock()
        mock_response.status_code = 200
        mock_http_request.return_value = mock_response

        response = self.client.get(self.url)
        response_data = response.json().get('data')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response_data['video_call_url'], "https://capture.kyc.idfy.com/captures?t=test"
        )
        self.assertEqual(response_data['profile_id'], "TestIDfy")

        # case x105 calling create profile
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()

        response = self.client.get(self.url)
        response_data = response.json().get('data')
        self.assertEqual(response.status_code, 403)

        # case try create profile using JTURBO
        jturbo_workflow = Workflow.objects.get_or_none(name=WorkflowConst.JULO_STARTER)
        self.application.workflow = jturbo_workflow
        self.application.save()

        response = self.client.get(self.url)
        response_data = response.json().get('data')
        self.assertEqual(response.status_code, 403)

    @patch('django.utils.timezone.now')
    @patch("requests.request")
    def test_create_profile_view_still_in_progress(self, mock_http_request, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 21, 0, 0)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_http_request.return_value = mock_response

        # update the feature setting with schenduler messages
        new_parameters = self.fs.parameters
        new_parameters.update(
            {
                "scheduler_messages": [
                    {
                        "open": {"hour": 8, "minute": 0},
                        "close": {"hour": 18, "minute": 0},
                        "set_date": "2023-10-10",
                    }
                ]
            }
        )
        self.fs.update_safely(parameters=new_parameters)

        IdfyVideoCallFactory(
            reference_id=self.application.application_xid,
            application_id=self.application.id,
            status=LabelFieldsIDFyConst.KEY_IN_PROGRESS,
            profile_url="https://capture.kyc.idfy.com/captures?t=test",
            profile_id="TestIDfy",
        )

        message = 'Video call hanya bisa dilakukan pada jam 08.00 - 18.00 WIB'
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], message)

        # For case success
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        response = self.client.get(self.url)
        response_data = response.json().get('data')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response_data['video_call_url'], "https://capture.kyc.idfy.com/captures?t=test"
        )
        self.assertEqual(response_data['profile_id'], "TestIDfy")

    @patch("requests.request")
    def test_create_profile_view_null(self, mock_http_request):
        mock_response = Mock()

        mock_response.status_code = 401

        mock_http_request.return_value = mock_response

        IdfyVideoCallFactory(
            application_id=self.application.id,
            status=LabelFieldsIDFyConst.KEY_COMPLETED,
        )

        response = self.client.get(self.url)
        response_data = response.json().get('data')
        self.assertEqual(response.status_code, 401)

    @patch("requests.request")
    def test_failed_create_profile_view(self, mock_http_request):
        mock_response = Mock()

        mock_response.status_code = 422
        mock_http_request.return_value = mock_response

        response = self.client.get(self.url)
        response_data = response.json().get('data')
        self.assertEqual(response.status_code, 400)

    @patch('django.utils.timezone.now')
    def test_create_profile_when_status_is_canceled(self, mock_timezone):
        link_capture = 'https://capture.kyc.idfy.com/captures?t=test'
        # mock office hours
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)

        # create application in idfy record
        self.idfy_record = IdfyVideoCallFactory(
            application_id=self.application.id,
            reference_id=self.application.application_xid,
            status=LabelFieldsIDFyConst.KEY_CANCELED,
            profile_url=link_capture,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.idfy_record.refresh_from_db()
        self.assertEqual(self.idfy_record.status, LabelFieldsIDFyConst.KEY_IN_PROGRESS)
        self.assertEqual(self.idfy_record.profile_url, link_capture)

        # hit again the create profile with status in_progress
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.idfy_record.refresh_from_db()
        self.assertEqual(self.idfy_record.status, LabelFieldsIDFyConst.KEY_IN_PROGRESS)
        self.assertEqual(self.idfy_record.profile_url, link_capture)

    @patch('django.utils.timezone.now')
    def test_office_hours_feature_setting(self, mock_timezone):
        # mock office hours = weekend
        mock_timezone.return_value = datetime(2023, 12, 16, 8, 0, 0)

        self.fs.parameters = {
            'weekdays': {
                'open': {
                    'hour': 8,
                    'minute': 0,
                },
                'close': {
                    'hour': 20,
                    'minute': 0,
                },
            },
            'holidays': {
                'open': {
                    'hour': 12,
                    'minute': 0,
                },
                'close': {
                    'hour': 20,
                    'minute': 30,
                },
            },
        }
        self.fs.save()

        IdfyVideoCallFactory(
            reference_id=self.application.application_xid,
            application_id=self.application.id,
            status=LabelFieldsIDFyConst.KEY_IN_PROGRESS,
            profile_url="https://capture.kyc.idfy.com/captures?t=test",
            profile_id="TestIDfy",
        )

        message = 'Video call hanya bisa dilakukan pada jam 12.00 - 20.30 WIB'
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], message)

        # weekday
        mock_timezone.return_value = datetime(2023, 12, 15, 8, 0, 0)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class TestIdfyVideoCallBack(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        # J1
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line_code = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.endpoint = '/api/application-form/v1/idfy/video/callback'
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line_code=self.product_line_code,
            workflow=self.workflow,
            application_xid=1000012425,
        )

        self.payload = {
            'config': {'id': '98918213131-2131231', 'overrides': None},
            'profile_data': {
                'completed_at': '2023-08-16T03:29:00Z',
                'created_at': '2023-08-16T02:46:49Z',
                'email': [],
                'mobile_number': [],
                'notes': None,
                'performed_by': [
                    {
                        'account_id': 'account_id_test',
                        'action': 'video_call',
                        'email': 'mr_testing@julo.co.id',
                        'performed_at': '2023-08-16T03:28:59Z',
                    },
                    {
                        'account_id': 'NA',
                        'action': 'review',
                        'email': 'NA',
                        'performed_at': '2023-08-16T03:28:59Z',
                    },
                ],
                'purged_at': None,
            },
            'profile_id': '615e91e9-b9f1-422b-bc54-8f126af3dad6',
            'reference_id': '1000012425',
            'resources': {
                'images': [
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'business_document.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': 'https://image',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'nil.selfie.nil.2.nil',
                        'source': 2,
                        'tags': None,
                        'type': 'selfie',
                        'value': 'https://image',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'ktp_1.nil.nil.2.front',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': 'https://image',
                    },
                ],
                'text': [
                    {
                        'attr': 'address',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'ktp_address.nil.address.3.nil',
                        'source': 3,
                        'tags': None,
                        'type': None,
                        'value': 'Address ktp',
                    },
                    {
                        'attr': 'dob',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'ktp_dob.nil.dob.3.nil',
                        'source': 3,
                        'tags': None,
                        'type': None,
                        'value': '2000-08-20',
                    },
                    {
                        'attr': 'place_of_birth',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'ktp_birth_place.nil.place_of_birth.3.nil',
                        'source': 3,
                        'tags': None,
                        'type': None,
                        'value': 'PLM',
                    },
                    {
                        'attr': 'name',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'ktp_name.nil.name.3.nil',
                        'source': 3,
                        'tags': None,
                        'type': None,
                        'value': 'ASD QWLR',
                    },
                    {
                        'attr': 'id_number',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'ktp_1.nil.id_number.3.nil',
                        'source': 3,
                        'tags': None,
                        'type': None,
                        'value': '1110001111119999',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'total_debt.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '200000',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'acc_number.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '32987987343',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'total_month.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '2000000',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'inc_month.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '4500000',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'pay_date.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '25',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'comp_tele.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '0214324324234',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'start_job.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '2021-01-25',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'comp_name.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': 'sdfsdf',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'family_no.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '081912344426',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'family_name.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': 'dsdfsdf',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'spouse_no.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '081912344426',
                    },
                    {
                        'attr': 'id_number',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'parent_no.nil.id_number.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '081912344426',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'spouse_name.nil.nil.2.nil',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': 'spouse name',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'parent_name.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': 'sdf',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'mothers_name.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': 'ibu kandung',
                    },
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'mobile_number.nil.nil.2.1',
                        'source': 2,
                        'tags': None,
                        'type': None,
                        'value': '081912344426',
                    },
                    {
                        'attr': 'name',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'nil.nil.name.0.nil',
                        'source': 0,
                        'tags': None,
                        'type': None,
                        'value': {'first_name': 'Test', 'last_name': 'JULO'},
                    },
                ],
            },
            'reviewer_action': 'approved',
            'status': 'capture_pending',
            'tasks': [
                {
                    'key': 'assisted_video.video_pd',
                    'resources': [],
                    'result': {
                        'automated_response': None,
                        'manual_response': {
                            'performed_by': {
                                'account_id': '9ca343b8-3d11-4c4b-b533-7cc00fcb6a06',
                                'action': 'video_call',
                                'email': 'mr_testing@julo.co.id',
                                'performed_at': '2023-08-16T03:28:59Z',
                            },
                            'skill_config': {},
                            'status': 'verified',
                            'status_reason': None,
                        },
                    },
                    'status': 'in_progress',
                }
            ],
            'version': 'v1.1',
            'tag': None,
        }

    def test_monthly_income_from_idfy(self):
        payload = deepcopy(self.payload)

        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            workflow=self.workflow,
        )

        self.application.update_safely(
            application_status_id=100,
        )
        payload['status'] = 'completed'
        response = self.client.post(self.endpoint, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.monthly_income, 4500000)

        # update payload for None or any False value in monthlu_income
        old_text_data = payload.get('resources').get('text')
        text = []
        for t in old_text_data:
            if t.get('ref_id') == 'inc_month.nil.nil.2.1':
                continue
            text.append(t)
        text.append(
            {
                'attr': None,
                'location': {},
                'metadata': {},
                'ref_id': 'inc_month.nil.nil.2.1',
                'source': 2,
                'tags': None,
                'type': None,
                'value': "",
            }
        )
        payload["resources"]["text"] = text
        response = self.client.post(self.endpoint, payload, format="json")
        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.application.monthly_income, 4500000)

    def test_idfy_manual_response_extra_fields(self):
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            workflow=self.workflow,
        )

        self.application.update_safely(
            application_status_id=100,
        )
        payload = deepcopy(self.payload)
        payload['status'] = 'completed'
        payload['tasks'][0]['tasks'] = [
            {
                'tasks': [
                    {
                        "key": "avkyc_pan_4689",
                        "resources": ["ktp_1.nil.nil.2.front"],
                        "result": {
                            "manual_response": {
                                "change_log": [],
                                "changed": False,
                                "extraction_output": {
                                    "agama": "ISLAM",
                                    "alamat": "LK.VI JUA JUA",
                                    "berlaku_hingga": "",
                                    "gol_darah": "",
                                    "jenis_kelamin": "LAKI-LAKI",
                                    "kecamatan": "KAYU AGUNG",
                                    "kel_desa": "JUA JUA",
                                    "kewarganegaraan": "WNI",
                                    "kota_or_kabupaten": "OGAN KOMERING ILIR",
                                    "nama": "TARMIDI HENGKI WUAYA",
                                    "nik": "1602050702860001",
                                    "pekerjaan": "WIRASWASTA",
                                    "provinci": "SUMATERA SELATAN",
                                    "rt_rw": "007/000",
                                    "status_perkawinan": "KAWIN",
                                    "tempat": "PALEMBANG",
                                    "tgl_lahir": "1986-02-07",
                                },
                            }
                        },
                        "status": "completed",
                        "task_id": "9c3b3d8a-0a1c-43a4-8bdf-652a3ab62099",
                        "task_type": "extract.idn_ktp",
                    }
                ]
            }
        ]
        response = self.client.post(self.endpoint, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.gender, 'Pria')
        self.assertEqual(self.application.fullname, 'TARMIDI HENGKI WUAYA')
        self.assertEqual(self.application.job_type, 'WIRASWASTA')
        self.assertEqual(self.application.marital_status, 'Menikah')

    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_selfie_to_application.delay'
    )
    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_ktp_to_application.delay'
    )
    def test_case_for_init_callback(
        self,
        mock_copy_resource_ktp,
        mock_copy_resource_selfie,
    ):
        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 200)

        mock_copy_resource_ktp.assert_not_called()
        mock_copy_resource_selfie.assert_not_called()

        data_record = IdfyVideoCall.objects
        self.assertEqual(data_record.count(), 1)
        idfy_data = data_record.last()
        self.assertEqual(idfy_data.status, 'capture_pending')
        self.assertEqual(idfy_data.application_id, self.application.id)

    @patch(
        'juloserver.application_form.services.idfy_service.get_zipcode_from_idfy_callback',
        return_value='12345',
    )
    @patch(
        'juloserver.application_form.services.idfy_service.send_user_attributes_to_moengage_for_idfy_completed_data.delay'
    )
    @patch('juloserver.application_flow.tasks.application_tag_tracking_task.delay')
    @patch(
        'juloserver.application_form.services.idfy_service.send_user_attributes_to_moengage_for_idfy_verification_success.delay'
    )
    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_selfie_to_application.delay'
    )
    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_ktp_to_application.delay'
    )
    @patch('juloserver.application_form.services.idfy_service.copy_resource_to_application')
    def test_case_for_complete_callback_longform(
        self,
        mock_copy_resource_to_app,
        mock_copy_resource_ktp,
        mock_copy_resource_selfie,
        mock_notification_moengage,
        mock_application_path_tag,
        mock_notification_completed,
        mock_get_zipcode,
    ):
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            workflow=self.workflow,
        )

        self.application.update_safely(
            application_status_id=100,
            onboarding_id=1,
        )

        mock_application_update = {
            'address_street_num': 'Address ktp',
            'dob': '1986-02-07',
            'birth_place': 'PALEMBANG',
            'total_current_debt': '200000',
            'bank_account_number': '32987987343',
            'monthly_income': '4500000',
            'monthly_expenses': '2000000',
            'payday': '25',
            'job_start': '2021-01-25',
            'company_name': 'sdfsdf',
            'spouse_mobile_phone': '081912344426',
            'spouse_name': 'spouse name',
            'mobile_phone_1': '081912344426',
            'kin_mobile_phone': '081912344426',
            'fullname': 'TARMIDI HENGKI WUAYA',
            'kin_name': 'dsdfsdf',
            'close_kin_name': 'sdf',
            'address_detail': 'LK.VI JUA JUA',
            'company_phone_number': '0214324324234',
            'name_in_bank': 'ASD QWLR',
            'job_type': 'WIRASWASTA',
            'close_kin_relationship': 'aaaaaa',
            'address_kecamatan': 'KAYU AGUNG',
            'address_kabupaten': 'OGAN KOMERING ILIR',
            'address_provinsi': 'SUMATERA SELATAN',
            'address_kelurahan': 'JUA JUA',
            'marital_status': 'Menikah',
            'gender': 'Pria',
            'home_status': 'Status',
            'close_kin_mobile_phone': '081912344499',
            'kin_relationship': 'parents',
        }
        self.application.update_safely(**mock_application_update, refresh=True)
        mock_copy_resource_to_app.return_value = (self.application, mock_application_update)

        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 200)

        self.payload['status'] = 'completed'
        self.payload['tasks'][0]['status'] = 'completed'
        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 200)

        mock_copy_resource_ktp.assert_called()
        mock_copy_resource_selfie.assert_called()
        mock_notification_moengage.assert_not_called()
        mock_application_path_tag.assert_called()
        mock_notification_completed.assert_called()

        self.application.refresh_from_db()

        data_record = IdfyVideoCall.objects.last()
        self.assertEqual(data_record.status_tasks, 'completed')
        self.assertEqual(data_record.status, 'completed')
        self.assertEqual(data_record.reviewer_action, 'approved')
        self.assertEqual(data_record.application_id, self.application.id)
        self.assertEqual(self.application.mobile_phone_1, '081912344426')
        self.assertEqual(self.application.address_street_num, 'Address ktp')
        self.assertEqual(self.application.spouse_name, 'spouse name')
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.FORM_PARTIAL
        )
        is_exist_passive_record = PassiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_passive_record.count(), 1)
        is_exist_active_record = ActiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_active_record.count(), 1)

    @patch(
        'juloserver.application_form.services.idfy_service.get_zipcode_from_idfy_callback',
        return_value='12345',
    )
    @patch(
        'juloserver.application_form.services.idfy_service.send_user_attributes_to_moengage_for_idfy_completed_data.delay'
    )
    @patch('juloserver.application_flow.tasks.application_tag_tracking_task.delay')
    @patch(
        'juloserver.application_form.services.idfy_service.send_user_attributes_to_moengage_for_idfy_verification_success.delay'
    )
    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_selfie_to_application.delay'
    )
    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_ktp_to_application.delay'
    )
    def test_case_for_complete_callback_for_lfs_application(
        self,
        mock_copy_resource_ktp,
        mock_copy_resource_selfie,
        mock_notification_moengage,
        mock_application_path_tag,
        mock_notification_completed,
        mock_get_zipcode,
    ):
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            workflow=self.workflow,
        )
        self.payload['tasks'][0]['tasks'] = [
            {
                'tasks': [
                    {
                        "key": "avkyc_pan_4689",
                        "resources": ["ktp_1.nil.nil.2.front"],
                        "result": {
                            "manual_response": {
                                "change_log": [],
                                "changed": False,
                                "extraction_output": {
                                    "agama": "ISLAM",
                                    "alamat": "LK.VI JUA JUA",
                                    "berlaku_hingga": "",
                                    "gol_darah": "",
                                    "jenis_kelamin": "LAKI-LAKI",
                                    "kecamatan": "KAYU AGUNG",
                                    "kel_desa": "JUA JUA",
                                    "kewarganegaraan": "WNI",
                                    "kota_or_kabupaten": "OGAN KOMERING ILIR",
                                    "nama": "TARMIDI HENGKI WUAYA",
                                    "nik": "1602050702860001",
                                    "pekerjaan": "WIRASWASTA",
                                    "provinci": "SUMATERA SELATAN",
                                    "rt_rw": "007/000",
                                    "status_perkawinan": "KAWIN",
                                    "tempat": "PALEMBANG",
                                    "tgl_lahir": "1986-02-07",
                                },
                            }
                        },
                        "status": "completed",
                        "task_id": "9c3b3d8a-0a1c-43a4-8bdf-652a3ab62099",
                        "task_type": "extract.idn_ktp",
                    },
                ]
            },
            {
                'tasks': [
                    {
                        "key": "verifyQA_1",
                        "resources": ["ktp_1.nil.nil.2.front"],
                        "result": {
                            "manual_response": {'value': 'aaaaaa'},
                        },
                        "status": "completed",
                        "task_id": "9c3b3d8a-0a1c-43a4-8bdf-652a3ab62099",
                        "task_type": "extract.idn_ktp",
                    },
                ]
            },
        ]

        self.application.update_safely(
            application_status_id=100,
            onboarding_id=3,
        )
        self.payload['status'] = 'completed'
        self.payload['tasks'][0]['status'] = 'completed'
        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 200)

        mock_copy_resource_ktp.assert_called()
        mock_copy_resource_selfie.assert_called()
        # mock_notification_moengage.assert_not_called()
        mock_application_path_tag.assert_called()
        # mock_notification_completed.assert_called()

        self.application.refresh_from_db()

        data_record = IdfyVideoCall.objects.last()
        self.assertEqual(data_record.status_tasks, 'completed')
        self.assertEqual(data_record.status, 'completed')
        self.assertEqual(data_record.reviewer_action, 'approved')
        self.assertEqual(data_record.application_id, self.application.id)
        self.assertEqual(self.application.mobile_phone_1, '081912344426')
        self.assertEqual(self.application.address_street_num, 'Address ktp')
        self.assertEqual(self.application.spouse_name, 'spouse name')
        # self.assertEqual(
        #     self.application.application_status_id, ApplicationStatusCodes.FORM_PARTIAL
        # )
        is_exist_passive_record = PassiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_passive_record.count(), 1)
        is_exist_active_record = ActiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_active_record.count(), 1)

    @patch(
        'juloserver.application_form.services.idfy_service.get_zipcode_from_idfy_callback',
        return_value='12345',
    )
    @patch(
        'juloserver.application_form.services.idfy_service.send_user_attributes_to_moengage_for_idfy_completed_data.delay'
    )
    @patch('juloserver.application_flow.tasks.application_tag_tracking_task.delay')
    @patch(
        'juloserver.application_form.services.idfy_service.send_user_attributes_to_moengage_for_idfy_verification_success.delay'
    )
    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_selfie_to_application.delay'
    )
    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_ktp_to_application.delay'
    )
    def test_case_for_complete_callback_for_lfs_split_emergency_contact_application(
        self,
        mock_copy_resource_ktp,
        mock_copy_resource_selfie,
        mock_notification_moengage,
        mock_application_path_tag,
        mock_notification_completed,
        mock_get_zipcode,
    ):
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            workflow=self.workflow,
        )
        self.payload['tasks'][0]['tasks'] = [
            {
                'tasks': [
                    {
                        "key": "avkyc_pan_4689",
                        "resources": ["ktp_1.nil.nil.2.front"],
                        "result": {
                            "manual_response": {
                                "change_log": [],
                                "changed": False,
                                "extraction_output": {
                                    "agama": "ISLAM",
                                    "alamat": "LK.VI JUA JUA",
                                    "berlaku_hingga": "",
                                    "gol_darah": "",
                                    "jenis_kelamin": "LAKI-LAKI",
                                    "kecamatan": "KAYU AGUNG",
                                    "kel_desa": "JUA JUA",
                                    "kewarganegaraan": "WNI",
                                    "kota_or_kabupaten": "OGAN KOMERING ILIR",
                                    "nama": "TARMIDI HENGKI WUAYA",
                                    "nik": "1602050702860001",
                                    "pekerjaan": "WIRASWASTA",
                                    "provinci": "SUMATERA SELATAN",
                                    "rt_rw": "007/000",
                                    "status_perkawinan": "KAWIN",
                                    "tempat": "PALEMBANG",
                                    "tgl_lahir": "1986-02-07",
                                },
                            }
                        },
                        "status": "completed",
                        "task_id": "9c3b3d8a-0a1c-43a4-8bdf-652a3ab62099",
                        "task_type": "extract.idn_ktp",
                    },
                ]
            },
            {
                'tasks': [
                    {
                        "key": "verifyQA_1",
                        "resources": ["ktp_1.nil.nil.2.front"],
                        "result": {
                            "manual_response": {'value': 'aaaaaa'},
                        },
                        "status": "completed",
                        "task_id": "9c3b3d8a-0a1c-43a4-8bdf-652a3ab62099",
                        "task_type": "extract.idn_ktp",
                    },
                ]
            },
        ]

        self.application.update_safely(
            application_status_id=100,
            onboarding_id=9,
        )
        self.payload['status'] = 'completed'
        self.payload['tasks'][0]['status'] = 'completed'
        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 200)

        mock_copy_resource_ktp.assert_called()
        mock_copy_resource_selfie.assert_called()
        mock_notification_moengage.assert_not_called()
        mock_application_path_tag.assert_called()
        mock_notification_completed.assert_called()

        self.application.refresh_from_db()

        data_record = IdfyVideoCall.objects.last()
        self.assertEqual(data_record.status_tasks, 'completed')
        self.assertEqual(data_record.status, 'completed')
        self.assertEqual(data_record.reviewer_action, 'approved')
        self.assertEqual(data_record.application_id, self.application.id)
        self.assertEqual(self.application.mobile_phone_1, '081912344426')
        self.assertEqual(self.application.address_street_num, 'Address ktp')
        self.assertEqual(self.application.spouse_name, 'spouse name')
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.FORM_PARTIAL
        )
        is_exist_passive_record = PassiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_passive_record.count(), 1)
        is_exist_active_record = ActiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_active_record.count(), 1)

    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_selfie_to_application.delay'
    )
    @patch(
        'juloserver.application_form.services.idfy_service.copy_resource_ktp_to_application.delay'
    )
    def test_case_for_bad_request_callback(
        self,
        mock_copy_resource_ktp,
        mock_copy_resource_selfie,
    ):
        self.payload = None
        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_case_if_customer_not_have_image_in_response(self):
        self.payload = {
            'config': {'id': '51d1b15f-71bf-4df2-a469', 'overrides': None},
            'device_info': {'final_ipv4': '35.12131321', 'user_agent': 'user_agent'},
            'profile_data': {
                'completed_at': '2023-08-29T04:07:15Z',
                'created_at': '2023-08-29T04:01:11Z',
                'email': [],
                'mobile_number': [],
                'notes': None,
                'performed_by': [
                    {
                        'account_id': 'b4dad2df-5559-4b2e-87ba',
                        'action': 'video_call',
                        'email': 'mr@testing.julo.co.id',
                        'performed_at': '2023-08-29T04:07:14Z',
                    },
                ],
                'purged_at': None,
            },
            'profile_id': 'a84de7a8-987f-47cb-934b',
            'reference_id': str(self.application.application_xid),
            'resources': {
                'documents': [
                    {
                        'attr': None,
                        'location': {},
                        'metadata': {},
                        'ref_id': 'user.profile_report.nil.4.nil',
                        'source': 4,
                        'tags': [],
                        'type': 'profile_report',
                        'value': '',
                    }
                ],
                'images': [],
                'text': [
                    {
                        'attr': 'name',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'nil.nil.name.0.nil',
                        'source': 0,
                        'tags': None,
                        'type': None,
                        'value': {'first_name': 'Test', 'last_name': 'JULO'},
                    },
                    {
                        "attr": "id_number",
                        "location": {},
                        "metadata": {},
                        "ref_id": "phone_no.nil.id_number.1.nil",
                        "source": 1,
                        "tags": None,
                        "type": None,
                        "value": "83822825720",
                    },
                ],
                'videos': [],
            },
            'reviewer_action': 'rejected',
            'schema_version': '1.0.0',
            'status': 'completed',
            'status_description': {'code': None, 'comments': None, 'reason': 'auto-close'},
            'status_detail': 'auto-close',
            'tasks': [
                {
                    'key': 'assisted_video.video_pd',
                    'resources': [],
                    'result': {
                        'automated_response': None,
                        'manual_response': {
                            'performed_by': {
                                'account_id': 'b4dad2df-5559-4b2e-87ba-5090d2db6a08',
                                'action': 'video_call',
                                'email': 'ops.pv22@julo.co.id',
                                'performed_at': '2023-08-29T04:07:14Z',
                            },
                            'skill_config': None,
                            'status': 'rejected',
                            'status_reason': 'Pelanggan telah terputus dari panggilan',
                        },
                    },
                    'status': 'processing',
                    'task_id': '66f58ca5-3750-4175-b885-dd6a8193c33d',
                    'task_type': 'assisted_video.video_pd',
                    'tasks': [
                        {'tasks': []},
                    ],
                }
            ],
            'version': 'v1.1',
            'tag': None,
        }

        self.application.update_safely(
            application_status_id=100,
        )
        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 200)
        data_record = IdfyVideoCall.objects.last()
        self.assertEqual(data_record.reviewer_action, 'rejected')
        self.assertEqual(data_record.reject_reason, 'Pelanggan telah terputus dari panggilan')
        self.assertEqual(data_record.status, 'completed')
        self.application.refresh_from_db()
        self.assertEqual(data_record.application_id, self.application.id)
        self.assertEqual(self.application.mobile_phone_1, '83822825720')
        self.assertEqual(
            self.application.application_status_id, ApplicationStatusCodes.FORM_CREATED
        )

    @patch('juloserver.application_form.services.idfy_service.process_application_status_change')
    def test_case_if_customer_have_rejected_from_idfy(self, mock_process_application_status_change):
        self.payload = {
            'config': {'id': '51d1b15f-71bf-4df2-a469', 'overrides': None},
            'device_info': {'final_ipv4': '35.12131321', 'user_agent': 'user_agent'},
            'profile_data': {
                'completed_at': '2023-08-29T04:07:15Z',
                'created_at': '2023-08-29T04:01:11Z',
                'email': [],
                'mobile_number': [],
                'notes': None,
                'performed_by': [
                    {
                        'account_id': 'b4dad2df-5559-4b2e-87ba',
                        'action': 'video_call',
                        'email': 'mr@testing.julo.co.id',
                        'performed_at': '2023-08-29T04:07:14Z',
                    },
                ],
                'purged_at': None,
            },
            'profile_id': 'a84de7a8-987f-47cb-934b',
            'reference_id': str(self.application.application_xid),
            'resources': {
                'documents': [],
                'images': [],
                'text': [
                    {
                        'attr': 'name',
                        'location': {},
                        'metadata': {},
                        'ref_id': 'nil.nil.name.0.nil',
                        'source': 0,
                        'tags': None,
                        'type': None,
                        'value': {'first_name': 'Test', 'last_name': 'JULO'},
                    }
                ],
                'videos': [],
            },
            'reviewer_action': 'rejected',
            'schema_version': '1.0.0',
            'status': 'completed',
            'status_description': {'code': None, 'comments': None, 'reason': 'auto-close'},
            'status_detail': 'auto-close',
            'tasks': [
                {
                    'key': 'assisted_video.video_pd',
                    'resources': [],
                    'result': {
                        'automated_response': None,
                        'manual_response': {
                            'performed_by': {
                                'account_id': 'b4dad2df-5559-4b2e-87ba-5090d2db6a08',
                                'action': 'video_call',
                                'email': 'ops.pv22@julo.co.id',
                                'performed_at': '2023-08-29T04:07:14Z',
                            },
                            'skill_config': None,
                            'status': 'rejected',
                            'status_reason': 'Verifikasi ID pelanggan tidak berhasil',
                        },
                    },
                    'status': 'processing',
                    'task_id': '66f58ca5-3750-4175-b885-dd6a8193c33d',
                    'task_type': 'assisted_video.video_pd',
                    'tasks': [
                        {'tasks': []},
                    ],
                }
            ],
            'version': 'v1.1',
            'tag': None,
        }

        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=135,
            type='happy',
            workflow=self.workflow,
        )
        self.application.update_safely(
            application_status_id=100,
        )
        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 200)
        data_record = IdfyVideoCall.objects.last()
        self.assertEqual(data_record.reviewer_action, 'rejected')
        self.assertEqual(data_record.reject_reason, 'Verifikasi ID pelanggan tidak berhasil')
        self.assertEqual(data_record.status, 'completed')
        self.assertEqual(data_record.application_id, self.application.id)
        mock_process_application_status_change.assert_called_with(
            self.application.id,
            ApplicationStatusCodes.APPLICATION_DENIED,
            'Verifikasi ID pelanggan tidak berhasil',
        )

    def test_idfy_callback_log(self):
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            workflow=self.workflow,
        )

        self.application.update_safely(
            application_status_id=100,
        )

        manual_response = {
            "change_log": [],
            "changed": False,
            "extraction_output": {
                "agama": "ISLAM",
                "alamat": "LK.VI JUA JUA",
                "berlaku_hingga": "",
                "gol_darah": "",
                "jenis_kelamin": "LAKI-LAKI",
                "kecamatan": "KAYU AGUNG",
                "kel_desa": "JUA JUA",
                "kewarganegaraan": "WNI",
                "kota_or_kabupaten": "OGAN KOMERING ILIR",
                "nama": "TARMIDI HENGKI WUAYA",
                "nik": "1602050702860001",
                "pekerjaan": "WIRASWASTA",
                "provinci": "SUMATERA SELATAN",
                "rt_rw": "007/000",
                "status_perkawinan": "KAWIN",
                "tempat": "PALEMBANG",
                "tgl_lahir": "1986-02-07",
            },
        }

        payload = deepcopy(self.payload)
        payload['status'] = 'completed'
        payload['tasks'][0]['tasks'] = [
            {
                'tasks': [
                    {
                        "key": "avkyc_pan_4689",
                        "resources": ["ktp_1.nil.nil.2.front"],
                        "result": {"manual_response": manual_response},
                        "status": "completed",
                        "task_id": "9c3b3d8a-0a1c-43a4-8bdf-652a3ab62099",
                        "task_type": "extract.idn_ktp",
                    }
                ]
            }
        ]
        response = self.client.post(self.endpoint, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()

        idfy_callback_log = IdfyCallBackLog.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertNotEqual(idfy_callback_log, None)
        self.assertDictEqual(manual_response, idfy_callback_log.callback_log)

    def test_idfy_auto_generate_zipcode(self):
        self.workflow_status_path = WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            workflow=self.workflow,
        )

        self.application.update_safely(
            application_status_id=100,
        )
        self.application.update_safely(
            address_kodepos=None,
            address_provinsi=None,
            address_kabupaten=None,
            address_kecamatan=None,
            address_kelurahan=None,
            refresh=True,
        )

        zipcode = '12345'

        province = ProvinceLookupFactory(province='SUMATERA SELATAN')
        city = CityLookupFactory(city='OGAN KOMERING ILIR', province=province)
        district = DistrictLookupFactory(district='KAYU AGUNG', city=city)
        SubDistrictLookupFactory(sub_district='JUA JUA', zipcode=zipcode, district=district)

        payload = deepcopy(self.payload)
        payload['status'] = 'completed'
        payload['tasks'][0]['tasks'] = [
            {
                'tasks': [
                    {
                        "key": "avkyc_pan_4689",
                        "resources": ["ktp_1.nil.nil.2.front"],
                        "result": {
                            "manual_response": {
                                "change_log": [],
                                "changed": False,
                                "extraction_output": {
                                    "agama": "ISLAM",
                                    "alamat": "LK.VI JUA JUA",
                                    "berlaku_hingga": "",
                                    "gol_darah": "",
                                    "jenis_kelamin": "LAKI-LAKI",
                                    "kecamatan": "KAYU AGUNG",
                                    "kel_desa": "JUA JUA",
                                    "kewarganegaraan": "WNI",
                                    "kota_or_kabupaten": "OGAN KOMERING ILIR",
                                    "nama": "TARMIDI HENGKI WUAYA",
                                    "nik": "1602050702860001",
                                    "pekerjaan": "WIRASWASTA",
                                    "provinci": "SUMATERA SELATAN",
                                    "rt_rw": "007/000",
                                    "status_perkawinan": "KAWIN",
                                    "tempat": "PALEMBANG",
                                    "tgl_lahir": "1986-02-07",
                                },
                            }
                        },
                        "status": "completed",
                        "task_id": "9c3b3d8a-0a1c-43a4-8bdf-652a3ab62099",
                        "task_type": "extract.idn_ktp",
                    }
                ]
            }
        ]
        response = self.client.post(self.endpoint, payload, format="json")
        # self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.address_kodepos, zipcode)


class TestApplicationResultFromIDFy(APITestCase):
    url = '/api/application-form/v1/video/result/{}'

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.payload = {
            'is_canceled': True,
        }
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
            is_active=True,
            parameters={
                'weekdays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 0,
                    },
                },
                'holidays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 30,
                    },
                },
            },
        )

    @patch('django.utils.timezone.now')
    def test_not_idfy(self, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        application = ApplicationFactory(customer=self.customer)

        resp = self.client.get(self.url.format(application.id))
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data['data']['idfy'], False)

    @patch('django.utils.timezone.now')
    def test_idfy(self, mock_timezone):
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        idfy_record = IdfyVideoCallFactory(application_id=application.id)

        # status is not completed
        resp = self.client.get(self.url.format(application.id))
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data['data']['idfy'], True)
        self.assertEqual(data['data']['video_status'], 'in_progress')
        self.assertEqual(data['data']['application'], {})

        # status is completed
        idfy_record.status = 'completed'
        idfy_record.save()
        resp = self.client.get(self.url.format(application.id))
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertEqual(data['data']['idfy'], True)
        self.assertEqual(data['data']['video_status'], 'completed')
        self.assertNotEqual(data['data']['application'], {})

        # case outside office hours but status in_completed status
        mock_timezone.return_value = datetime(2023, 10, 10, 21, 0, 0)
        idfy_record.update_safely(status=LabelFieldsIDFyConst.KEY_COMPLETED)
        resp = self.client.get(self.url.format(application.id))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['video_status'], LabelFieldsIDFyConst.KEY_COMPLETED)

        # case outside office hours
        mock_timezone.return_value = datetime(2023, 10, 10, 21, 0, 0)
        idfy_record.update_safely(status=LabelFieldsIDFyConst.KEY_IN_PROGRESS)
        resp = self.client.get(self.url.format(application.id))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['data']['video_status'])

    @patch('django.utils.timezone.now')
    def test_idfy_status_with_change_to_canceled(self, mock_timezone):
        """
        Case for User already in_progress status for IDFy
        """

        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)
        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )
        idfy_record = IdfyVideoCallFactory(application_id=application.id)

        # in_progress
        idfy_record.update_safely(status=LabelFieldsIDFyConst.KEY_IN_PROGRESS)

        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        idfy_record.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_CANCELED)
        self.assertEqual(
            response.json()['data']['destination_page'], ApplicationDirectionConst.PRODUCT_PICKER
        )

        # check status when hit endpoint get status
        response_status = self.client.get(
            self.url.format(application.id), self.payload, format='json'
        )
        self.assertEqual(response_status.status_code, 200)
        self.assertEqual(
            response_status.json()['data']['video_status'], LabelFieldsIDFyConst.KEY_CANCELED
        )

        # update is canceled to False
        self.payload['is_canceled'] = False
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        idfy_record.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_IN_PROGRESS)

        # hit with same payload with current status
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_IN_PROGRESS)

    @patch('django.utils.timezone.now')
    def test_idfy_status_with_change_to_canceled_with_destination_page(self, mock_timezone):
        """
        Case for User already in_progress status for IDFy
        """

        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)

        first_app = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        first_app.update_safely(
            application_status_id=ApplicationStatusCodes.OFFER_REGULAR,
        )

        # create other app
        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )
        idfy_record = IdfyVideoCallFactory(application_id=application.id)

        # in_progress
        idfy_record.update_safely(status=LabelFieldsIDFyConst.KEY_IN_PROGRESS)

        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        idfy_record.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_CANCELED)
        self.assertEqual(
            response.json()['data']['destination_page'], ApplicationDirectionConst.FORM_SCREEN
        )

        # update is canceled to False
        self.payload['is_canceled'] = False
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        idfy_record.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_IN_PROGRESS)

        # hit with same payload with current status
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_IN_PROGRESS)

    @patch('django.utils.timezone.now')
    def test_for_case_customers_havent_init_record_in_video_call_idfy(self, mock_timezone):
        # mocking agent are available
        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)

        # create init app
        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        # try hit endpoint status video call with POST & canceled is True as payload
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['data']['destination_page'], ApplicationDirectionConst.PRODUCT_PICKER
        )

        # case for canceled is False
        self.payload['is_canceled'] = False
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['data']['destination_page'], ApplicationDirectionConst.VIDEO_CALL_SCREEN
        )

        # set case outside office hours agent
        mock_timezone.return_value = datetime(2023, 10, 10, 21, 0, 0)

        # check case go to video call screen
        self.payload['is_canceled'] = False
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0],
            'Video call hanya bisa dilakukan pada jam 08.00 - 20.00 WIB',
        )

        # check case go to form
        self.payload['is_canceled'] = True
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['data']['destination_page'], ApplicationDirectionConst.PRODUCT_PICKER
        )

    @patch('django.utils.timezone.now')
    def test_idfy_status_already_completed(self, mock_timezone):
        """
        Case for User already completed status for IDFy
        """

        mock_timezone.return_value = datetime(2023, 10, 10, 8, 0, 0)

        # create other app
        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        application.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )
        idfy_record = IdfyVideoCallFactory(
            application_id=application.id,
            status=LabelFieldsIDFyConst.KEY_COMPLETED,
            reference_id=application.application_xid,
            profile_url='https://videocall',
        )
        self.payload['is_canceled'] = True
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        idfy_record.refresh_from_db()
        # makesure the status still in completed
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_COMPLETED)

        # case in_canceled False
        self.payload['is_canceled'] = False
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        idfy_record.refresh_from_db()
        # makesure the status still in completed
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_COMPLETED)

        # set for no available time for agent
        mock_timezone.return_value = datetime(2023, 10, 10, 18, 0, 0)

        self.payload['is_canceled'] = True
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        idfy_record.refresh_from_db()
        # makesure the status still in completed
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_COMPLETED)

        # for case is_canceled False
        self.payload['is_canceled'] = False
        response = self.client.post(self.url.format(application.id), self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        idfy_record.refresh_from_db()
        # makesure the status still in completed
        self.assertEqual(idfy_record.status, LabelFieldsIDFyConst.KEY_COMPLETED)


class TestIdfyInstructionPage(TestCase):
    url = '/api/application-form/v1/video/entry-page'

    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_feature_setting_not_found(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 404)

    def test_success(self):
        FeatureSettingFactory(
            feature_name="idfy_instruction_page",
            is_active=True,
            parameters={
                'button_text': 'Mulai Video Call',
                'instruction_image_url': 'info-card/IDFY_INSTRUCTION_PAGE.png',
            },
        )
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)


class TestApplicationDestination(TestCase):
    def setUp(self):
        self.endpoint = '/api/application-form/v1/app-destination-page'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        # J1
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line_code_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        # Jturbo
        self.workflow_jturbo = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_line_code_jturbo = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )

    def test_for_user_no_have_application(self):
        response = self.client.get(self.endpoint)
        json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json['data']['destination_page'], ApplicationDirectionConst.PRODUCT_PICKER)

    def test_for_user_have_application_j1_in_x100(self):
        application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_line_code_j1,
        )
        application_j1.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        response = self.client.get(self.endpoint)
        json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json['data']['destination_page'], ApplicationDirectionConst.PRODUCT_PICKER)

    def test_for_user_have_both_app_in_x100(self):
        application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_line_code_j1,
        )
        application_j1.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        # jturbo
        application_jturbo = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_jturbo,
            product_line=self.product_line_code_jturbo,
        )
        application_jturbo.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        response = self.client.get(self.endpoint)
        json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json['data']['destination_page'], ApplicationDirectionConst.HOME_SCREEN)

    def test_for_user_have_app_in_190(self):
        application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_line_code_j1,
        )
        application_j1.update_safely(
            application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        )

        # jturbo
        application_jturbo = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_jturbo,
            product_line=self.product_line_code_jturbo,
        )
        application_jturbo.update_safely(
            application_status_id=ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        )

        response = self.client.get(self.endpoint)
        json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json['data']['destination_page'], ApplicationDirectionConst.HOME_SCREEN)

    def test_for_user_have_app_in_offer_to_j1(self):
        # jturbo
        application_jturbo = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_jturbo,
            product_line=self.product_line_code_jturbo,
        )
        application_jturbo.update_safely(
            application_status_id=ApplicationStatusCodes.OFFER_REGULAR,
        )

        # J1
        application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_line_code_j1,
        )
        application_j1.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_CREATED,
        )

        response = self.client.get(self.endpoint)
        json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json['data']['destination_page'], ApplicationDirectionConst.HOME_SCREEN)

    def test_for_use_have_app_in_active_status(self):
        application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_line_code_j1,
        )
        application_j1.update_safely(
            application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        )

        response = self.client.get(self.endpoint)
        json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json['data']['destination_page'], ApplicationDirectionConst.HOME_SCREEN)

        application_j1.update_safely(
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
        )

        response = self.client.get(self.endpoint)
        json = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json['data']['destination_page'], ApplicationDirectionConst.HOME_SCREEN)


class TestBottomSheetContents(TestCase):
    def setUp(self):
        self.endpoint = '/api/application-form/v1/bottomsheet-contents'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.bottomsheet_title = 'Registrasi Julo'
        self.bottomsheet_description = (
            'Pastikan kamu sudah menyiapkan dan memenuhi persyaratan di bawah, ya!'
        )
        self.mobile_feature_setting = MobileFeatureSettingFactory(
            is_active=True,
            feature_name=MobileFeatureNameConst.BOTTOMSHEET_CONTENT_PRODUCT_PICKER,
            parameters=[
                {
                    'product': 'j1',
                    'title': 'Registrasi Julo',
                    'description': 'Pastikan kamu sudah menyiapkan dan memenuhi persyaratan di bawah, ya!',
                    'button_text': 'Lanjutkan',
                    'message': [
                        {
                            'message_icon_url': '/test1.jpg',
                            'message_text': 'KTP asli',
                        },
                        {
                            'message_icon_url': '/test1.jpg',
                            'message_text': 'Usia minimum 18 Tahun',
                        },
                        {
                            'message_icon_url': '/test1.jpg',
                            'message_text': 'Tinggal di Indonesia',
                        },
                        {
                            'message_icon_url': '/test1.jpg',
                            'message_text': 'Berpenghasilan minimal Rp2.500.000',
                        },
                    ],
                },
            ],
        )

    def test_bottomsheet_success(self):
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)

        response_data = response.json()
        self.assertEqual(response_data['data'][0]['title'], self.bottomsheet_title)
        self.assertEqual(response_data['data'][0]['description'], self.bottomsheet_description)

        for item in response_data['data'][0]['message']:
            self.assertIsNotNone(item['message_icon_url'])
            self.assertIsNotNone(item['message_text'])

        self.assertEqual(
            len(response_data['data'][0]['message']),
            len(self.mobile_feature_setting.parameters[0].get('message')),
        )

    def test_bottomsheet_negative_case(self):
        self.mobile_feature_setting.is_active = False
        self.mobile_feature_setting.save()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 404)


class TestApplicationMTLForm(TestCase):
    def setUp(self):
        self.endpoint = '/api/application-form/v1/application/apply'
        self.client = APIClient()
        self.user = AuthUserFactory()

        self.customer = CustomerFactory(user=self.user)
        self.email = 'abjad@gmail.com'
        self.fullname = 'Abcdaed'
        self.application = ApplicationFactory(
            email=self.email, customer=self.customer, application_xid=12313123131
        )

        self.bank = BankFactory(bank_code='001')
        self.payload = {
            'email': self.email,
            'fullname': self.fullname,
            'date_of_birth': '1992-09-09',
            'old_phone_number': '08981298231',
            'new_phone_number': '08981298131',
            'is_privacy_agreed': True,
            'name_in_bank': self.fullname,
            'bank_code': self.bank.bank_code,
            'bank_account_number': '102030405060',
        }

    def test_case_if_success_and_cannot_submit_the_form(self):
        self.payload['email'] = ''
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)

        self.payload['email'] = 'Abjad@gmail.com'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('application_id', response.json()['data'])

        mtl_application = ReviveMtlRequest.objects.filter(email=self.payload['email']).last()
        date_of_birth = format_date(mtl_application.date_of_birth, 'yyyy-MM-dd', locale='id_ID')

        self.assertIsNotNone(mtl_application)
        self.assertEqual(mtl_application.application_id, self.application.id)
        self.assertEqual(mtl_application.email, self.payload['email'])
        self.assertEqual(mtl_application.fullname, self.payload['fullname'])
        self.assertEqual(date_of_birth, self.payload['date_of_birth'])
        self.assertEqual(mtl_application.old_phone_number, self.payload['old_phone_number'])
        self.assertEqual(mtl_application.new_phone_number, self.payload['new_phone_number'])
        self.assertEqual(mtl_application.bank_name, self.bank.bank_name)
        self.assertEqual(mtl_application.bank_account_number, self.payload['bank_account_number'])
        self.assertEqual(mtl_application.name_in_bank, self.payload['name_in_bank'])

        # double submit
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Anda sudah pernah mengirim tanggapan Anda')

    def test_case_request_submit_the_form(self):
        # privacy policy not agreed
        self.payload['is_privacy_agreed'] = False
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0],
            'Anda harus menyetujui kebijakan privasi untuk mengajukan formulir',
        )

        self.payload['is_privacy_agreed'] = True
        self.payload.pop('bank_code')
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0],
            'Anda harus mengisi data rekening Anda',
        )

        self.payload['bank_code'] = self.bank.bank_code
        self.payload['old_phone_number'] = ''
        self.payload['new_phone_number'] = '08981298131'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 200)

        self.payload['fullname'] = 'abjad@'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Mohon cek kembali nama lengkap Anda')

        self.payload['fullname'] = 'abjad'
        self.payload['new_phone_number'] = ''
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)

        self.payload['old_phone_number'] = '+6281298131'
        self.payload['new_phone_number'] = '+6281298131'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)

        self.payload['old_phone_number'] = ''
        self.payload['new_phone_number'] = '+6281298131'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)

        self.payload['fullname'] = ''
        self.payload['old_phone_number'] = ''
        self.payload['new_phone_number'] = '081298131'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)

        self.payload.pop('email')
        self.payload['fullname'] = 'abjad'
        self.payload['old_phone_number'] = ''
        self.payload['new_phone_number'] = '08981298131'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_case_if_email_not_found(self):
        """
        This case should be can accept the data in our table
        """

        self.payload['email'] = 'testing_notfound@gmail.com'
        self.payload['old_phone_number'] = ""

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('application_id', response.json()['data'])
        data_revive = ReviveMtlRequest.objects.filter(email__iexact=self.payload['email']).last()
        date_of_birth = format_date(data_revive.date_of_birth, 'yyyy-MM-dd', locale='id_ID')
        self.assertIsNotNone(data_revive)
        self.assertEqual(data_revive.email, self.payload['email'])
        self.assertEqual(data_revive.fullname, self.payload['fullname'])
        self.assertEqual(date_of_birth, self.payload['date_of_birth'])
        self.assertEqual(data_revive.old_phone_number, self.payload['old_phone_number'])
        self.assertEqual(data_revive.new_phone_number, self.payload['new_phone_number'])

        # keep all data even if email not found
        self.assertIsNone(data_revive.application_id)
        self.assertEqual(data_revive.bank_name, self.bank.bank_name)
        self.assertEqual(data_revive.bank_account_number, self.payload['bank_account_number'])
        self.assertEqual(data_revive.name_in_bank, self.payload['name_in_bank'])

    def test_send_form_with_param_application_xid(self):
        self.payload['julo_mtl_form'] = 12313123131
        self.payload['email'] = 'testing_notfound@gmail.com'
        self.payload['old_phone_number'] = ""

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('application_id', response.json()['data'])
        data_revive = ReviveMtlRequest.objects.filter(email__iexact=self.payload['email']).last()
        self.assertIsNotNone(data_revive)
        self.assertEqual(data_revive.application_id, self.application.id)
        self.assertEqual(data_revive.email, self.payload['email'])
        self.assertEqual(data_revive.fullname, self.payload['fullname'])


class TestEmergencyContactsForm(APITestCase):
    url = '/api/application-form/v1/application/emergency-contacts'

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()

        self.customer = CustomerFactory(user=self.user)
        self.onboarding = OnboardingFactory(id=9)
        self.application = ApplicationFactory(customer=self.customer, onboarding=self.onboarding)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_update_emergency_contacts(self):
        request = {
            'kin_relationship': 'saudara kandung',
            'kin_name': 'John Snow',
            'kin_mobile_phone': '08981298131',
            'close_kin_name': 'Daenerys',
            'close_kin_mobile_phone': '08981298122',
        }

        self.application.update_safely(application_status_id=100)

        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 200)

        application = Application.objects.filter(
            customer_id=self.customer.id, onboarding_id=self.onboarding.id
        ).last()

        self.assertEqual(request['kin_relationship'], application.kin_relationship)
        self.assertEqual(request['kin_name'], application.kin_name)
        self.assertEqual(request['kin_mobile_phone'], application.kin_mobile_phone)
        self.assertEqual(request['close_kin_name'], application.close_kin_name)
        self.assertEqual(request['close_kin_mobile_phone'], application.close_kin_mobile_phone)

    def test_move_emergency_contact_status_to_190(self):
        request = {
            "close_kin_name": "",
            "close_kin_mobile_phone": "",
            "kin_name": "hera",
            "kin_mobile_phone": "081812348478",
            "kin_relationship": "Saudara kandung",
            "spouse_name": "forgot",
            "spouse_mobile_phone": "0888923308478",
        }

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        StatusLookupFactory(status_code=188)
        WorkflowStatusPathFactory(
            status_previous=188,
            status_next=190,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        self.application.update_safely(
            application_status_id=188,
            workflow_id=self.workflow.id,
        )

        response = self.client.post(self.url, request, format='json')

        response_data = response.json()['data']
        self.assertEqual(response_data['is_kin_approved'], 0)
        self.assertEqual(response.status_code, 200)

        application = Application.objects.filter(
            customer_id=self.customer.id, onboarding_id=self.onboarding.id
        ).last()

        self.assertEqual(request['kin_relationship'], application.kin_relationship)
        self.assertEqual(request['kin_name'], application.kin_name)
        self.assertEqual(request['kin_mobile_phone'], application.kin_mobile_phone)
        self.assertEqual(request['spouse_name'], application.spouse_name)
        self.assertEqual(request['spouse_mobile_phone'], application.spouse_mobile_phone)
        self.assertEqual(190, application.application_status_id)

        application_history = ApplicationHistory.objects.filter(
            application_id=self.application.id,
        ).last()

        self.assertEqual(application_history.status_old, 188)
        self.assertEqual(application_history.status_new, 190)
        self.assertEqual(application_history.change_reason, 'customer_triggered')

    def test_failed_saving_emergency_contact(self):
        # emergency contact have 2 same phone number
        request = {
            'kin_relationship': 'saudara kandung',
            'kin_name': 'Gale',
            'kin_mobile_phone': '08981298131',
            'close_kin_name': 'Karlach',
            'close_kin_mobile_phone': '08981298131',
        }

        self.application.update_safely(application_status_id=105)

        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 400)

        # emergency contact same with application.mobile_phone 1
        request['kin_mobile_phone'] = self.application.mobile_phone_1
        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 400)

        # emergency contact same with application.mobile_phone 2
        request['kin_mobile_phone'] = '08981298144'
        self.application.update_safely(mobile_phone_2='08981298144', refresh=True)
        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 400)

        # name is under 3 characters
        request['kin_mobile_phone'] = '08981298139'
        request['close_kin_name'] = 'Ao'
        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 400)

        # kin_mobile_phone already sent
        request['close_kin_name'] = 'Wyll'
        request['kin_mobile_phone'] = '08111133332222'

        SmsHistoryFactory(
            application_id=self.application.id,
            to_mobile_phone=format_e164_indo_phone_number(request['kin_mobile_phone']),
            template_code='consent_code_request',
        )

        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 400)

        # case already approved
        self.application.update_safely(is_kin_approved=1, refresh=True)
        request['kin_mobile_phone'] = '08111133332222'
        self.assertEqual(response.status_code, 400)

    @patch(
        'juloserver.application_form.tasks.application_task.run_send_sms_for_emergency_contact_consent'
    )
    @patch(
        'juloserver.application_form.services.application_service.process_application_status_change'
    )
    def test_refill_emergency_contact(
        self,
        mock_process_application,
        mock_run_send_sms,
    ):
        request = {
            'kin_relationship': 'saudara kandung',
            'kin_name': 'Gale',
            'kin_mobile_phone': '08981298131',
        }

        self.application.update_safely(application_status_id=105)

        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 200)

        self.application.update_safely(is_kin_approved=2, refresh=True)
        self.assertEqual(self.application.kin_mobile_phone, request['kin_mobile_phone'])
        self.assertEqual(self.application.kin_name, request['kin_name'])

        SmsHistoryFactory(
            application_id=self.application.id,
            to_mobile_phone=format_e164_indo_phone_number(request['kin_mobile_phone']),
            template_code='consent_code_request',
        )

        request = {
            'kin_relationship': 'saudara kandung',
            'kin_name': 'Gale',
            'kin_mobile_phone': '08981298131',
        }

        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 400)

        request['kin_mobile_phone'] = '085931114416'
        request['kin_name'] = 'Astarion'
        response = self.client.post(self.url, request, format='json')
        self.assertEqual(response.status_code, 200)

        application_field_change = ApplicationFieldChange.objects.filter(
            application_id=self.application.id,
        )
        self.assertEqual(application_field_change.count(), 4)

        kin_name_change = application_field_change.filter(field_name='kin_name').last()
        self.assertEqual(kin_name_change.old_value, 'Gale')
        self.assertEqual(kin_name_change.new_value, 'Astarion')

        kin_phone_number_change = application_field_change.filter(
            field_name='kin_mobile_phone'
        ).last()
        self.assertEqual(kin_phone_number_change.old_value, '08981298131')
        self.assertEqual(kin_phone_number_change.new_value, '085931114416')

    @patch(
        'juloserver.application_form.tasks.application_task.run_send_sms_for_emergency_contact_consent'
    )
    @patch(
        'juloserver.application_form.services.application_service.process_application_status_change'
    )
    def test_refill_emergency_contact_after_rejected(
        self,
        mock_process_application,
        mock_run_send_sms,
    ):

        request = {
            'kin_relationship': 'saudara kandung',
            'kin_name': 'Minthara',
            'kin_mobile_phone': '08111199221',
        }

        # refil emergency contact after rejected
        self.application.update_safely(is_kin_approved=2, refresh=True)
        response = self.client.post(self.url, request, format='json')

        mock_run_send_sms.assert_called()
        self.assertEqual(response.status_code, 200)


class TestEmergencyContactConsentApi(TestCase):
    def setUp(self):
        self.endpoint = '/api/application-form/v1/emergency-contacts/consent'
        self.client = APIClient()
        self.user = None

        self.onboarding = OnboardingFactory(id=9)
        self.application = ApplicationFactory(onboarding=self.onboarding)
        self.application.save()

    @patch('django.utils.timezone.now')
    def test_retrieve_consent_form_info(self, mock_now):
        mock_now.return_value = timezone.make_aware(datetime(2024, 1, 15, 12, 0, 0))
        sms_cdate = timezone.make_aware(datetime(2024, 1, 15, 11, 0, 0))

        code = generate_consent_form_code(5)
        self.application.update_safely(
            is_kin_approved=0,
            kin_consent_code=code,
            refresh=True,
            kin_relationship='Famili lainnya',
        )

        self.sms_history = SmsHistoryFactory(
            application=self.application, template_code='consent_code_request', cdate=sms_cdate
        )
        self.endpoint = self.endpoint + '?data={}'.format(code)

        response = self.client.get(self.endpoint)
        response_data = response.json().get('data')
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response_data['fullname'], self.application.fullname)
        self.assertEqual(response_data['phone_number'], self.application.mobile_phone_1)
        self.assertEqual(response_data['kin_relationship'], self.application.kin_relationship)

    @patch(
        'juloserver.application_form.services.application_service.send_user_attributes_to_moengage_for_consent_received.delay'
    )
    @patch('django.utils.timezone.now')
    def test_record_consent_form(self, mock_now, mock_moengage):
        mock_now.return_value = timezone.make_aware(datetime(2024, 1, 15, 12, 0, 0))
        sms_cdate = timezone.make_aware(datetime(2024, 1, 15, 11, 0, 0))

        self.application.update_safely(
            is_kin_approved=0, refresh=True, kin_relationship='Famili lainnya'
        )

        self.sms_history = SmsHistoryFactory(
            application=self.application, template_code='consent_code_request', cdate=sms_cdate
        )

        data = {
            'consent_response': 1,
            'application_xid': self.application.application_xid,
        }

        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, 200)

        self.application.refresh_from_db()
        self.assertEqual(self.application.is_kin_approved, data['consent_response'])
        mock_moengage.assert_called()


class TestRetrieveOCRResult(TestCase):
    def setUp(self):
        self.base_url = '/api/application-form/v1/application/ocr_result'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.onboarding = OnboardingFactory(id=3)
        self.application = ApplicationFactory(onboarding=self.onboarding, customer=self.customer)
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()

        self.ktp_ocr_result = OcrKtpResultFactory(application_id=self.application.id)

    def test_retrieve_ocr_result_success(self):
        self.endpoint = self.base_url + '/' + str(self.application.id)
        self.ktp_ocr_result.update_safely(
            gender='laki-laki',
        )
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['gender'], 'Pria')

        self.ktp_ocr_result.update_safely(
            gender='laki laki',
        )
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['gender'], 'Pria')

        self.ktp_ocr_result.update_safely(
            gender='Pria',
        )
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['gender'], 'Pria')

        self.ktp_ocr_result.update_safely(
            gender='Wanita',
        )
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['gender'], 'Wanita')


    def test_retrieve_ocr_result_negative_case(self):
        self.endpoint = self.base_url + '/' + str(self.application.id)

        # OCR result not found
        self.ktp_ocr_result.delete()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Hasil OCR tidak ditemukan', response.json()['errors'])

        # Application not found
        self.application.delete()
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Aplikasi tidak ditemukan', response.json()['errors'])


class TestVideoCallAvailabilityView(TestCase):
    def setUp(self):
        self.endpoint = '/api/application-form/v1/video/availability'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
        )
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
            is_active=True,
            parameters={
                'weekdays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 20,
                        'minute': 0,
                    },
                },
                'holidays': {
                    'open': {
                        'hour': 8,
                        'minute': 0,
                    },
                    'close': {
                        'hour': 18,
                        'minute': 00,
                    },
                },
                "scheduler_messages": [],
            },
        )

    @patch('django.utils.timezone.now')
    def test_retrieve_availability_status(self, mock_now):
        # workday & available
        mock_now.return_value = timezone.make_aware(datetime(2024, 7, 1, 9, 0, 0))

        # change time and hours all same time
        new_parameters = self.setting.parameters
        new_parameters['holidays']['close']['hour'] = 20
        self.setting.parameters = new_parameters
        self.setting.save()

        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json_response['data']['is_available'])
        self.assertEqual(json_response['data']['title'], 'Jam Operasional (Waktu Indonesia Barat)')
        self.assertEqual(json_response['data']['message'], 'Senin-Minggu: 08.00-20.00 WIB')
        self.assertEqual(json_response['data']['button_message'], 'Jam operasional 08.00-20.00 WIB')

        # workday & not available
        mock_now.return_value = timezone.make_aware(datetime(2024, 7, 1, 6, 0, 0))

        # change time and hours to default
        new_parameters = self.setting.parameters
        new_parameters['holidays']['close']['hour'] = 18
        self.setting.parameters = new_parameters
        self.setting.save()

        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json_response['data']['is_available'])
        self.assertEqual(json_response['data']['title'], 'Jam Operasional (Waktu Indonesia Barat)')
        self.assertEqual(
            json_response['data']['message'],
            'Senin-Jumat: 08.00-20.00 WIB<br>Sabtu-Minggu: 08.00-18.00 WIB',
        )
        self.assertEqual(json_response['data']['button_message'], 'Jam operasional 08.00-20.00 WIB')

        # weekend & available
        mock_now.return_value = timezone.make_aware(datetime(2024, 7, 7, 17, 0, 0))

        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['is_available'])
        self.assertEqual(json_response['data']['title'], 'Jam Operasional (Waktu Indonesia Barat)')
        self.assertEqual(
            json_response['data']['message'],
            'Senin-Jumat: 08.00-20.00 WIB<br>Sabtu-Minggu: 08.00-18.00 WIB',
        )
        self.assertEqual(json_response['data']['button_message'], 'Jam operasional 08.00-18.00 WIB')

        # weekend & not available
        test_time = timezone.make_aware(datetime(2024, 7, 7, 19, 0, 0))
        mock_now.return_value = test_time

        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json_response['data']['is_available'])
        self.assertEqual(json_response['data']['title'], 'Jam Operasional (Waktu Indonesia Barat)')
        self.assertEqual(
            json_response['data']['message'],
            'Senin-Jumat: 08.00-20.00 WIB<br>Sabtu-Minggu: 08.00-18.00 WIB',
        )
        self.assertEqual(json_response['data']['button_message'], 'Jam operasional 08.00-18.00 WIB')

    @patch('django.utils.timezone.now')
    def test_scheduler_message(self, mock_now):

        # Case for In Office Hours
        # workday & available 2024-09-02 09:00
        mock_now.return_value = timezone.make_aware(datetime(2024, 9, 2, 9, 0, 0))

        new_parameters = self.setting.parameters
        new_parameters['scheduler_messages'].append(
            {
                "open": {"hour": 8, "minute": 0},
                "close": {"hour": 20, "minute": 0},
                "set_date": "2024-09-02",
            },
        )
        self.setting.parameters = new_parameters
        self.setting.save()

        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json_response['data']['is_available'])
        self.assertEqual(json_response['data']['title'], 'Jam Operasional (Waktu Indonesia Barat)')
        self.assertEqual(json_response['data']['message'], 'Senin-Minggu: 08.00-20.00 WIB')
        self.assertEqual(json_response['data']['button_message'], 'Jam operasional 08.00-20.00 WIB')

        # Case for Outside Office Hours
        mock_now.return_value = timezone.make_aware(datetime(2024, 9, 2, 7, 0, 0))

        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json_response['data']['is_available'])
        self.assertEqual(json_response['data']['title'], 'Jam Operasional (Waktu Indonesia Barat)')
        self.assertEqual(
            json_response['data']['message'],
            'Senin-Jumat: 08.00-20.00 WIB<br>'
            'Sabtu-Minggu: 08.00-18.00 WIB<br>'
            '02 September: 08.00-20.00 WIB',
        )
        self.assertEqual(json_response['data']['button_message'], 'Jam operasional 08.00-20.00 WIB')

    @patch('django.utils.timezone.now')
    def test_scheduler_with_day_off_case(self, mock_now):

        # Case for Outside Office Hours
        mock_now.return_value = timezone.make_aware(datetime(2024, 9, 2, 7, 0, 0))

        new_parameters = self.setting.parameters
        new_parameters['scheduler_messages'].append(
            {
                "open": {"hour": 9, "minute": 0},
                "close": {"hour": 21, "minute": 0},
                "set_date": "2024-09-02",
            },
        )
        new_parameters['scheduler_messages'].append(
            {
                "open": {"hour": 0, "minute": 0},
                "close": {"hour": 0, "minute": 0},
                "set_date": "2024-09-05",
            }
        )
        self.setting.parameters = new_parameters
        self.setting.save()

        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json_response['data']['is_available'])
        self.assertEqual(json_response['data']['title'], 'Jam Operasional (Waktu Indonesia Barat)')
        self.assertEqual(
            json_response['data']['message'],
            'Senin-Jumat: 08.00-20.00 WIB<br>'
            'Sabtu-Minggu: 08.00-18.00 WIB<br>'
            '02 September: 09.00-21.00 WIB<br>'
            '05 September: Tidak beroperasi',
        )
        self.assertEqual(json_response['data']['button_message'], 'Jam operasional 09.00-21.00 WIB')

        # Outside office hours but in same day dayoff
        mock_now.return_value = timezone.make_aware(datetime(2024, 9, 5, 7, 0, 0))
        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json_response['data']['is_available'])
        self.assertEqual(json_response['data']['title'], 'Jam Operasional (Waktu Indonesia Barat)')
        self.assertEqual(
            json_response['data']['message'],
            'Senin-Jumat: 08.00-20.00 WIB<br>'
            'Sabtu-Minggu: 08.00-18.00 WIB<br>'
            '02 September: 09.00-21.00 WIB<br>'
            '05 September: Tidak beroperasi',
        )
        self.assertEqual(
            json_response['data']['button_message'], 'Tersedia besok di jam 08.00-20.00 WIB'
        )

    @patch('django.utils.timezone.now')
    def test_scheduler_with_feature_setting_is_off(self, mock_now):

        # Case for Outside Office Hours
        mock_now.return_value = timezone.make_aware(datetime(2024, 9, 2, 7, 0, 0))

        self.setting.is_active = False
        self.setting.save()

        response = self.client.get(self.endpoint)
        json_response = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json_response['data']['is_available'])
        self.assertIsNone(json_response['data']['message'])
        self.assertIsNone(json_response['data']['title'])
        self.assertIsNone(json_response['data']['button_message'])

    def test_have_existing_record_phone_number(self):
        ApplicationPhoneRecordFactory(
            customer_id=self.customer.id,
            application_id=self.application.id,
            mobile_phone_number='08982932323232',
        )

        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['data']['is_need_submit_phone_number'])

    def test_empty_record_phone_number(self):
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['data']['is_need_submit_phone_number'])


class TestAgentAssistedApplicationUpdate(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()

        # Create or get the required group
        self.group_name = 'j1_agent_assisted_100'
        group, created = Group.objects.get_or_create(name=self.group_name)
        self.group = group

        # Create Application Path Tag
        ApplicationTagFactory(
            application_tag=AgentAssistedSubmissionConst.TAG_NAME,
            is_active=True,
        )

        ApplicationPathTagStatusFactory(
            application_tag=AgentAssistedSubmissionConst.TAG_NAME, status=1, definition="success"
        )

        # Create other test data
        self.customer = CustomerFactory()
        self.onboarding = OnboardingFactory(id=3)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer, onboarding=self.onboarding, workflow=self.workflow
        )
        self.application.application_status = StatusLookup.objects.get(status_code=100)
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.data = {
            "application_status": 100,
            "application_number": 1,
            "longitude": 1,
            "latitude": 1,
            "email": 'testing@julofinance.com',
            "fullname": 'JuloName',
            "dob": '1990-01-01',
            "marital_status": 'Lajang',
            "mother_maiden_name": 'Mama',
            "address_street_num": 'Nomor 12AB',
            "address_provinsi": 'Jawa Barat',
            "address_kabupaten": 'Bogor',
            "address_kecamatan": 'Parung Panjang',
            "address_kelurahan": 'Kabasiran',
            "address_kodepos": '',
            "kin_relationship": 'Orang tua',
            "close_kin_name": 'Bama',
            "close_kin_mobile_phone": '089677537749',
            "job_type": 'Pegawai negeri',
            "job_industry": 'Admin Finance/HR',
            "job_description": 'Admin',
            "payday": 30,
            "monthly_income": 15000000,
            "monthly_expenses": 10000000,
            "total_current_debt": 100000,
            "loan_purpose": 'Modal usaha',
            "bank_name": 'BANK CENTRAL ASIA, Tbk (BCA)',
            "bank_account_number": '43985',
            "company_phone_number": '0219898398',
            "birth_place": "Jakarta",
        }

        self.endpoint = (
            f'/api/application-form/v1/application/{self.application.id}/assisted-submission'
        )

        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_job_and_company_phone', return_value=True)
    def test_success_assisted_submission(
        self,
        mock_check_company_phone,
        mock_check_liveness,
        mock_check_selfie,
    ):
        # Add user to the group
        self.user.groups.add(self.group)
        self.user.save()

        # simulate address geolocation from registration
        # AddressGeolocationFactory(customer=self.customer)

        # Data for LongForm Shortened
        self.data['loan_purpose_desc'] = None
        self.data['home_status'] = None
        self.data['occupied_since'] = None
        self.data['dependent'] = 0

        response = self.client.patch(
            self.endpoint,
            data=self.data,
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.application_status_id, 105)
        self.assertTrue(self.application.is_agent_assisted_submission())

    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=False)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=False)
    @patch.object(ApplicationUpdateV3, 'check_job_and_company_phone', return_value=True)
    def test_fail_assisted_submission(
        self,
        mock_check_company_phone,
        mock_check_liveness,
        mock_check_selfie,
    ):

        # case Agent not in group
        self.data['loan_purpose_desc'] = None
        self.data['home_status'] = None
        self.data['occupied_since'] = None
        self.data['dependent'] = 0

        response = self.client.patch(
            self.endpoint,
            data=self.data,
            format='json',
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn(
            'Agent ini tidak diperbolehkan melakukan submission', response.json()['errors']
        )

        # Add user to the group
        self.user.groups.add(self.group)
        self.user.save()

        # Case no selfie or liveness data
        AddressGeolocationFactory(customer=self.customer)
        response = self.client.patch(
            self.endpoint,
            data=self.data,
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Customer belum melakukan cek liveness atau foto selfie", response.json()['errors']
        )

        # Success
        mock_check_liveness.return_value = True
        mock_check_selfie.return_value = True

        response = self.client.patch(
            self.endpoint,
            data=self.data,
            format='json',
        )
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.application_flow.handlers.JuloOneWorkflowAction')
    @patch.object(Application, 'is_agent_assisted_submission', return_value=True)
    @patch('juloserver.application_flow.tasks.handle_iti_ready.delay')
    def test_x105_handler_run(
        self, mock_handle_iti, mock_is_agent_assisted, MockJuloOneWorkflowAction
    ):
        # Mock the necessary action methods
        mock_action_instance = MockJuloOneWorkflowAction.return_value
        mock_action_instance.is_terms_agreed.return_value = False
        mock_action_instance.check_fraud_bank_account_number.return_value = False
        mock_action_instance.trigger_anaserver_status105 = MagicMock()

        handler = JuloOne105Handler(
            application=self.application,
            new_status_code=ApplicationStatusCodes.FORM_PARTIAL,
            change_reason='move',
            note='',
            old_status_code=100,
        )

        handler.post()
        mock_action_instance.trigger_anaserver_status105.assert_not_called()

        mock_action_instance.is_terms_agreed.return_value = True
        handler.post()
        mock_action_instance.trigger_anaserver_status105.assert_called_once()


class TestAgentAssistedApplicationTnC(TestCase):
    def setUp(self):
        self.application_tag = ApplicationTagFactory(
            application_tag=AgentAssistedSubmissionConst.TAG_NAME,
            is_active=True,
        )

        self.application_path_tag_status = ApplicationPathTagStatusFactory(
            application_tag=AgentAssistedSubmissionConst.TAG_NAME, status=1, definition="success"
        )

        self.customer = CustomerFactory()
        self.onboarding = OnboardingFactory(id=3)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            customer=self.customer, onboarding=self.onboarding, workflow=self.workflow
        )
        self.application.application_status = StatusLookup.objects.get(status_code=105)
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.save()

        self.app_xid = self.application.application_xid

        self.application_path_tag = ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=self.application_path_tag_status,
        )

        self.client = APIClient()
        self.user = None
        self.url = '/api/application-form/v1/sales-ops-assistance/tnc'

    @patch('django.utils.timezone.now')
    def test_salesops_token_mechanism(self, mock_now):
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        fixed_now = timezone.datetime(2024, 8, 16, 12, 0, 0, tzinfo=jakarta_tz)
        mock_now.return_value = fixed_now

        expire_time = fixed_now + timedelta(hours=AgentAssistedSubmissionConst.TOKEN_EXPIRE_HOURS)
        web_token = generate_web_token(expire_time, self.app_xid)

        self.web_token = AgentAssistedWebTokenFactory(
            application_id=self.application.id,
            session_token=web_token,
            expire_time=expire_time,
            is_active=True,
        )

        self.application.is_term_accepted = False
        self.application.is_verification_agreed = False
        self.application.save()

        # empty token case
        url = self.url + '?application_xid={}'.format(self.app_xid)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

        # token not found
        url = self.url + '?application_xid={}'.format(self.app_xid) + '&token=somerandomtoken'

        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.json()['data']['token'])

        # token already expired
        url = (
            self.url
            + '?application_xid={}'.format(self.app_xid)
            + '&token={}'.format(self.web_token.session_token)
        )
        mock_now.return_value = fixed_now + timedelta(hours=20)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.json()['data']['token'])

        # success case
        self.web_token.refresh_from_db()
        url = (
            self.url
            + '?application_xid={}'.format(self.app_xid)
            + '&token={}'.format(self.web_token.session_token)
        )

        mock_now.return_value = fixed_now
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    @patch('django.utils.timezone.now')
    def test_salesops_get_tnc(self, mock_now):
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        fixed_now = timezone.datetime(2024, 8, 16, 12, 0, 0, tzinfo=jakarta_tz)
        mock_now.return_value = fixed_now

        expire_time = fixed_now + timedelta(hours=AgentAssistedSubmissionConst.TOKEN_EXPIRE_HOURS)
        web_token = generate_web_token(expire_time, self.app_xid)

        self.web_token = AgentAssistedWebTokenFactory(
            application_id=self.application.id,
            session_token=web_token,
            expire_time=expire_time,
            is_active=True,
        )

        self.application.is_term_accepted = False
        self.application.is_verification_agreed = False
        self.application.save()

        # not agent assisted application
        self.application_path_tag.application_id = int(self.application.id) + 1
        self.application_path_tag.save()

        url = (
            self.url
            + '?application_xid={}'.format(self.app_xid)
            + '&token={}'.format(self.web_token.session_token)
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

        # not x105
        self.application_path_tag.application_id = self.application.id
        self.application_path_tag.save()

        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()

        url = (
            self.url
            + '?application_xid={}'.format(self.app_xid)
            + '&token={}'.format(self.web_token.session_token)
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

        # already agree to tnc
        self.application.is_term_accepted = True
        self.application.is_verification_agreed = True
        self.application.save()

        url = (
            self.url
            + '?application_xid={}'.format(self.app_xid)
            + '&token={}'.format(self.web_token.session_token)
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

        # success
        self.application.is_term_accepted = False
        self.application.is_verification_agreed = False
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()

        url = (
            self.url
            + '?application_xid={}'.format(self.app_xid)
            + '&token={}'.format(self.web_token.session_token)
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    @patch(
        'juloserver.application_form.services.product_picker_service.generate_address_location_for_application'
    )
    @patch(
        'juloserver.application_form.services.application_service.process_application_status_change'
    )
    @patch('django.utils.timezone.now')
    def test_salesops_agree_to_tnc(self, mock_now, mock_status_change, mock_generate_geolocation):
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        fixed_now = timezone.datetime(2024, 8, 16, 12, 0, 0, tzinfo=jakarta_tz)
        mock_now.return_value = fixed_now

        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105,
        )

        self.work_flow_status_path_j1 = WorkflowStatusPathFactory(
            status_previous=105,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        expire_time = fixed_now + timedelta(hours=AgentAssistedSubmissionConst.TOKEN_EXPIRE_HOURS)
        web_token = generate_web_token(expire_time, self.app_xid)

        self.web_token = AgentAssistedWebTokenFactory(
            application_id=self.application.id,
            session_token=web_token,
            expire_time=expire_time,
            is_active=True,
        )

        self.data = {'application_xid': None, 'token': web_token, 'latitude': 0.0, 'longitude': 0.0}

        # empty application_xid case
        response = self.client.post(
            self.url,
            data=self.data,
            format='json',
        )

        self.assertEqual(response.status_code, 400)

        # application is not agent_assisted_submission_case
        self.data['application_xid'] = self.application.application_xid
        self.application_path_tag.application_id = int(self.application.id) + 1
        self.application_path_tag.save()

        response = self.client.post(
            self.url,
            data=self.data,
            format='json',
        )

        # application already accept tnc
        self.data['latitude'] = 0.0
        self.data['longitude'] = 0.0

        self.application_path_tag.application_id = self.application.id
        self.application_path_tag.save()

        self.application.is_verification_agreed = True
        self.application.is_term_accepted = True
        self.application.save()

        response = self.client.post(
            self.url,
            data=self.data,
            format='json',
        )

        self.assertEqual(response.status_code, 400)

        # application is not x105
        self.application.is_verification_agreed = False
        self.application.is_term_accepted = False
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()

        response = self.client.post(
            self.url,
            data=self.data,
            format='json',
        )

        self.assertEqual(response.status_code, 400)

        # success case
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()

        self.data['is_tnc_approved'] = True
        self.data['is_data_validated'] = True

        response = self.client.post(
            self.url,
            data=self.data,
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        mock_status_change.assert_called_with(
            self.application.id,
            105,
            change_reason='Consented for Data Processing',
        )


class TestApplicationPhoneRecord(TestCase):
    def setUp(self):
        self.endpoint = '/api/application-form/v1/application/phone-number/submit'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(
            customer=self.customer,
        )
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.payload = {'application_id': self.application.id, 'phone_number': '083822825720'}

    def test_application_phone_record_is_success(self):

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 200)

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Kamu sudah pernah mengirimkan No. HP')

    def test_application_phone_record_is_success_phone_number_11digits(self):

        self.payload['phone_number'] = '08986167326'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 200)

    def test_application_phone_record_is_failed_application_id_empty(self):

        self.payload['application_id'] = 0
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Terjadi kesalahan ketika mengirimkan data')

    def test_application_phone_number_record_failed(self):
        self.payload['phone_number'] = ''

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0], 'Nomor HP yang perlu didaftarkan tidak boleh kosong'
        )

    def test_application_phone_number_record_failed_format_number(self):
        self.payload['phone_number'] = '628986167326'

        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Mohon gunakan format Nomor HP 08xxxxxxxxx')


class TestAgentAssignFlowWebLog(TestCase):
    def setUp(self):
        self.endpoint = '/api/user_action_logs/v1/agent-assign-web-logs'
        self.client = APIClient()
        self.application = ApplicationFactory()
        now = timezone.localtime(datetime.now())

        expire_time = now + timedelta(hours=AgentAssistedSubmissionConst.TOKEN_EXPIRE_HOURS)
        web_token = generate_web_token(expire_time, self.application.application_xid)

        self.token = AgentAssistedWebTokenFactory(
            application_id=self.application.id,
            session_token=web_token,
            expire_time=expire_time,
            is_active=True,
        )
        self.payload = dict(
            date=now,
            module='test',
            element='test',
            application_id=self.application.id,
            event='test',
            application_xid=self.application.application_xid,
            token=self.token.session_token,
        )

    def test_success(self):
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 201)

    def test_unauthorized(self):
        self.payload['token'] = 'fake'
        response = self.client.post(self.endpoint, self.payload, format='json')
        self.assertEqual(response.status_code, 403)


class TestConfirmCustomerNIK(TestCase):
    def setUp(self):
        self.base_url = '/api/application-form/v1/application/confirm-ktp'
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.onboarding = OnboardingFactory(id=3)
        self.application = ApplicationFactory(onboarding=self.onboarding, customer=self.customer)
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()

    def test_confirm_nik(self):
        self.endpoint = self.base_url + '/' + str(self.application.id)

        data = {'nik': '3576014403910003'}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, 200)

        # change NIK, should record to CustomerFieldChange
        data = {'nik': '3576014403910012'}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, 200)

        customer_change = CustomerFieldChange.objects.filter(customer=self.customer).last()
        self.assertEqual(customer_change.field_name, 'nik')
        self.assertEqual(customer_change.old_value, '3576014403910003')
        self.assertEqual(customer_change.new_value, '3576014403910012')

        # invalid length
        data = {'nik': '35760144039100122'}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, 400)

        # invalid NIK format
        data = {'nik': '9999999999999999'}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, 400)

        # empty nik
        data = None
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, 400)

        # customer_id doesn't match with the application table
        self.application.customer.id = 555
        self.application.save()
        data = {'nik': '35760144039100123'}
        response = self.client.post(self.endpoint, data=data)
        self.assertEqual(response.status_code, 400)


class TestGetMotherMaidenNameSetting(TestCase):
    def setUp(self):

        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow_j1,
            product_line=self.product_line_j1,
        )
        self.endpoint = '/api/application-form/v1/mother-maiden-name/setting/{}'
        self.app_version = '9.1.0'
        self.client.credentials(
            HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key,
            HTTP_X_APP_VERSION=self.app_version,
        )
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.MOTHER_NAME_VALIDATION,
            start_date=datetime.now() - timedelta(days=1),
            end_date=datetime.now() + timedelta(days=50),
            is_active=True,
            is_permanent=False,
            criteria={
                "app_version": ">=9.1.0",
                "app_id": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
                "improper_names": [
                    "MAMAH",
                ],
            },
        )

    def test_getting_improper_name(self):

        url = self.endpoint.format(self.application.id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()['data']['improper_names'])

    def test_getting_improper_name_is_empty(self):

        self.experiment_setting.update_safely(is_active=False)
        url = self.endpoint.format(self.application.id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['improper_names'], [])
