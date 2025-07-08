from mock import patch
from rest_framework.test import APIClient, APITestCase
from django.core.urlresolvers import reverse

from datetime import datetime
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    WorkflowFactory,
    ProductLineFactory,
    IdfyVideoCallFactory,
    OnboardingFactory,
)
from juloserver.julo.constants import (
    FeatureNameConst,
    ProductLineCodes,
    WorkflowConst,
    OnboardingIdConst,
    IdentifierKeyHeaderAPI,
)
from juloserver.liveness_detection.models import (
    PassiveLivenessDetection,
    ActiveLivenessDetection,
)
from juloserver.liveness_detection.tests.factories import (
    PassiveLivenessDetectionFactory,
    ActiveLivenessDetectionFactory,
)
from django.test import override_settings


class TestPreCheck(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)

    @patch('juloserver.standardized_api_response.mixin.api_logger')
    @patch('juloserver.liveness_detection.views.pre_check_liveness')
    def test_logging_data(self, mock_pre_check_liveness, mock_logger):
        # test log data when status code >=400
        mock_pre_check_liveness.return_value = {}
        data = {'skip_customer': 'aaaaaaaaaaaaa'}
        result = self.client.post('/api/liveness-detection/v1/pre-check', data=data)
        self.assertEqual(result.status_code, 400)
        mock_logger.info.assert_called_once()

    @patch('juloserver.standardized_api_response.mixin.api_logger')
    @patch('juloserver.liveness_detection.views.pre_check_liveness')
    def test_dont_logging_data(self, mock_pre_check_liveness, mock_logger):
        # test doesn't log data when status code < 400
        mock_pre_check_liveness.return_value = {}
        result = self.client.post('/api/liveness-detection/v1/pre-check')
        self.assertEqual(result.status_code, 200)
        mock_logger.info.assert_not_called()

    def test_for_user_idfy_got_approved(self):

        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.LIVENESS_DETECTION,
            is_active=True,
            parameters={
                'active_liveness': {
                    'retry': 2,
                    'timeout': 10,
                    'is_active': True,
                    'timeout_retry': 3,
                    'max_face_ratio': 0.5,
                    'min_face_ratio': 0.05,
                    'score_threshold': 0.92,
                    'extra_segment_count': 4,
                    'valid_segment_count': 4,
                    'skip_application_failed': True,
                    'application_eyes_detection_retry': 2,
                    'application_face_detection_retry': 2,
                    'application_face_detection_counter': 10,
                },
                'passive_liveness': {
                    'timeout': 10,
                    'template': True,
                    'is_active': True,
                    'crop_image': False,
                    'timeout_retry': 3,
                    'max_face_ratio': 0.5,
                    'min_face_ratio': 0.05,
                    'face_attributes': True,
                    'facial_features': True,
                    'icao_attributes': True,
                    'score_threshold': 88,
                    'crop_image_with_removed_background': False,
                },
                'app_version_to_skip': '6.4.1',
            },
        )

        self.application.update_safely(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )

        self.idfy_record = IdfyVideoCallFactory(
            reference_id=self.application.application_xid,
            status='completed',
            reviewer_action='approved',
            application_id=self.application.id,
        )

        # for case already have case passed on passive liveness
        created_data_passive = PassiveLivenessDetectionFactory(
            application=self.application, customer=self.customer, status='passed'
        )

        # try to hit again endpoint
        result = self.client.post('/api/liveness-detection/v1/pre-check')
        self.assertEqual(result.status_code, 200)
        is_exist_passive_record = PassiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_passive_record.count(), 1)
        # reset created data passive liveness
        created_data_passive.delete()

        result = self.client.post('/api/liveness-detection/v1/pre-check')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['active_liveness'], False)
        self.assertEqual(result.json()['data']['passive_liveness'], False)

        # check configuration stored to table
        is_exist_active_record = ActiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertTrue(is_exist_active_record.exists())
        self.assertEqual(is_exist_active_record.last().status, 'skipped_customer')

        is_exist_passive_record = PassiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertTrue(is_exist_passive_record.exists())
        self.assertEqual(is_exist_passive_record.last().status, 'skipped_customer')

        # make sure only one data creating
        result = self.client.post('/api/liveness-detection/v1/pre-check')
        self.assertEqual(result.status_code, 200)
        is_exist_passive_record = PassiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_passive_record.count(), 1)

        is_exist_active_record = ActiveLivenessDetection.objects.filter(
            application=self.application,
            customer=self.customer,
        )
        self.assertEqual(is_exist_active_record.count(), 3)

        # case for rejected
        self.idfy_record.update_safely(
            reviewer_action='rejected',
        )
        result = self.client.post('/api/liveness-detection/v1/pre-check')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['active_liveness'], True)
        self.assertEqual(result.json()['data']['passive_liveness'], True)

    def test_multiple_x100_liveness(self):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.LIVENESS_DETECTION,
            is_active=True,
            parameters={
                'active_liveness': {
                    'retry': 2,
                    'timeout': 10,
                    'is_active': True,
                    'timeout_retry': 3,
                    'max_face_ratio': 0.5,
                    'min_face_ratio': 0.05,
                    'score_threshold': 0.92,
                    'extra_segment_count': 4,
                    'valid_segment_count': 4,
                    'skip_application_failed': True,
                    'application_eyes_detection_retry': 2,
                    'application_face_detection_retry': 2,
                    'application_face_detection_counter': 10,
                },
                'passive_liveness': {
                    'timeout': 10,
                    'template': True,
                    'is_active': True,
                    'crop_image': False,
                    'timeout_retry': 3,
                    'max_face_ratio': 0.5,
                    'min_face_ratio': 0.05,
                    'face_attributes': True,
                    'facial_features': True,
                    'icao_attributes': True,
                    'score_threshold': 88,
                    'crop_image_with_removed_background': False,
                },
                'app_version_to_skip': '6.4.1',
            },
        )

        self.application.update_safely(
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            onboarding=OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID),
            customer=self.customer,
            udate=datetime(year=2023, month=9, day=6),
        )
        self.application.application_status_id = '100'
        self.application.save()

        # hit endpoint with no form_data
        form_data = {'skip_customer': False}

        result = self.client.post('/api/liveness-detection/v1/pre-check', data=form_data)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['active_liveness'], True)
        self.assertEqual(result.json()['data']['passive_liveness'], True)

        # application has no record
        form_data['application_id'] = self.application.id

        result = self.client.post('/api/liveness-detection/v1/pre-check', data=form_data)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['active_liveness'], True)
        self.assertEqual(result.json()['data']['passive_liveness'], True)

        # application has liveness record:
        created_data_passive = PassiveLivenessDetectionFactory(
            application=self.application, customer=self.customer, status='passed'
        )
        created_data_active = ActiveLivenessDetectionFactory(
            application=self.application, customer=self.customer, status='passed'
        )
        result = self.client.post('/api/liveness-detection/v1/pre-check', data=form_data)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['active_liveness'], False)
        self.assertEqual(result.json()['data']['passive_liveness'], False)

        self.fs.delete()
        result = self.client.post('/api/liveness-detection/v1/pre-check', data=form_data)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['active_liveness'], False)
        self.assertEqual(result.json()['data']['passive_liveness'], False)

    def test_precheck_for_ios(self):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.LIVENESS_DETECTION,
            is_active=True,
            parameters={
                'active_liveness': {
                    'retry': 2,
                    'timeout': 10,
                    'is_active': True,
                    'timeout_retry': 3,
                    'max_face_ratio': 0.5,
                    'min_face_ratio': 0.05,
                    'score_threshold': 0.92,
                    'extra_segment_count': 4,
                    'valid_segment_count': 4,
                    'skip_application_failed': True,
                    'application_eyes_detection_retry': 2,
                    'application_face_detection_retry': 2,
                    'application_face_detection_counter': 10,
                },
                'passive_liveness': {
                    'timeout': 10,
                    'template': True,
                    'is_active': True,
                    'crop_image': False,
                    'timeout_retry': 3,
                    'max_face_ratio': 0.5,
                    'min_face_ratio': 0.05,
                    'face_attributes': True,
                    'facial_features': True,
                    'icao_attributes': True,
                    'score_threshold': 88,
                    'crop_image_with_removed_background': False,
                },
                'app_version_to_skip': '6.4.1',
            },
        )

        # hit endpoint with no form_data
        form_data = {
            'skip_customer': False,
            'application_id': self.application.id,
            'client_type': 'ios',
            'service_check_type': 'dot_digital_identity',
            'active_method': 'magnifeye',
        }

        result = self.client.post('/api/liveness-detection/v3/pre-check', data=form_data)
        print(result.json())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['active_liveness'], False)
        self.assertEqual(result.json()['data']['passive_liveness'], False)



