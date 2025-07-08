import copy
import logging
import random

import semver
from django.db import transaction

from juloserver.face_recognition.constants import ImageType
from juloserver.face_recognition.services import upload_selfie_image
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import ApplicationStatusCodes, FeatureNameConst
from juloserver.julo.models import Application, Customer, FeatureSetting, Image
from juloserver.liveness_detection.clients import get_dot_core_client
from juloserver.liveness_detection.constants import (
    ActiveLivenessCheckMessage,
    ActiveLivenessPosition,
    ApplicationReasonFailed,
    LivenessCheckResponseStatus,
    LivenessCheckStatus,
    LivenessCheckType,
    PassiveLivenessCheckMessage,
    position_lost_map,
    InspectCustomerResult,
)
from juloserver.liveness_detection.exceptions import (
    DotCoreClientError,
    DotCoreClientInternalError,
    DotCoreServerError,
    DotCoreServerTimeout,
)
from juloserver.liveness_detection.models import (
    ActiveLivenessDetection,
    PassiveLivenessDetection,
)
from juloserver.liveness_detection.tasks import check_passive_liveness_async
from juloserver.liveness_detection.utils import (
    convert_image_to_base64,
    encrypt_android_app_license,
    get_max_count,
)

dot_core_client = get_dot_core_client()
sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def check_active_liveness(
    segments: list,
    customer: Customer,
    start_status: str,
    application_failed=None,
) -> tuple:
    response = {'retry_count': 0, 'max_retry': 0, 'message': ''}
    application = customer.application_set.last()
    if (
        not application
        or (not application.is_julo_one() and not application.is_julo_starter())
        or application.status != ApplicationStatusCodes.FORM_CREATED
    ):
        response['message'] = ActiveLivenessCheckMessage.APPLICATION_NOT_FOUND
        return LivenessCheckResponseStatus.APPLICATION_NOT_FOUND, response

    liveness_detection = ActiveLivenessDetection.objects.filter(application=application).last()
    if not liveness_detection or liveness_detection.status not in (
        LivenessCheckStatus.FAILED,
        start_status,
        LivenessCheckStatus.ERROR,
        LivenessCheckStatus.TIMEOUT,
    ):
        response['message'] = ActiveLivenessCheckMessage.ACTIVE_LIVENESS_NOT_FOUND
        return LivenessCheckResponseStatus.ACTIVE_LIVENESS_NOT_FOUND, response

    configs = get_liveness_config(LivenessCheckType.ACTIVE)
    if not configs:
        response['message'] = ActiveLivenessCheckMessage.ERROR
        liveness_detection.update_safely(status=LivenessCheckStatus.FEATURE_IS_OFF)
        return LivenessCheckResponseStatus.SUCCESS, response

    configs = liveness_detection.configs or configs
    response['max_retry'] = configs['retry']
    retry_count = liveness_detection.attempt + 1
    response['retry_count'] = retry_count
    if liveness_detection.attempt >= configs['retry']:
        liveness_detection.update_safely(attempt=retry_count)
        response['message'] = ActiveLivenessCheckMessage.LIMIT_EXCEEDED
        return LivenessCheckResponseStatus.LIMIT_EXCEEDED, response

    should_create = True
    if retry_count == 1:  # check for the first attempt
        should_create = False
        if liveness_detection.status != start_status:
            response['message'] = ActiveLivenessCheckMessage.ACTIVE_LIVENESS_NOT_FOUND
            return LivenessCheckResponseStatus.ACTIVE_LIVENESS_NOT_FOUND, response

    if should_create:
        if liveness_detection.status not in (LivenessCheckStatus.FAILED, LivenessCheckStatus.ERROR):
            response['message'] = ActiveLivenessCheckMessage.ACTIVE_LIVENESS_NOT_FOUND
            return LivenessCheckResponseStatus.ACTIVE_LIVENESS_NOT_FOUND, response

        dot_api_version = get_api_version(configs)
        liveness_detection = ActiveLivenessDetection.objects.create(
            application=application,
            customer=customer,
            status=start_status,
            sequence=liveness_detection.sequence,
            attempt=retry_count,
            api_version=dot_api_version,
            configs=configs,
        )

    data_to_update = {}
    if application_failed:
        if configs['skip_application_failed']:
            liveness_detection.update_safely(
                status=LivenessCheckStatus.APPLICATION_DETECT_FAILED,
                error_code=application_failed,
                attempt=retry_count,
            )
            return LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED, response

        liveness_detection.update_safely(
            status=LivenessCheckStatus.FAILED,
            error_code=application_failed,
            attempt=retry_count,
        )
        return LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED, response

    valid_segments = validate_active_liveness_sequence(
        segments, liveness_detection, configs['valid_segment_count']
    )
    if not valid_segments:
        liveness_detection.update_safely(attempt=retry_count, status=LivenessCheckStatus.FAILED)
        response['message'] = ActiveLivenessCheckMessage.SEQUENCE_INCORRECT
        return LivenessCheckResponseStatus.SEQUENCE_INCORRECT, response

    if check_duplicate_segments(valid_segments):
        images = [{'image_id': '', 'position': segment['dot_position']} for segment in segments]
        liveness_detection.update_safely(
            attempt=retry_count,
            status=LivenessCheckStatus.APPLICATION_DETECT_FAILED,
            error_code=ApplicationReasonFailed.SEGMENT_DUPLICATED,
            images=images,
        )
        response['message'] = ActiveLivenessCheckMessage.SEQUENCE_INCORRECT
        return LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED, response

    images = []
    for segment in valid_segments:
        image_type = f'{LivenessCheckType.ACTIVE}_{segment["dot_position"]}'
        image = upload_selfie_image(segment['image'], application.id, image_type)
        segment['image'] = convert_image_to_base64(segment['image'])
        segment['dotPosition'] = segment.pop('dot_position')
        images.append({'image_id': image.id, 'position': segment['dotPosition']})
    data_to_update.update(images=images, attempt=retry_count)
    elapsed = None
    try:
        result, elapsed, vendor_result = dot_core_client.check_active_liveness(
            valid_segments, configs
        )
        logger.info(
            'active_liveness_detect_success|application={}, result={}'.format(
                application.id, result
            )
        )
    except (
        DotCoreServerError,
        DotCoreServerTimeout,
        DotCoreClientInternalError,
        DotCoreClientError,
    ) as error:
        sentry_client.captureException()
        (message,) = error.args
        error_code = None
        status = LivenessCheckStatus.ERROR
        if isinstance(error, (DotCoreServerError, DotCoreClientError)):
            elapsed = message['elapsed']
            error_code = message['response'].get('errorCode')
            if isinstance(error, DotCoreClientError):
                status = LivenessCheckStatus.FAILED
                liveness_detection.update_safely(
                    **data_to_update, status=status, error_code=error_code, latency=elapsed
                )
                response['message'] = ActiveLivenessCheckMessage.FAILED
                return LivenessCheckResponseStatus.FAILED, response
        elif isinstance(error, DotCoreServerTimeout):
            status = LivenessCheckStatus.TIMEOUT

        liveness_detection.update_safely(
            **data_to_update, status=status, error_code=error_code, latency=elapsed
        )
        response['message'] = ActiveLivenessCheckMessage.ERROR
        if retry_count == configs['retry']:
            return LivenessCheckResponseStatus.APPLICATION_DETECT_FAILED, response
        return LivenessCheckResponseStatus.ERROR, response

    if result.get('score') is None:
        error_message = 'check_active_liveness_error_incorrect_data|response={}'.format(result)
        logger.warning(error_message)
        liveness_detection.update_safely(
            **data_to_update,
            status=LivenessCheckStatus.FAILED,
            error_code=result.get('errorCode', 'incorrect_data'),
            latency=elapsed,
            liveness_vendor_result=vendor_result,
        )
        response['message'] = ActiveLivenessCheckMessage.FAILED
        return LivenessCheckResponseStatus.FAILED, response
    if result['score'] < configs['score_threshold']:
        liveness_detection.update_safely(
            **data_to_update,
            status=LivenessCheckStatus.FAILED,
            score=result['score'],
            latency=elapsed,
            error_code=result.get('errorCode'),
            liveness_vendor_result=vendor_result,
        )
        response['message'] = ActiveLivenessCheckMessage.FAILED
        return LivenessCheckResponseStatus.FAILED, response

    liveness_detection.update_safely(
        **data_to_update,
        status=LivenessCheckStatus.PASSED,
        latency=elapsed,
        score=result['score'],
        liveness_vendor_result=vendor_result,
    )
    response['message'] = ActiveLivenessCheckMessage.SUCCESS
    return LivenessCheckResponseStatus.SUCCESS, response


