IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp']
LIVENESS_UPLOAD_IMAGE_MAX_SIZE = 1024 * 1024 * 8  # Max size upload 8 MB


class LivenessType(object):
    PASSIVE = 'passive'
    SMILE = 'smile'


class LivenessImageService(object):
    S3 = 's3'
    OSS = 'oss'


class LivenessImageStatus(object):
    INACTIVE = -1
    ACTIVE = 0
    RESUBMISSION_REQ = 1


class LivenessHTTPGeneralErrorMessage(object):
    INTERNAL_SERVER_ERROR = 'Kesalahan server internal.'
    UNAUTHORIZED = 'Autentikasi tidak valid atau tidak ditemukan.'
    INVALID_REQUEST = 'Permintaan tidak valid.'
    HTTP_METHOD_NOT_ALLOWED = 'Metode Tidak Diizinkan.'
    FORBIDDEN_ACCESS = 'Akses tidak diizinkan'
    NOT_ALLOWED_IMAGE_SIZE = "Ukuran file terlalu besar, maksimal file 8 MB"
    INVALID_FILE = "file tidak valid"


class ImageLivenessType(object):
    PASSIVE = 'passive'
    SMILE = 'smile'
    NEUTRAL = 'neutral'


class LivenessResultStatus(object):
    SUCCESS = 'success'
    FAILED = 'failed'


class LivenessResultMappingStatus(object):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
