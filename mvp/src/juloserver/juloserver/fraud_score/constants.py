class BonzaConstants():
    APPLICATION_FIELDS = [
        'application_id', 'application_status', 'cdate',
        'close_kin_mobile_phone', 'close_kin_name', 'close_kin_relationship', 'company_address',
        'company_name', 'company_phone_number', 'customer_credit_limit', 'is_deleted',
        'job_description', 'job_function', 'job_industry', 'job_start', 'job_type', 'kin_dob',
        'kin_gender', 'kin_mobile_phone', 'kin_name', 'kin_relationship', 'loan_amount_request',
        'loan_duration_request', 'loan_purpose',
        'loan_purpose_desc', 'loan_purpose_description_expanded', 'mobile_phone_1',
        'mobile_phone_2', 'monthly_expenses', 'monthly_housing_cost', 'monthly_income',
        'name_in_bank', 'new_mobile_phone', 'spouse_dob', 'spouse_has_whatsapp',
        'spouse_mobile_phone', 'spouse_name', 'udate']

    APPLICATION_PHONE_FIELDS = ['mobile_phone_1', 'mobile_phone_2', 'close_kin_mobile_phone',
                                'kin_mobile_phone', 'spouse_mobile_phone', 'company_phone_number',
                                'new_mobile_phone']

    LOAN_TRANSACTION_FIELDS = [
        'application_id', 'disbursement_id', 'fund_transfer_ts', 'installment_amount',
        'loan_amount', 'loan_disbursement_amount', 'loan_disbursement_method',
        'loan_duration', 'loan_purpose', 'loan_status', 'loan_transaction_id', 'udate', 'cdate']

    LOAN_PAYMENT_FIELDS = [
        'cdate', 'due_amount', 'due_date', 'installment_interest',
        'installment_principal', 'late_fee_amount', 'late_fee_applied', 'loan_transaction_id',
        'loan_payment_id', 'paid_amount', 'paid_date', 'paid_interest', 'paid_late_fee',
        'paid_principal', 'udate', 'payment_number']

    DEFAULT_BONZA_SCORING_THRESHOLD_HARD_REJECT = 50
    DEFAULT_BONZA_SCORING_THRESHOLD_SOFT_REJECT = 33

    NON_ELIGIBLE_SCORE_HARD_REJECT = ("Untuk alasan keamanan maka transaksi kamu "
                                      "tidak dapat di proses. Mohon kontak cs JULO "
                                      "untuk lebih lanjut "
                                      "<br>"
                                      "<br>"
                                      "Email: <br>"
                                      "<strong> cs@julo.co.id <strong>")

    NON_ELIGIBLE_SCORE_SOFT_REJECT = ("Yah, sayang sekali! Transaksi gagal. <br>"
                                      "Silakan segera hubungi tim CS JULO "
                                      "<br>"
                                      "<br>"
                                      "Telepon: <br>"
                                      "<strong> 021-50919034 atau 021-50919038 <strong>")

    LOAN_PREDICTION_FIELDS = [
        'available_limit', 'first_limit', 'customer_id', 'cdate_loan',
        'loan_amount', 'loan_duration', 'loan_id', 'transaction_method_id',
        'installment_amount', 'application_id', 'loan_status_code']

    API_TIMEOUTS = {
        'application': 5,
        'loan_transaction': 5,
        'loan_payment': 5,
        'loan_scoring': 1.1,
        'inhouse_loan_scoring': 1.1,
        'inhouse_loan_storing': 5}

    HARD_REJECT_REASON = 'hard'
    SOFT_REJECT_REASON = 'soft'

    DEFAULT_REVERIFY_EXPIRY_DAYS = 180


class SeonConstant:
    class Target:
        APPLICATION = 'application'

    class Trigger:
        APPLICATION_SUBMIT = 'application_submit'


class RequestErrorType:
    HTTP_ERROR = 'http_error'
    CONNECT_TIMEOUT_ERROR = 'connect_timeout_error'
    READ_TIMEOUT_ERROR = 'read_timeout_error'
    CONNECTION_ERROR = 'connection_error'
    OTHER_ERROR = 'other_request_error'
    UNKNOWN_ERROR = 'unknown_error'


class MonnaiConstants:
    ADDRESS_VERIFICATION = 'ADDRESS_VERIFICATION'
    DEVICE_DETAILS = 'DEVICE_DETAILS'
    APP = 'APP'
    TIMESTAMPFORMAT = '%Y-%m-%dT%H:%M:%SZ'
    CONSENT_DETAILS = 'consentDetails'


class FraudPIIFieldTypeConst:
    NAME = 'name'
    EMAIL = 'email'
    PHONE_NUMBER = 'phone_number'
    KTP = 'ktp'

    class NameField:
        FIRST_NAME = 'first_name'
        MIDDLE_NAME = 'middle_name'
        LAST_NAME = 'last_name'


class FeatureNameConst:
    FRAUD_PII_MASKING = 'fraud_pii_masking'
    MOCK_MONNAI_INSIGHT = 'mock_monnai_insight'
    MOCK_MONNAI_URL = 'mock_monnai_url'
    MOCK_TRUST_GUARD_URL = 'mock_trust_guard_url'


class TrustGuardConst:
    EVENT_NEED_ACCOUNT_PARAM = ['LOGIN', 'OPEN_APP', 'APPLICATION']

    class EventType:
        LOGIN = ('LOGIN', 'login')
        OPEN_APP = ('OPEN_APP', 'login')
        APPLICATION = ('APPLICATION', 'register')
        TRANSACTION = ('TRANSACTION', 'loan')

    class DeviceType:
        ANDROID = 'android'
        IOS = 'ios'
