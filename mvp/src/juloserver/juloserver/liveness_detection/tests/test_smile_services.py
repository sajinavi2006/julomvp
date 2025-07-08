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
from juloserver.liveness_detection.smile_liveness_services import (
    detect_liveness,
    pre_check_liveness,
    get_liveness_info,
    start_liveness_process,
    get_liveness_detection_result,
)
from juloserver.liveness_detection.models import ActiveLivenessDetection, PassiveLivenessDetection


class TestCheckSmileLiveness(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.image = File(
            file=io.BytesIO(b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x01\x01"), name='test'
        )
        self.workflow = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.application.application_status_id = 100
        self.application.save()
        self.feature_settings = FeatureSettingFactory(
            feature_name=FeatureNameConst.SMILE_LIVENESS_DETECTION,
            is_active=True,
            parameters={
                'web': {
                    'skip_application_failed': True,
                    'passive_threshold': 0.8,
                    'smile_threshold': 1.0,
                    'timeout_retry': 2,
                    'timeout': 5,
                    'retry': 3,
                    'is_active': True,
                },
                'android': {
                    'skip_application_failed': True,
                    'passive_threshold': 0.8,
                    'smile_threshold': 1.0,
                    'timeout_retry': 2,
                    'timeout': 5,
                    'retry': 3,
                    'is_active': True,
                },
            },
        )
        self.configs = self.feature_settings.parameters.get('web', {})

    def _mock_ddis_client(
        self,
        mock_service,
        mock_get_api_info=True,
        mock_create_customer=True,
        mock_create_customer_selfie=True,
        mock_create_customer_liveness=True,
        mock_upload_neutral_image=True,
        mock_upload_passive_image=True,
        mock_upload_smile_image=True,
        mock_evaluate_smile=True,
        mock_evaluate_passive=True,
        mock_delete_customer=True,
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
        if mock_upload_neutral_image:
            mock_service.upload_neutral_image.return_value = {}, 0
        if mock_upload_passive_image:
            mock_service.upload_passive_image.return_value = {}, 0
        if mock_upload_smile_image:
            mock_service.upload_smile_image.return_value = {}, 0
        if mock_evaluate_smile:
            mock_service.evaluate_smile.return_value = {}, 0
        if mock_evaluate_passive:
            mock_service.evaluate_passive.return_value = {}, 0
        if mock_delete_customer:
            mock_service.delete_customer.return_value = {}, 0

    def test_application_not_found(self):
        customer = CustomerFactory()
        result, data = detect_liveness(customer, [])
        self.assertEqual(result, 'application_not_found')

    def test_liveness_detection_not_found(self):
        result, data = detect_liveness(self.customer, [])

        self.assertEqual(result, 'smile_liveness_not_found')

    def test_max_retry(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            attempt=3,
            configs=self.configs,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            attempt=3,
            configs=self.configs,
            client_type='web',
        )
        result, data = detect_liveness(self.customer, [])
        self.assertEqual(result, 'limit_exceeded')

    def test_feature_is_off(self):
        self.feature_settings.is_active = False
        self.feature_settings.update_safely(
            parameters={
                'web': {
                    'skip_application_failed': True,
                    'passive_threshold': 0.8,
                    'smile_threshold': 1.0,
                    'timeout_retry': 2,
                    'timeout': 5,
                    'retry': 3,
                    'is_active': False,
                },
                'android': {
                    'skip_application_failed': True,
                    'passive_threshold': 0.8,
                    'smile_threshold': 1.0,
                    'timeout_retry': 2,
                    'timeout': 5,
                    'retry': 3,
                    'is_active': False,
                },
            },
        )
        self.configs = self.feature_settings.parameters.get('web', {})
        active_liveness_detection = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            attempt=1,
            configs=self.configs,
            client_type='web',
        )
        passive_liveness_detection = PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            attempt=1,
            configs=self.configs,
            client_type='web',
        )
        # max retry but the feature is off
        result, data = detect_liveness(self.customer, [])
        self.assertEqual(result, 'feature_is_off')

    def test_application_failed(self):
        self.feature_settings.is_active = False
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        result, data = detect_liveness(self.customer, [], application_failed=True)
        self.assertEqual(result, 'application_detect_failed')

    def test_incorrect_images(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        images = [
            {'image': None, 'type': 'neutral', 'value_type': 'file'},
            {'image': self.image, 'type': 'smile', 'value_type': 'file'},
        ]
        result, data = detect_liveness(self.customer, images)
        self.assertEqual(result, 'smile_image_incorrect')

    @patch('juloserver.liveness_detection.smile_liveness_services.upload_selfie_image')
    @patch('juloserver.liveness_detection.smile_liveness_services.get_dot_digital_identity_client')
    def test_dot_core_internal_error(self, mock_ddis_client, mock_upload_selfie_image):
        self.feature_settings.is_active = False
        at = ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        ps = PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        images = [
            {'image': self.image, 'type': 'neutral', 'value_type': 'file'},
            {'image': self.image, 'type': 'smile', 'value_type': 'file'},
        ]
        image = ImageFactory()
        # internal error
        mock_upload_selfie_image.return_value = image
        mock_ddis_client().get_api_info.side_effect = DotServerError(
            {'response': {'error_code': 'error'}, 'elapsed': 10}
        )
        result, data = detect_liveness(self.customer, images)
        self.assertEqual(result, 'error')

        # retry after error
        at.refresh_from_db()
        ps.refresh_from_db()
        self.feature_settings.is_active = True
        result, data = detect_liveness(self.customer, images)
        self.assertEqual(result, 'error')

    @patch('juloserver.liveness_detection.smile_liveness_services.upload_selfie_image')
    @patch('juloserver.liveness_detection.smile_liveness_services.get_dot_digital_identity_client')
    def test_dot_core_internal_failed(self, mock_ddis_client, mock_upload_selfie_image):
        self.feature_settings.is_active = False
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        images = [
            {'image': self.image, 'type': 'neutral', 'value_type': 'file'},
            {'image': self.image, 'type': 'smile', 'value_type': 'file'},
        ]
        image = ImageFactory()
        mock_upload_selfie_image.return_value = image
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        active_liveness_vendor_result = ActiveLivenessVendorResultFactory()
        # dot core server response incorrect format
        self._mock_ddis_client(mock_ddis_client())
        mock_ddis_client().active_vendor_result = active_liveness_vendor_result
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        result, data = detect_liveness(self.customer, images)
        self.assertEqual(result, 'failed')

        # failed
        self.feature_settings.is_active = True
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        active_liveness_vendor_result = ActiveLivenessVendorResultFactory()
        mock_ddis_client().get_api_info.return_value = {'build': {'version': '1.0'}}, 0
        mock_ddis_client().create_customer.return_value = {
            'id': 'eb49ec95-07f7-4ff4-8d81-a3f274198a9f',
            'links': {'self': '/api/v1/customers/eb49ec95-07f7-4ff4-8d81-a3f274198a9f'},
        }, 0
        self._mock_ddis_client(
            mock_ddis_client(), mock_evaluate_smile=False, mock_evaluate_passive=False
        )
        mock_ddis_client().evaluate_smile.return_value = {'score': 0.5}, 0
        mock_ddis_client().evaluate_passive.return_value = {'score': 0.5}, 0
        mock_ddis_client().active_vendor_result = active_liveness_vendor_result
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        result, data = detect_liveness(self.customer, images)
        self.assertEqual(result, 'failed')

    @patch('juloserver.liveness_detection.smile_liveness_services.upload_selfie_image')
    @patch('juloserver.liveness_detection.smile_liveness_services.get_dot_digital_identity_client')
    def test_success(self, mock_ddis_client, mock_upload_selfie_image):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        images = [
            {'image': self.image, 'type': 'neutral', 'value_type': 'file'},
            {'image': self.image, 'type': 'smile', 'value_type': 'file'},
        ]
        image = ImageFactory()
        mock_upload_selfie_image.return_value = image
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        active_liveness_vendor_result = ActiveLivenessVendorResultFactory()
        # dot core server response incorrect format
        self._mock_ddis_client(
            mock_ddis_client(), mock_evaluate_smile=False, mock_evaluate_passive=False
        )
        mock_ddis_client().evaluate_smile.return_value = {'score': 1.0}, 0
        mock_ddis_client().evaluate_passive.return_value = {'score': 1.0}, 0
        mock_ddis_client().active_vendor_result = active_liveness_vendor_result
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        result, data = detect_liveness(self.customer, images)
        self.assertEqual(result, 'success')

    @patch('juloserver.liveness_detection.smile_liveness_services.get_file_from_oss')
    @patch('juloserver.liveness_detection.smile_liveness_services.get_dot_digital_identity_client')
    def test_detect_passive_only(self, mock_ddis_client, mock_get_file_from_oss):
        self.feature_settings.is_active = False
        # failed
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            configs=self.configs,
            client_type='web',
        )
        selfie_image = ImageFactory()
        images = [
            {'image': selfie_image.id, 'type': 'selfie', 'value_type': 'uploaded_id'},
        ]
        mock_get_file_from_oss.return_value = self.image
        passive_liveness_vendor_result = PassiveLivenessVendorResultFactory()
        # dot core server response incorrect format
        self._mock_ddis_client(
            mock_ddis_client(),
            mock_evaluate_smile=False,
            mock_evaluate_passive=False,
            mock_upload_smile_image=False,
            mock_upload_neutral_image=False,
        )
        mock_ddis_client().evaluate_passive.return_value = {'score': 0.5}, 0
        mock_ddis_client().passive_vendor_result = passive_liveness_vendor_result
        result, data = detect_liveness(
            self.customer, images, check_passive=True, check_active=False
        )
        self.assertEqual(result, 'failed')

        # success
        self.feature_settings.is_active = True
        mock_ddis_client().evaluate_passive.return_value = {'score': 1.0}, 0
        result, data = detect_liveness(
            self.customer, images, check_passive=True, check_active=False
        )
        self.assertEqual(result, 'success')


class TestPreCheck(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    def _create_feature_setting(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SMILE_LIVENESS_DETECTION,
            is_active=True,
            parameters={
                'web': {
                    'skip_application_failed': True,
                    'passive_threshold': 0.8,
                    'smile_threshold': 1.0,
                    'timeout_retry': 2,
                    'timeout': 5,
                    'retry': 3,
                    'is_active': True,
                },
                'android': {
                    'skip_application_failed': True,
                    'passive_threshold': 0.8,
                    'smile_threshold': 1.0,
                    'timeout_retry': 2,
                    'timeout': 5,
                    'retry': 3,
                    'is_active': True,
                },
            },
        )

    def test_application_invalid(self):
        result = pre_check_liveness(self.customer, 'Web')
        self.assertEqual(
            {'active_liveness': False, 'passive_liveness': False, 'liveness_retry': None}, result
        )
        self.assertIsNone(ActiveLivenessDetection.objects.get_or_none(customer=self.customer))
        self.assertIsNone(PassiveLivenessDetection.objects.get_or_none(customer=self.customer))

    def test_feature_off(self):
        self.application.application_status_id = 100
        self.application.save()
        result = pre_check_liveness(self.customer, 'Web')
        self.assertEqual(
            {'active_liveness': False, 'passive_liveness': False, 'liveness_retry': None}, result
        )

        active_liveness_detection = ActiveLivenessDetection.objects.get(customer=self.customer)
        passive_liveness_detection = PassiveLivenessDetection.objects.get(customer=self.customer)
        self.assertEqual(active_liveness_detection.status, 'feature_is_off')
        self.assertEqual(passive_liveness_detection.status, 'feature_is_off')

    def test_pre_check_liveness_success(self):
        self._create_feature_setting()
        self.application.application_status_id = 100
        self.application.save()
        result = pre_check_liveness(self.customer, 'web')
        self.assertEqual(
            {'active_liveness': True, 'passive_liveness': True, 'liveness_retry': 3},
            result,
        )
        active_liveness_detection = ActiveLivenessDetection.objects.get(customer=self.customer)
        passive_liveness_detection = PassiveLivenessDetection.objects.get(customer=self.customer)
        self.assertEqual(active_liveness_detection.status, 'initial')
        self.assertEqual(passive_liveness_detection.status, 'initial')

    def test_skip_for_customer(self):
        self._create_feature_setting()
        self.application.application_status_id = 100
        self.application.save()
        result = pre_check_liveness(self.customer, 'web', skip_customer=True)
        self.assertEqual(
            {'active_liveness': True, 'passive_liveness': True, 'liveness_retry': 3},
            result,
        )
        active_liveness_detection = ActiveLivenessDetection.objects.get(customer=self.customer)
        passive_liveness_detection = PassiveLivenessDetection.objects.get(customer=self.customer)
        self.assertEqual(active_liveness_detection.status, 'skipped_customer')
        self.assertEqual(passive_liveness_detection.status, 'skipped_customer')


class TestGetLivenessInfo(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    def test_not_found(self):
        self.assertEqual(
            get_liveness_info(self.customer),
            {'active_liveness_detection': None, 'passive_liveness_detection': None},
        )

    def test_success(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.STARTED,
            client_type='web',
        )
        self.assertEqual(
            get_liveness_info(self.customer),
            {
                'active_liveness_detection': {
                    'status': 'started',
                    'attempt': 0,
                    'max_attempt': 0,
                    'error_code': None,
                },
                'passive_liveness_detection': {
                    'status': 'started',
                    'attempt': 0,
                    'max_attempt': 0,
                    'error_code': None,
                },
            },
        )


class TestStartLivenessProgress(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    def test_not_found(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.FAILED,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.FAILED,
            client_type='web',
        )
        self.assertEqual(
            start_liveness_process(self.customer),
            ('smile_liveness_not_found', 'Liveness detection not found'),
        )

    def test_already_attempted(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.FAILED,
            attempt=1,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.FAILED,
            attempt=1,
            client_type='web',
        )
        self.assertEqual(start_liveness_process(self.customer), ('started', 'Started'))

    def test_success(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.INITIAL,
            attempt=1,
            client_type='web',
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer,
            application=self.application,
            status=LivenessCheckStatus.INITIAL,
            attempt=1,
            client_type='web',
        )
        self.assertEqual(start_liveness_process(self.customer), ('started', 'Started'))


class TestGetLivenessDetectionResult(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    def test_success(self):
        ActiveLivenessDetectionFactory(
            customer=self.customer, status='passed', application=self.application
        )
        PassiveLivenessDetectionFactory(
            customer=self.customer, status='passed', application=self.application
        )
        result = get_liveness_detection_result(
            self.application, check_active=True, check_passive=True
        )
        self.assertEqual(result, True)

    def test_failed(self):
        active_detection = ActiveLivenessDetectionFactory(
            customer=self.customer, status='failed', application=self.application
        )
        passive_detection = PassiveLivenessDetectionFactory(
            customer=self.customer, status='failed', application=self.application
        )
        result = get_liveness_detection_result(
            self.application, check_active=True, check_passive=True
        )
        self.assertEqual(result, False)

        # not enough retry
        active_detection.update_safely(refresh=False, status='error', configs={'retry': 3})
        passive_detection.update_safely(refresh=False, status='error', configs={'retry': 3})
        result = get_liveness_detection_result(
            self.application, check_active=True, check_passive=True
        )
        self.assertEqual(result, False)

        # enough retry
        active_detection.update_safely(refresh=False, status='error', attempt=3)
        passive_detection.update_safely(refresh=False, status='error', attempt=3)
        result = get_liveness_detection_result(
            self.application, check_active=True, check_passive=True
        )
        self.assertEqual(result, True)
