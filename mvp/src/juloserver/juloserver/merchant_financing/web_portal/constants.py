from builtins import object

class WebPortalErrorMessage:
    SUCCESSFUL = 'Berhasil'
    SUCCESSFUL_LOGIN = 'Login berhasil'
    SUCCESSFUL_REGISTER = 'Pendaftaran berhasil'
    SUCCESSFUL_LOGOUT = 'You’ve Been Logged Out'
    INVALID_FIELD_FORMAT = 'Invalid Field Format'
    INVALID_LOGIN = 'Pastikan NIK dan password sesuai'
    INVALID_REGISTER = 'NIK atau Password tidak sesuai'
    INVALID_AUTH = 'Need Authentication credentials'


class DistributorUploadDetails(object):
    DISTRIBUTOR_CODE = 'distributor_code'
    DISTRIBUTOR_NAME = 'distributor_name'
    DISTRIBUTOR_BANK_NAME = 'distributor_bank_name'
    BANK_ACCOUNT = 'bank_account'
    BANK_NAME = 'bank_name'
    BANK_CODE = 'bank_code'
    CSV_HEADER_LIST = [
        'distributor code',
        'distributor_name',
        'distributor_bank_name',
        'bank_account',
        'bank_name',
        'bank_code'
    ]


DISTRIBUTOR_UPLOAD_MAPPING_FIELDS = [
    ("distributor code", DistributorUploadDetails.DISTRIBUTOR_CODE),
    ("distributor name", DistributorUploadDetails.DISTRIBUTOR_NAME),
    ("distributor bank name", DistributorUploadDetails.DISTRIBUTOR_BANK_NAME),
    ("bank account", DistributorUploadDetails.BANK_ACCOUNT),
    ("bank name", DistributorUploadDetails.BANK_NAME),
    ("bank code", DistributorUploadDetails.BANK_CODE),
]