def check_application_liveness_detection_result(application):
    active_liveness = ActiveLivenessDetection.objects.filter(application=application).last()
    passive_liveness = PassiveLivenessDetection.objects.get_or_none(application=application)
    pass_active_liveness_conditions, pass_passive_liveness_conditions, pass_video_injection = (
        True,
        True,
        True,
    )
    if active_liveness:
        pass_active_liveness_conditions = active_liveness.status != LivenessCheckStatus.FAILED
        if active_liveness.video_injection == InspectCustomerResult.VIDEO_INJECTED.value:
            pass_video_injection = False

    if passive_liveness:
        pass_passive_liveness_conditions = passive_liveness.status != LivenessCheckStatus.FAILED
    elif active_liveness:
        pass_passive_liveness_conditions = False

    change_reasons = []
    if not pass_active_liveness_conditions:
        change_reasons.append('failed active liveness')
    if not pass_passive_liveness_conditions:
        change_reasons.append('failed passive liveness')
    if not pass_video_injection:
        change_reasons.append('failed video injection')

    if change_reasons:
        return False, ' and '.join(change_reasons)

    return True, ''


def check_duplicate_segments(segments):
    for i in range(len(segments) - 1):
        if segments[i]['dot_position'] == segments[i + 1]['dot_position']:
            return True

    return False


