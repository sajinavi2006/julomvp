
from builtins import object
class QismoConst(object):
    SIGNIN_PATH = '/api/v1/auth'
    AGENT_LIST_PATH = '/api/v1/admin/agents'
    ASSIGN_AGGENT_PATH = '/api/v1/admin/service/assign_agent'


# Advance AI blasklist check status
class BlacklistCheckStatus(object):
    PASS = 'PASS'
    NEEDS_VERIFICATION = 'NEEDS_VERIFICATION'
    REJECT = 'REJECT'
    INVALID_ID_NUMBER = 'INVALID_ID_NUMBER'
    INVALID_PHONE_NUMBER = 'INVALID_PHONE_NUMBER'


# Advance AI id check status
class IDCheckStatus(object):
    SUCCESS = 'SUCCESS'
    PERSON_NOT_FOUND = 'PERSON_NOT_FOUND'
    INVALID_ID_NUMBER = 'INVALID_ID_NUMBER'
    RETRY_LATER = 'RETRY_LATER'


class DigisignResultCode(object):
    SUCCESS = '00'
    BACK_OR_CANCEL = '01'
    DATA_NOT_FOUND = '05'
    GENERAL_ERROR = '06'
    CUSTOMER_NOT_ALLOWED_FOR_AUTOMATIC_SIGNING = '07'
    AUTHENTICATION_NOT_VALID = '12'
    EMAIL_OR_NIK_HAVE_REGISTERED = '14'
    DATA_REQUEST_INCOMPLETE = '28'
    FORMAT_REQUEST_IS_WRONG = '30'
    TOKEN_NOT_VALID = '55'
    INSUFFICIENT_BALANCE = '61'

    @classmethod
    def fail_to_145(cls):
        return [
            cls.BACK_OR_CANCEL,
            cls.DATA_NOT_FOUND,
            cls.GENERAL_ERROR,
            cls.CUSTOMER_NOT_ALLOWED_FOR_AUTOMATIC_SIGNING,
            cls.AUTHENTICATION_NOT_VALID,
            cls.FORMAT_REQUEST_IS_WRONG,
            cls.TOKEN_NOT_VALID,
            cls.INSUFFICIENT_BALANCE,
            cls.EMAIL_OR_NIK_HAVE_REGISTERED,
            cls.DATA_REQUEST_INCOMPLETE
        ]

    @classmethod
    def fail_to_147(cls):
        return [cls.AUTHENTICATION_NOT_VALID]

class DigisignResponseInfo(object):
    SYSTEM_FOUND_MORE_THAN_1_FACE = "System found more than 1 face on selfie photo"
    NO_FACE_FOUND_ON_SELFIE = "No face found on selfie photo"
    FACE_ON_SELFIE_OR_KTP_NOT_FOUND = (
        "Error, can't find face on selfie/KTP image. Make sure clearly foto and image is not inverted")
    NO_FACE_FOUND_ON_KTP = "No face found on KTP image"
    VERIFICATION_DATA_TEXT_FAIL = 'verifikasi data text gagal'
    DATA_KTP_NOT_FOUND = 'Data KTP tidak ditemukan'

    @classmethod
    def fail_info_to_147(cls):
        return [
            cls.SYSTEM_FOUND_MORE_THAN_1_FACE,
            cls.NO_FACE_FOUND_ON_SELFIE,
            cls.FACE_ON_SELFIE_OR_KTP_NOT_FOUND,
            cls.NO_FACE_FOUND_ON_KTP
        ]

    @classmethod
    def exclude_info(cls):
        return [
            cls.VERIFICATION_DATA_TEXT_FAIL,
            cls.DATA_KTP_NOT_FOUND,
        ]

class DigisignResponseCode(object):
    SUCCESS = 200
    TOKEN_OR_USER_ADMIN_NOT_VALID = 403
    USER_NOT_FOUND = 401
    DOCUMENT_NOT_FOUND = 404


# Product type provide by Sepulsa
class SepulsaProductType(object):
    MOBILE = 'mobile'
    ELECTRICITY = 'electricity'
    BPJS_KESEHATAN = 'bpjs_kesehatan'
    E_WALLET = 'ewallet'
    MOBILE_POSTPAID = 'mobile_postpaid'
    ELECTRICITY_POSTPAID = 'electricity_postpaid'
    PDAM = 'pdam'
    TRAIN_TICKET = 'train'
    E_WALLET_OPEN_PAYMENT = 'ewallet_open_payment'


class SMSPurpose(object):
    MARKETING = 'marketing'


class RedisKey:
    DOKU_CLIENT_ACCESS_TOKEN = 'doku:access_token'


class DOKUSnapResponseCode:
    SUCCESS_B2B_TOKEN = "2007300"
    SUCCESS_INQUIRY_STATUS = "2002600"
