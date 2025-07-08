class ProcessJuloversStatus:
    SUCCESS = 'success'
    EMAIL_EXISTED = 'email existed'
    PHONE_NUMBER_EXISTED = 'phone number_existed'


class JuloverConst:
    DEFAULT_CREDIT_SCORE = 'A'
    DEFAULT_CYCLE_PAYDAY = 31
    DEFAULT_MAX_DURATION = 4
    DEFAULT_INTEREST = 0


class JuloverReason:
    LIMIT_GENERATION = 'Julover Limit Generation From Set Limit'
    CREDIT_SCORE_GENERATION = 'Julover Credit Score Generation'


class JuloverPageConst:
    EMAIL_AT_190 = 'email_at_190'

    CHOICES = (
        (EMAIL_AT_190, 'Notification Email Content At 190'),
    )
