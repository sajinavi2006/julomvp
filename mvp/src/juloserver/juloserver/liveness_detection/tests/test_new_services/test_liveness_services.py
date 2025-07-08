import io

from django.core.files import File
from django.test.testcases import TestCase
from mock import patch

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    ImageFactory,
    WorkflowFactory,
)
from juloserver.liveness_detection.constants import LivenessCheckStatus
from juloserver.liveness_detection.exceptions import DotServerError
from juloserver.liveness_detection.tests.factories import (
    ActiveLivenessDetectionFactory,
    ActiveLivenessVendorResultFactory,
    ApplicationFactory,
    CustomerFactory,
    PassiveLivenessDetectionFactory,
    PassiveLivenessVendorResultFactory,
)
from juloserver.liveness_detection.new_services.liveness_services import (
    detect_liveness,
    pre_check_liveness,
)
from juloserver.liveness_detection.models import ActiveLivenessDetection, PassiveLivenessDetection


class TestPreCheck(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    def _create_feature_setting(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.NEW_LIVENESS_DETECTION,
            is_active=True,
            parameters={
                'android': {
                    'skip_application_failed': True,
                    'passive_threshold': 0.8,
                    'eye_gaze_threshold': 1.0,
                    'timeout_retry': 2,
                    'timeout': 5,
                    'retry': 3,
                    'is_active': True,
                },
            },
        )

    def test_application_invalid(self):
        result = pre_check_liveness(self.customer, 'android')
        self.assertEqual(
            {
                'active_liveness': False,
                'passive_liveness': False,
                'liveness_retry': None,
                'extra_data': {},
            },
            result,
        )
        self.assertIsNone(ActiveLivenessDetection.objects.get_or_none(customer=self.customer))
        self.assertIsNone(PassiveLivenessDetection.objects.get_or_none(customer=self.customer))

    def test_feature_off(self):
        self.application.application_status_id = 100
        self.application.save()
        result = pre_check_liveness(self.customer, 'android')
        self.assertEqual(
            {
                'active_liveness': False,
                'passive_liveness': False,
                'liveness_retry': None,
                'extra_data': {},
            },
            result,
        )

        active_liveness_detection = ActiveLivenessDetection.objects.get(customer=self.customer)
        passive_liveness_detection = PassiveLivenessDetection.objects.get(customer=self.customer)
        self.assertEqual(active_liveness_detection.status, 'feature_is_off')
        self.assertEqual(passive_liveness_detection.status, 'feature_is_off')

    @patch(
        'juloserver.liveness_detection.new_services.liveness_services.get_dot_digital_identity_client'
    )
    def test_pre_check_liveness_success(self, mock_ddis_client):
        self._create_feature_setting()
        self.application.application_status_id = 100
        self.application.save()
        mock_ddis_client().generate_challenge.return_value = (
            {"details": {"corners": ["TOP_LEFT"]}},
            0,
        )
        mock_ddis_client().get_api_info.return_value = {'build': {'version': '1.0'}}, 0
        mock_ddis_client().create_customer.return_value = {
            'id': 'eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
            'links': {'self': '/api/v1/customers/eb49ec95-07f7-4ff4-8d81-a3f274198a9f'},
        }, 0
        mock_ddis_client().create_customer_liveness.return_value = {}, 0
        result = pre_check_liveness(
            self.customer, 'android', check_passive=True, active_method='eye-gaze'
        )
        self.assertEqual(
            {
                'active_liveness': True,
                'passive_liveness': True,
                'liveness_retry': 3,
                'extra_data': {'eye_gaze_challenge': ['TOP_LEFT']},
            },
            result,
        )
        active_liveness_detection = ActiveLivenessDetection.objects.get(customer=self.customer)
        passive_liveness_detection = PassiveLivenessDetection.objects.get(customer=self.customer)
        self.assertEqual(active_liveness_detection.status, 'initial')
        self.assertEqual(active_liveness_detection.sequence, ['TOP_LEFT'])
        self.assertEqual(passive_liveness_detection.status, 'initial')

    def test_skip_for_customer(self):
        self._create_feature_setting()
        self.application.application_status_id = 100
        self.application.save()
        result = pre_check_liveness(self.customer, 'android', skip_customer=True)
        self.assertEqual(
            {
                'active_liveness': True,
                'passive_liveness': True,
                'liveness_retry': 3,
                'extra_data': {},
            },
            result,
        )
        active_liveness_detection = ActiveLivenessDetection.objects.get(customer=self.customer)
        passive_liveness_detection = PassiveLivenessDetection.objects.get(customer=self.customer)
        self.assertEqual(active_liveness_detection.status, 'skipped_customer')
        self.assertEqual(passive_liveness_detection.status, 'skipped_customer')


class TestCheckLiveness(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.record = File(
            file=io.BytesIO(b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01"), name='test'
        )
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.application.application_status_id = 100
        self.application.save()
        self.feature_settings = FeatureSettingFactory(
            feature_name=FeatureNameConst.NEW_LIVENESS_DETECTION,
            is_active=True,
            parameters={
                'android': {
                    'skip_application_failed': True,
                    'passive_threshold': 0.8,
                    'eye_gaze_threshold': 1.0,
                    'magnifeye_threshold': 1.0,
                    'smile_threshold': 1.0,
                    'timeout_retry': 2,
                    'timeout': 5,
                    'retry': 3,
                    'is_active': True,
                },
            },
        )
        self.configs = self.feature_settings.parameters.get('android', {})

    def _mock_ddis_client(
        self,
        mock_service,
        mock_get_api_info=True,
        mock_create_customer=True,
        mock_create_customer_selfie=True,
        mock_create_customer_liveness=True,
        mock_upload_record=True,
        mock_evaluate_eye_gaze=True,
        mock_evaluate_smile=True,
        mock_evaluate_passive=True,
        mock_delete_customer=True,
        mock_provide_customer_liveness_selfie=True,
    ):
        if mock_get_api_info:
            mock_service.get_api_info.return_value = {'build': {'version': '1.0'}}, 0
        if mock_create_customer:
            mock_service.create_customer.return_value = {
                'id': 'eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
                'links': {'self': '/api/v1/customers/eb49ec95-07f7-4ff4-8d81-a3f274198a9f'},
            }, 0
        if mock_create_customer_selfie:
            mock_service.create_customer_selfie.return_value = {
                'detection': {
                    'confidence': 0.9174,
                    'faceRectangle': {
                        'topLeft': {'x': 117, 'y': 174},
                        'topRight': {'x': 452, 'y': 155},
                        'bottomRight': {'x': 478, 'y': 601},
                        'bottomLeft': {'x': 143, 'y': 620},
                    },
                },
                'links': {'self': '/api/v1/customers/eb49ec95-07f7-4ff4-8d81-a3f274198a9f/selfie'},
                'warnings': [],
            }, 0
        if mock_create_customer_liveness:
            mock_service.create_customer_liveness.return_value = {}, 0
        if mock_upload_record:
            mock_service.upload_record.return_value = {
                "selfie": {
                    "detection": {
                        "confidence": 0.34,
                        "faceRectangle": {
                            "topLeft": {"x": 10, "y": 20},
                            "topRight": {"x": 10, "y": 20},
                            "bottomRight": {"x": 10, "y": 20},
                            "bottomLeft": {"x": 10, "y": 20},
                        },
                    }
                },
                "links": {"selfie": "string"},
                "errorCode": "INVALID_DATA",
            }, 0
        if mock_evaluate_eye_gaze:
            mock_service.evaluate_eye_gaze.return_value = {}, 0
        if mock_evaluate_passive:
            mock_service.evaluate_passive.return_value = {}, 0
        if mock_delete_customer:
            mock_service.delete_customer.return_value = {}, 0
        if mock_provide_customer_liveness_selfie:
            mock_service.provide_customer_liveness_selfie.return_value = {}, 0

    def test_application_not_found(self):
        customer = CustomerFactory()
        result, data = detect_liveness(customer, [])
        self.assertEqual(result, 'application_not_found')

    def test_liveness_detection_not_found(self):
        result, data = detect_liveness(self.customer, [])

        self.assertEqual(result, 'liveness_not_found')

    def test_max_retry(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            attempt=3,
            configs=self.configs,
            client_type='android',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            attempt=3,
            configs=self.configs,
            client_type='android',
        )
        result, data = detect_liveness(self.customer, [])
        self.assertEqual(result, 'limit_exceeded')

    def test_application_failed(self):
        self.feature_settings.is_active = False
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        result, data = detect_liveness(self.customer, [], application_failed=True)
        self.assertEqual(result, 'application_detect_failed')

    @patch(
        'juloserver.liveness_detection.new_services.liveness_services.get_dot_digital_identity_client'
    )
    def test_dot_service_internal_error(self, mock_ddis_client):
        self.feature_settings.is_active = False
        self.feature_settings.save()
        at = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        ps = PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        mock_ddis_client().upload_record.side_effect = DotServerError(
            {'response': {'error_code': 'error'}, 'elapsed': 10}
        )
        result, data = detect_liveness(self.customer, self.record)
        self.assertEqual(result, 'error')

        # retry after error
        at.refresh_from_db()
        ps.refresh_from_db()
        at.status = LivenessCheckStatus.STARTED
        at.save()
        ps.status = LivenessCheckStatus.STARTED
        ps.save()
        self.feature_settings.is_active = True
        self.feature_settings.save()
        result, data = detect_liveness(self.customer, self.record)
        self.assertEqual(result, 'error')

    @patch(
        'juloserver.liveness_detection.new_services.liveness_services.get_dot_digital_identity_client'
    )
    def test_dot_service_internal_failed(self, mock_ddis_client):
        self.feature_settings.is_active = False
        self.feature_settings.save()
        at = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        ps = PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        active_liveness_vendor_result = ActiveLivenessVendorResultFactory()
        self._mock_ddis_client(mock_ddis_client())
        mock_ddis_client().active_vendor_result = active_liveness_vendor_result
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        result, data = detect_liveness(self.customer, self.record, active_method='eye-gaze')
        self.assertEqual(result, 'failed')

        # failed
        self.feature_settings.is_active = True
        self.feature_settings.save()
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        active_liveness_vendor_result = ActiveLivenessVendorResultFactory()
        mock_ddis_client().get_api_info.return_value = {'build': {'version': '1.0'}}, 0
        mock_ddis_client().create_customer.return_value = {
            'id': 'eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
            'links': {'self': '/api/v1/customers/eb49ec95-07f7-4ff4-8d81-a3f274198a9f'},
        }, 0
        self._mock_ddis_client(
            mock_ddis_client(), mock_evaluate_eye_gaze=False, mock_evaluate_passive=False
        )
        mock_ddis_client().evaluate_eye_gaze.return_value = {'score': 0.5}, 0
        mock_ddis_client().evaluate_passive.return_value = {'score': 0.5}, 0
        mock_ddis_client().active_vendor_result = active_liveness_vendor_result
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        mock_ddis_client().inspect_customer.return_value = {}, 0
        at.refresh_from_db()
        ps.refresh_from_db()
        at.status = LivenessCheckStatus.STARTED
        at.save()
        ps.status = LivenessCheckStatus.STARTED
        ps.save()
        result, data = detect_liveness(self.customer, self.record, active_method='eye-gaze')
        self.assertEqual(result, 'failed')

    @patch(
        'juloserver.liveness_detection.new_services.liveness_services.get_dot_digital_identity_client'
    )
    def test_success_eye_gaze(self, mock_ddis_client):
        at = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
            internal_customer_id='eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        active_liveness_vendor_result = ActiveLivenessVendorResultFactory()
        self._mock_ddis_client(
            mock_ddis_client(), mock_evaluate_eye_gaze=False, mock_evaluate_passive=False
        )
        mock_ddis_client().evaluate_eye_gaze.return_value = {'score': 1.0}, 0
        mock_ddis_client().evaluate_passive.return_value = {'score': 1.0}, 0
        mock_ddis_client().active_vendor_result = active_liveness_vendor_result
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        mock_ddis_client().inspect_customer.return_value = (
            {
                "selfieInspection": {
                    "similarityWith": {},
                    "genderEstimate": "F",
                    "genderConsistency": {},
                    "ageEstimate": 32,
                    "ageDifferenceWith": {},
                    "hasMask": False,
                },
                "security": {"videoInjection": {"evaluated": True, "detected": True}},
                "links": {"documentInspection": "string"},
            },
            0,
        )
        result, data = detect_liveness(self.customer, self.record, active_method='eye-gaze')
        self.assertEqual(result, 'success')
        at.refresh_from_db()
        self.assertEqual(at.video_injection, 'video_injected')

    @patch(
        'juloserver.liveness_detection.new_services.liveness_services.get_dot_digital_identity_client'
    )
    def test_success_magnifeye(self, mock_ddis_client):
        at = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
            internal_customer_id='eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        active_liveness_vendor_result = ActiveLivenessVendorResultFactory()
        self._mock_ddis_client(
            mock_ddis_client(), mock_evaluate_eye_gaze=False, mock_evaluate_passive=False
        )
        mock_ddis_client().evaluate_magnifeye.return_value = {'score': 1.0}, 0
        mock_ddis_client().evaluate_passive.return_value = {'score': 1.0}, 0
        mock_ddis_client().active_vendor_result = active_liveness_vendor_result
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        mock_ddis_client().inspect_customer.return_value = (
            {
                "selfieInspection": {
                    "similarityWith": {},
                    "genderEstimate": "F",
                    "genderConsistency": {},
                    "ageEstimate": 32,
                    "ageDifferenceWith": {},
                    "hasMask": False,
                },
                "security": {"videoInjection": {"evaluated": True, "detected": True}},
                "links": {"documentInspection": "string"},
            },
            0,
        )
        result, data = detect_liveness(self.customer, self.record, active_method='magnifeye')
        self.assertEqual(result, 'success')
        at.refresh_from_db()
        self.assertEqual(at.video_injection, 'video_injected')

    @patch(
        'juloserver.liveness_detection.new_services.liveness_services.get_dot_digital_identity_client'
    )
    def test_detect_passive_only(self, mock_ddis_client):
        self.feature_settings.is_active = False
        self.feature_settings.save()
        # failed
        passive_liveness = PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        self._mock_ddis_client(
            mock_ddis_client(),
            mock_evaluate_eye_gaze=False,
            mock_evaluate_passive=False,
        )
        mock_ddis_client().evaluate_passive.return_value = {'score': 0.5}, 0
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        mock_ddis_client().inspect_customer.return_value = {}, 0
        result, data = detect_liveness(
            self.customer, self.record, check_passive=True, check_active=False
        )
        self.assertEqual(result, 'failed')

        # success
        self.feature_settings.is_active = True
        self.feature_settings.save()
        passive_liveness.status = LivenessCheckStatus.STARTED
        passive_liveness.save()
        mock_ddis_client().evaluate_passive.return_value = {'score': 1.0}, 0
        result, data = detect_liveness(
            self.customer, self.record, check_passive=True, check_active=False
        )
        self.assertEqual(result, 'success')

    @patch(
        'juloserver.liveness_detection.new_services.liveness_services.get_dot_digital_identity_client'
    )
    def test_success_smile(self, mock_ddis_client):
        at = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
            internal_customer_id='eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='android',
        )
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        active_liveness_vendor_result = ActiveLivenessVendorResultFactory()
        self._mock_ddis_client(
            mock_ddis_client(), mock_evaluate_smile=False, mock_evaluate_passive=False
        )
        mock_ddis_client().evaluate_smile.return_value = {'score': 1.0}, 0
        mock_ddis_client().evaluate_passive.return_value = {'score': 1.0}, 0
        mock_ddis_client().active_vendor_result = active_liveness_vendor_result
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        mock_ddis_client().inspect_customer.return_value = (
            {
                "selfieInspection": {
                    "similarityWith": {},
                    "genderEstimate": "F",
                    "genderConsistency": {},
                    "ageEstimate": 32,
                    "ageDifferenceWith": {},
                    "hasMask": False,
                },
                "security": {"videoInjection": {"evaluated": True, "detected": True}},
                "links": {"documentInspection": "string"},
            },
            0,
        )
        result, data = detect_liveness(self.customer, self.record, active_method='smile')
        self.assertEqual(result, 'success')
        at.refresh_from_db()
        self.assertEqual(at.video_injection, 'video_injected')
