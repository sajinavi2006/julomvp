import logging
import time

from django.db import transaction
from django.core.files.uploadedfile import TemporaryUploadedFile

from rest_framework.status import HTTP_401_UNAUTHORIZED, HTTP_404_NOT_FOUND

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import ApplicationStatusCodes, FeatureNameConst
from juloserver.julo.models import Application, FeatureSetting, Customer
from juloserver.liveness_detection.exceptions import (
    DotClientError,
    DotClientInternalError,
    DotServerError,
    DotServerTimeout,
)
from juloserver.liveness_detection.clients import (
    get_dot_digital_identity_client,
    DotDigitalIdentityClient,
)
from juloserver.liveness_detection.constants import (
    ActiveLivenessCheckMessage,
    LivenessCheckResponseStatus,
    LivenessCheckStatus,
    SmileLivenessCheckMessage,
    ServiceCheckType,
    NewLivenessImage,
)
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
)
from juloserver.liveness_detection.constants import (
    ActiveLivenessMethod,
    NewLivenessCheckMessage,
    InspectCustomerResult,
)
from juloserver.face_recognition.services import (
    upload_selfie_image,
    convert_temporary_to_inmem_file,
)

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class DotDigitalIdentityService:
    def __init__(
        self,
        ddis_client: DotDigitalIdentityClient,
        configs: dict,
        active_liveness_detection: ActiveLivenessDetection,
        passive_liveness_detection: PassiveLivenessDetection = None,
        record=None,
    ):
        self.configs = configs
        self.active_liveness_detection = active_liveness_detection
        self.passive_liveness_detection = passive_liveness_detection
        self.ddis_client = ddis_client
        self.ddis_customer = (
            self.active_liveness_detection.internal_customer_id
            if self.active_liveness_detection
            else None
        )
        self.ddis_client.customer_id = self.ddis_customer
        self.exception_raised = False
        self.update_active_data = {}
        self.update_passive_data = {}
        self.current_detect_status = None
        self.record = record
        self.fresh_process = True
        self.record_selfie_origin_link = None
        self.selfie_origin_link = None

    def _call_api(self, function_call: callable, parameters: dict) -> tuple:
        logger.info(
            'trigger_{}|active_liveness_detection={}, passive_liveness_detection={}, '
            'ddis_customer={}'.format(
                function_call,
                self.active_liveness_detection,
                self.passive_liveness_detection,
                self.ddis_customer,
            )
        )
        try:
            return function_call(**parameters)
        except (
            DotServerError,
            DotServerTimeout,
            DotClientInternalError,
            DotClientError,
        ) as error:
            sentry_client.captureException()
            self.exception_raised = True
            (message,) = error.args
            error_code = None
            elapsed = None
            status = LivenessCheckStatus.ERROR
            if isinstance(error, (DotServerError, DotClientError)):
                elapsed = message['elapsed']
                error_code = message['response'].get('errorCode')
                if isinstance(error, DotClientError):
                    if int(message['status']) != HTTP_401_UNAUTHORIZED:
                        status = LivenessCheckStatus.FAILED
                    if not self.fresh_process and int(message['status']) != HTTP_404_NOT_FOUND:
                        status = LivenessCheckStatus.FAILED
                        # {'errorCode': 'NOT_FOUND', 'errorMessage': 'Customer was not found.'}
            elif isinstance(error, DotServerTimeout):
                status = LivenessCheckStatus.TIMEOUT
            self.current_detect_status = status
            self.error_code = error_code
            self.elapsed = elapsed

        return None, None

    def get_api_info(self):
        server_info, _ = self._call_api(self.ddis_client.get_api_info, {})
        if self.exception_raised:
            self._capture_exception_data()
            return False
        try:
            api_version = server_info.get('build', {}).get('version', 'can not get the version')
        except Exception:
            sentry_client.captureException()
            self.current_detect_status = LivenessCheckStatus.ERROR
            if self.active_liveness_detection:
                self.update_active_data.update(
                    status=LivenessCheckStatus.ERROR,
                    error_code=server_info.get('errorCode', 'incorrect_data'),
                )
            if self.passive_liveness_detection:
                self.update_passive_data.update(
                    status=LivenessCheckStatus.ERROR,
                    error_code=server_info.get('errorCode', 'incorrect_data'),
                )
            return False
        if self.active_liveness_detection:
            self.update_active_data.update(api_version=api_version)
        if self.passive_liveness_detection:
            self.update_active_data.update(api_version=api_version)

        return True

    def create_customer(self):
        customer_result, _ = self._call_api(self.ddis_client.create_customer, {})
        if self.exception_raised:
            self._capture_exception_data()
            return False
        try:
            self.ddis_customer = customer_result['id']
        except (KeyError, ValueError):
            self.current_detect_status = LivenessCheckStatus.ERROR
            sentry_client.captureException()
            if self.active_liveness_detection:
                self.update_active_data.update(
                    status=LivenessCheckStatus.ERROR,
                    error_code=customer_result.get('errorCode', 'incorrect_data'),
                )
            if self.passive_liveness_detection:
                self.update_passive_data.update(
                    status=LivenessCheckStatus.ERROR,
                    error_code=customer_result.get('errorCode', 'incorrect_data'),
                )
            return False

        return True

    def create_customer_selfie(self):
        customer_selfie_result, elapsed = self._call_api(
            self.ddis_client.create_customer_selfie,
            {'selfie_origin_link': self.record_selfie_origin_link},
        )
        if self.exception_raised:
            self._capture_exception_data()
            return False

        try:
            self.selfie_origin_link = customer_selfie_result['links']['self']
        except (KeyError, ValueError) as e:
            logger.error(
                'liveness_detection_create_customer_selfie_error|'
                'customer_id={}, error={}, result={}'.format(
                    self.ddis_customer, str(e), customer_selfie_result
                )
            )
            self.exception_raised = True
            status = LivenessCheckStatus.ERROR
            error_code = customer_selfie_result.get('errorCode', 'incorrect_data')
            warnings = customer_selfie_result.get('warnings', [])
            if error_code == 'INVALID_DATA':
                status = LivenessCheckStatus.FAILED
            elif warnings:
                status = LivenessCheckStatus.FAILED

            self.current_detect_status = status
            self.error_code = error_code
            self.elapsed = elapsed
            self._capture_exception_data()

            return False

        return True

    def provide_customer_liveness_selfie(self):
        self._call_api(
            self.ddis_client.provide_customer_liveness_selfie,
            {'selfie_origin_link': self.selfie_origin_link},
        )
        if self.exception_raised:
            self._capture_exception_data()
            return False

        return True

    def create_customer_liveness(self):
        self._call_api(self.ddis_client.create_customer_liveness, {})
        if self.exception_raised:
            self._capture_exception_data()
            return False

        return True

    def _capture_exception_data(self):
        if self.exception_raised:
            if self.active_liveness_detection:
                self.update_active_data.update(
                    status=self.current_detect_status, error_code=self.error_code
                )
            if self.passive_liveness_detection:
                self.update_passive_data.update(
                    status=self.current_detect_status,
                    error_code=self.error_code,
                    score=None,
                )

    def init_customer_process(self):
        if not self.get_api_info():
            return False

        if not self.create_customer():
            return False

        self.ddis_client.customer_id = self.ddis_customer
        self.update_active_data['internal_customer_id'] = self.ddis_customer

        if not self.create_customer_liveness():
            return False

        return True

    def generate_challenge(self):
        if not self.init_customer_process():
            return False, None

        challenge, _ = self._call_api(
            self.ddis_client.generate_challenge,
            {'active_type': ActiveLivenessMethod.EYE_GAZE.value},
        )
        if self.exception_raised:
            self._capture_exception_data()
            return False, None

        return True, {
            'internal_customer_id': self.ddis_customer,
            'sequence': challenge['details']['corners'],
        }

    def upload_record(self, record):
        """submit binary record to evaluate all liveness method and video injection"""
        result, elapsed = self._call_api(self.ddis_client.upload_record, {'record': record})
        if self.exception_raised:
            self._capture_exception_data()
            return False

        try:
            self.record_selfie_origin_link = result['links']['selfie']
        except KeyError as e:
            logger.error(
                'liveness_detection_upload_record_error|'
                'customer_id={}, error={}, result={}'.format(self.ddis_customer, str(e), result)
            )
            self.exception_raised = True
            status = LivenessCheckStatus.ERROR
            error_code = result.get('errorCode', 'incorrect_data')
            if error_code == 'INVALID_DATA':
                status = LivenessCheckStatus.FAILED
            self.current_detect_status = status
            self.error_code = error_code
            self.elapsed = elapsed

            return False

        return result

    def check_active_liveness(self, active_method) -> tuple:
        # evaluate
        ddis_client_evaluate_method = None
        if active_method == ActiveLivenessMethod.EYE_GAZE.value:
            ddis_client_evaluate_method = self.ddis_client.evaluate_eye_gaze
        if active_method == ActiveLivenessMethod.MAGNIFEYE.value:
            ddis_client_evaluate_method = self.ddis_client.evaluate_magnifeye
        if active_method == ActiveLivenessMethod.SMILE.value:
            ddis_client_evaluate_method = self.ddis_client.evaluate_smile

        evaluate_result, _ = self._call_api(ddis_client_evaluate_method, {})
        if self.exception_raised:
            self._capture_exception_data()
            return False, None

        if self.ddis_client.active_vendor_result:
            self.update_active_data.update(
                liveness_vendor_result=self.ddis_client.active_vendor_result
            )

        if evaluate_result.get('score') is None:
            self.current_detect_status = LivenessCheckStatus.FAILED
            error_message = 'check_active_liveness_error_incorrect_data|response={}'.format(
                evaluate_result
            )
            logger.warning(error_message)
            self.update_active_data.update(
                status=LivenessCheckStatus.FAILED,
                error_code=evaluate_result.get('errorCode', 'incorrect_data'),
            )
            self.update_passive_data.update(
                status=LivenessCheckStatus.FAILED,
                error_code=evaluate_result.get('errorCode', 'incorrect_data'),
                score=None,
            )
            return False, None

        active_threshold = None
        if active_method == ActiveLivenessMethod.EYE_GAZE.value:
            active_threshold = self.configs['eye_gaze_threshold']
        if active_method == ActiveLivenessMethod.MAGNIFEYE.value:
            active_threshold = self.configs['magnifeye_threshold']
        if active_method == ActiveLivenessMethod.SMILE.value:
            active_threshold = self.configs['smile_threshold']

        if evaluate_result['score'] < active_threshold:
            self.update_active_data.update(
                status=LivenessCheckStatus.FAILED,
                score=evaluate_result['score'],
            )
            return True, evaluate_result['score']
        self.update_active_data.update(
            status=LivenessCheckStatus.PASSED,
            score=evaluate_result['score'],
        )
        return True, evaluate_result['score']

    def check_passive_liveness(self) -> tuple:
        self.create_customer_selfie()
        if self.exception_raised:
            self._capture_exception_data()
            return False, None

        self.provide_customer_liveness_selfie()
        if self.exception_raised:
            self._capture_exception_data()
            return False, None

        evaluate_result, _ = self._call_api(self.ddis_client.evaluate_passive, {})
        if self.exception_raised:
            self._capture_exception_data()
            return False, None

        if self.ddis_client.passive_vendor_result:
            self.update_passive_data.update(
                liveness_vendor_result=self.ddis_client.passive_vendor_result
            )
        if evaluate_result.get('score') is None:
            error_message = 'check_passive_liveness_error_incorrect_data|response={}'.format(
                evaluate_result
            )
            logger.warning(error_message)
            self.current_detect_status = LivenessCheckStatus.FAILED
            self.update_passive_data.update(
                status=self.current_detect_status,
                error_code=evaluate_result.get('errorCode', 'incorrect_data'),
                score=None,
            )
            self.update_active_data.update(
                status=self.current_detect_status,
                error_code=evaluate_result.get('errorCode', 'incorrect_data'),
            )
            return False, None

        if evaluate_result['score'] < self.configs['passive_threshold']:
            self.update_passive_data.update(
                status=LivenessCheckStatus.FAILED,
                score=evaluate_result['score'],
                error_code=evaluate_result.get('errorCode'),
            )
            return True, evaluate_result['score']

        self.update_passive_data.update(
            status=LivenessCheckStatus.PASSED, score=evaluate_result['score'], error_code=None
        )
        return True, evaluate_result['score']

    def inspect_customer(self):
        inspect_result, _ = self._call_api(self.ddis_client.inspect_customer, {})
        if self.exception_raised or not inspect_result:
            logger.info('inspect_customer_exception_raised')
            return False, None

        result = inspect_result.get('security', {}).get('videoInjection', {}).get('detected')
        if result is None:
            error_message = 'inspect_customer_error_incorrect_data|response={}'.format(
                inspect_result
            )
            logger.warning(error_message)
            self.active_liveness_detection.update_safely(
                video_injection=InspectCustomerResult.SERVER_ERROR.value
            )
            return False, None

        if not result:
            video_injection = InspectCustomerResult.NOT_VIDEO_INJECTED.value
        else:
            video_injection = InspectCustomerResult.VIDEO_INJECTED.value

        self.active_liveness_detection.update_safely(video_injection=video_injection)
        return True, video_injection

    def check_liveness(
        self,
        record: bytes,
        check_passive: bool = False,
        active_method: str = None,
        fresh_progress: bool = False,
    ) -> bool:
        self.fresh_process = fresh_progress
        if fresh_progress:
            if not self.init_customer_process():
                return False

            if not self.create_customer_liveness():
                return False

        if not self.upload_record(record):
            return False

        smile_score = None
        check_smile = False
        if active_method == ActiveLivenessMethod.SMILE.value:
            check_smile = True
            smile_result, smile_score = self.check_active_liveness(ActiveLivenessMethod.SMILE.value)
            if not smile_result:
                return False

        eye_gaze_score = None
        check_eye_gaze = False
        if active_method == ActiveLivenessMethod.EYE_GAZE.value:
            check_eye_gaze = True
            eye_gaze_result, eye_gaze_score = self.check_active_liveness(
                ActiveLivenessMethod.EYE_GAZE.value
            )
            if not eye_gaze_result:
                return False

        magnif_eye_score = None
        check_magnif_eye = False
        if active_method == ActiveLivenessMethod.MAGNIFEYE.value:
            check_magnif_eye = True
            magnif_eye_result, magnif_eye_score = self.check_active_liveness(
                ActiveLivenessMethod.MAGNIFEYE.value
            )
            if not magnif_eye_result:
                return False

        passive_score = None
        if check_passive:
            passive_result, passive_score = self.check_passive_liveness()
            if not passive_result:
                return False

        self.inspect_customer()
        self._delete_customer()
        result = self.evaluate_final_result(
            check_smile,
            check_passive,
            check_eye_gaze,
            check_magnif_eye,
            smile_score,
            passive_score,
            eye_gaze_score,
            magnif_eye_score,
        )

        return result

    def evaluate_final_result(
        self,
        check_smile: bool,
        check_passive: bool,
        check_eye_gaze: bool,
        check_magnif_eye: bool,
        smile_score: float,
        passive_score: float,
        eye_gaze_score: float,
        magnif_eye_score: float,
    ) -> bool:
        if check_smile and smile_score < self.configs['smile_threshold']:
            self.current_detect_status = LivenessCheckStatus.FAILED
            return False
        if check_passive and passive_score < self.configs['passive_threshold']:
            self.current_detect_status = LivenessCheckStatus.FAILED
            return False
        if check_eye_gaze and eye_gaze_score < self.configs['eye_gaze_threshold']:
            self.current_detect_status = LivenessCheckStatus.FAILED
            return False
        if check_magnif_eye and magnif_eye_score < self.configs['magnifeye_threshold']:
            self.current_detect_status = LivenessCheckStatus.FAILED
            return False

        self.current_detect_status = LivenessCheckStatus.PASSED
        return True

    def _delete_customer(self):
        try:
            self.ddis_client.delete_customer()
        except Exception:
            sentry_client.captureException()