class TestIOSAppLicense(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        self.license_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.LIVENESS_DETECTION_IOS_LICENSE,
            is_active=True,
            parameters={
                "version": "2.1",
                "contract": {
                    "dot": {
                        "mobile": {
                            "face": {"enabled": True},
                            "palm": {"enabled": True},
                            "document": {"enabled": True},
                            "faceLite": {"enabled": True},
                        }
                    },
                    "hwids": ["AUC/VBBxraZ8ztID"],
                    "idkit": {"database_size": 0, "max_client_connections": 0},
                    "customer": "JULO",
                    "products": ["iface"],
                    "expiration": {"day": 21, "year": 2025, "month": 11},
                },
                "contract_signature": "I4PwmXjgPyMkVjIDAefI72yQfWxMKzf44oztgQmXRT19D9ULjOdovHbDfFjQDTpVHbDwEotq5wEMDw9ZTck7bNN20TsQ6xAsXXaTTfNmdTvdqI+DZ5pAzKFl/8nViF1gUV3XcU2e+BQShHIINRS7myiXcb9vevFgtkugYIYy84M=",
            },
        )
        self.device_header = {
            IdentifierKeyHeaderAPI.X_DEVICE_ID: 'E78E234E-4981-4BB7-833B-2B6CEC2F56DF',
            IdentifierKeyHeaderAPI.X_PLATFORM: 'iOS',
            IdentifierKeyHeaderAPI.X_PLATFORM_VERSION: '18.0',
        }

    @override_settings(LIVENESS_LICENSE_KEY='6QK1EjFArqnoQSs_djWlyEZWd1F2fTbs-gboj9GjaZ0=')
    def test_ios_license_request(self):
        # success request
        response = self.client.get(reverse('ios-license'), **self.device_header)
        self.assertEqual(response.status_code, 200)

        # not ios request
        non_ios_header = {
            "HTTP_X_DEVICE_ID": "E78E234E-4981-4BB7-833B-2B6CEC2F56DF",
            "HTTP_X_PLATFORM": "Android",
            "HTTP_X_PLATFORM_VERSION": "12.0",
        }
        response = self.client.get(reverse('ios-license'), **non_ios_header)
        self.assertEqual(response.status_code, 400)