def check_passive_liveness(image: Image, customer: Customer, async_detection=False) -> tuple:
    application = customer.application_set.last()
    if (
        not application
        or (not application.is_julo_one() and not application.is_julo_starter())
        or application.status != ApplicationStatusCodes.FORM_PARTIAL
    ):
        logger.warning(
            'passive_liveness_check_invalid_application_status_or_application_not_found|'
            'application_id={},application_status={}'.format(
                application.id if application else None, application.status if application else None
            )
        )
        return (
            LivenessCheckResponseStatus.APPLICATION_NOT_FOUND,
            PassiveLivenessCheckMessage.APPLICATION_NOT_FOUND,
        )
    current_liveness_detection = PassiveLivenessDetection.objects.filter(
        application=application
    ).last()

    if current_liveness_detection:
        if current_liveness_detection.status != LivenessCheckStatus.FEATURE_IS_OFF:
            logger.warning(
                'already_check_passive_liveness|application_id={}'.format(application.id)
            )
        return (
            LivenessCheckResponseStatus.ALREADY_CHECKED,
            PassiveLivenessCheckMessage.ALREADY_CHECKED,
        )

    configs = get_liveness_config(LivenessCheckType.PASSIVE)
    if not configs:
        return LivenessCheckResponseStatus.ERROR, ActiveLivenessCheckMessage.ERROR

    dot_api_version = get_api_version(configs)
    liveness_detection = PassiveLivenessDetection.objects.create(
        customer=customer,
        application=application,
        status=LivenessCheckStatus.INITIAL,
        image=image,
        configs=configs,
        api_version=dot_api_version,
    )

    if not async_detection:
        check_passive_liveness_async(image.id, application.id, liveness_detection.id, configs)
    else:
        check_passive_liveness_async.delay(image.id, application.id, liveness_detection.id, configs)

    return (LivenessCheckResponseStatus.SUCCESS, PassiveLivenessCheckMessage.SUCCESS)


