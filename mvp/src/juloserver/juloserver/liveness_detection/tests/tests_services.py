import io

from django.core.files import File
from django.test import override_settings
from django.test.testcases import TestCase
from mock import patch

from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    ImageFactory,
    WorkflowFactory,
)
from juloserver.liveness_detection.constants import LivenessCheckStatus
from juloserver.liveness_detection.exceptions import DotCoreServerError
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
)
from juloserver.liveness_detection.services import (
    check_active_liveness,
    check_application_liveness_detection_result,
    check_passive_liveness,
    detect_face,
    get_active_liveness_info,
    get_active_liveness_sequence,
    get_android_app_license,
    pre_check_liveness,
    start_active_liveness_process,
)
from juloserver.liveness_detection.tests.factories import (
    ActiveLivenessDetectionFactory,
    ActiveLivenessVendorResultFactory,
    ApplicationFactory,
    CustomerFactory,
    PassiveLivenessDetectionFactory,
    PassiveLivenessVendorResultFactory,
)


class TestGetActiveLivenessSequence(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.application.application_status_id = 100
        self.application.save()

    def test_application_not_found(self):
        customer = CustomerFactory()
        result, data = get_active_liveness_sequence(customer)
        self.assertEqual(result, 'application_not_found')

        # application is not J1 customer
        workflow = WorkflowFactory(name='FakeWorkflow', handler='FakeWorkflowHandler')
        application = ApplicationFactory(customer=customer, workflow=workflow)
        application.application_status_id = 100
        application.save()
        result, data = get_active_liveness_sequence(customer)
        self.assertEqual(result, 'application_not_found')

    def test_already_check_liveness_detection(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='success'
        )
        result, data = get_active_liveness_sequence(self.customer)
        self.assertEqual(result, 'already_checked')

    def test_get_sequence_error(self):
        result, data = get_active_liveness_sequence(self.customer)
        self.assertEqual(result, 'success')
        self.assertEqual(data, [])

    @patch('juloserver.liveness_detection.services.dot_core_client')
    def test_get_sequence_success(self, mock_get_dot_core_client):
        FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'active_liveness': {
                    'is_active': True,
                    'valid_segment_count': 3,
                    'extra_segment_count': 3,
                }
            },
        )
        mock_get_dot_core_client.get_api_info.return_value = {
            "build": {
                "artifact": "dot-core-server",
                "group": "com.innovatrics.dot",
                "name": "dot-core-server",
                "version": "3.9.0",
            }
        }
        result, data = get_active_liveness_sequence(self.customer)
        self.assertEqual(result, 'success')
        self.assertEqual(len(data), 6)