def validate_liveness_status(
    check_active: bool,
    check_passive: bool,
    active_liveness_detection: ActiveLivenessDetection,
    passive_liveness_detection: PassiveLivenessDetection,
) -> bool:
    if check_active and (not active_liveness_detection or not active_liveness_detection.configs):
        return False
    if check_passive and (not passive_liveness_detection or not passive_liveness_detection.configs):
        return False

    valid_started_statuses = [
        LivenessCheckStatus.STARTED,
    ]
    if check_active and check_passive:
        if (
            active_liveness_detection.status == LivenessCheckStatus.STARTED
            and passive_liveness_detection.status != LivenessCheckStatus.STARTED
        ) or (
            passive_liveness_detection.status == LivenessCheckStatus.STARTED
            and active_liveness_detection.status != LivenessCheckStatus.STARTED
        ):
            return False

    if check_active and active_liveness_detection.status not in valid_started_statuses:
        return False

    if check_passive and passive_liveness_detection.status not in valid_started_statuses:
        return False

    return True


def update_liveness_detection(
    active_liveness: ActiveLivenessDetection,
    passive_liveness: PassiveLivenessDetection,
    *args,
    **kwargs
):
    with transaction.atomic():
        if active_liveness:
            active_liveness.update_safely(**kwargs.get('update_active_data', {}))
        if passive_liveness:
            passive_liveness.update_safely(**kwargs.get('update_passive_data', {}))


