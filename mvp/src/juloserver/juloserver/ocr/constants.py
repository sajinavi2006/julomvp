from builtins import object

APPLICATION_KEY_MAPPING = {
    'nik': 'ktp',
    'nama': 'fullname',
    'jenis_kelamin': 'gender',
    'tempat_tanggal_lahir': 'tempat_tanggal_lahir',
    'provinsi': 'address_provinsi',
    'kabupaten': 'address_kabupaten',
    'alamat': 'address_street_num',
    'kelurahan': 'address_kelurahan',
    'kecamatan': 'address_kecamatan',
}

APPLICATION_FIELDS_TYPE = {
    'personal_info': ['fullname', 'gender', 'tempat_tanggal_lahir', 'ktp'],
    'address': [
        'address_provinsi',
        'address_kabupaten',
        'address_kelurahan',
        'address_street_num',
        'address_kecamatan',
    ],
}

GENDER_MAPPING = {'laki-laki': 'PRIA', 'perempuan': 'WANITA'}


class OCRFileUploadConst(object):
    UPLOAD_FILE_ERROR_MESSAGE = 'Invalid image'
    MAX_UPLOAD_FILE_SIZE = 5 * 1024 * 1024
    ALLOWED_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg"]
    ALLOWED_CHARACTER_PATTERN = r'^[a-zA-Z0-9_\-/.]+$'


class OCRProcessMsg(object):
    DONE = 'Done'
    DETECTOR_FAILED = 'Failed at object detection'
    FILTER_FAILED = 'Failed at personal info filter'
    RECOGNITION_FAILED = 'Failed at text recognition'


class OCRAPIResponseStatus:
    SUCCESS = 'success'
    FAIL = 'fail'


class OCRKTPExperimentConst:

    GROWTHBOOK = 'Growthbook'
    KEY_GROUP_NAME = 'value'
    KEY_CUSTOMER_ID = 'hash_value'
