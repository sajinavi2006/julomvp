import logging
import time
import base64

from django.db import transaction
from django.conf import settings
from rest_framework.status import HTTP_401_UNAUTHORIZED

from juloserver.julo.utils import get_file_from_oss
from juloserver.face_recognition.services import upload_selfie_image
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import ApplicationStatusCodes, FeatureNameConst
from juloserver.julo.models import Application, FeatureSetting, Image, Customer
from juloserver.liveness_detection.clients import (
    get_dot_digital_identity_client,
    DotDigitalIdentityClient,
)
from juloserver.liveness_detection.constants import (
    ActiveLivenessCheckMessage,
    LivenessCheckResponseStatus,
    LivenessCheckStatus,
    SmileLivenessCheckMessage,
    SmileLivenessPicture,
    PassiveImagePicture,
    ServiceCheckType,
    ActiveLivenessType,
    ImageValueType,
)
from juloserver.liveness_detection.exceptions import (
    DotClientError,
    DotClientInternalError,
    DotServerError,
    DotServerTimeout,
    PassiveImageNotFound,
    PassiveImageParseFail,
)
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
)
from juloserver.liveness_detection.utils import (
    convert_image_to_base64,
)
from juloserver.liveness_detection.services import get_valid_segments

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class DotDigitalIdentityService:
    def __init__(
        self,
        ddis_client: DotDigitalIdentityClient,
        configs: dict,
        active_liveness_detection: ActiveLivenessDetection,
        passive_liveness_detection: PassiveLivenessDetection,
        neutral_image: str,
        smile_image: str,
        passive_image: str = None,
    ):
        self.configs = configs
        self.active_liveness_detection = active_liveness_detection
        self.passive_liveness_detection = passive_liveness_detection
        self.ddis_client = ddis_client
        self.ddis_customer = None
        self.neutral_image = neutral_image
        self.smile_image = smile_image
        self.passive_image = passive_image
        self.exception_raised = False
        self.update_active_data = {}
        self.update_passive_data = {}
        self.current_detect_status = None

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
        self._call_api(self.ddis_client.create_customer_selfie, {'image': self.neutral_image})
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

    def check_liveness(self, check_smile: bool = True, check_passive: bool = True) -> bool:
        if not self.get_api_info():
            return False

        if not self.create_customer():
            return False

        self.ddis_client.customer_id = self.ddis_customer
        if check_smile:
            if not self.create_customer_selfie():
                return False

        if not self.create_customer_liveness():
            return False

        smile_score = None
        if check_smile:
            smile_result, smile_score = self.check_smile_liveness(
                self.neutral_image, self.smile_image
            )
            if not smile_result:
                return False

        passive_score = None
        if check_passive:
            passive_result, passive_score = self.check_passive_liveness(self.passive_image)
            if not passive_result:
                return False

        self._delete_customer()

        result = self.evaluate_final_result(check_smile, check_passive, smile_score, passive_score)

        return result

    def check_smile_liveness(self, neutral_image: str, smile_image: str) -> tuple:
        # submit neutral
        submit_neutral_image_result, _ = self._call_api(
            self.ddis_client.upload_neutral_image, {'image': neutral_image}
        )
        if self.exception_raised:
            self._capture_exception_data()
            return False, None
        elif submit_neutral_image_result.get('errorCode'):
            self.current_detect_status = LivenessCheckStatus.FAILED
            self.update_active_data.update(
                status=self.current_detect_status,
                error_code=submit_neutral_image_result.get('errorCode', 'incorrect_data'),
            )
            self.update_passive_data.update(
                status=self.current_detect_status,
                error_code=submit_neutral_image_result.get('errorCode', 'incorrect_data'),
                score=None,
            )
            return False, None

        # submit smile
        submit_smile_image_result, _ = self._call_api(
            self.ddis_client.upload_smile_image, {'image': smile_image}
        )
        if self.exception_raised:
            self._capture_exception_data()
            return False, None
        elif submit_smile_image_result.get('errorCode'):
            self.current_detect_status = LivenessCheckStatus.FAILED
            self.update_active_data.update(
                status=self.current_detect_status,
                error_code=submit_smile_image_result.get('errorCode', 'incorrect_data'),
            )
            self.update_passive_data.update(
                status=self.current_detect_status,
                error_code=submit_smile_image_result.get('errorCode', 'incorrect_data'),
                score=None,
            )
            return False, None

        # evaluate
        evaluate_result, _ = self._call_api(self.ddis_client.evaluate_smile, {})
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

        if evaluate_result['score'] < self.configs['smile_threshold']:
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

    def check_passive_liveness(self, passive_image: str) -> tuple:
        submit_passive_image_result, _ = self._call_api(
            self.ddis_client.upload_passive_image, {'image': passive_image}
        )
        if self.exception_raised:
            self._capture_exception_data()
            return False, None
        elif submit_passive_image_result.get('errorCode'):
            self.current_detect_status = LivenessCheckStatus.FAILED
            self.update_passive_data.update(
                status=self.current_detect_status,
                error_code=submit_passive_image_result.get('errorCode', 'incorrect_data'),
            )
            self.update_active_data.update(
                status=self.current_detect_status,
                error_code=submit_passive_image_result.get('errorCode', 'incorrect_data'),
                score=None,
            )
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
            )
            return True, evaluate_result['score']

        self.update_passive_data.update(
            status=LivenessCheckStatus.PASSED, score=evaluate_result['score'], error_code=None
        )
        return True, evaluate_result['score']

    def evaluate_final_result(
        self, check_smile: bool, check_passive: bool, smile_score: float, passive_score: float
    ) -> bool:
        if check_smile and smile_score < self.configs['smile_threshold']:
            self.current_detect_status = LivenessCheckStatus.FAILED
            return False
        if check_passive and passive_score < self.configs['passive_threshold']:
            self.current_detect_status = LivenessCheckStatus.FAILED
            return False

        self.current_detect_status = LivenessCheckStatus.PASSED
        return True

    def _delete_customer(self):
        try:
            self.ddis_client.delete_customer()
        except Exception:
            sentry_client.captureException()