def detect_face(
    liveness_detection: PassiveLivenessDetection,
    base64_image: str,
    configs: dict,
    application_id: int,
) -> tuple:
    elapsed = None
    try:
        result, elapsed, vendor_result = dot_core_client.check_passive_liveness(
            base64_image, configs
        )
        logger.info(
            'passive_liveness_detect_success|application={}, result={}'.format(
                application_id, result
            )
        )
    except (
        DotCoreServerError,
        DotCoreServerTimeout,
        DotCoreClientInternalError,
        DotCoreClientError,
    ) as error:
        sentry_client.captureException()
        (message,) = error.args
        error_code = None
        status = LivenessCheckStatus.ERROR
        if isinstance(error, (DotCoreServerError, DotCoreClientError)):
            elapsed = message['elapsed']
            error_code = message['response'].get('errorCode')
            if isinstance(error, DotCoreClientError):
                status = LivenessCheckStatus.FAILED
                liveness_detection.update_safely(
                    status=status, error_code=error_code, latency=elapsed
                )
                return (LivenessCheckResponseStatus.FAILED, ActiveLivenessCheckMessage.FAILED)
        elif isinstance(error, DotCoreServerTimeout):
            status = LivenessCheckStatus.TIMEOUT

        liveness_detection.update_safely(status=status, error_code=error_code, latency=elapsed)
        return (LivenessCheckResponseStatus.ERROR, ActiveLivenessCheckMessage.ERROR)

    try:
        passive_liveness_result = result['faces'][0]['faceAttributes']['passiveLiveness']
        if passive_liveness_result.get('score') is None:
            raise KeyError()
    except (KeyError, IndexError, TypeError):
        error_message = 'check_passive_liveness_incorrect_data|application={}, response={}'.format(
            application_id, result
        )
        logger.warning(error_message)
        liveness_detection.update_safely(
            status=LivenessCheckStatus.FAILED,
            error_code=result.get('errorCode', 'incorrect_data'),
            latency=elapsed,
            liveness_vendor_result=vendor_result,
        )
        return (LivenessCheckResponseStatus.FAILED, PassiveLivenessCheckMessage.FAILED)

    if passive_liveness_result['score'] < configs['score_threshold']:
        liveness_detection.update_safely(
            status=LivenessCheckStatus.FAILED,
            score=passive_liveness_result['score'],
            latency=elapsed,
            liveness_vendor_result=vendor_result,
        )
        return (LivenessCheckResponseStatus.FAILED, PassiveLivenessCheckMessage.FAILED)

    liveness_detection.update_safely(
        status=LivenessCheckStatus.PASSED,
        latency=elapsed,
        score=passive_liveness_result['score'],
        liveness_vendor_result=vendor_result,
    )
    return (LivenessCheckResponseStatus.SUCCESS, PassiveLivenessCheckMessage.SUCCESS)


def get_active_liveness_sequence(customer: Customer) -> tuple:
    application = customer.application_set.last()
    if (
        not application
        or (not application.is_julo_one() and not application.is_julo_starter())
        or application.status != ApplicationStatusCodes.FORM_CREATED
    ):
        return (
            LivenessCheckResponseStatus.APPLICATION_NOT_FOUND,
            ActiveLivenessCheckMessage.APPLICATION_NOT_FOUND,
        )

    current_liveness_detection = ActiveLivenessDetection.objects.filter(
        application=application
    ).last()
    if current_liveness_detection and current_liveness_detection.status not in (
        LivenessCheckStatus.INITIAL,
        LivenessCheckStatus.STARTED,
        LivenessCheckStatus.FAILED,
        LivenessCheckStatus.ERROR,
    ):
        return (
            LivenessCheckResponseStatus.ALREADY_CHECKED,
            ActiveLivenessCheckMessage.ALREADY_CHECKED,
        )

    configs = get_liveness_config(LivenessCheckType.ACTIVE)
    if current_liveness_detection and current_liveness_detection.status in (
        LivenessCheckStatus.FAILED,
        LivenessCheckStatus.ERROR,
    ):
        return LivenessCheckResponseStatus.SUCCESS, current_liveness_detection.sequence

    sequence = random_liveness_challenge_order(configs)
    if not sequence:
        if current_liveness_detection:
            current_liveness_detection.update_safely(status=LivenessCheckStatus.FEATURE_IS_OFF)
        return LivenessCheckResponseStatus.SUCCESS, []

    if not current_liveness_detection:
        dot_api_version = get_api_version(configs)
        ActiveLivenessDetection.objects.create(
            application=application,
            customer=customer,
            status=LivenessCheckStatus.INITIAL,
            sequence=sequence,
            api_version=dot_api_version,
            configs=configs,
        )
    else:
        current_liveness_detection.update_safely(sequence=sequence, configs=configs)

    return LivenessCheckResponseStatus.SUCCESS, sequence


def get_active_liveness_info(customer: Customer):
    application = Application.objects.filter(customer=customer).last()
    if not application:
        return

    liveness_detection = ActiveLivenessDetection.objects.filter(application=application).last()

    if not liveness_detection:
        return

    return {'status': liveness_detection.status, 'attempt': liveness_detection.attempt}


def get_android_app_license(is_encrypted=False):
    license_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LIVENESS_DETECTION_ANDROID_LICENSE, is_active=True
    )
    if not license_setting or not license_setting.parameters:
        return

    data = license_setting.parameters
    if is_encrypted:
        return encrypt_android_app_license(data)

    return data


def get_ios_app_license(is_encrypted=False):
    license_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LIVENESS_DETECTION_IOS_LICENSE, is_active=True
    )
    if not license_setting or not license_setting.parameters:
        return

    data = license_setting.parameters
    if is_encrypted:
        return encrypt_android_app_license(data)

    return data


def get_api_info(configs=None) -> dict:
    try:
        result = dot_core_client.get_api_info(configs)
    except Exception:
        sentry_client.captureException()
        return {}
    return result