def map_liveness_check_status_to_response(status: str) -> tuple:
    if status == LivenessCheckStatus.PASSED:
        return LivenessCheckResponseStatus.SUCCESS, SmileLivenessCheckMessage.SUCCESS
    if status == LivenessCheckStatus.FAILED:
        return LivenessCheckResponseStatus.FAILED, SmileLivenessCheckMessage.FAILED
    if status in (LivenessCheckStatus.ERROR, LivenessCheckStatus.TIMEOUT):
        return LivenessCheckResponseStatus.ERROR, SmileLivenessCheckMessage.ERROR


def pre_check_liveness(
    customer: Customer,
    client_type: str,
    skip_customer: bool = False,
    check_active: bool = True,
    check_passive=True,
    active_method=None,
) -> dict:
    application = Application.objects.filter(customer=customer).last()
    check_active = True
    check_passive = True
    if not application or application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
        return {
            'active_liveness': False,
            'passive_liveness': False,
            'liveness_retry': None,
            'extra_data': {},
        }

    configs = get_liveness_config(client_type)
    is_active_liveness_active, is_passive_liveness_active = False, False
    if configs:
        is_active_liveness_active, is_passive_liveness_active = True, True

    data = {
        'active_liveness': is_active_liveness_active,
        'passive_liveness': is_passive_liveness_active,
        'liveness_retry': configs.get('retry'),
        'extra_data': {},
    }
    current_active_liveness, current_passive_liveness = None, None
    is_max_retries_passive, is_max_retries_active = False, False
    if check_active:
        current_active_liveness = ActiveLivenessDetection.objects.filter(
            customer=customer, application=application
        ).last()
    if check_passive:
        current_passive_liveness = PassiveLivenessDetection.objects.filter(
            customer=customer, application=application
        ).last()

    if skip_customer:
        update_data = dict(
            customer=customer,
            application=application,
            status=LivenessCheckStatus.SKIPPED_CUSTOMER,
            client_type=client_type,
            service_type=ServiceCheckType.DDIS,
        )
        with transaction.atomic():
            if check_active:
                ActiveLivenessDetection.objects.create(**update_data, detect_type=active_method)
            if check_passive:
                if not current_passive_liveness:
                    PassiveLivenessDetection.objects.create(**update_data, attempt=0)
                else:
                    current_passive_liveness.update_safely(
                        status=LivenessCheckStatus.SKIPPED_CUSTOMER,
                        client_type=client_type,
                        service_type=ServiceCheckType.DDIS,
                    )
            return data

    current_attempt = min(
        0 if not current_active_liveness else (current_active_liveness.attempt or 0),
        0 if not current_passive_liveness else (current_passive_liveness.attempt or 0),
    )

    if check_active:
        is_max_retries_active = (
            True
            if current_active_liveness
            # and current_active_liveness.attempt
            and current_active_liveness.configs
            and current_attempt > current_active_liveness.configs.get('retry', 0)
            else False
        )

    if check_passive:
        is_max_retries_passive = (
            True
            if current_passive_liveness
            # and current_passive_liveness.attempt
            and current_passive_liveness.configs
            and current_attempt > current_active_liveness.configs.get('retry', 0)
            else False
        )

    if not is_passive_liveness_active or not is_active_liveness_active:
        update_data = dict(
            customer=customer,
            application=application,
            status=LivenessCheckStatus.FEATURE_IS_OFF,
            client_type=client_type,
            service_type=ServiceCheckType.DDIS,
            attempt=current_attempt,
        )

    with transaction.atomic():
        if check_passive:
            if not is_passive_liveness_active:
                if not current_passive_liveness:
                    PassiveLivenessDetection.objects.create(**update_data)
                elif not is_max_retries_passive:
                    current_passive_liveness.update_safely(**update_data)
            elif not current_passive_liveness:
                current_passive_liveness = PassiveLivenessDetection.objects.create(
                    application=application,
                    customer=customer,
                    status=LivenessCheckStatus.INITIAL,
                    client_type=client_type,
                    service_type=ServiceCheckType.DDIS,
                    configs=configs,
                    attempt=current_attempt,
                )
            elif current_passive_liveness and not is_max_retries_active:
                current_passive_liveness.update_safely(
                    status=LivenessCheckStatus.INITIAL,
                    client_type=client_type,
                    service_type=ServiceCheckType.DDIS,
                    attempt=current_attempt,
                )

        if check_active:
            if not is_active_liveness_active:
                if not current_active_liveness or not is_max_retries_active:
                    ActiveLivenessDetection.objects.create(**update_data, detect_type=active_method)
            elif not current_active_liveness or not is_max_retries_active:
                create_data = dict(
                    application=application,
                    customer=customer,
                    status=LivenessCheckStatus.INITIAL,
                    client_type=client_type,
                    service_type=ServiceCheckType.DDIS,
                    detect_type=active_method,
                    configs=configs,
                    attempt=current_attempt,
                )
                active_liveness_detection = ActiveLivenessDetection.objects.create(**create_data)
                if active_method == ActiveLivenessMethod.EYE_GAZE.value:
                    dot_digital_identity_client = get_dot_digital_identity_client(configs)
                    dot_digital_identity_service = DotDigitalIdentityService(
                        dot_digital_identity_client,
                        configs,
                        active_liveness_detection,
                        current_passive_liveness,
                        None,
                    )
                    (
                        challenge_result,
                        challenge_data,
                    ) = dot_digital_identity_service.generate_challenge()
                    if not challenge_result:
                        raise DotServerError()

                    sequence = challenge_data.get('sequence', [])
                    active_liveness_detection.update_safely(
                        sequence=sequence,
                        internal_customer_id=challenge_data.get('internal_customer_id'),
                    )
                    data['extra_data']['eye_gaze_challenge'] = sequence

    return data


