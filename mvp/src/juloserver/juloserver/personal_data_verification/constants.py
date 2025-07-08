from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.personal_data_verification.serializers import (
    BureauApplicationEmailSerializer,
    BureauApplicationPhoneSerializer,
    BureauApplicationMobileIntelligenceSerializer
)

DUKCAPIL_TAB_CRM_STATUSES = [
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
]


DIRECT_DUKCAPIL_TAB_CRM_STATUSES = [ApplicationStatusCodes.SCRAPED_DATA_VERIFIED]

DUKCAPIL_DATA_NOT_FOUND_ERRORS = ['Data not found']

# Dukcapil Official API Constants

VERIFICATION_FIELDS = ['TGL_LHR', 'TMPT_LHR', 'NAMA_LGKP']
EXTRA_FIELDS = [
    'JENIS_KLMIN',
    'STATUS_KAWIN',
    'ALAMAT',
    'JENIS_PKRJN',
    'KAB_NAME',
    'KEC_NAME',
    'KEL_NAME',
    'PROP_NAME',
]

MIN_NO_OF_VERIFICATION_FIELDS_TO_PASS = 2

DUKCAPIL_KEY_MAPPING = {
    'TGL_LHR': 'birthdate',
    'TMPT_LHR': 'birthplace',
    'NAMA_LGKP': 'name',
    'JENIS_KLMIN': 'gender',
    'STATUS_KAWIN': 'marital_status',
    'ALAMAT': 'address_street',
    'JENIS_PKRJN': 'job_type',
    'KAB_NAME': 'address_kabupaten',
    'KEC_NAME': 'address_kecamatan',
    'KEL_NAME': 'address_kelurahan',
    'PROP_NAME': 'address_provinsi',
}


class FeatureNameConst(object):
    DUKCAPIL_VERIFICATION = 'dukcapil_verification'
    DUKCAPIL_BYPASS_TOGGLE = 'dukcapil_bypass_toggle'
    BUREAU_SERVICES = 'bureau_services'
    DUKCAPIL_VERIFICATION_LEADGEN = 'dukcapil_verification_leadgen'
    DUKCAPIL_BYPASS_TOGGLE_LEADGEN = 'dukcapil_bypass_toggle_leadgen'


class DukcapilFeatureMethodConst:
    ASLIRI = 'asliri'
    DIRECT = 'direct'
    DIRECT_V2 = 'direct_v2'


class DukcapilResponseSourceConst:
    ASLIRI = 'AsliRI'
    DIRECT = 'Dukcapil'


DUKCAPIL_METHODS = [
    DukcapilFeatureMethodConst.ASLIRI,
    DukcapilFeatureMethodConst.DIRECT,
    DukcapilFeatureMethodConst.DIRECT_V2,
]

DUKCAPIL_DIRECT_METHODS = [
    DukcapilFeatureMethodConst.DIRECT,
    DukcapilFeatureMethodConst.DIRECT_V2,
]


class DukcapilDirectConst:
    VERIFICATION_FIELDS = {
        'birthplace',
        'birthdate',
        'name',
    }


class DukcapilDirectError:
    EMPTY_QUOTA = 'EMPTY_QUOTA'
    API_TIMEOUT = 'API Timeout'
    FOUND_DEAD = '11'
    FOUND_DUPLICATE = '12'
    NOT_FOUND = '13'
    NOT_FOUND_INVALID_NIK = '15'
    FOUND_NON_ACTIVE = '14'

    @classmethod
    def not_eligible(cls):
        return (
            cls.FOUND_DEAD,
            cls.API_TIMEOUT,
            cls.NOT_FOUND,
            cls.NOT_FOUND_INVALID_NIK,
            cls.FOUND_DUPLICATE,
            cls.FOUND_NON_ACTIVE,
        )

    @classmethod
    def is_fraud(cls):
        return (cls.FOUND_DEAD,)


class DukcapilFRClient:
    ANDROID = 'JULOAndroidApp'
    IOS = 'JULOIOSApp'


DUKCAPIL_FR_TYPE = 'Face'
DUKCAPIL_FR_POSITION = 'F'
DUKCAPIL_FR_THRESHOLD = 1


class BureauConstants(object):
    EMAIL_SOCIAL = 'email-social'
    PHONE_SOCIAL = 'phone-social'
    MOBILE_INTELLIGENCE = 'mobile-intelligence'
    EMAIL_ATTRIBUTES = 'email-attributes'
    DEVICE_INTELLIGENCE = 'device-fingerprint'

    SERVICE_MODEL_MAPPING = {
        EMAIL_SOCIAL: 'BureauEmailSocial',
        PHONE_SOCIAL: 'BureauPhoneSocial',
        MOBILE_INTELLIGENCE: 'BureauMobileIntelligence',
        EMAIL_ATTRIBUTES: 'BureauEmailAttributes',
        DEVICE_INTELLIGENCE: 'BureauDeviceIntelligence'
    }

    SERVICE_SERIALIZER_MAPPING = {
        EMAIL_SOCIAL: BureauApplicationEmailSerializer,
        PHONE_SOCIAL: BureauApplicationPhoneSerializer,
        MOBILE_INTELLIGENCE: BureauApplicationMobileIntelligenceSerializer,
        EMAIL_ATTRIBUTES: BureauApplicationEmailSerializer
    }

    @classmethod
    def all_services(cls):
        return (
            cls.EMAIL_ATTRIBUTES,
            cls.EMAIL_SOCIAL,
            cls.PHONE_SOCIAL,
            cls.MOBILE_INTELLIGENCE,
            cls.DEVICE_INTELLIGENCE,
        )

    @classmethod
    def alternate_data_services(cls):
        return (
            cls.EMAIL_ATTRIBUTES,
            cls.EMAIL_SOCIAL,
            cls.PHONE_SOCIAL,
            cls.MOBILE_INTELLIGENCE,
        )

    @classmethod
    def sdk_services(cls):
        return (
            cls.DEVICE_INTELLIGENCE,
        )
