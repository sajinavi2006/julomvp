DEFAULT_WAITING_DIGISIGN_CALLBACK_TIMEOUT_SECONDS = 10

class RegistrationStatus:
    ERROR = "error"
    REGISTERED = "registered"
    WAITING_VERIFICATION = "waiting_verification"
    VERIFIED = "verified"
    SOFT_REJECTED = "soft_rejected"
    HARD_REJECTED = "hard_rejected"
    INITIATED = "initiated"

    CHOICES = [
        (ERROR, ERROR),
        (REGISTERED, REGISTERED),
        (WAITING_VERIFICATION, WAITING_VERIFICATION),
        (VERIFIED, VERIFIED),
        (SOFT_REJECTED, SOFT_REJECTED),
        (HARD_REJECTED, HARD_REJECTED),
        (INITIATED, INITIATED),
    ]

    STATUS_CODE_MAPPING = {
        0: ERROR,
        1: REGISTERED,
        2: WAITING_VERIFICATION,
        3: VERIFIED,
        4: SOFT_REJECTED,
        5: HARD_REJECTED,
        6: INITIATED,
    }

    DONE_STATUS = {
        REGISTERED,
        VERIFIED,
    }

    @staticmethod
    def get_status(status_code):
        return RegistrationStatus.STATUS_CODE_MAPPING.get(status_code)


class RegistrationErrorCode:
    PROGRAM_ERROR = "program_error"
    USER_NOT_VERIFIED_YET = "user_not_verified_yet"
    USER_ALREADY_REGISTERED = "user_already_registered"
    REGISTRATION_TOKEN_NOT_FOUND = "registration_token_not_found"

    CHOICES = [
        (PROGRAM_ERROR, PROGRAM_ERROR),
        (USER_NOT_VERIFIED_YET, USER_NOT_VERIFIED_YET),
        (USER_ALREADY_REGISTERED, USER_ALREADY_REGISTERED),
        (REGISTRATION_TOKEN_NOT_FOUND, REGISTRATION_TOKEN_NOT_FOUND),
    ]


class SigningStatus:
    UPLOADED = 'uploaded'
    COMPLETED = 'completed'
    PROCESSING = 'processing'
    FAILED = 'failed' # used for internal
    INTERNAL_TIMEOUT = 'internal_timeout' # used for internal

    CHOICES = [
        (UPLOADED, UPLOADED),
        (COMPLETED, COMPLETED),
        (PROCESSING, PROCESSING),
        (FAILED, FAILED),
        (INTERNAL_TIMEOUT, INTERNAL_TIMEOUT),
    ]

    @classmethod
    def success(cls):
        return [cls.UPLOADED, cls.COMPLETED]

    @classmethod
    def allow_moving_statuses(cls):
        return {
            cls.PROCESSING: {cls.UPLOADED, cls.COMPLETED, cls.FAILED},
        }


class DocumentType:
    LOAN_AGREEMENT_BORROWER = 'loan_agreement_borrower'

    CHOICES = [
        (LOAN_AGREEMENT_BORROWER, LOAN_AGREEMENT_BORROWER),
    ]


class LoanAgreementSignature:
    defaults = {
        'j1': {'pos_x': 20, 'pos_y': 165, 'page': 10},
        'j_turbo': {'pos_x': 20, 'pos_y': 165, 'page': 10},
        'axiata_web': {'pos_x': 20, 'pos_y': 165, 'page': 7},
    }

    pos_x = None
    pos_y = None
    page = None

    @classmethod
    def _set_defaults(cls, pos_x_value=None, pos_y_value=None, page_value=None, sign_type='j1'):
        defaults = cls.defaults.get(sign_type, {})

        cls.pos_x = pos_x_value or defaults.get('pos_x', cls.pos_x)
        cls.pos_y = pos_y_value or defaults.get('pos_y', cls.pos_y)
        cls.page = page_value or defaults.get('page', cls.page)

        return cls.pos_x, cls.pos_y, cls.page

    @classmethod
    def j1(cls, sign_position=None):
        if sign_position:
            return cls._set_defaults(
                sign_position.get("pos_x"),
                sign_position.get("pos_y"),
                sign_position.get("page"),
                sign_type='j1'
            )
        return cls._set_defaults(sign_type='j1')

    @classmethod
    def j_turbo(cls, sign_position=None):
        if sign_position:
            return cls._set_defaults(
                sign_position.get("pos_x"),
                sign_position.get("pos_y"),
                sign_position.get("page"),
                sign_type='j_turbo'
            )
        return cls._set_defaults(sign_type='j_turbo')

    @classmethod
    def axiata_web(cls, sign_position=None):
        if sign_position:
            return cls._set_defaults(
                sign_position.get("pos_x"),
                sign_position.get("pos_y"),
                sign_position.get("page"),
            )
        return cls._set_defaults(sign_type='axiata_web')


class LoanDigisignErrorMessage:
    INTERNAL_CALLBACK_TIMEOUT = ("Waiting for callback too long, digisign timed out and loan "
                                 "switched to doodle")


class DigisignFeeTypeConst:
    REGISTRATION_DUKCAPIL_FEE_TYPE = 'REGISTRATION_DUKCAPIL_FEE'
    REGISTRATION_FR_FEE_TYPE = 'REGISTRATION_FR_FEE'
    REGISTRATION_LIVENESS_FEE_TYPE = 'REGISTRATION_LIVENESS_FEE'

    REGISTRATION_FEE_TYPE_CHOICES = (
        (REGISTRATION_DUKCAPIL_FEE_TYPE, 'Registration Dukcapil Fee'),
        (REGISTRATION_FR_FEE_TYPE, 'Registration FR Fee'),
        (REGISTRATION_LIVENESS_FEE_TYPE, 'Registration Liveness Fee'),
    )

    REGISTRATION_FEES = [
        REGISTRATION_DUKCAPIL_FEE_TYPE,
        REGISTRATION_FR_FEE_TYPE,
        REGISTRATION_LIVENESS_FEE_TYPE,
    ]

    # Mapping from the registration status api to the internal status
    REGISTRATION_STATUS_MAPPING_FEES = {
        'dukcapil_present': REGISTRATION_DUKCAPIL_FEE_TYPE,
        'fr_present': REGISTRATION_FR_FEE_TYPE,
        'liveness_present': REGISTRATION_LIVENESS_FEE_TYPE,
    }

    REGISTRATION_FEE_CREATED_STATUS = 'created'
    REGISTRATION_FEE_CHARGED_STATUS = 'charged'
    REGISTRATION_FEE_CANCELLED_STATUS = 'cancelled'

    REGISTRATION_FEE_STATUS_CHOICES = (
        (REGISTRATION_FEE_CREATED_STATUS, 'Registration Fee Created Status'),
        (REGISTRATION_FEE_CHARGED_STATUS, 'Registration Fee Charged Status'),
        (REGISTRATION_FEE_CANCELLED_STATUS, 'Registration Fee Cancelled Status'),
    )