class TestCheckAtiveLiveness(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.image = File(
            file=io.BytesIO(b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01"), name='test'
        )
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.application.application_status_id = 100
        self.application.save()

    def test_application_not_found(self):
        customer = CustomerFactory()
        result, data = check_active_liveness([], customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'application_not_found')

    def test_liveness_detection_not_found(self):
        FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'active_liveness': {
                    'valid_segment_count': 3,
                    'retry': 2,
                    'is_active': True,
                }
            },
        )
        result, data = check_active_liveness([], self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'active_liveness_not_found')

    def test_config_not_found(self):
        ActiveLivenessDetectionFactory(customer=self.customer, application=self.application)
        result, data = check_active_liveness([], self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'success')

    def test_incorrect_sequence(self):
        active_liveness = ActiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, sequence=['TOP_LEFT', 'TOP_RIGHT']
        )
        FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'active_liveness': {
                    'valid_segment_count': 4,
                    'retry': 2,
                    'is_active': True,
                }
            },
        )
        segments = [
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': self.image, 'dot_position': 'BOTTOM_LEFT'},
        ]
        result, data = check_active_liveness(segments, self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'sequence_incorrect')
        # duplicate segment
        active_liveness.update_safely(
            sequence=[
                'TOP_LEFT',
                'TOP_RIGHT',
                'BOTTOM_RIGHT',
                'BOTTOM_LEFT',
                'TOP_LEFT',
                'TOP_LEFT',
            ]
        )
        segments = [
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': None, 'dot_position': 'TOP_RIGHT'},
            {'image': None, 'dot_position': 'BOTTOM_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_LEFT'},
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
        ]
        result, data = check_active_liveness(segments, self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'application_detect_failed')

    @patch('juloserver.liveness_detection.services.get_api_version')
    @patch('juloserver.liveness_detection.services.upload_selfie_image')
    @patch('juloserver.liveness_detection.services.dot_core_client')
    def test_dot_core_internal_error(
        self, mock_dot_core_client, mock_upload_selfie_image, mock_get_api_version
    ):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            sequence=['TOP_LEFT', 'TOP_RIGHT', 'BOTTOM_RIGHT', 'BOTTOM_RIGHT'],
        )
        FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'active_liveness': {
                    'valid_segment_count': 2,
                    'retry': 2,
                    'is_active': True,
                }
            },
        )
        segments = [
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': self.image, 'dot_position': 'TOP_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_RIGHT'},
        ]
        image = ImageFactory()
        # internal error
        mock_upload_selfie_image.return_value = image
        mock_dot_core_client.check_active_liveness.side_effect = DotCoreServerError(
            {'response': {'error_code': 'error'}, 'elapsed': 10}
        )
        result, data = check_active_liveness(segments, self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'error')
        self.assertEqual(data['retry_count'], 1)

        # max_retry and app_version is a new
        segments = [
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': self.image, 'dot_position': 'TOP_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_RIGHT'},
        ]
        mock_get_api_version.return_value = '1.1.1'
        result, data = check_active_liveness(segments, self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'application_detect_failed')
        self.assertEqual(data['retry_count'], 2)

    @patch('juloserver.liveness_detection.services.upload_selfie_image')
    @patch('juloserver.liveness_detection.services.dot_core_client')
    def test_dot_core_internal_failed(self, mock_dot_core_client, mock_upload_selfie_image):
        liveness_detection = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            sequence=['TOP_LEFT', 'TOP_RIGHT', 'BOTTOM_RIGHT', 'BOTTOM_LEFT'],
        )
        feature_setting = FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'active_liveness': {
                    'valid_segment_count': 2,
                    'score_threshold': 1,
                    'retry': 2,
                    'max_retry': 3,
                    'is_active': True,
                }
            },
        )
        segments = [
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': self.image, 'dot_position': 'TOP_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_LEFT'},
        ]
        image = ImageFactory()
        mock_upload_selfie_image.return_value = image
        # dot core server response incorrect format
        vendor_result = ActiveLivenessVendorResultFactory()
        mock_dot_core_client.check_active_liveness.return_value = {}, 10, vendor_result
        result, data = check_active_liveness(segments, self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'failed')
        # failed
        liveness_detection.status = 'initial'
        liveness_detection.save()
        segments = [
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': self.image, 'dot_position': 'TOP_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_LEFT'},
        ]
        mock_dot_core_client.check_active_liveness.return_value = {'score': 0.99}, 10, vendor_result
        result, data = check_active_liveness(segments, self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'failed')
        # score is 0
        liveness_detection.status = 'initial'
        liveness_detection.save()
        segments = [
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': self.image, 'dot_position': 'TOP_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_LEFT'},
        ]
        mock_dot_core_client.check_active_liveness.return_value = {'score': 0.0}, 10, vendor_result
        feature_setting_params = feature_setting.parameters
        feature_setting_params['active_liveness']['score_threshold'] = -1
        feature_setting.update_safely(parameters=feature_setting_params)
        result, data = check_active_liveness(segments, self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'success')

    @patch('juloserver.liveness_detection.services.upload_selfie_image')
    @patch('juloserver.liveness_detection.services.dot_core_client')
    def test_success(self, mock_dot_core_client, mock_upload_selfie_image):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            sequence=['TOP_LEFT', 'TOP_RIGHT', 'BOTTOM_RIGHT', 'BOTTOM_LEFT'],
        )
        FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'active_liveness': {
                    'valid_segment_count': 2,
                    'score_threshold': 1,
                    'retry': 2,
                    'max_retry': 3,
                    'is_active': True,
                }
            },
        )
        segments = [
            {'image': self.image, 'dot_position': 'TOP_LEFT'},
            {'image': self.image, 'dot_position': 'TOP_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_RIGHT'},
            {'image': self.image, 'dot_position': 'BOTTOM_LEFT'},
        ]
        image = ImageFactory()
        mock_upload_selfie_image.return_value = image
        vendor_result = ActiveLivenessVendorResultFactory()
        mock_dot_core_client.check_active_liveness.return_value = {'score': 1}, 10, vendor_result
        result, data = check_active_liveness(segments, self.customer, LivenessCheckStatus.INITIAL)
        self.assertEqual(result, 'success')