def get_smile_liveness_config(client_type) -> dict:
    setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.SMILE_LIVENESS_DETECTION, is_active=True
    )

    if not setting:
        return {}

    client_setting = setting.parameters.get(client_type, {})
    if client_setting and client_setting.get('is_active'):
        return client_setting

    return {}


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


def validate_smile_liveness_images(
    images: list, check_passive: bool = True, check_active: bool = True
) -> bool:
    valid_images = get_valid_segments(images)
    if len(valid_images) != len(images):
        return False
    if check_active and check_passive:
        if len(valid_images) != 2:
            return False
        all_image_types = [image['type'] for image in valid_images]
        if sorted(all_image_types) != sorted(SmileLivenessPicture.get_all_value()):
            return False
    elif check_passive:
        if len(valid_images) != 1:
            return False
        if valid_images[0]['type'] != PassiveImagePicture.SELFIE.value:
            return False

    return True


def process_images(application: Application, images: list, check_both: bool) -> tuple:
    converted_images = {}
    active_record_images = []
    passive_record_image_id = None

    def _handle_uploaded_image_type(image_id):
        image = Image.objects.filter(pk=image_id).last()
        if not image:
            logger.error(
                'ddis_process_image_passive_image_not_found|'
                'application_id={}'.format(application.id)
            )
            raise PassiveImageNotFound('application {} has no selfie image'.format(application.id))
        nonlocal passive_record_image_id
        passive_record_image_id = image.id
        remote_filepath = image.image_url
        if not remote_filepath:
            logger.error(
                'ddis_process_image_passive_image_remote_file_path_is_not_found|'
                'image_id={}, application_id={}'.format(image.id, application.id)
            )
            raise PassiveImageParseFail('Passive image {} has no remote_filepath'.format(image.id))

        try:
            image_file = get_file_from_oss(settings.OSS_MEDIA_BUCKET, image.url)
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        except Exception:
            raise PassiveImageParseFail('Convert to base64 for image {} failed'.format(image.id))

        converted_images[PassiveImagePicture.SELFIE.value] = base64_image
        converted_images[SmileLivenessPicture.NEUTRAL.value] = base64_image

    def _handle_file_image_type(file):
        image_type = 'smile_check_{}'.format(image['type'])
        upload_image = upload_selfie_image(image['image'], application.id, image_type)
        base64_image = convert_image_to_base64(image['image'])
        converted_images[image['type']] = base64_image
        if image['type'] in SmileLivenessPicture.get_all_value():
            active_record_images.append({'image_id': upload_image.id, 'type': image['type']})
            if check_both and image['type'] == SmileLivenessPicture.NEUTRAL.value:
                nonlocal passive_record_image_id
                passive_record_image_id = upload_image.id
                converted_images[PassiveImagePicture.SELFIE.value] = base64_image

    for image in images:
        if image['value_type'] == ImageValueType.UPLOADED_ID:
            _handle_uploaded_image_type(image['image'])
            break
        elif image['value_type'] == ImageValueType.FILE:
            _handle_file_image_type(image)

    return converted_images, active_record_images, passive_record_image_id


