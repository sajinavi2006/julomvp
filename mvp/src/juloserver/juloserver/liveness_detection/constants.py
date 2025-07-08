from enum import Enum

IMAGE_UPLOAD_MAX_SIZE = 5242880  # bytes
DEFAULT_CACHING_TIME = 300
DEFAULT_API_RETRY = 3


class ApplicationReasonFailed:
    NO_MORE_SEGMENTS = 'no_more_segments'
    EYES_NOT_DETECTED = 'eyes_not_detected'
    FACE_TRACKING_FAILED = 'face_tracking_failed'
    SEGMENT_DUPLICATED = 'segment_duplicated'
    INIT_FAILED = 'init_failed'


class ActiveLivenessCheckMessage:
    ALREADY_CHECKED = 'Your application already passed liveness detection'
    ERROR = 'Server error'
    SUCCESS = 'Success'
    FAILED = 'Failed'
    APPLICATION_NOT_FOUND = 'Application not found'
    SEQUENCE_INCORRECT = 'Position sequence is incorrect'
    ACTIVE_LIVENESS_NOT_FOUND = 'Active liveness not found'
    LIMIT_EXCEEDED = 'The number of attempts has reached the limit'
    STARTED = 'Started'


class ActiveLivenessPosition:
    TOP_LEFT = 'TOP_LEFT'
    TOP_RIGHT = 'TOP_RIGHT'
    BOTTOM_LEFT = 'BOTTOM_LEFT'
    BOTTOM_RIGHT = 'BOTTOM_RIGHT'
    ALL = [TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT]


class CacheKeys:
    API_INFO = {'key': 'liveness_api_info', 'timeout': 600}
    DDIS_API_INFO = {'key': 'ddis_liveness_api_info', 'timeout': 600}


class LivenessCheckStatus:
    INITIAL = 'initial'
    STARTED = 'started'
    PASSED = 'passed'
    FAILED = 'failed'
    ERROR = 'error'
    TIMEOUT = 'timeout'
    FEATURE_IS_OFF = 'feature_is_off'
    APPLICATION_DETECT_FAILED = 'application_detect_failed'
    SKIPPED_CUSTOMER = 'skipped_customer'
    REAPPLY = 'reapply'


class LivenessCheckHTTPStatus:
    HTTP_INTERNAL_SERVER_ERROR = 520
    HTTP_CONFLICT_STATUS = 409
    LIMIT_EXCEEDED = 429
    APPLICATION_DETECT_FAILED = 204


class LivenessCheckType:
    ACTIVE = 'active_liveness'
    PASSIVE = 'passive_liveness'


class LivenessCheckResponseStatus:
    SUCCESS = 'success'
    FAILED = 'failed'
    ERROR = 'error'
    APPLICATION_NOT_FOUND = 'application_not_found'
    SEQUENCE_INCORRECT = 'sequence_incorrect'
    ALREADY_CHECKED = 'already_checked'
    ACTIVE_LIVENESS_NOT_FOUND = 'active_liveness_not_found'
    LIMIT_EXCEEDED = 'limit_exceeded'
    APPLICATION_DETECT_FAILED = 'application_detect_failed'
    STARTED = 'started'
    SMILE_LIVENESS_NOT_FOUND = 'smile_liveness_not_found'
    SMILE_IMAGE_INCORRECT = 'smile_image_incorrect'
    FEATURE_IS_OFF = 'feature_is_off'
    LIVENESS_NOT_FOUND = 'liveness_not_found'


class PassiveLivenessCheckMessage:
    ALREADY_CHECKED = 'Your application already passed liveness detection'
    APPLICATION_NOT_FOUND = 'Application not found'
    ERROR = 'Server error'
    SUCCESS = 'Success'
    FAILED = 'Failed'


class LivenessVendor:
    INNOVATRICS = 'innovatrics'


class LivenessErrorCode:
    REMOTE_FILE_NOT_FOUND = 'internal_error_remote_file_not_found'
    NOT_TRIGGER_DETECTION = 'internal_error_not_run_detection'


position_lost_map = {
    ActiveLivenessPosition.TOP_LEFT: [
        ActiveLivenessPosition.TOP_RIGHT,
        ActiveLivenessPosition.BOTTOM_LEFT,
        ActiveLivenessPosition.BOTTOM_RIGHT,
    ],
    ActiveLivenessPosition.TOP_RIGHT: [
        ActiveLivenessPosition.TOP_LEFT,
        ActiveLivenessPosition.BOTTOM_LEFT,
        ActiveLivenessPosition.BOTTOM_RIGHT,
    ],
    ActiveLivenessPosition.BOTTOM_LEFT: [
        ActiveLivenessPosition.TOP_RIGHT,
        ActiveLivenessPosition.TOP_LEFT,
        ActiveLivenessPosition.BOTTOM_RIGHT,
    ],
    ActiveLivenessPosition.BOTTOM_RIGHT: [
        ActiveLivenessPosition.TOP_LEFT,
        ActiveLivenessPosition.TOP_RIGHT,
        ActiveLivenessPosition.BOTTOM_LEFT,
    ],
}


class SmileLivenessPicture(Enum):
    NEUTRAL = 'neutral'
    SMILE = 'smile'

    @classmethod
    def get_all_value(cls):
        return [item.value for item in cls]


class PassiveImagePicture(Enum):
    SELFIE = 'selfie'


class ActiveLivenessType:
    SMILE = 'smile'
    EYE_GAZE = 'eye-gaze'


class SmileLivenessCheckMessage:
    ALREADY_CHECKED = 'Your application already passed liveness detection'
    ERROR = 'Server error'
    SUCCESS = 'Success'
    FAILED = 'Failed'
    APPLICATION_NOT_FOUND = 'Application not found'
    IMAGE_INCORRECT = 'Images are incorrect'
    LIVENESS_NOT_FOUND = 'Liveness detection not found'
    LIMIT_EXCEEDED = 'The number of attempts has reached the limit'
    STARTED = 'Started'
    FEATURE_IS_OFF = 'Feature is off'


class ServiceCheckType:
    DDIS = 'dot_digital_identity'
    DCS = 'dot_core'


class ClientType:
    WEB = 'web'
    ANDROID = 'android'
    IOS = 'ios'


class ImageValueType:
    UPLOADED_ID = 'uploaded_id'
    FILE = 'file'


class ActiveLivenessMethod(Enum):
    EYE_GAZE = 'eye-gaze'
    SMILE = 'smile'
    MAGNIFEYE = 'magnifeye'


class NewLivenessCheckMessage:
    ALREADY_CHECKED = 'Your application already passed liveness detection'
    ERROR = 'Server error'
    SUCCESS = 'Success'
    FAILED = 'Failed'
    APPLICATION_NOT_FOUND = 'Application not found'
    IMAGE_INCORRECT = 'Images are incorrect'
    LIVENESS_NOT_FOUND = 'Liveness detection not found'
    LIMIT_EXCEEDED = 'The number of attempts has reached the limit'
    STARTED = 'Started'
    FEATURE_IS_OFF = 'Feature is off'


class InspectCustomerResult(Enum):
    VIDEO_INJECTED = 'video_injected'
    NOT_VIDEO_INJECTED = 'not_video_injected'
    SERVER_ERROR = 'server_error'


class NewLivenessImage:
    LIVENESS_IMAGE_TYPE = 'selfie'
    IMAGE_TYPE = 'selfie_check_liveness'
