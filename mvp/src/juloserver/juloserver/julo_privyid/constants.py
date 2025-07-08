from builtins import object
PRIVY_IMAGE_TYPE = {
    'ktp': 'ktp_self',
    'selfie': 'crop_selfie',
    'ktp_reupload': 'ktp_self_ops',
    'selfie_reupload': 'selfie_ops',

    'ktp_privy': 'ktp_privy',
    'selfie_privy': 'just_selfie_privy',
    'sim_privy': 'drivers_license_privy',
    'kk_privy': 'foto_kartu_keluraga_privy',
    'ektp_privy': 'e_ktp_privy',
    'selfie_dengan_ktp_privy': 'selfie_privy',
    'passport_privy': 'passport_privy',
    'passport_selfie_privy': 'passport_selfie_privy'
    }


class CustomerStatusPrivy(object):
    WAITING = 'waiting'
    REJECTED = 'rejected'
    VERIFIED = 'verified'
    REGISTERED = 'registered'
    INVALID = 'invalid'
    ALLOW_UPLOAD = [VERIFIED, REGISTERED]


class DocumentStatusPrivy(object):
    COMPLETED = "Completed"
    IN_PROGRESS = "In Progress"


class PrivyReUploadCodes(object):
    CATEGORY_KTP = 'KTP'
    CATEGORY_SELFIE = 'SELFIE'
    CATEGORY_FILE_FORMAT = 'FILE-SUPPORT'

    KTP = 'KTP_CODES'
    KK = 'KK_CODES'
    E_KTP = 'E_KTP_CODES'
    DRIVING_LICENSE = 'DRIVER_LICENSE_CODES'
    REJECTED = 'REJECTED_CODES'
    SELFIE = 'SELFIE_CODES'
    SELFIE_WITH_KTP = 'SELFIE_WITH_KTP_CODES'
    PASSPORT = 'PASSPORT'
    PASSPORT_SELFIE = 'PASSPORT_SELFIE'

    LIST_CODES = [KTP, KK, E_KTP, DRIVING_LICENSE, SELFIE, SELFIE_WITH_KTP,
                  PASSPORT, PASSPORT_SELFIE]

    IMAGE_MAPPING = {
        KTP: 'ktp_privy',
        E_KTP: 'ektp_privy',
        SELFIE: 'selfie_privy',
        SELFIE_WITH_KTP: 'selfie_dengan_ktp_privy',
        DRIVING_LICENSE: 'sim_privy',
        KK: 'kk_privy',
        PASSPORT: 'passport_privy',
        PASSPORT_SELFIE: 'passport_selfie_privy'
    }