class TestCheckPassiveLiveness(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.image = ImageFactory()
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.application.application_status_id = 105
        self.application.save()

    def test_application_not_found(self):
        customer = CustomerFactory()
        result, data = check_passive_liveness(self.image, customer)
        self.assertEqual(result, 'application_not_found')

    def test_already_check_liveness_detection(self):
        PassiveLivenessDetectionFactory(customer=self.customer, application=self.application)
        result, data = check_passive_liveness(self.image, self.customer)
        self.assertEqual(result, 'already_checked')

    def test_config_not_found(self):
        result, data = check_passive_liveness(self.image, self.customer)
        self.assertEqual(result, 'error')


class TestDetectFace(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.image = File(
            file=io.BytesIO(b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01"), name='test'
        )
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.liveness_detection = PassiveLivenessDetectionFactory(
            customer=self.customer, application=self.application
        )

    @patch('juloserver.liveness_detection.services.upload_selfie_image')
    @patch('juloserver.liveness_detection.services.dot_core_client')
    def test_dot_core_internal_error(self, mock_dot_core_client, mock_upload_selfie_image):
        configs = {}
        image = ImageFactory()
        # internal error
        mock_upload_selfie_image.return_value = image
        mock_dot_core_client.check_passive_liveness.side_effect = DotCoreServerError(
            {'response': {'error_code': 'error'}, 'elapsed': 10}
        )
        result, data = detect_face(self.liveness_detection, '', configs, self.application.id)
        self.assertEqual(result, 'error')

    @patch('juloserver.liveness_detection.services.upload_selfie_image')
    @patch('juloserver.liveness_detection.services.dot_core_client')
    def test_dot_core_internal_failed(self, mock_dot_core_client, mock_upload_selfie_image):
        configs = {'score_threshold': 1}
        image = ImageFactory()
        mock_upload_selfie_image.return_value = image
        # dot core server response incorrect format
        vendor_result = PassiveLivenessVendorResultFactory()
        mock_dot_core_client.check_passive_liveness.return_value = {}, 10, vendor_result
        result, data = detect_face(self.liveness_detection, '', configs, self.application.id)
        self.assertEqual(result, 'failed')
        # failed
        application = ApplicationFactory()
        image = ImageFactory()
        mock_upload_selfie_image.return_value = image
        vendor_result = PassiveLivenessVendorResultFactory()
        mock_dot_core_client.check_passive_liveness.return_value = (
            {'faces': [{'faceAttributes': {'passiveLiveness': {'score': 0.99}}}]},
            10,
            vendor_result,
        )
        result, data = detect_face(self.liveness_detection, '', configs, self.application.id)
        self.assertEqual(result, 'failed')

    @patch('juloserver.liveness_detection.services.upload_selfie_image')
    @patch('juloserver.liveness_detection.services.dot_core_client')
    def test_success(self, mock_dot_core_client, mock_upload_selfie_image):
        application = ApplicationFactory(customer=self.customer)
        configs = {'score_threshold': -1}
        image = ImageFactory()
        mock_upload_selfie_image.return_value = image
        vendor_result = PassiveLivenessVendorResultFactory()
        mock_dot_core_client.check_passive_liveness.return_value = (
            {'faces': [{'faceAttributes': {'passiveLiveness': {'score': 0.0}}}]},
            10,
            vendor_result,
        )
        result, data = detect_face(self.liveness_detection, '', configs, self.application.id)
        self.assertEqual(result, 'success')


class TestCheckApplicationLivenessResult(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.image = File(
            file=io.BytesIO(b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01"), name='test'
        )
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

    def test_active_liveness_failed(self):
        active_liveness_detection = ActiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='failed'
        )
        passive_liveness_detection = PassiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='success'
        )

        result, change_reason = check_application_liveness_detection_result(self.application)
        self.assertEqual((result, change_reason), (False, 'failed active liveness'))

    def test_passive_liveness_failed(self):
        active_liveness_detection = ActiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='success'
        )
        passive_liveness_detection = PassiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='failed'
        )

        result, change_reason = check_application_liveness_detection_result(self.application)
        self.assertEqual((result, change_reason), (False, 'failed passive liveness'))

    def test_both_failed(self):
        active_liveness_detection = ActiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='failed'
        )
        passive_liveness_detection = PassiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='failed'
        )

        result, change_reason = check_application_liveness_detection_result(self.application)
        self.assertEqual(
            (result, change_reason), (False, 'failed active liveness and failed passive liveness')
        )

    def test_all_failed(self):
        active_liveness_detection = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status='failed',
            video_injection='video_injected',
        )
        passive_liveness_detection = PassiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='failed'
        )

        result, change_reason = check_application_liveness_detection_result(self.application)
        self.assertEqual(
            (result, change_reason),
            (
                False,
                'failed active liveness and failed passive liveness and failed video injection',
            ),
        )

    def test_success(self):
        active_liveness_detection = ActiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='success'
        )
        passive_liveness_detection = PassiveLivenessDetectionFactory(
            customer=self.customer, application=self.application, status='success'
        )

        result, change_reason = check_application_liveness_detection_result(self.application)
        self.assertEqual(result, True)