def get_api_version(configs=None) -> str:
    api_info = get_api_info(configs)
    return api_info.get('build', {}).get('version', 'can not get the version')


def get_liveness_config(detection_type: str = None) -> dict:
    all_configs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.LIVENESS_DETECTION, is_active=True
    )
    if not all_configs:
        return {}
    if not detection_type:
        return all_configs.parameters

    configs = all_configs.parameters.get(detection_type, {})
    if not configs.get('is_active'):
        return {}

    return configs


def pre_check_liveness(customer, skip_customer=False, app_version=None, application_id=None):
    from juloserver.application_form.services.idfy_service import skip_liveness_detection

    application = (
        Application.objects.filter(id=application_id).last()
        if application_id
        else Application.objects.filter(customer=customer).last()
    )
    if not application or (not application.is_julo_one() and not application.is_julo_starter()):
        return {
            'active_liveness': False,
            'passive_liveness': False,
        }

    if application.is_idfy_approved():
        logger.info(
            {
                'message': 'Feature liveness skipped for this application',
                'application': application.id,
                'process': 'idfy_skip_liveness',
            }
        )
        skip_liveness_detection(application.id)
        return {
            'active_liveness': False,
            'passive_liveness': False,
        }

    configs = get_liveness_config()
    active_configs = configs.get(LivenessCheckType.ACTIVE, {})
    is_active_liveness_active = active_configs.get('is_active', False)
    is_passive_liveness_active = configs.get(LivenessCheckType.PASSIVE, {}).get('is_active', False)
    is_skip_app_version = app_version and configs.get('app_version_to_skip')
    if is_skip_app_version:
        if semver.match(app_version, "<=%s" % configs.get('app_version_to_skip')):
            is_active_liveness_active = False
            is_passive_liveness_active = False

    if application_id:
        if is_active_liveness_active:
            is_active_liveness_active = get_previous_active_liveness(application)
        if is_passive_liveness_active:
            is_passive_liveness_active = get_previous_passive_liveness(application)

    data = {
        'active_liveness': is_active_liveness_active,
        'passive_liveness': is_passive_liveness_active,
    }

    if is_active_liveness_active:
        data.update(
            active_liveness_retry=active_configs['retry'],
            valid_segment_count=active_configs['valid_segment_count'],
            application_eyes_detection_retry=active_configs['application_eyes_detection_retry'],
            application_face_detection_retry=active_configs['application_face_detection_retry'],
            application_face_detection_counter=active_configs['application_face_detection_counter'],
        )
    # TODO: remove is_reapply_app check if there is a handler for reapply application
    if skip_customer or not is_active_liveness_active or not is_passive_liveness_active:
        current_active_liveness = ActiveLivenessDetection.objects.filter(
            customer=customer, application=application
        ).last()
        is_max_retries_active = (
            True
            if is_active_liveness_active
            and current_active_liveness
            and current_active_liveness.attempt > active_configs['retry']
            else False
        )
        current_passive_liveness = PassiveLivenessDetection.objects.filter(
            customer=customer, application=application
        ).last()
        with transaction.atomic():
            if skip_customer:
                update_data = dict(
                    customer=customer,
                    application=application,
                    status=LivenessCheckStatus.SKIPPED_CUSTOMER,
                )
                if (
                    not current_passive_liveness
                    or current_passive_liveness.status != LivenessCheckStatus.SKIPPED_CUSTOMER
                ):
                    ActiveLivenessDetection.objects.create(**update_data)
                if not current_passive_liveness and not is_passive_liveness_active:
                    PassiveLivenessDetection.objects.create(**update_data)
                return data

            update_data = dict(
                customer=customer,
                application=application,
                status=LivenessCheckStatus.FEATURE_IS_OFF,
            )
            if (
                not current_active_liveness or not is_max_retries_active
            ) and not is_active_liveness_active:
                update_data.update(status=LivenessCheckStatus.FEATURE_IS_OFF)
                ActiveLivenessDetection.objects.create(**update_data)
            if not current_passive_liveness and not is_passive_liveness_active:
                update_data.update(status=LivenessCheckStatus.FEATURE_IS_OFF)
                PassiveLivenessDetection.objects.create(**update_data)

    return data


def get_valid_segments(segments: list) -> list:
    return [segment for segment in segments if segment.get('image')]


