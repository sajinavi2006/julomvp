AUTHENTICATION_KEYWORD_HEADER = "Api-Key"


class ERROR_MESSAGE:
    API_KEY_NOT_PROVIDED = "No API Key provided."
    API_KEY_INCORRECT_FORMAT = "Incorrect API Key format."
    API_KEY_INVALID_DATA = "API Key was invalid"
    API_KEY_EXPIRED = "API Key has already expired."
    USER_TOKEN_INVALID_DATA = "User token was invalid."
    USER_TOKEN_EXPIRED = "User token has already expired."
    EXTERNAL_PARTY_NOT_FOUND = "No external party and matching with this API Key."
    EXTERNAL_PARTY_NOT_ACTIVE = "This external party is not active."
    USER_EXTERNAL_PARTY_NOT_FOUND = "No external party and user matching with this API Key."
    MSG_NIK_EMAIL_REQUIRED = "NIK and email are required."
    MSG_DATA_NOT_FOUND = "Data not found."
    USER_EXTERNAL_PARTY_EXPIRY_TIME = "Expiry time does not exceed 1 day or not less than today."
    USER_EXTERNAL_PARTY_IDENTIFIER_REQUIRED = "Identifier is required."
    USER_APPLICATION_NOT_FOUND = "Application not found."
    USER_IDENTIFIER_NOT_VALID = "Email is not allowed."
    USER_IDENTIFIER_MUST_BE_EMAIL = "identifier must be valid email."
    USER_IDENTIFIER_NOT_FOUND = "User not found."
    USER_IDENTIFIER_NOT_ALLOWED = "User identifier not allowed."
    ACCOUNT_NOT_FOUND = "Account was not found."
    LOAN_NOT_FOUND = "Loan was not found."
    USECASE_PARAM_INVALID = "Invalid use case."
    NEXT_PAYMENT_NOT_FOUND = "Next payment was not found."
    LAST_PAYMENT_NOT_FOUND = "Last payment was not found."
    OLDEST_UNPAID_PAYMENT_NOT_FOUND = "Last unpaid payment was not found."


ALLOWLISTED_EMAIL_DOMAIN = ["julofinance.com", "julo.co.id", "yellow.ai"]

YELLOW_API_USE_CASE = {
    "loan": [
        "loan_amount",
        "loan_duration",
        "installment_amount",
        "cashback_earned_total",
        "loan_disbursement_amount",
    ],
    "next_payment": [
        "due_date",
        "due_amount",
        "principal_amount",
        "interest_amount",
        "late_fee_amount",
    ],
    "last_payment": ["paid_date", "paid_amount"],
}