def start_liveness_process(
    customer: Customer, start_active: bool = True, start_passive: bool = True
) -> tuple:
    start_statuses = (LivenessCheckStatus.INITIAL, LivenessCheckStatus.STARTED)
    active_liveness_detection, passive_liveness_detection = None, None
    if start_active:
        active_liveness_detection = ActiveLivenessDetection.objects.filter(customer=customer).last()
    if start_passive:
        passive_liveness_detection = PassiveLivenessDetection.objects.filter(
            customer=customer
        ).last()

    if not active_liveness_detection or not passive_liveness_detection:
        return (
            LivenessCheckResponseStatus.SMILE_LIVENESS_NOT_FOUND,
            SmileLivenessCheckMessage.LIVENESS_NOT_FOUND,
        )

    active_attempt = (
        0 if not active_liveness_detection.attempt else active_liveness_detection.attempt
    )
    passive_attempt = (
        0 if not passive_liveness_detection.attempt else passive_liveness_detection.attempt
    )

    if (active_liveness_detection and active_attempt > 0) or (
        passive_liveness_detection and passive_attempt > 0
    ):
        return LivenessCheckResponseStatus.STARTED, SmileLivenessCheckMessage.STARTED
    if (
        start_active
        and (
            not active_liveness_detection or active_liveness_detection.status not in start_statuses
        )
        or start_passive
        and (
            not passive_liveness_detection
            or passive_liveness_detection.status not in start_statuses
        )
    ):
        return (
            LivenessCheckResponseStatus.SMILE_LIVENESS_NOT_FOUND,
            SmileLivenessCheckMessage.LIVENESS_NOT_FOUND,
        )

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

    return LivenessCheckResponseStatus.STARTED, SmileLivenessCheckMessage.STARTED