def random_liveness_challenge_order(configs) -> list:
    if not configs:
        return []

    segment_count = configs['valid_segment_count'] + configs['extra_segment_count']
    positions = copy.deepcopy(ActiveLivenessPosition.ALL)

    positions_len = len(positions)
    if segment_count < positions_len:
        return random.sample(positions, segment_count)

    random.shuffle(positions)
    positions_set = set(ActiveLivenessPosition.ALL)
    for i in range(positions_len, segment_count):
        j = i - positions_len + 1
        missing_position = positions_set - set(positions[j:i])
        positions.extend(list(missing_position))

    return positions


def start_active_liveness_process(customer: Customer) -> tuple:
    liveness_detection = ActiveLivenessDetection.objects.filter(customer=customer).last()
    if liveness_detection:
        if liveness_detection.attempt > 0:
            return LivenessCheckResponseStatus.STARTED, ActiveLivenessCheckMessage.STARTED
    if not liveness_detection or liveness_detection.status not in (
        LivenessCheckStatus.INITIAL,
        LivenessCheckStatus.STARTED,
    ):
        return (
            LivenessCheckResponseStatus.ACTIVE_LIVENESS_NOT_FOUND,
            ActiveLivenessCheckMessage.ACTIVE_LIVENESS_NOT_FOUND,
        )

    if liveness_detection.status != LivenessCheckStatus.STARTED:
        liveness_detection.update_safely(status=LivenessCheckStatus.STARTED)

    return LivenessCheckResponseStatus.STARTED, ActiveLivenessCheckMessage.STARTED


def rearrange_liveness_sequence(segments):
    n = len(segments)
    if not n:
        return segments

    count = {
        ActiveLivenessPosition.BOTTOM_LEFT: {'count': 0, 'segments': []},
        ActiveLivenessPosition.BOTTOM_RIGHT: {'count': 0, 'segments': []},
        ActiveLivenessPosition.TOP_LEFT: {'count': 0, 'segments': []},
        ActiveLivenessPosition.TOP_RIGHT: {'count': 0, 'segments': []},
    }
    for segment in segments:
        count[segment['dot_position']]['count'] += 1
        count[segment['dot_position']]['segments'].append(segment)

    max_count, max_pos = get_max_count(count, ActiveLivenessPosition.ALL)
    res = [None] * n
    ind = 0

    while count[max_pos]['count']:
        if ind >= n:
            break
        res[ind] = count[max_pos]['segments'].pop()
        ind += 2
        count[max_pos]['count'] -= 1

    remain_positions = position_lost_map[max_pos]
    for position in remain_positions:
        while count[position]['count'] > 0:
            if ind >= n:
                ind = 1
            res[ind] = count[position]['segments'].pop()
            ind += 2
            count[position]['count'] -= 1

    for i in range(n):
        if not res[i]:
            res[i] = count[max_pos]['segments'].pop()

    return res


def trigger_passive_liveness(application):
    """trigger after long form submission, when application status is 105"""
    active_liveness = ActiveLivenessDetection.objects.filter(application=application).last()
    if not active_liveness:
        logger.error('active_liveness_not_found|application_id={}'.format(application.id))
        return

    face_image = Image.objects.filter(
        image_source=application.id, image_type=ImageType.SELFIE
    ).last()
    if not face_image:
        logger.error(
            'application_flow_check_passive_liveness_image_not_found|'
            'application_id={}'.format(application.id)
        )
        return
    logger.info(
        'start_to_run_passive_liveness_check|application_id={}, face_image_id={}'.format(
            application.id, face_image.id
        )
    )
    return check_passive_liveness(face_image, application.customer)


def validate_active_liveness_sequence(
    segments: list, active_liveness_detection: ActiveLivenessDetection, min_segments_length: int
) -> list:
    current_sequence = active_liveness_detection.sequence
    for i in range(min(len(current_sequence), len(segments))):
        if current_sequence[i] != segments[i]['dot_position']:
            return []

    valid_segments = get_valid_segments(segments)
    valid_segments = rearrange_liveness_sequence(valid_segments)
    if len(valid_segments) < min_segments_length:
        return []

    return valid_segments[:min_segments_length]


def get_previous_active_liveness(application):
    active_liveness_detection = ActiveLivenessDetection.objects.filter(
        application=application
    ).last()

    return not (active_liveness_detection and active_liveness_detection.status == 'passed')


def get_previous_passive_liveness(application):
    passive_liveness_detection = PassiveLivenessDetection.objects.filter(
        application=application
    ).last()

    return not (passive_liveness_detection and passive_liveness_detection.status == 'passed')