class TestGetLivenessConfigStatus(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

    def test_pre_check_liveness_failed(self):
        self.application.application_status_id = 100
        self.application.save()
        result = pre_check_liveness(self.customer)
        self.assertEqual({'active_liveness': False, 'passive_liveness': False}, result)
        self.assertIsNotNone(ActiveLivenessDetection.objects.get(customer=self.customer))
        self.assertIsNotNone(PassiveLivenessDetection.objects.get(customer=self.customer))
        # application is not J1
        workflow = WorkflowFactory(name='FakeWorkflow', handler='FakeWorkflowHandler')
        application = ApplicationFactory(workflow=workflow)
        application.application_status_id = 100
        application.save()
        result = pre_check_liveness(application.customer)
        self.assertEqual({'active_liveness': False, 'passive_liveness': False}, result)

    def test_pre_check_liveness_success(self):
        FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'active_liveness': {
                    'is_active': True,
                    'application_eyes_detection_retry': 2,
                    'application_face_detection_retry': 2,
                    'application_face_detection_counter': 10,
                    'retry': 2,
                    'valid_segment_count': 4,
                },
                'passive_liveness': {
                    'is_active': True,
                },
            },
        )
        result = pre_check_liveness(self.customer)
        self.assertEqual(
            {
                'active_liveness': True,
                'passive_liveness': True,
                'application_eyes_detection_retry': 2,
                'application_face_detection_retry': 2,
                'application_face_detection_counter': 10,
                'active_liveness_retry': 2,
                'valid_segment_count': 4,
            },
            result,
        )
        self.assertIsNone(ActiveLivenessDetection.objects.get_or_none(customer=self.customer))
        self.assertIsNone(PassiveLivenessDetection.objects.get_or_none(customer=self.customer))

    def test_pre_check_liveness_skip_customer(self):
        FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'active_liveness': {
                    'is_active': True,
                    'application_eyes_detection_retry': 2,
                    'application_face_detection_retry': 2,
                    'application_face_detection_counter': 10,
                    'retry': 2,
                    'valid_segment_count': 4,
                },
                'passive_liveness': {
                    'is_active': True,
                },
            },
        )
        result = pre_check_liveness(self.customer, skip_customer=True)
        self.assertEqual(
            {
                'active_liveness': True,
                'passive_liveness': True,
                'application_eyes_detection_retry': 2,
                'application_face_detection_retry': 2,
                'application_face_detection_counter': 10,
                'active_liveness_retry': 2,
                'valid_segment_count': 4,
            },
            result,
        )
        liveness_detection_record = ActiveLivenessDetection.objects.filter(
            customer=self.customer
        ).last()
        self.assertIsNotNone(liveness_detection_record)
        self.assertIsNone(PassiveLivenessDetection.objects.get_or_none(customer=self.customer))

        # test_max_retry
        liveness_detection_record.update_safely(status='failed', attempt=2)
        result = pre_check_liveness(self.customer, skip_customer=True)
        self.assertEqual(
            {
                'active_liveness': True,
                'passive_liveness': True,
                'application_eyes_detection_retry': 2,
                'application_face_detection_retry': 2,
                'application_face_detection_counter': 10,
                'active_liveness_retry': 2,
                'valid_segment_count': 4,
            },
            result,
        )
        liveness_detection_record = ActiveLivenessDetection.objects.last()
        self.assertEqual(liveness_detection_record.status, 'skipped_customer')

    def test_skip_for_appversion(self):
        FeatureSettingFactory(
            feature_name='liveness_detection',
            is_active=True,
            parameters={
                'app_version_to_skip': '1.0.0',
                'active_liveness': {
                    'is_active': True,
                    'application_eyes_detection_retry': 2,
                    'application_face_detection_retry': 2,
                    'application_face_detection_counter': 10,
                },
                'passive_liveness': {
                    'is_active': True,
                },
            },
        )
        result = pre_check_liveness(self.customer, app_version='1.0.0')
        self.assertEqual(
            {
                'active_liveness': False,
                'passive_liveness': False,
            },
            result,
        )
        self.assertIsNotNone(ActiveLivenessDetection.objects.get_or_none(customer=self.customer))
        self.assertIsNotNone(PassiveLivenessDetection.objects.get_or_none(customer=self.customer))


