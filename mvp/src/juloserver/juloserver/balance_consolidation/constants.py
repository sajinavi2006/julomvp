from juloserver.portal.object.dashboard.constants import JuloUserRoles

MAX_BALANCE_CONSOLIDATION_LOCK = 3
TOKEN_EXPIRATION_DAYS = 7
ELEMENTS_IN_TOKEN = 3


class BalanceConsolidationStatus:
    DRAFT = 'draft'
    ON_REVIEW = 'on_review'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    ABANDONED = 'abandoned'
    CANCELLED = 'cancelled'
    DISBURSED = 'disbursed'

    CHOICES = (
        (APPROVED, 'Approved'),
        (CANCELLED, 'Cancelled'),
        (REJECTED, 'Rejected'),
    )

    @classmethod
    def blocked_create_statuses(cls):
        return [cls.ON_REVIEW, cls.APPROVED, cls.DISBURSED]

    @classmethod
    def get_available_update_statuses(cls):
        return [
            cls.APPROVED,
            cls.CANCELLED,
            cls.REJECTED,
        ]

    @classmethod
    def get_allow_moving_status(cls):
        return {
            cls.DRAFT: {cls.ON_REVIEW, cls.REJECTED},
            cls.ON_REVIEW: {cls.APPROVED, cls.REJECTED, cls.CANCELLED},
            cls.APPROVED: {cls.ABANDONED, cls.DISBURSED},
            cls.REJECTED: set(),
            cls.ABANDONED: set(),
            cls.CANCELLED: set(),
            cls.DISBURSED: set(),
        }


class FileTypeUpload:
    PDF = '.pdf'

    @classmethod
    def valid_file_types(cls):
        return [cls.PDF]


class HTTPMethod:
    GET = "GET"
    POST = "POST"
    PUT = 'PUT'


class StatusResponse:
    SUCCESS = 'success'
    FAILED = 'failed'


class MessageBankNameValidation:
    Name_BANK_NOT_FOUND_AND_VERIFY_FIRST = 'Name bank validation not found, Please verify first.'
    BALANCE_CONSOLIDATION_NOT_FOUND = 'Balance consolidation not found.'
    SUBMIT_SUCCESS = 'Submit validation successful.'
    REFRESH_SUCCESS = 'Refresh successfully.'
    NAME_BANK_FAIL_CAUSE_APPROVED_CONSOLIDATION = (
        'Cannot validate name bank because balance consolidation is approved'
    )


class BalanceConsolidationMessageException:
    DATA_NOT_MATCH = 'The loan data not match with the balance consolidation.'
    NOT_FOUND = 'Balance consolidation not found.'
    INVALID_LOAN_AMOUNT = 'Invalid loan amount value'
    INVALID_LOAN_DATE = 'Invalid loan date value'


REQUIRED_GROUPS = [
    JuloUserRoles.DOCUMENT_VERIFIER,
    JuloUserRoles.BO_DATA_VERIFIER,
    JuloUserRoles.BO_SD_VERIFIER,
]


class BalanceConsolidationInfo:
    TITLE = 'Yuk, Tuntasin Tukar Tambah Limitmu!'
    MESSAGE = 'Selangkah lagi prosesnya selesai. Yuk, selesaikan sekarang dan kamu bisa nikmati limitmu di JULO!'


class BalanceConsolidationValidation:
    MIN_LOAN_OUTSTANDING_AMOUNT = 300000
    MIN_LOAN_PRINCIPAL_AMOUNT = 300000
    MAX_LOAN_OUTSTANDING_AMOUNT = 20000000
    MAX_LOAN_PRINCIPAL_AMOUNT = 20000000


class BalanceConsolidationFeatureName:
    BALANCE_CONS_TOKEN_CONFIG = 'balance_cons_token_config'
    BANK_WHITELIST = 'balance_cons_bank_whitelist'
    BALANCE_CONS_CRM_CONFIG = 'balance_cons_crm_config'


class UploadPDFFileMessage:
    WRONG_PDF_TYPE = 'The upload file must be a PDF type.'
    UPLOAD_SUCCESS = 'The upload file was uploaded successfully.'


class BalconLimitIncentiveConst:
    LIMIT_INCENTIVE_FS_NAME = 'limit_incentive_config'


class FeatureNameConst:
    BALANCE_CONSOLIDATION_FDC_CHECKING = 'balance_consolidation_fdc_checking'
    FETCH_FDC_DATA_DELAY = 'fetch_fdc_data_delay'