def get_liveness_config(client_type) -> dict:
    setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.NEW_LIVENESS_DETECTION, is_active=True
    )

    if not setting:
        return {}

    client_setting = setting.parameters.get(client_type, {})
    if client_setting and client_setting.get('is_active'):
        return client_setting

    return {}


def detect_liveness(
    customer: Customer,
    record,
    check_passive: bool = True,
    check_active: bool = True,
    application_failed: bool = False,
    application_status_trigger: str = ApplicationStatusCodes.FORM_CREATED,
    active_method: str = None,
) -> tuple:
    response = {'retry_count': 0, 'max_retry': 0, 'message': '', 'error_code': {}}
    application = Application.objects.filter(customer_id=customer.id).last()
    if not application or application.status != application_status_trigger:
        logger.warning(
            'detect_liveness_application_failed|'
            'customer={}, application={}, status_trigger={}, active_method={}'.format(
                customer, application, application_status_trigger, active_method
            )
        )
        response['message'] = SmileLivenessCheckMessage.APPLICATION_NOT_FOUND
        return LivenessCheckResponseStatus.APPLICATION_NOT_FOUND, response
    active_liveness_detection, passive_liveness_detection = None, None

    if not check_active and not check_passive:
        response['message'] = SmileLivenessCheckMessage.LIVENESS_NOT_FOUND
        logger.warning('both_check_are_false|application={}'.format(application.id))
        return LivenessCheckResponseStatus.LIVENESS_NOT_FOUND, response

    if check_active:
        active_liveness_detection = ActiveLivenessDetection.objects.filter(
            application=application
        ).last()
    if check_passive:
        passive_liveness_detection = PassiveLivenessDetection.objects.filter(
            application=application
        ).last()

    valid_liveness_status = validate_liveness_status(
        check_active, check_passive, active_liveness_detection, passive_liveness_detection
    )

    if not valid_liveness_status:
        response['message'] = NewLivenessCheckMessage.LIVENESS_NOT_FOUND
        logger.warning(
            'detect_liveness_application_liveness_not_found|'
            'customer={}, application={}, status_trigger={}, active_liveness_detection={}, '
            'passive_liveness_detection={}, check_active={}, check_passive={},'
            'active_method={}'.format(
                customer.id,
                application.id,
                application_status_trigger,
                active_liveness_detection,
                passive_liveness_detection,
                check_active,
                check_passive,
                active_method,
            )
        )
        return LivenessCheckResponseStatus.LIVENESS_NOT_FOUND, response

    if check_passive:
        retry_count = (
            passive_liveness_detection.attempt + 1 if passive_liveness_detection.attempt else 1
        )
    else:
        retry_count = active_liveness_detection.attempt + 1

    configs = (
        active_liveness_detection.configs
        if active_liveness_detection
        else passive_liveness_detection.configs
    )
    response['max_retry'] = configs['retry']
    response['retry_count'] = retry_count
    if passive_liveness_detection.attempt >= configs['retry']:
        update_liveness_detection(
            active_liveness_detection,
            passive_liveness_detection,
            update_active_data=dict(attempt=retry_count),
            update_passive_data=dict(attempt=retry_count),
        )
        response['message'] = ActiveLivenessCheckMessage.LIMIT_EXCEEDED
        return LivenessCheckResponseStatus.LIMIT_EXCEEDED, response

    update_passive_data = dict(attempt=retry_count)
    update_active_data = dict(attempt=retry_count)
    if application_failed:
        _update_data = dict(
            status=LivenessCheckStatus.FAILED,
            error_code=application_failed,
        )
        update_liveness_detection(
            active_liveness_detection,
            passive_liveness_detection,
            update_active_data=_update_data,
            update_passive_data=_update_data,
        )
        if configs['skip_application_failed']:
            update_passive_data.update(status=LivenessCheckStatus.FAILED)
            update_active_data.update(status=LivenessCheckStatus.FAILED)
            update_liveness_detection(
                active_liveness_detection,
                passive_liveness_detection,
                update_active_data=update_active_data,
                update_passive_data=update_passive_data,
            )

            return LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED, response

        update_liveness_detection(
            active_liveness_detection,
            passive_liveness_detection,
            update_active_data=update_active_data,
            update_passive_data=update_passive_data,
        )
        return LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED, response

    # detect liveness
    dot_digital_identity_client = get_dot_digital_identity_client(configs)
    dot_digital_identity_service = DotDigitalIdentityService(
        dot_digital_identity_client,
        configs,
        active_liveness_detection,
        passive_liveness_detection,
        record=record,
    )
    fresh_progress = False
    if active_method in (ActiveLivenessMethod.MAGNIFEYE.value, ActiveLivenessMethod.SMILE.value):
        fresh_progress = True
    start_time = time.time()
    dot_digital_identity_service.check_liveness(
        record.read(),
        check_passive=check_passive,
        active_method=active_method,
        fresh_progress=fresh_progress,
    )
    elapsed = int((time.time() - start_time) * 1000)
    update_active_data.update(
        **dot_digital_identity_service.update_active_data,
        latency=elapsed,
    )
    update_passive_data.update(**dot_digital_identity_service.update_passive_data, latency=elapsed)
    update_liveness_detection(
        active_liveness_detection,
        passive_liveness_detection,
        update_active_data=update_active_data,
        update_passive_data=update_passive_data,
    )
    result, message = map_liveness_check_status_to_response(
        dot_digital_identity_service.current_detect_status
    )

    response['message'] = message

    if active_liveness_detection:
        response['error_code'].update(
            {"active_liveness_detection": active_liveness_detection.error_code}
        )

    if passive_liveness_detection:
        response['error_code'].update(
            {"passive_liveness_detection": passive_liveness_detection.error_code}
        )

    return result, response


