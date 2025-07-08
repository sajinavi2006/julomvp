from builtins import object
from juloserver.julo.constants import OnboardingIdConst


class ValidateNIKEmail(object):
    ERROR_MESSAGE = (
        "Nomor handphone bermasalah. "
        "Jika ada masalah dengan nomor handphone kamu "
        "saat proses masuk/daftar, silakan hubungi CS "
        "untuk info lebih lanjut. <br><br>Telepon:</br></br>"
        "<br>021-5091 9034 / 021-5091 9035</br>"
        "<br><br>Email:</br></br><br>cs@julo.co.id</br>"
    )


class RegistrationByOnboarding:

    API_V2 = (
        OnboardingIdConst.LONGFORM_ID,
        OnboardingIdConst.LONGFORM_SHORTENED_ID,
        OnboardingIdConst.LF_REG_PHONE_ID,
        OnboardingIdConst.LFS_REG_PHONE_ID,
        OnboardingIdConst.JULO_STARTER_FORM_ID,
        OnboardingIdConst.JULO_360_EXPERIMENT_ID,
    )

    API_V3 = (
        OnboardingIdConst.LONGFORM_ID,
        OnboardingIdConst.LONGFORM_SHORTENED_ID,
        OnboardingIdConst.LF_REG_PHONE_ID,
        OnboardingIdConst.LFS_REG_PHONE_ID,
        OnboardingIdConst.JULO_STARTER_ID,
        OnboardingIdConst.JULO_360_EXPERIMENT_ID,
        OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT,
    )

    API_V4 = API_V3
    API_V5 = API_V3
    API_V6 = API_V5


class DefinedRegistrationClassName:

    API_V2 = 'RegisterJuloOneUserV2'
    API_V3 = 'RegisterUserV3'
    API_V4 = 'RegisterUserV4'
    API_V5 = 'RegisterUserV5'
    API_V6 = 'RegisterUserV6'
    API_SYNC_REGISTER = 'SyncRegisterUser'


class ConfigUserJstarterConst:
    """
    Key parameters in Feature Setting
    specific_user_for_jstarter
    """

    OPERATION_KEY = 'operation'
    VALUE_KEY = 'value'

    CONTAIN_KEY = 'contain'
    EQUAL_KEY = 'equal'


NEW_FDC_FLOW_APP_VERSION = '8.11.0'


class BypassGoogleAuthServiceConst:

    BYPASS_EMAIL_EQUAL = 'bypass_email_equal'
    BYPASS_EMAIL_PATTERN = 'bypass_email_pattern'


class SyncRegistrationConst:

    SYNC_J360_TO_REGULAR_FLOW = 'sync_j360_to_regular_flow'
    SYNC_REGULAR_TO_J360_FLOW = 'sync_regular_to_j360_flow'


class ErrorMsgCrossDevices:

    TITLE = "Kamu Tidak Bisa Masuk dengan HP Ini"
    BUTTON_MSG = "Kembali"

    PARAMETERS = {
        "android_to_iphone": {
            "title": TITLE,
            "message": "Silakan gunakan Androidmu untuk "
            "masuk ke JULO dan selesaikan dulu proses pendaftarannya. "
            "Jika sudah tak ada akses ke HP sebelumnya, "
            "silakan kontak CS kami, ya!",
            "button": BUTTON_MSG,
            "link_image": None,
        },
        "iphone_to_android": {
            "title": TITLE,
            "message": "Silakan gunakan iPhonemu untuk "
            "masuk ke JULO dan selesaikan dulu proses pendaftarannya. "
            "Jika sudah tak ada akses ke HP sebelumnya, "
            "silakan kontak CS kami, ya!",
            "button": BUTTON_MSG,
            "link_image": None,
        },
    }


class StatusCrossDevices:

    KEY_STATUS_CODE = 'status_code'
    KEY_EXPIRY_STATUS_CODE = 'expiry_status_code'
