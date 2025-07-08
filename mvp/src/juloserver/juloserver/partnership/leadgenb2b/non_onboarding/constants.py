class LeadgenJ1RequestKeysMapping:
    LOAN_CREATION = {
        "loan_duration": "duration",
        "self_bank_account": "selfBankAccount",
        "bank_account_destination_id": "bankAccountDestination",
        "loan_purpose": "purpose",
        "loan_amount_request": "amountRequest",
        "partner": "partnerName",
        "account_id": "accountId",
        "gcm_reg_id": "gcmRegId",
        "android_id": "androidId",
        "transaction_type_code": "transactionTypeCode",
    }

    LOAN_CALCULATION = {
        "self_bank_account": "selfBankAccount",
        "loan_amount_request": "loanAmountRequest",
        "account_id": "accountId",
        "transaction_type_code": "transactionTypeCode",
        "is_dbr": "isDbr",
        "is_show_saving_amount": "isShowSavingAmount",
        "is_tax": "isTax",
    }

    DBR_CHECK = {
        "transaction_type_code": "transactionTypeCode",
        "monthly_installment": "installmentAmount",
        "first_monthly_installment": "firstInstallmentAmount",
    }


class LeadgenLoanCancelChangeReason:
    LEADGEN_INACTIVE_LOAN = "Leadgen process to 216 - inactive_loan"


class TransactionStatusLSP:
    IN_PROGRESS = 'in-progress'
    LATE = 'late'
    PAID_OFF = 'paid-off'
    PENDING = 'pending'
    SUCCESS = 'success'
    FAILED = 'failed'


class PaymentStatusLSP:
    NOT_DUE = 'not-due'
    LATE = 'late'
    PAID_ON_TIME = 'paid-on-time'
    PAID_LATE = 'paid-late'


class PaymentMethodTypes:
    BANK_VA = "Virtual Account"
    RETAIL = "Retail"
    E_WALLET = "E-Wallet"


class PaymentMethodName:
    PERMATA = 'PERMATA Bank'


class LeadgenLoanActionOptions:
    ACTIVE = 'active'
    IN_ACTIVE = 'in_active'
    PAID_OFF = 'paid-off'