def start_liveness_process(
    customer: Customer, start_active: bool = True, start_passive: bool = True
) -> tuple:
    start_active = True
    start_passive = True
    # start_statuses = (LivenessCheckStatus.INITIAL, LivenessCheckStatus.STARTED)
    active_liveness_detection, passive_liveness_detection = None, None
    if start_active:
        active_liveness_detection = ActiveLivenessDetection.objects.filter(customer=customer).last()
    if start_passive:
        passive_liveness_detection = PassiveLivenessDetection.objects.filter(
            customer=customer
        ).last()

    if (start_active and not active_liveness_detection) or (
        start_passive and not passive_liveness_detection
    ):
        return (
            LivenessCheckResponseStatus.LIVENESS_NOT_FOUND,
            SmileLivenessCheckMessage.LIVENESS_NOT_FOUND,
        )

    # if (
    #     start_active
    #     and (
    #         not active_liveness_detection
    #         or active_liveness_detection.status not in start_statuses
    #     )
    #     or start_passive
    #     and (
    #         not passive_liveness_detection
    #         or passive_liveness_detection.status not in start_statuses
    #     )
    # ):
    #     return (
    #         LivenessCheckResponseStatus.LIVENESS_NOT_FOUND,
    #         SmileLivenessCheckMessage.LIVENESS_NOT_FOUND,
    #     )

    with transaction.atomic():
        if (
            active_liveness_detection
            and active_liveness_detection.status != LivenessCheckStatus.STARTED
        ):
            active_liveness_detection.update_safely(status=LivenessCheckStatus.STARTED)
        if (
            passive_liveness_detection
            and passive_liveness_detection.status != LivenessCheckStatus.STARTED
        ):
            passive_liveness_detection.update_safely(status=LivenessCheckStatus.STARTED)

    return LivenessCheckResponseStatus.STARTED, NewLivenessCheckMessage.STARTED


def start_upload_image_liveness(selfie_image, application_id):

    application = Application.objects.filter(pk=application_id).last()
    application_status_id = application.application_status_id
    if application_status_id != ApplicationStatusCodes.FORM_CREATED:
        logger.info(
            {
                'message': '[LivenessUploadImage] skip process application not in x100',
                'application_id': application_id,
                'application_status_code': application_status_id,
            }
        )
        return

    active_liveness = ActiveLivenessDetection.objects.filter(application_id=application_id).last()
    if not active_liveness or active_liveness.images:
        return

    if isinstance(selfie_image, TemporaryUploadedFile):
        selfie_image = convert_temporary_to_inmem_file(selfie_image)

    image_data = upload_selfie_image(
        image=selfie_image,
        application=application_id,
        image_type=NewLivenessImage.IMAGE_TYPE,
    )
    logger.info(
        {
            'message': '[LivenessUploadImage] upload image selfie',
            'image_id': image_data.id if image_data else None,
            'application_id': application_id,
        }
    )

    if not image_data:
        return

    structure_images = [{'image_id': image_data.id, 'type': NewLivenessImage.LIVENESS_IMAGE_TYPE}]
    active_liveness.update_safely(images=structure_images)

    return image_data.id
