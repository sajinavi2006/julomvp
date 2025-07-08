from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from unittest.mock import ANY
import mock
import json
from django.test import Client, TestCase
from mock import patch
from rest_framework.test import APIClient, APITestCase
from requests.models import Response

import juloserver.apiv3.views
from juloserver.julo.constants import IdentifierKeyHeaderAPI
from juloserver.apiv2.constants import ErrorMessage
from juloserver.apiv3.views import ApplicationUpdateV3
from juloserver.julo.models import (
    Device,
    StatusLookup,
    Application,
    AddressGeolocation,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    DeviceFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ProductLineFactory,
    SuspiciousDomainFactory,
    MobileFeatureSettingFactory,
    OtpRequestFactory,
    ImageFactory,
    OnboardingFactory,
    FeatureSettingFactory,
)
from juloserver.julo.constants import ProductLineCodes, WorkflowConst
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.otp.constants import SessionTokenAction
from juloserver.julo.models import Image, ApplicationScrapeAction
from juloserver.liveness_detection.tests.factories import (
    ActiveLivenessDetectionFactory,
    ActiveLivenessVendorResultFactory,
    PassiveLivenessDetectionFactory,
    PassiveLivenessVendorResultFactory,
)
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
)
from juloserver.julo.tests.factories import (
    ExperimentSettingFactory,
    ApplicationHistoryFactory,
)
from juloserver.application_flow.factories import (
    ApplicationTagFactory,
    ApplicationPathTagStatusFactory,
)
from juloserver.julo.constants import ExperimentConst
from datetime import datetime, timedelta
from juloserver.application_form.constants import OfflineBoothConst
from juloserver.application_flow.models import (
    ApplicationPathTagStatus,
    ApplicationPathTag,
)


class TestTNCAndPrivacyNoticeAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()

    def test_success_get_tnc_and_privacynotice(self):
        response = self.client.get('/api/v4/tnc-and-privacynotice')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)


