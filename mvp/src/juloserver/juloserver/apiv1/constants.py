from juloserver.julo.banks import BankCodes

EXCLUDE_BCA_BANK_CODES_WEB_FORM = [BankCodes.BCA, BankCodes.BCA_SYARIAH]

UPLOAD_IMAGE_GENERAL_ERROR = "Pastikan foto yang kamu gunakan dalam format PNG, JPG atau JPEG, ya!"


class ListImageTypes:
    """
    List image type not allowed to change in customer side
    If application already submit to x105
    """

    IMAGE_TYPES = ['ktp_self', 'selfie_check_liveness', 'crop_selfie', 'selfie', 'raw_ktp_ocr']
    KEY_PARAMETER_CONFIG = 'allow_app_status'