@override_settings(LIVENESS_LICENSE_KEY='6QK1EjFArqnoQSs_djWlyEZWd1F2fTbs-gboj9GjaZ0=')
class TestGetLivenessLicenseConfig(TestCase):
    def setUp(self) -> None:
        self.license = {
            "version": "2.1",
            "contract": {
                "customer": "julo",
                "expiration": {"day": 22, "month": 1, "year": 2022},
                "hwids": ["ewqeqwewqeqweqw"],
                "products": ["iface"],
                "idkit": {"database_size": 0, "max_client_connections": 0},
            },
            "contract_signature": "ewqeqweqweqweqwewq",
        }

    def test_license_not_found(self):
        result = get_android_app_license(is_encrypted=True)
        self.assertIsNone(result)

    def test_success(self):
        FeatureSettingFactory(
            feature_name='liveness_detection_android_license',
            is_active=True,
            parameters=self.license,
        )
        # no encryption
        result = get_android_app_license()
        self.assertEqual(result, self.license)

        # with ecryption
        result = get_android_app_license(is_encrypted=True)
        self.assertNotEqual(result, self.license)


class TestGetActiveLiveness(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()

    def test_not_found(self):
        result = get_active_liveness_info(self.customer)
        self.assertIsNone(result)
        application = ApplicationFactory(customer=self.customer)
        result = get_active_liveness_info(self.customer)
        self.assertIsNone(result)

    def test_success(self):
        application = ApplicationFactory(customer=self.customer)
        liveness_detection = ActiveLivenessDetectionFactory(
            customer=self.customer, application=application
        )
        result = get_active_liveness_info(self.customer)
        self.assertIsNotNone(result)


class TestStartActiveLiveness(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()

    def test_not_found(self):
        result, data = start_active_liveness_process(self.customer)
        self.assertEqual(result, 'active_liveness_not_found')

    def test_success(self):
        liveness_detection = ActiveLivenessDetectionFactory(customer=self.customer)
        result, data = start_active_liveness_process(self.customer)
        self.assertEqual(result, 'started')
        liveness_detection.refresh_from_db()
        self.assertEqual(liveness_detection.status, 'started')