def map_liveness_check_status_to_response(status: str) -> tuple:
    if status == LivenessCheckStatus.PASSED:
        return LivenessCheckResponseStatus.SUCCESS, SmileLivenessCheckMessage.SUCCESS
    if status == LivenessCheckStatus.FAILED:
        return LivenessCheckResponseStatus.FAILED, SmileLivenessCheckMessage.FAILED
    if status in (LivenessCheckStatus.ERROR, LivenessCheckStatus.TIMEOUT):
        return LivenessCheckResponseStatus.ERROR, SmileLivenessCheckMessage.ERROR


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

    retry_statuses = [
        LivenessCheckStatus.FAILED,
        LivenessCheckStatus.ERROR,
        LivenessCheckStatus.TIMEOUT,
    ]
    valid_started_statuses = [
        LivenessCheckStatus.STARTED,
        *retry_statuses,
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

        if (
            active_liveness_detection.status not in valid_started_statuses
            and passive_liveness_detection.status not in retry_statuses
        ) or (
            passive_liveness_detection.status not in valid_started_statuses
            and active_liveness_detection.status not in retry_statuses
        ):
            return False

        return True

    if check_active and active_liveness_detection.status not in valid_started_statuses:
        return False

    if check_passive and passive_liveness_detection.status not in valid_started_statuses:
        return False

    return True


def detect_liveness(
    customer: Customer,
    images: list,
    check_passive: bool = True,
    check_active: bool = True,
    application_failed: bool = False,
    application_status_trigger: str = ApplicationStatusCodes.FORM_CREATED,
) -> tuple:
    response = {'retry_count': 0, 'max_retry': 0, 'message': ''}
    response = {'retry_count': 0, 'max_retry': 0, 'message': '', 'error_code': {}}
    application = customer.application_set.last()
    if not application or application.status != application_status_trigger:
        logger.warning(
            'detect_smile_liveness_application_failed|'
            'customer={}, application={}, status_trigger={}'.format(
                customer, application, application_status_trigger
            )
        )
        response['message'] = SmileLivenessCheckMessage.APPLICATION_NOT_FOUND
        return LivenessCheckResponseStatus.APPLICATION_NOT_FOUND, response
    active_liveness_detection, passive_liveness_detection = None, None

    if not check_active and not check_passive:
        response['message'] = SmileLivenessCheckMessage.LIVENESS_NOT_FOUND
        logger.warning('both_check_are_false|application={}'.format(application.id))
        return LivenessCheckResponseStatus.SMILE_LIVENESS_NOT_FOUND, response

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
        response['message'] = SmileLivenessCheckMessage.LIVENESS_NOT_FOUND
        logger.warning(
            'detect_smile_liveness_application_liveness_not_found|'
            'customer={}, application={}, status_trigger={}, active_liveness_detection={}, '
            'passive_liveness_detection={}, check_active={}, check_passive={}'.format(
                customer.id,
                application.id,
                application_status_trigger,
                active_liveness_detection,
                passive_liveness_detection,
                check_active,
                check_passive,
            )
        )
        return LivenessCheckResponseStatus.SMILE_LIVENESS_NOT_FOUND, response

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

    should_create = True
    if retry_count == 1:  # check for the first attempt
        should_create = False
        if (
            active_liveness_detection
            and active_liveness_detection.status != LivenessCheckStatus.STARTED
        ) or (
            passive_liveness_detection
            and passive_liveness_detection.status != LivenessCheckStatus.STARTED
        ):
            response['message'] = SmileLivenessCheckMessage.LIVENESS_NOT_FOUND
            return LivenessCheckResponseStatus.SMILE_LIVENESS_NOT_FOUND, response

        """
        To handle if user first attempt and livenesss status is started
        in this status liveness feature is turn off, so we update
        to current liveness to FEATURE_IS_OFF and skip liveness for this user
        """
        configs = get_smile_liveness_config(passive_liveness_detection.client_type)
        if not configs:
            update_data = dict(attempt=retry_count, status=LivenessCheckStatus.FEATURE_IS_OFF)
            active_liveness_detection.update_safely(**update_data)
            passive_liveness_detection.update_safely(**update_data)
            response['message'] = SmileLivenessCheckMessage.FEATURE_IS_OFF
            logger.warning(
                'detect_smile_liveness_application_liveness_not_found|'
                'customer={}, application={}, status_trigger={}, active_liveness_detection={}, '
                'passive_liveness_detection={}, check_active={}, check_passive={}'.format(
                    customer.id,
                    application.id,
                    application_status_trigger,
                    active_liveness_detection,
                    passive_liveness_detection,
                    check_active,
                    check_passive,
                )
            )
            return LivenessCheckResponseStatus.FEATURE_IS_OFF, response

    if should_create:
        configs = get_smile_liveness_config(passive_liveness_detection.client_type)
        with transaction.atomic():
            if check_active:
                previous_active_liveness_detection = active_liveness_detection
                active_liveness_detection = ActiveLivenessDetection.objects.create(
                    application=application,
                    customer=customer,
                    status=(
                        LivenessCheckStatus.INITIAL
                        if configs
                        else LivenessCheckStatus.FEATURE_IS_OFF
                    ),
                    attempt=retry_count,
                    configs=configs,
                    detect_type=previous_active_liveness_detection.detect_type,
                    service_type=previous_active_liveness_detection.service_type,
                    client_type=previous_active_liveness_detection.client_type,
                )
            if check_passive:
                update_data = dict(
                    attempt=retry_count,
                    configs=configs,
                )
                if not configs:
                    update_data['status'] = LivenessCheckStatus.FEATURE_IS_OFF
                passive_liveness_detection.update_safely(**update_data)

        if not configs:
            response['message'] = SmileLivenessCheckMessage.FEATURE_IS_OFF
            return LivenessCheckResponseStatus.FEATURE_IS_OFF, response

    update_passive_data = dict(attempt=retry_count)
    update_active_data = dict(attempt=retry_count)
    if application_failed:
        _update_data = dict(
            status=LivenessCheckStatus.FAILED,
            error_code=application_failed,
        )
        update_passive_data.update(**_update_data)
        update_active_data.update(**_update_data)
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

    if not validate_smile_liveness_images(images, check_passive, check_active):
        update_passive_data.update(status=LivenessCheckStatus.FAILED)
        update_active_data.update(status=LivenessCheckStatus.FAILED)
        update_liveness_detection(
            active_liveness_detection,
            passive_liveness_detection,
            update_active_data=update_active_data,
            update_passive_data=update_passive_data,
        )
        response['message'] = SmileLivenessCheckMessage.IMAGE_INCORRECT
        return LivenessCheckResponseStatus.SMILE_IMAGE_INCORRECT, response

    try:
        converted_images, active_record_images, passive_record_image_id = process_images(
            application, images, check_active and check_passive
        )
    except PassiveImageNotFound:
        sentry_client.captureException()
        update_active_data.update(status=LivenessCheckStatus.FAILED)
        update_liveness_detection(
            active_liveness_detection,
            passive_liveness_detection,
            update_active_data=update_active_data,
            update_passive_data=update_passive_data,
        )
        response['message'] = SmileLivenessCheckMessage.IMAGE_INCORRECT
        return LivenessCheckResponseStatus.SMILE_IMAGE_INCORRECT, response
    except PassiveImageParseFail:
        sentry_client.captureException()
        update_active_data.update(status=LivenessCheckStatus.ERROR)
        update_liveness_detection(
            active_liveness_detection,
            passive_liveness_detection,
            update_active_data=update_active_data,
            update_passive_data=update_passive_data,
        )
        response['message'] = SmileLivenessCheckMessage.ERROR
        return LivenessCheckResponseStatus.ERROR, response

    # detect liveness
    dot_digital_identity_client = get_dot_digital_identity_client(configs)
    dot_digital_identity_service = DotDigitalIdentityService(
        dot_digital_identity_client,
        configs,
        active_liveness_detection,
        passive_liveness_detection,
        converted_images.get('neutral'),
        converted_images.get('smile'),
        converted_images.get('selfie'),
    )
    start_time = time.time()
    dot_digital_identity_service.check_liveness(
        check_smile=check_active, check_passive=check_passive
    )
    elapsed = int((time.time() - start_time) * 1000)
    update_active_data.update(
        **dot_digital_identity_service.update_active_data,
        latency=elapsed,
        images=active_record_images
    )
    update_passive_data.update(
        **dot_digital_identity_service.update_passive_data,
        latency=elapsed,
        image_id=passive_record_image_id,
    )
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


def pre_check_liveness(
    customer: Customer,
    client_type: str,
    skip_customer: bool = False,
    check_active: bool = True,
    check_passive=True,
) -> dict:
    application = Application.objects.filter(customer=customer).last()
    if not application or application.application_status_id != ApplicationStatusCodes.FORM_CREATED:
        return {'active_liveness': False, 'passive_liveness': False, 'liveness_retry': None}

    configs = get_smile_liveness_config(client_type)
    is_active_liveness_active, is_passive_liveness_active = False, False
    if configs:
        is_active_liveness_active, is_passive_liveness_active = True, True

    data = {
        'active_liveness': is_active_liveness_active,
        'passive_liveness': is_passive_liveness_active,
        'liveness_retry': configs.get('retry'),
    }
    current_active_liveness, current_passive_liveness = None, None
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
                if not current_active_liveness:
                    ActiveLivenessDetection.objects.create(
                        **update_data, detect_type=ActiveLivenessType.SMILE
                    )
            if check_passive:
                if not current_passive_liveness:
                    PassiveLivenessDetection.objects.create(**update_data, attempt=0)
            return data

    if not is_passive_liveness_active or not is_active_liveness_active:
        if check_active:
            is_max_retries_active = (
                True
                if current_active_liveness
                and current_active_liveness.attempt
                and current_active_liveness.configs
                and current_active_liveness.attempt
                > current_active_liveness.configs.get('retry', 0)
                else False
            )

        if check_passive:
            is_max_retries_passive = (
                True
                if current_passive_liveness
                and current_passive_liveness.attempt
                and current_passive_liveness.configs
                and current_passive_liveness.attempt
                > current_active_liveness.configs.get('retry', 0)
                else False
            )

        update_data = dict(
            customer=customer,
            application=application,
            status=LivenessCheckStatus.FEATURE_IS_OFF,
            client_type=client_type,
            service_type=ServiceCheckType.DDIS,
        )

    if check_active:
        if not is_active_liveness_active:
            if not current_active_liveness or not is_max_retries_active:
                ActiveLivenessDetection.objects.create(
                    **update_data, detect_type=ActiveLivenessType.SMILE
                )
        elif not current_active_liveness:
            ActiveLivenessDetection.objects.create(
                application=application,
                customer=customer,
                status=LivenessCheckStatus.INITIAL,
                client_type=client_type,
                service_type=ServiceCheckType.DDIS,
                detect_type=ActiveLivenessType.SMILE,
                configs=configs,
            )

    if check_passive:
        if not is_passive_liveness_active:
            if not current_passive_liveness:
                PassiveLivenessDetection.objects.create(**update_data, attempt=0)
            elif not is_max_retries_passive:
                current_passive_liveness.update_safely(**update_data)
        elif not current_passive_liveness:
            PassiveLivenessDetection.objects.create(
                application=application,
                customer=customer,
                status=LivenessCheckStatus.INITIAL,
                client_type=client_type,
                service_type=ServiceCheckType.DDIS,
                configs=configs,
                attempt=0,
            )

    return data


def get_liveness_info(customer: Customer):
    application = Application.objects.filter(customer=customer).last()
    if not application:
        return {}

    active_liveness_detection = ActiveLivenessDetection.objects.filter(
        application=application
    ).last()
    passive_liveness_detection = PassiveLivenessDetection.objects.filter(
        application=application
    ).last()

    return {
        'active_liveness_detection': {
            'status': active_liveness_detection.status,
            'attempt': active_liveness_detection.attempt,
            'max_attempt': active_liveness_detection.configs.get('retry', 0)
            if active_liveness_detection.configs
            else 0,
            'error_code': active_liveness_detection.error_code,
        }
        if active_liveness_detection
        else None,
        'passive_liveness_detection': {
            'status': passive_liveness_detection.status,
            'attempt': passive_liveness_detection.attempt,
            'max_attempt': passive_liveness_detection.configs.get('retry', 0)
            if passive_liveness_detection.configs
            else 0,
            'error_code': passive_liveness_detection.error_code,
        }
        if passive_liveness_detection
        else None,
    }


def get_liveness_detection_result(
    application: Application,
    check_active: bool = True,
    check_passive: bool = True,
) -> bool:
    not_passed_statuses = (
        LivenessCheckStatus.FAILED,
        LivenessCheckStatus.INITIAL,
        LivenessCheckStatus.STARTED,
    )
    internal_error_retry_statuses = (LivenessCheckStatus.ERROR, LivenessCheckStatus.TIMEOUT)
    if check_active:
        active_liveness_detection = ActiveLivenessDetection.objects.filter(
            application=application
        ).last()
        configs = active_liveness_detection.configs or {}
        if (
            not active_liveness_detection
            or active_liveness_detection.status in not_passed_statuses
            or (
                configs
                and active_liveness_detection.status in internal_error_retry_statuses
                and active_liveness_detection.attempt != configs.get('retry')
            )
        ):
            return False

    if check_passive:
        passive_liveness_detection = PassiveLivenessDetection.objects.filter(
            application=application
        ).last()
        configs = passive_liveness_detection.configs or {}
        if (
            not passive_liveness_detection
            or passive_liveness_detection.status in not_passed_statuses
            or (
                configs
                and passive_liveness_detection.status in internal_error_retry_statuses
                and passive_liveness_detection.attempt != configs.get('retry')
            )
        ):
            return False

    return True