class TestApplicationUpdateV4(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status = StatusLookup.objects.get(status_code=100)
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.workflow = WorkflowFactory(worklow_name=WorkflowConst.JULO_ONE)
        self.application.save()
        self.device = DeviceFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.data = {
            "application_status": 100,
            "device": self.device.id,
            "application_number": 1,
            "longitude": 1,
            "latitude": 1,
            "email": 'testing@julofinance.com',
            "ktp": '6234560402199780',
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
        self.endpoint = '/api/v4/application/{}/'
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.ADDITIONAL_MESSAGE_SUBMIT_APP,
            parameters={
                'banner_url': 'https://',
            },
        )

    def hit_endpoint_to_update(self):
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        return response

    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=False)
    def test_missing_liveness(self, mock_check_liveness):
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.application.workflow = julo_one_workflow
        self.application.save()
        resp = self.client.patch(
            self.endpoint.format(self.application.id), data=self.data, format='json'
        )
        self.assertEqual(resp.status_code, 400)
        json = resp.json()
        self.assertFalse(json['success'])
        self.assertEqual(json['errors'][0], 'Cek kembali halaman selfie dan ambil ulang foto kamu')

    # @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    # @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    # def test_incorrect_company_phone(self, mock_check_liveness, mock_check_selfie_submission):
    #     resp = self.client.patch(
    #         self.endpoint.format(self.application.id),
    #         data={**self.data, "company_phone_number": "085290837483"},
    #         format='json',
    #     )
    #     self.assertEqual(resp.status_code, 400)
    #     self.assertEqual(
    #         resp.json()['detail'],
    #         'Jika pekerjaan Pegawai negeri, nomor telepon kantor tidak boleh GSM',
    #     )

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_special_character(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_process_application_status_change,
    ):
        resp = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data, "loan_purpose_desc": "ÓasdasdasdÓ"},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_claim_from_new_apk_short_form_without_application_to_old_apk_105(
        self, mock1, mock2, mock3
    ):
        claimed_customer = CustomerFactory(nik=None, email=None, phone='08999999999')
        claimed_customer.is_active = True
        claimed_customer.save()

        self.customer.nik = '3320000606900005'
        self.customer.email = 'thanos@avenger.com'
        self.customer.is_active = True
        self.customer.phone = None
        self.customer.save()

        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()

        resp = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data, 'mobile_phone_1': '08999999999'},
        )
        self.assertEqual(resp.status_code, 200)

        claimed_customer.refresh_from_db()
        self.customer.refresh_from_db()

        self.assertFalse(claimed_customer.is_active)
        self.assertTrue(self.customer.is_active)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_claim_from_new_apk_short_form_has_application_100_to_old_apk_105(
        self, mock1, mock2, mock3
    ):
        claimed_customer = CustomerFactory(nik=None, email=None, phone='08999999999')
        claimed_customer.is_active = True
        claimed_customer.save()
        app = ApplicationFactory(customer=claimed_customer)
        app.application_status = StatusLookupFactory(status_code=100)
        app.save()

        self.customer.nik = '3320000606900005'
        self.customer.email = 'thanos@avenger.com'
        self.customer.is_active = True
        self.customer.phone = None
        self.customer.save()

        resp = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data, 'mobile_phone_1': '08999999999'},
        )
        self.assertEqual(resp.status_code, 200)

        claimed_customer.refresh_from_db()
        self.customer.refresh_from_db()

        self.assertFalse(claimed_customer.is_active)
        self.assertTrue(self.customer.is_active)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    def test_claim_from_new_apk_short_form_105_to_old_apk_105(self, mock1, mock2, mock3):
        claimed_customer = CustomerFactory(nik=None, email=None, phone='08999999999')
        claimed_customer.is_active = True
        claimed_customer.save()
        app = ApplicationFactory(customer=claimed_customer)
        app.application_status = StatusLookupFactory(status_code=105)
        app.save()

        self.customer.nik = '3320000606900005'
        self.customer.email = 'thanos@avenger.com'
        self.customer.is_active = True
        self.customer.phone = None
        self.customer.save()

        resp = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data, 'mobile_phone_1': '08999999999'},
        )
        self.assertEqual(resp.status_code, 200)

        claimed_customer.refresh_from_db()
        self.customer.refresh_from_db()

        self.assertTrue(claimed_customer.is_active)
        self.assertTrue(self.customer.is_active)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        To check submission data with onboarding_id correct
        Test with case make sure onboarding_id not updated if not None.
        """
        longform_id = 1
        self.application.onboarding_id = longform_id
        self.application.save()

        self.data['loan_purpose_desc'] = "Untuk program investasi."

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], longform_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_shortened(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        To check submission data with onboarding_id correct
        Test with case make sure onboarding_id verify with correct after submission.
        """

        longform_shortened_id = 3
        self.application.onboarding_id = longform_shortened_id
        self.application.save()

        # Data with LongForm Shortened
        self.data['loan_purpose_desc'] = None
        self.data['home_status'] = None
        self.data['occupied_since'] = None
        self.data['dependent'] = 0

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], longform_shortened_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_shortened_is_none(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case with onboarding_id is None and submit the data.
        """

        # Set 3 because, this is hit to endpoint Longform with empty data loan_purpose_desc, etc
        onboarding_id = 3
        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = None
        self.data['home_status'] = None
        self.data['occupied_since'] = None
        self.data['dependent'] = None

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '7.0.0'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)
        self.application.refresh_from_db()
        assert self.application.app_version == '7.0.0'

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_is_none(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case with onboarding_id is None and submit the data.
        """
        # Set 1 because, this is hit to endpoint Longform without data loan_purpose_desc, etc
        onboarding_id = 1
        self.application.onboarding_id = None
        self.application.save()

        # Data form loan_purpose_desc available for LongForm.
        self.data['loan_purpose_desc'] = "Untuk program investasi."

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_birth_place_valid(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case with birth_place is valid
        """
        self.data['birth_place'] = "Bandung"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_birth_place_with_special_character(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case special character with birth_place is not valid
        """
        self.data['birth_place'] = "Bandung, Jawa Barat"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Tempat lahir tidak valid')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_birth_place_with_numeric(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case numeric with birth_place is not valid
        """
        self.data['birth_place'] = "Bandung 123"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Tempat lahir tidak valid')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_birth_place_with_empty_data(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case empty data / empty string with birth_place is not valid
        """

        # birthplace with empty string
        self.data['birth_place'] = ""
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Tempat lahir Harus Diisi')

        # birthplace is None
        self.data['birth_place'] = None
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Tempat lahir Harus Diisi')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_dependent_lf(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case with onboarding_id is 1 and submit the data.
        """

        # Set 1 because dependent is 1
        onboarding_id = 1
        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = None
        self.data['home_status'] = None
        self.data['occupied_since'] = None
        self.data['dependent'] = 1

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_dependent_lfs(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case with onboarding_id is 3 and submit the data.
        """

        # Set 3 because dependent is 0
        onboarding_id = 3
        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = ""
        self.data['home_status'] = ""
        self.data['occupied_since'] = None
        self.data['dependent'] = 0

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_dependent_string_lfs(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case with onboarding_id is 3 and submit the data.
        """

        # Set 3 because dependent is 0
        onboarding_id = 3
        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = ""
        self.data['home_status'] = ""
        self.data['occupied_since'] = None
        self.data['dependent'] = "0"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_dependent_is_zero_int_lfs(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform data criteria 0 -> integer
        """

        onboarding_id = 1
        last_education = "S1"

        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = "Keterangan untuk pinjaman"
        self.data['home_status'] = "Kontrak"
        self.data['last_education'] = last_education
        self.data['occupied_since'] = "1992-12-23"
        self.data['dependent'] = 0

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)
        self.assertEqual(response.json()['last_education'], last_education)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_dependent_is_zero_str_lfs(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform data criteria dependent 0 -> string
        """

        onboarding_id = 1
        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = "Keterangan untuk pinjaman"
        self.data['home_status'] = "Kontrak"
        self.data['last_education'] = "S1"
        self.data['occupied_since'] = "1992-12-23"
        self.data['dependent'] = "0"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_dependent_not_zero_lfs(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform data criteria dependent 2 -> string
        """

        onboarding_id = 1
        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = "Keterangan untuk pinjaman"
        self.data['home_status'] = "Kontrak"
        self.data['last_education'] = "S1"
        self.data['occupied_since'] = "1992-12-23"
        self.data['dependent'] = "2"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_dependent_is_none_lfs(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform data criteria dependent None
        """

        onboarding_id = 1
        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = "Keterangan untuk pinjaman"
        self.data['home_status'] = "Kontrak"
        self.data['last_education'] = "S1"
        self.data['occupied_since'] = "1992-12-23"
        self.data['dependent'] = None

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_nik_is_none(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case if nik is empty string when submission data
        """

        self.application.onboarding_id = None
        self.application.save()
        self.data['ktp'] = None

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], "NIK tidak boleh kosong")

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_nik_is_empty_string(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform data criteria dependent None
        """

        self.application.onboarding_id = None
        self.application.save()
        self.data['ktp'] = ""

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], "NIK tidak boleh kosong")

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_nik_is_not_16_digits(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case if NIK when submission is not 16 digits
        """

        self.application.onboarding_id = None
        self.application.save()

        # is 15 digits
        self.data['ktp'] = "123450402199723"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], "KTP has to be 16 numeric digits")

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_nik_is_not_valid(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case if NIK when submission is not 16 digits
        """

        self.application.onboarding_id = None
        self.application.save()

        # is not valid
        self.data['ktp'] = "1234560000099723"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], "NIK tidak valid")

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_nik_start_with_0(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case if NIK when submission is not 16 digits
        """

        self.application.onboarding_id = None
        self.application.save()

        # is not valid
        self.data['ktp'] = "0123456000009972"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], "NIK tidak valid")

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_lf_for_register_by_phone_nik_email(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform with onboarding_id 4
        onboarding_id 4 -> register by NIK/Email/Phone with Longform as Form
        """

        # First onboarding_id when registration
        onboarding_id = 4
        self.application.onboarding_id = onboarding_id
        self.application.save()

        # data for LF -> LongForm
        self.data['loan_purpose_desc'] = "Keterangan untuk pinjaman"
        self.data['home_status'] = "Kontrak"
        self.data['last_education'] = "S1"
        self.data['occupied_since'] = "1992-12-23"
        self.data['dependent'] = "0"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        # onboarding_id make sure without updated
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_lfs_for_register_by_phone_nik_email(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform with onboarding_id 5
        onboarding_id 5 -> register by NIK/Email/Phone with Longform Shortened as Form
        """

        # First onboarding_id when registration
        onboarding_id = 5
        self.application.onboarding_id = onboarding_id
        self.application.save()

        # data for LFS -> LongForm Shortened
        self.data['loan_purpose_desc'] = ""
        self.data['home_status'] = ""
        self.data['occupied_since'] = None
        self.data['dependent'] = "0"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        # onboarding_id make sure without updated
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_without_onboarding_response(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        From response success
        Remove key onboarding and keep for key "onboarding_id"
        """

        # First onboarding_id when registration
        onboarding_id = 5
        self.application.onboarding_id = onboarding_id
        self.application.save()

        # data for LFS -> LongForm Shortened
        self.data['loan_purpose_desc'] = ""
        self.data['home_status'] = ""
        self.data['occupied_since'] = None
        self.data['dependent'] = "0"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        # make sure onboarding is status code 200[OK]
        self.assertEqual(response.status_code, 200)

        # Make sure for onboarding key is removed.
        self.assertNotIn('onboarding', response.json())

        # Make sure for onboarding_id is keep exists
        self.assertIn('onboarding_id', response.json())

        # Make sure for onboarding_id is keep exists and same value
        # with onboarding_id when register
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_monthly_housing_cost_negative(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_process_application_status_change,
    ):
        """
        Case if monthly_housing_cost is -1
        """

        resp = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data, "monthly_housing_cost": -1},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        json = resp.json()
        self.assertEqual(json['monthly_housing_cost'], 0)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_monthly_housing_cost_negative_string(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_process_application_status_change,
    ):
        """
        Case if monthly_housing_cost is string and negative
        """

        resp = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data, "monthly_housing_cost": "-1"},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        json = resp.json()
        self.assertEqual(json['monthly_housing_cost'], 0)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_lfs_and_data_must_none(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform with onboarding_id 3
        If LongForm Shortened:
        loan_purpose_desc should be None
        home_status should be None
        occupied_since should be None
        dependent should be None
        """

        # First onboarding_id when registration
        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()

        # data for LFS -> LongForm Shortened
        self.data['loan_purpose_desc'] = ""
        self.data['home_status'] = ""
        self.data['occupied_since'] = None
        self.data['dependent'] = "0"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)
        self.assertIsNone(response.json()['loan_purpose_desc'])
        self.assertIsNone(response.json()['home_status'])
        self.assertIsNone(response.json()['occupied_since'])
        self.assertIsNone(response.json()['dependent'])

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_lfs_and_data_must_not_none(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case for longform with onboarding_id 1
        If LongForm:
        loan_purpose_desc should be not None
        home_status should be not None
        occupied_since should be not None
        dependent should be not None
        """

        # First onboarding_id when registration
        onboarding_id = 1
        self.application.onboarding_id = onboarding_id
        self.application.save()

        # data for LongForm
        self.data['loan_purpose_desc'] = "Keterangan untuk pinjaman"
        self.data['home_status'] = "Kontrak"
        self.data['last_education'] = "S1"
        self.data['occupied_since'] = "1992-12-23"
        self.data['dependent'] = "0"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)
        self.assertIsNotNone(response.json()['loan_purpose_desc'])
        self.assertIsNotNone(response.json()['home_status'])
        self.assertIsNotNone(response.json()['occupied_since'])
        self.assertIsNotNone(response.json()['dependent'])

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    @patch('juloserver.apiv3.views.handle_post_user_submit_application.delay')
    def test_register_lfs_trigger_post_application_submit(
        self,
        mock_handle_post_user_submit_application,
        *args,
    ):
        """
        Case the post application submit should be triggered
        """
        post_data = {
            **self.data,
            'seon_sdk_fingerprint': 'test-seon-fingerprint',
        }
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data=post_data,
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        mock_handle_post_user_submit_application.assert_called_once_with(
            customer_id=self.application.customer_id,
            application_id=self.application.id,
            ip_address='127.0.0.1',
            request_data=mock.ANY,
        )

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    @patch('juloserver.apiv3.views.handle_post_user_submit_application.delay')
    def test_register_lfs_trigger_post_application_submit_with_headers(
        self,
        mock_handle_post_user_submit_application,
        *args,
    ):
        """
        Case the post application submit should be triggered
        """

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            HTTP_X_FORWARDED_FOR='192.168.1.1',
        )
        self.assertEqual(response.status_code, 200)

        mock_handle_post_user_submit_application.assert_called_once_with(
            customer_id=self.application.customer_id,
            application_id=self.application.id,
            ip_address='192.168.1.1',
            request_data=mock.ANY,
        )

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    @patch('juloserver.apiv3.views.handle_post_user_submit_application.delay')
    def test_register_lfs_trigger_post_application_submit_exception(
        self,
        mock_handle_post_user_submit_application,
        *args,
    ):
        """
        Case the post application submit should be triggered
        """
        mock_handle_post_user_submit_application.side_effect = Exception('test')
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            HTTP_X_FORWARDED_FOR='127.0.0.1',
        )
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_response_application_with_same_onboarding_j360(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        To make sure onboarding_id is keep without update condition form
        """

        # First onboarding_id when registration
        # Regist with onboarding ID J360
        onboarding_id = 8
        self.application.onboarding_id = onboarding_id
        self.application.save()

        # Data for LFS -> LongForm Shortened
        self.data['loan_purpose_desc'] = ""
        self.data['home_status'] = ""
        self.data['occupied_since'] = None
        self.data['dependent'] = "0"

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        # make sure onboarding is status code 200[OK]
        self.assertEqual(response.status_code, 200)

        # Make sure for onboarding_id is keep exists
        self.assertIn('onboarding_id', response.json())

        # Make sure for onboarding_id is keep exists and same value
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_case_full_name_validation_when_submit(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        To make sure data submit with the correct data.
        """

        # First onboarding_id when registration
        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()

        # Data fullname with special characters
        self.data['fullname'] = "Mayjend. Tito Suparto, S.Pd."
        self.data['spouse_name'] = "Sumarni, S.Pd."
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Data fullname with special characters
        self.data['fullname'] = "Mayjend Tito Suparto"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Data fullname with special characters
        self.data['fullname'] = "Mayjend Tito - Suparto"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Data fullname with special characters
        self.data['fullname'] = "Mayjend Tito-Suparto"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Case with invalid name
        self.data['fullname'] = "ay'i"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Case with invalid name
        self.data['fullname'] = "a'i"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # Data fullname with special characters
        self.data['fullname'] = "Mayj3nd T1to Suparto"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

        # Case with invalid name
        self.data['fullname'] = "Mayjend. Tito Suparto, S.Pd. !-#@z%^"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

        # Case with invalid name
        self.data['fullname'] = ",-."
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

        # Case with invalid name
        self.data['fullname'] = "ai"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_case_mother_maiden_name_validation_when_submit(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        # First onboarding_id when registration
        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()

        self.data['fullname'] = "Mayjend. Tito Suparto, S.Pd"
        self.data['spouse_name'] = "Tina Suparto, S.Pd"
        self.data['mother_maiden_name'] = "Tini Suparto, S.Pd"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 200)

        # refresh the table
        self.application.refresh_from_db()
        self.customer.refresh_from_db()

        # make sure data should be updated
        self.assertEqual(self.application.fullname, self.data['fullname'])
        self.assertEqual(self.application.spouse_name, self.data['spouse_name'])
        self.assertEqual(self.customer.mother_maiden_name, self.data['mother_maiden_name'])

        # try negative case
        self.data['fullname'] = "Mayjend. Tito Suparto, S.Pd"
        self.data['spouse_name'] = "Tina Suparto, S.Pd"
        self.data['mother_maiden_name'] = "Tini Suparto, S.Pd. !-#@z%^"
        response = self.hit_endpoint_to_update()
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_response_application_with_case_application_upgrade(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        To make sure condition if user do upgrade from JTurbo to J1
        And this case user will submit some fields.
        """

        # Record with onboarding ID JTurbo
        onboarding_id = 7
        self.application.onboarding_id = onboarding_id
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )
        self.application.application_status_id = 191
        self.application.save()

        # create application J1
        j1_application = ApplicationFactory(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        j1_application.application_status_id = 100
        j1_application.onboarding_id = 3
        j1_application.dob = '1997-02-02'
        j1_application.gender = 'Pria'
        j1_application.save()

        # payload when upgrade form
        data_for_upgrade = {
            'birth_place': 'Bandung',
            'mother_maiden_name': 'Ibu',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '0219091029',
            'monthly_expenses': 25000000,
            'total_current_debt': 1000000,
            'loan_purpose': 'Biaya Kesehatan',
            'is_upgrade': True,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )

        # make sure onboarding is status code 200[OK]
        self.assertEqual(response.status_code, 200)
        response = response.json()

        # Make sure for onboarding_id is keep exists
        self.assertIn('onboarding_id', response)
        self.assertEqual(response['birth_place'], 'Bandung')
        self.assertEqual(response['mother_maiden_name'], 'Ibu')
        self.assertEqual(response['mobile_phone_2'], '083837287383')
        self.assertEqual(response['company_phone_number'], '0219091029')
        self.assertEqual(response['monthly_expenses'], 25000000)
        self.assertEqual(response['total_current_debt'], 1000000)
        self.assertEqual(response['loan_purpose'], 'Biaya Kesehatan')
        self.assertEqual(response['onboarding_id'], 3)
        self.assertEqual(response['dob'], '1997-02-02')
        self.assertEqual(response['gender'], 'Pria')
        self.assertNotIn('is_upgrade', response)

        data_for_upgrade_update = {
            'fullname': 'Changed',
            'gender': 'Wanita',
            'email': 'changed@mail.com',
            'mobile_phone_1': '085969696969',
            'monthly_expenses': 25000000,
            'total_current_debt': 1000000,
            'loan_purpose': 'Biaya Kesehatan',
            'is_upgrade': True,
            'onboarding_id': '1',
            'ktp': '3514142005880001',
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade_update},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        response = response.json()

        self.assertIn('onboarding_id', response)
        self.assertNotEqual(response['fullname'], 'Changed')
        self.assertNotEqual(response['ktp'], '3514142005880001')
        self.assertNotEqual(response['mobile_phone_1'], '085969696969')
        self.assertEqual(response['monthly_expenses'], 25000000)
        self.assertEqual(response['total_current_debt'], 1000000)
        self.assertEqual(response['loan_purpose'], 'Biaya Kesehatan')
        self.assertEqual(response['onboarding_id'], 3)
        self.assertNotEqual(response['email'], data_for_upgrade_update['email'])
        self.assertNotEqual(response['gender'], 'Wanita')
        self.assertIsNone(response['name_in_bank'])
        self.assertNotIn('is_upgrade', response)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_response_application_with_invalid_case_application_upgrade(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """ """

        # Record with onboarding ID JTurbo
        onboarding_id = 7
        self.application.onboarding_id = onboarding_id
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )
        self.application.application_status_id = 191
        self.application.save()

        # create application J1
        j1_application = ApplicationFactory(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        j1_application.application_status_id = 100
        j1_application.onboarding_id = 3
        j1_application.dob = '1997-02-02'
        j1_application.gender = 'Pria'
        j1_application.occupied_since = None
        j1_application.home_status = None
        j1_application.dependent = 0
        j1_application.loan_purposes_desc = None
        j1_application.save()

        # payload when upgrade form
        data_for_upgrade = {
            'birth_place': 'Bandung',
            'mother_maiden_name': 'Ibu',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '0219091029',
            'monthly_expenses': 25000000,
            'total_current_debt': 1000000,
            'loan_purpose': 'Biaya Kesehatan',
            'is_upgrade': None,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Bad request')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_response_application_with_missing_body_request_upgrade(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """ """

        # Record with onboarding ID JTurbo
        onboarding_id = 7
        self.application.onboarding_id = onboarding_id
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )
        self.application.application_status_id = 191
        self.application.save()

        # create application J1
        j1_application = ApplicationFactory(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            customer=self.customer,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        j1_application.application_status_id = 100
        j1_application.onboarding_id = 3
        j1_application.dob = '1997-02-02'
        j1_application.gender = 'Pria'
        j1_application.occupied_since = None
        j1_application.home_status = None
        j1_application.dependent = 0
        j1_application.loan_purposes_desc = None
        j1_application.save()

        # payload when upgrade form
        data_for_upgrade = {
            'birth_place': 'Bandung',
            'mother_maiden_name': '',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '0219091029',
            'monthly_expenses': 25000000,
            'total_current_debt': 1000000,
            'loan_purpose': 'Biaya Kesehatan',
            'is_upgrade': True,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Invalid request')

        # payload when upgrade form
        data_for_upgrade = {
            'birth_place': 'Bandung',
            'mother_maiden_name': 'Ibu Kandung',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '',
            'monthly_expenses': 25000000,
            'total_current_debt': 1000000,
            'loan_purpose': 'Biaya Kesehatan',
            'is_upgrade': True,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Invalid request')

        # payload when upgrade form
        data_for_upgrade = {
            'birth_place': 'Bandung',
            'mother_maiden_name': 'Ibu Kandung',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '0219091029',
            'monthly_expenses': 0,
            'total_current_debt': 0,
            'loan_purpose': 'Biaya Kesehatan',
            'is_upgrade': True,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors'][0], 'Invalid request')

        # payload when upgrade form
        j1_application.update_safely(mobile_phone_1='083837287383')
        data_for_upgrade = {
            'birth_place': 'Bandung',
            'mother_maiden_name': 'Ibu Kandung',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '0219091029',
            'monthly_expenses': 25000000,
            'total_current_debt': 25000000,
            'loan_purpose': 'Biaya Kesehatan',
            'is_upgrade': True,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0], 'Mohon maaf, nomor HP yang dimasukkan sudah digunakan'
        )

        j1_application.update_safely(mobile_phone_1='083837287381')
        data_for_upgrade = {
            'birth_place': 'Bandung',
            'mother_maiden_name': 'Ibu Kandung',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '0219091029',
            'monthly_expenses': 25000000,
            'total_current_debt': 0,
            'loan_purpose': 'Biaya Kesehatan',
            'is_upgrade': True,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total_current_debt'], 0)

        j1_application.refresh_from_db()
        self.assertEqual(j1_application.total_current_debt, 0)

        # case for check
        j1_application.update_safely(mobile_phone_1='083837287381')
        data_for_upgrade = {
            'total_current_debt': 0,
            'birth_place': 'Bandung',
            'mother_maiden_name': 'Ibu Kandung',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '0219091029',
            'monthly_expenses': 25000000,
            'loan_purpose': '',
            'is_upgrade': True,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

        # case for check
        j1_application.update_safely(mobile_phone_1='083837287381')
        data_for_upgrade = {
            'birth_place': 'Bandung',
            'mother_maiden_name': 'Ibu Kandung',
            'mobile_phone_2': '083837287383',
            'company_phone_number': '0219091029',
            'monthly_expenses': 25000000,
            'loan_purpose': '',
            'is_upgrade': True,
            'total_current_debt': 0,
        }

        response = self.client.patch(
            self.endpoint.format(j1_application.id),
            data={**data_for_upgrade},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_shortened_when_add_is_upgrade(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        Case with onboarding_id is None and submit the data.
        """

        # Set 3 because, this is hit to endpoint Longform with empty data loan_purpose_desc, etc
        onboarding_id = 3
        self.application.onboarding_id = None
        self.application.save()

        self.data['loan_purpose_desc'] = None
        self.data['home_status'] = None
        self.data['occupied_since'] = None
        self.data['dependent'] = 0
        self.data['is_upgrade'] = None

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '7.0.0'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

        # if case is upgrade is False
        self.data['is_upgrade'] = False

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '7.0.0'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], onboarding_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch(
        'juloserver.application_flow.tasks.move_application_to_x133_for_suspicious_email.apply_async'
    )
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_suspicious_email_domain_J1_with_suspicious_domain(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_suspicious_domain,
        mock_status_change,
    ):
        SuspiciousDomainFactory(email_domain="@test.com")
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        WorkflowStatusPathFactory(
            status_previous=100, status_next=105, workflow=self.workflow_j1, is_active=True
        )
        WorkflowStatusPathFactory(
            status_previous=105, status_next=133, workflow=self.workflow_j1, is_active=True
        )
        longform_id = 1
        self.application.onboarding_id = longform_id
        self.application.email = 'abcd@test.com'
        self.application.product_line_id = ProductLineCodes.J1
        self.application.workflow = self.workflow_j1
        self.application.save()
        self.data['loan_purpose_desc'] = "Untuk program investasi."
        self.data['email'] = 'test@test.com'
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.application.refresh_from_db()
        self.assertEqual(mock_status_change.call_count, 2)
        mock_suspicious_domain.assert_called_once()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], longform_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch(
        'juloserver.application_flow.tasks.move_application_to_x133_for_suspicious_email.apply_async'
    )
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_suspicious_email_domain_J1_with_no_suspicious_domain(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_suspicious_domain,
        mock_status_change,
    ):
        SuspiciousDomainFactory(email_domain="@test.com")
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        WorkflowStatusPathFactory(
            status_previous=100, status_next=105, workflow=self.workflow_j1, is_active=True
        )
        WorkflowStatusPathFactory(
            status_previous=105, status_next=133, workflow=self.workflow_j1, is_active=True
        )
        longform_id = 1
        self.application.onboarding_id = longform_id
        self.application.email = 'abcd@gmail.com'
        self.application.product_line_id = ProductLineCodes.J1
        self.application.workflow = self.workflow_j1
        self.application.save()
        self.data['loan_purpose_desc'] = "Untuk program investasi."
        self.data['email'] = 'abcd@gmail.com'
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.application.refresh_from_db()
        self.assertEqual(mock_status_change.call_count, 2)
        mock_suspicious_domain.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], longform_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch(
        'juloserver.application_flow.tasks.move_application_to_x133_for_suspicious_email.apply_async'
    )
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_suspicious_email_domain_non_J1_with_suspicious_domain(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_suspicious_domain,
        mock_status_change,
    ):
        SuspiciousDomainFactory(email_domain="@test.com")
        self.workflow_j1 = WorkflowFactory(name=WorkflowConst.GRAB)
        WorkflowStatusPathFactory(
            status_previous=100, status_next=105, workflow=self.workflow_j1, is_active=True
        )
        WorkflowStatusPathFactory(
            status_previous=105, status_next=133, workflow=self.workflow_j1, is_active=True
        )
        longform_id = 1
        self.application.onboarding_id = longform_id
        self.application.email = 'abcd@test.com'
        self.application.product_line_id = ProductLineCodes.GRAB
        self.application.workflow = self.workflow_j1
        self.application.save()
        self.data['loan_purpose_desc'] = "Untuk program investasi."
        self.data['email'] = 'abcd@test.com'
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.application.refresh_from_db()
        self.assertEqual(mock_status_change.call_count, 2)
        mock_suspicious_domain.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], longform_id)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_submit_application_with_data_contains_code(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        To prevent when submit user can fill the fields with XSS Payload
        """

        # list payloads
        list_of_test_payload = (
            '<script src="https://julo.co.id/"></script>',
            '"-prompt(8)-;"',
            "'-prompt(8)-;'",
            '";a=prompt,a()//',
            "'-eval(\"window'pro'%2B'mpt'\");-'",
            '"><script src="https://js.rip/r0"</script>>',
            '"-eval("window\'pro\'%2B\'mpt\'");-"',
            '{{constructor.constructor(alert1)()}}',
            '"onclick=prompt(8)>"@x.y',
            '"onclick=prompt(8)><svg/onload=prompt(8)>"@x.y',
            '¼script¾alert(¢XSS¢)¼/script¾',
            '%253Cscript%253Ealert(\'XSS\')%253C%252Fscript%253E',
            '‘; alert(1);',
        )

        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()

        for payload in list_of_test_payload:
            self.data['name_in_bank'] = payload

            # hit endpoint submission
            response = self.client.patch(
                self.endpoint.format(self.application.id),
                data={**self.data},
                format='json',
                **{'HTTP_X_APP_VERSION': '7.0.0'},
            )
            self.assertEqual(response.status_code, 400)

            # case for mother maiden name
            self.data['mother_maiden_name'] = payload

            # hit endpoint submission
            response = self.client.patch(
                self.endpoint.format(self.application.id),
                data={**self.data},
                format='json',
                **{'HTTP_X_APP_VERSION': '7.0.0'},
            )
            self.assertEqual(response.status_code, 400)

        # for success 200
        self.data['mother_maiden_name'] = 'Ibunda'
        self.data['name_in_bank'] = self.data['fullname']
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '7.0.0'},
        )
        self.customer.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.customer.mother_maiden_name, 'Ibunda')

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_otp_validation_view(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        """
        To prevent phone number modification on application update
        """

        self.otp_phone_number = '081234567890'
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
            phone_number=self.otp_phone_number,
            is_used=True,
            action_type=SessionTokenAction.VERIFY_PHONE_NUMBER,
        )

        # Submitted phone number different with OTP phone number
        self.submitted_phone_number = "08999999999"
        resp = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data, 'mobile_phone_1': self.submitted_phone_number},
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn(ErrorMessage.PHONE_NUMBER_MISMATCH, resp.json()['errors'])

        # Submitted phone number same with OTP phone number
        self.submitted_phone_number = self.otp_phone_number
        resp = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data, 'mobile_phone_1': self.submitted_phone_number},
        )

        self.assertEqual(resp.status_code, 200)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_close_kin_mobile_phone(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        number = '022198939822'
        self.data['close_kin_mobile_phone'] = number
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '8.11.0'},
        )
        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['close_kin_mobile_phone'], number)
        self.assertEqual(self.application.close_kin_mobile_phone, number)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_submit_application_with_data_contains_some_symbol(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()

        job_description = 'R&D / Ilmuwan / Peneliti'
        address_kelurahan = 'Berebas Pantai (Berbas Pantai)'
        company_name = 'PT Julo (HQ)'
        address_provinsi = 'Nanggroe Aceh Darussalam (NAD)'
        bank_name = 'Bank Jago (Jago)'

        self.data['job_description'] = job_description
        self.data['address_kelurahan'] = address_kelurahan
        self.data['company_name'] = company_name
        self.data['address_provinsi'] = address_provinsi
        self.data['bank_name'] = bank_name

        # hit endpoint submission
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '8.11.1'},
        )

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.application.job_description, job_description)
        self.assertEqual(self.application.address_kelurahan, address_kelurahan)
        self.assertEqual(self.application.company_name, company_name)
        self.assertEqual(self.application.address_provinsi, address_provinsi)
        self.assertEqual(self.application.bank_name, bank_name)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_empty_close_kin_mobile_phone(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        self.data['close_kin_mobile_phone'] = None
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '8.11.0'},
        )
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.apiv2.views.process_application_status_change')
    def test_case_submit_form_with_upgrade_flow_process_image(self, mock_status_change):
        """
        To make sure user can submit with case upgrade form
        """

        # application JTurbo
        self.application.onboarding_id = 7
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER
        )
        self.application.application_status_id = 191
        self.application.save()

        # Jturbo image
        target_type_images = ('ktp_self', 'selfie', 'crop_selfie')
        for image in target_type_images:
            ImageFactory(image_type=image, image_source=self.application.id)

        # active liveness
        vendor = ActiveLivenessVendorResultFactory()
        ActiveLivenessDetectionFactory(
            application=self.application,
            customer=self.customer,
            liveness_vendor_result=vendor,
        )

        # passive liveness
        vendor_passive_case = PassiveLivenessVendorResultFactory()
        PassiveLivenessDetectionFactory(
            application=self.application,
            customer=self.customer,
            liveness_vendor_result=vendor_passive_case,
        )

        # create application for J1
        self.application_j1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application_j1.update_safely(
            application_status_id=100,
            onboarding_id=3,
        )

        self.data['is_upgrade'] = 'true'
        response = self.client.patch(
            self.endpoint.format(self.application_j1.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)

        # check image data for application J1
        is_exist_for_image = Image.objects.filter(image_source=self.application_j1.id).exists()
        self.assertTrue(is_exist_for_image)

        is_exists_for_active_liveness = ActiveLivenessDetection.objects.filter(
            application_id=self.application_j1.id
        ).exists()
        self.assertTrue(is_exists_for_active_liveness)

        is_exists_for_passive_liveness = PassiveLivenessDetection.objects.filter(
            application_id=self.application_j1.id
        ).exists()
        self.assertTrue(is_exists_for_passive_liveness)

    @patch('juloserver.apiv2.views.check_and_storing_location')
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_shortened_with_latlong_mandatory(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_check_and_storing_location,
    ):
        """
        To check submission data with onboarding_id correct
        Test with case make sure onboarding_id verify with correct after submission.
        """

        longform_shortened_id = 3
        self.application.onboarding_id = longform_shortened_id
        self.application.save()

        # Data with LongForm Shortened
        self.data['loan_purpose_desc'] = None
        self.data['home_status'] = None
        self.data['occupied_since'] = None
        self.data['dependent'] = 0

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['onboarding_id'], longform_shortened_id)
        self.assertTrue(mock_check_and_storing_location.called)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_register_with_data_longform_shortened_without_latlong(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
    ):

        longform_shortened_id = 3
        self.application.onboarding_id = longform_shortened_id
        self.application.save()

        # Data with LongForm Shortened
        self.data['loan_purpose_desc'] = None
        self.data['home_status'] = None
        self.data['occupied_since'] = None
        self.data['dependent'] = 0
        self.data.pop('latitude')
        self.data.pop('longitude')

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_success_offline_activation_booth(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        longform_shortened_id = 3
        self.application.onboarding_id = longform_shortened_id
        self.application.save()

        self.setting = ExperimentSettingFactory(
            code=ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE,
            start_date=datetime.now() - timedelta(minutes=10),
            end_date=datetime.now() + timedelta(days=50),
            is_active=True,
            criteria={'referral_code': ['JULO123', 'JULO#1']},
            is_permanent=False,
        )

        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105,
        )
        self.path_tag = ApplicationTagFactory(
            application_tag=OfflineBoothConst.TAG_NAME, is_active=True
        )
        self.path_tag_status = ApplicationPathTagStatusFactory(
            application_tag=OfflineBoothConst.TAG_NAME, status=1
        )

        referral_code_set = 'JULO123'
        self.data['referral_code'] = referral_code_set
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        path_tag = ApplicationPathTagStatus.objects.filter(
            application_tag=OfflineBoothConst.TAG_NAME, status=OfflineBoothConst.SUCCESS_VALUE
        ).last()
        application_path = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=path_tag
        ).exists()
        self.assertTrue(application_path)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_success_without_activation_booth(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        longform_shortened_id = 3
        self.application.onboarding_id = longform_shortened_id
        self.application.save()

        self.setting = ExperimentSettingFactory(
            code=ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE,
            start_date=datetime.now() - timedelta(minutes=10),
            end_date=datetime.now() + timedelta(days=50),
            is_active=True,
            criteria={'referral_code': 'JULO123'},
            is_permanent=False,
        )

        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105,
        )
        self.path_tag = ApplicationTagFactory(
            application_tag=OfflineBoothConst.TAG_NAME, is_active=True
        )
        self.path_tag_status = ApplicationPathTagStatusFactory(
            application_tag=OfflineBoothConst.TAG_NAME, status=1
        )

        self.data['referral_code'] = ''
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        path_tag = ApplicationPathTagStatus.objects.filter(
            application_tag=OfflineBoothConst.TAG_NAME, status=OfflineBoothConst.SUCCESS_VALUE
        ).last()
        application_path = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=path_tag
        ).exists()
        self.assertFalse(application_path)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_success_offline_activation_booth_with_not_listed_the_code(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        longform_shortened_id = 3
        self.application.onboarding_id = longform_shortened_id
        self.application.save()

        self.setting = ExperimentSettingFactory(
            code=ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE,
            start_date=datetime.now() - timedelta(minutes=10),
            end_date=datetime.now() + timedelta(days=50),
            is_active=True,
            criteria={'referral_code': ['JULO123', 'JULO#1']},
            is_permanent=False,
        )

        ApplicationHistoryFactory(
            application_id=self.application.id,
            status_old=100,
            status_new=105,
        )
        self.path_tag = ApplicationTagFactory(
            application_tag=OfflineBoothConst.TAG_NAME, is_active=True
        )
        self.path_tag_status = ApplicationPathTagStatusFactory(
            application_tag=OfflineBoothConst.TAG_NAME, status=1
        )

        referral_code_set = 'JULO1234'
        self.data['referral_code'] = referral_code_set
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        path_tag = ApplicationPathTagStatus.objects.filter(
            application_tag=OfflineBoothConst.TAG_NAME, status=OfflineBoothConst.SUCCESS_VALUE
        ).last()
        application_path = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=path_tag
        ).exists()
        self.assertFalse(application_path)
        self.assertEqual(response.status_code, 200)

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_not_allowed_onboarding_id_j360_j1(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        self.application.onboarding_id = 10
        self.application.save()

        # mobile phone
        self.data['mobile_phone_1'] = '083822825710'

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.onboarding_id, 10)
        self.assertEqual(self.application.email, self.data['email'])
        self.assertEqual(self.application.ktp, self.data['ktp'])

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_success_with_onboarding_id_j360_j1(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        self.application.onboarding_id = 10
        register_phone_number = '08111122223333'
        self.application.mobile_phone_1 = register_phone_number
        self.application.save()

        self.data['mobile_phone_1'] = '083822825710'
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.email, self.data['email'])
        self.assertEqual(self.application.ktp, self.data['ktp'])

        self.application.refresh_from_db()
        application = Application.objects.get(pk=self.application.id)
        self.assertNotEqual(application.mobile_phone_1, self.data['mobile_phone_1'])
        self.assertEqual(application.mobile_phone_1, register_phone_number)

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_success_with_handle_existing_email(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        # for case reapply
        self.customer.update_safely(nik=self.data['ktp'], email=self.data['email'])

        other_customer_email = 'testing@gmail.com'
        other_customer = CustomerFactory(nik='671612323623723', email=other_customer_email)

        self.application.onboarding_id = 10
        self.application.mobile_phone_1 = '083822825710'
        self.application.save()

        # simulate submit with same email in other customer
        correct_email = self.data['email']
        self.data['email'] = other_customer_email

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0],
            'Email yang Anda masukkan telah terdaftar. ' 'Mohon gunakan email lain',
        )

        # simulate submit with correct email
        self.data['email'] = correct_email
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.email, self.data['email'])
        self.assertEqual(self.application.ktp, self.data['ktp'])

    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_submit_application_with_julo_phone_number(
        self, mock_check_liveness, mock_check_selfie_submission
    ):
        self.data['company_phone_number'] = '02150919034'

        resp = self.client.patch(
            '/api/v3/application/{}/'.format(self.application.id),
            data={**self.data},
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()['errors'],
            [
                "Maaf, nomor telepon perusahaan yang kamu masukkan tidak "
                "valid. Mohon masukkan nomor lainnya."
            ],
        )

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_success_mobile_phone_as_company_phone_number(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        # simulate submit with same email in other customer
        self.data['company_phone_number'] = '0898298239232'

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        application = Application.objects.get(pk=self.application.id)
        application.refresh_from_db()
        self.assertEqual(application.company_phone_number, self.data['company_phone_number'])

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_success_save_address_latlong(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        # simulate submit with same email in other customer
        self.data['address_latitude'] = -6
        self.data['address_longitude'] = 106

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        application = Application.objects.get(pk=self.application.id)
        application.refresh_from_db()

        address_geolocation = AddressGeolocation.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertEqual(address_geolocation.address_latitude, self.data['address_latitude'])
        self.assertEqual(address_geolocation.address_longitude, self.data['address_longitude'])
        self.assertEqual(application.fullname, self.data['fullname'])

    @patch('juloserver.julo.services.is_allow_to_change_status', return_value=True)
    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_success_save_address_latlong_is_empty(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_status_change,
        mock_is_allow_change_status,
    ):

        # simulate submit with same email in other customer
        self.data['address_latitude'] = None
        self.data['address_longitude'] = None

        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        application = Application.objects.get(pk=self.application.id)
        application.refresh_from_db()

        address_geolocation = AddressGeolocation.objects.filter(
            application_id=self.application.id
        ).last()
        self.assertIsNone(address_geolocation.address_latitude)
        self.assertIsNone(address_geolocation.address_longitude)
        self.assertEqual(application.fullname, self.data['fullname'])

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_submit_application_with_data_contains_some_symbol_chars(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()

        job_description = 'R&D / Ilmuwan / Peneliti'
        address_kelurahan = 'Berebas Pantai (Berbas Pantai)'
        address_provinsi = 'Nanggroe Aceh Darussalam (NAD)'
        bank_name = 'Bank Jago (Jago)'
        address_street_num = 'PONDOK CINA RESIDENCE 2\nBLOK C 1 004/002'
        company_name = 'D\u2019glow Test Company'

        self.data['job_description'] = job_description
        self.data['address_kelurahan'] = address_kelurahan
        self.data['address_provinsi'] = address_provinsi
        self.data['bank_name'] = bank_name
        self.data['address_street_num'] = address_street_num
        self.data['company_name'] = company_name

        # hit endpoint submission
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '1.0.1'},
        )

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.application.job_description, job_description)
        self.assertEqual(self.application.address_kelurahan, address_kelurahan)
        self.assertEqual(self.application.address_provinsi, address_provinsi)
        self.assertEqual(self.application.bank_name, bank_name)

    @patch('juloserver.apiv2.views.process_application_status_change')
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_submit_application_bank_account_number(
        self, mock_check_liveness, mock_check_selfie_submission, mock_status_change
    ):
        onboarding_id = 3
        self.application.onboarding_id = onboarding_id
        self.application.save()

        # Nomor rekening pribadi
        bank_account_number = '03720 46 956'
        self.data['bank_account_number'] = bank_account_number

        # hit endpoint submission
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '1.0.1'},
        )
        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['errors'][0],
            'Nomor Rekening Pribadi hanya diperbolehkan diisi dengan Angka',
        )

        # clean data
        bank_account_number = bank_account_number.replace(" ", "")
        self.data['bank_account_number'] = bank_account_number
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '1.0.1'},
        )
        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.application.bank_account_number, bank_account_number)

    @patch.object(ApplicationUpdateV3, 'is_validated_mother_maiden_name', return_value=False)
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_additional_message_is_shown(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_validation_mother,
    ):
        # hit endpoint submission
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '9.1.0'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('additional_message', response.json()['data'])

    @patch.object(ApplicationUpdateV3, 'is_validated_mother_maiden_name', return_value=False)
    @patch.object(ApplicationUpdateV3, 'check_selfie_submission', return_value=True)
    @patch.object(ApplicationUpdateV3, 'check_liveness', return_value=True)
    def test_additional_message_is_not_shown(
        self,
        mock_check_liveness,
        mock_check_selfie_submission,
        mock_validation_mother,
    ):
        # hit endpoint submission
        response = self.client.patch(
            self.endpoint.format(self.application.id),
            data={**self.data},
            format='json',
            **{'HTTP_X_APP_VERSION': '9.0.0'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.json()['data'])


class TestDeviceScrapedDataUploadV4(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status = StatusLookup.objects.get(status_code=100)
        self.application.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application.workflow = WorkflowFactory(worklow_name=WorkflowConst.JULO_ONE)
        self.application.save()
        self.device = DeviceFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        self.ios_id = 'E78E234E-4981-4BB7-833B-2B6CEC2F56DF'

        self.ios_device_header = {
            IdentifierKeyHeaderAPI.X_DEVICE_ID: self.ios_id,
            IdentifierKeyHeaderAPI.X_PLATFORM: 'iOS',
            IdentifierKeyHeaderAPI.X_PLATFORM_VERSION: '18.0',
        }

        self.endpoint = '/api/v4/etl/dsd/'
        self.android_payload = {
            'application_id': self.application.id,
            'app_details': [],
            'battery_detail': {
                'battery_health': 2,
                'battery_level': 68,
                'battery_status': 2,
                'charging_type': 2,
            },
            'phone_details': {
                'brand': 'samsung',
                'device': 'z3s',
                'display': 'TP1A.220624.014.G988BXXUIHWH9',
                'id': 'TP1A.220624.014',
                'manufacturer': 'samsung',
                'model': 'SM-G988B',
                'os_api_level': '13',
                'product': 'z3sxxx',
                'sdk': '33',
                'serial': 'unknown',
                'type': 'user',
                'user': 'dpi',
                'version': '4.19.87-27102101',
            },
        }

        self.ios_payload = {
            "application_id": self.application.id,
            "wifi_details": [
                {"bssid": "d4:35:38:3d:6e:47", "ssid": "FreeHotspot", "signal_strength": 0.5}
            ],
            "battery_detail": {"battery_level": 100, "battery_status": 2},
            "app_details": [],
            "phone_details": {
                "brand": "iPhone",
                "device": "iPhone",
                "build_version": "Darwin Kernel Version 22.6.0: Tue Jul  2 20:47:35 PDT 2024; root:xnu-8796.142.1.703.8~1/RELEASE_ARM64_T8015",
                "manufacturer": "Apple",
                "model": "iPhone 16 Pro",
                "os_version": "16.7.10",
                "os_major_version": 16,
                "cpu_arch": "arm64|x86",
            },
        }

    @patch('juloserver.apiv3.services.dsd_service.post_anaserver')
    def test_call_dsd_v4_using_ios(self, mock_call_anaserver):
        structure_response = {'response': 'OK'}
        mock_response = Response()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response._content = json.dumps(structure_response).encode('UTF-8')
        mock_call_anaserver.return_value = mock_response

        response = self.client.post(
            self.endpoint,
            data=self.ios_payload,
            format='json',
            **self.ios_device_header,
        )
        self.assertEqual(response.status_code, 200)

        called_args, called_kwargs = mock_call_anaserver.call_args
        self.assertEqual(called_args[0], '/api/amp/v1/ios-device-scraped-data/')

        # check application scrape action
        application_scrape = ApplicationScrapeAction.objects.filter(
            application_id=self.application.id,
            scrape_type='dsd',
        ).exists()
        self.assertTrue(application_scrape)

    @patch('juloserver.apiv3.services.dsd_service.post_anaserver')
    def test_call_dsd_v4_using_android(self, mock_call_anaserver):
        structure_response = {'response': 'OK'}
        mock_response = Response()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response._content = json.dumps(structure_response).encode('UTF-8')
        mock_call_anaserver.return_value = mock_response

        response = self.client.post(
            self.endpoint,
            data=self.android_payload,
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        called_args, called_kwargs = mock_call_anaserver.call_args
        self.assertEqual(called_args[0], '/api/amp/v1/device-scraped-data2/')

        # check application scrape action
        application_scrape = ApplicationScrapeAction.objects.filter(
            application_id=self.application.id,
            scrape_type='dsd',
        )
        self.assertTrue(application_scrape.exists())
