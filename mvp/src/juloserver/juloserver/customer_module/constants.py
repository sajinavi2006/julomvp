from builtins import object
from datetime import datetime
from juloserver.account.constants import AccountConstant
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
)
from django.conf import settings


# customer fields mapping to application fields
CUSTOMER_APPLICATION_MAP_FIELDS = {
    'app_version': 'app_version',
    'web_version': 'web_version',
    'current_application_id': 'id',
    'current_application_xid': 'application_xid',
    'application_number': 'application_number',
    'application_is_deleted': 'is_deleted',
    'application_status_id': 'application_status_id',
    'onboarding_id': 'onboarding_id',
    'product_line_id': 'product_line_id',
    'partner_id': 'partner_id',
    'workflow_id': 'workflow_id',
    'loan_purpose': 'loan_purpose',
    'marketing_source': 'marketing_source',
    'referral_code': 'referral_code',
    'address_detail': 'address_detail',
    'gender': 'gender',
    'dob': 'dob',
    'address_street_num': 'address_street_num',
    'address_provinsi': 'address_provinsi',
    'address_kabupaten': 'address_kabupaten',
    'address_kecamatan': 'address_kecamatan',
    'address_kelurahan': 'address_kelurahan',
    'address_kodepos': 'address_kodepos',
    'mobile_phone_2': 'mobile_phone_2',
    'marital_status': 'marital_status',
    'spouse_name': 'spouse_name',
    'spouse_mobile_phone': 'spouse_mobile_phone',
    'kin_name': 'kin_name',
    'kin_mobile_phone': 'kin_mobile_phone',
    'kin_relationship': 'kin_relationship',
    'close_kin_mobile_phone': 'close_kin_mobile_phone',
    'close_kin_name': 'close_kin_name',
    'close_kin_relationship': 'close_kin_relationship',
    'birth_place': 'birth_place',
    'last_education': 'last_education',
    'job_type': 'job_type',
    'job_description': 'job_description',
    'job_industry': 'job_industry',
    'job_start': 'job_start',
    'company_name': 'company_name',
    'company_phone_number': 'company_phone_number',
    'payday': 'payday',
    'monthly_income': 'monthly_income',
    'monthly_expenses': 'monthly_expenses',
    'total_current_debt': 'total_current_debt',
    'teaser_loan_amount': 'teaser_loan_amount',
    'bank_name': 'bank_name',
    'name_in_bank': 'name_in_bank',
    'bank_account_number': 'bank_account_number',
    'name_bank_validation_id': 'name_bank_validation_id',
    'is_term_accepted': 'is_term_accepted',
    'is_verification_agreed': 'is_verification_agreed',
    'is_document_submitted': 'is_document_submitted',
    'is_courtesy_call': 'is_courtesy_call',
    'is_assisted_selfie': 'is_assisted_selfie',
    'is_fdc_risky': 'is_fdc_risky',
    'bss_eligible': 'bss_eligible',
    'current_device_id': 'device_id',
    'application_merchant_id': 'merchant_id',
    'application_company_id': 'company_id',
    'monthly_housing_cost': 'monthly_housing_cost',
    'loan_purpose_desc': 'loan_purpose_desc',
}


class BankAccountCategoryConst(object):
    SELF = 'self'
    ECOMMERCE = 'ecommerce'
    PARTNER = 'partner'
    INSTALLMENT = 'installment'
    FAMILY = 'family'
    OTHER = 'other'
    EDUCATION = 'edukasi'
    BALANCE_CONSOLIDATION = 'balance_consolidation'
    HEALTHCARE = 'healthcare'
    EWALLET = 'e-wallet'

    @classmethod
    def transfer_dana_categories(cls):
        return [cls.PARTNER, cls.INSTALLMENT, cls.FAMILY, cls.OTHER]


class CashbackBalanceStatusConstant:
    FREEZE = 'freeze'
    UNFREEZE = 'unfreeze'


class AppActionFlagConst(object):
    UNIDENTIFIED = 'Unidentified'
    INSTALLED = 'Installed'
    NOT_INSTALLED = 'Not Installed'
    INSTALLED_CRITERIA_EVENT_NAMES = ('first_open', 'session_start')
    NOT_INSTALLED_CRITERIA_EVENT_NAME = 'app_remove'
    UNINSTALLED_AND_UNIDENTIFIED_APP = 'uninstalled_and_unidentified_app'


class ChangeCustomerPrimaryPhoneMessages:
    SUCCESS = (
        "Nomor HP telah disimpan. Demi keamanan, "
        "silakan kembali login untuk melanjutkan "
        "proses perubahan nomor HP. Cek kembali "
        "halaman profile kamu, ya."
    )

    FAILED_DUPLICATE = (
        "Kamu tidak berhasil melakukan perubahan "
        "nomor HP. Hubungi cs@julo.co.id "
        "atau customer service untuk bantuan."
    )


class FeatureNameConst(object):
    ALLOW_MULTIPLE_VA = 'allow_multiple_va'
    VALIDITY_TIMER = 'validity_timer'
    CX_DETOKENIZE = 'cx_detokenize'


class MasterAgreementConst(object):
    FOOTER_URL = 'footer.png'
    SUBJECT = 'JULO'
    TEMPLATE = 'master_agreement_email.html'
    EMAIL_FROM = 'cs@julo.co.id'
    NAME_FROM = 'JULO'
    PHONE_1 = '021-50919034'
    PHONE_2 = '021-50919035'


class AccountDeletionRequestStatuses:
    PENDING = 'pending'
    REJECTED = 'rejected'
    APPROVED = 'approved'
    CANCELLED = 'cancelled'
    FAILED = 'failed'
    #  we treat like success and not vedict_date =>  auto_approved
    SUCCESS = 'success'
    # reverted => failed status
    REVERTED = 'reverted'
    # we treat like success and vedict_date =>  auto_approved
    AUTO_APPROVED = 'auto_approved'
    MANUAL_DELETED = 'manual_deleted'


class FailedAccountDeletionRequestStatuses:
    NOT_EXISTS = 'NOT_EXISTS'
    LOANS_ON_DISBURSEMENT = 'LOANS_ON_DISBURSEMENT'
    ACTIVE_LOANS = 'HAS_ACTIVE_LOANS'
    ACCOUNT_NOT_ELIGIBLE = 'ACCOUNT_NOT_ELIGIBLE'
    APPLICATION_NOT_ELIGIBLE = 'APPLICATION_NOT_ELIGIBLE'
    EMPTY_REASON = 'EMPTY_REASON'
    EMPTY_DETAIL_REASON = 'EMPTY_DETAIL_REASON'
    INVALID_DETAIL_REASON = 'INVALID_DETAIL_REASON'


ongoing_account_deletion_request_statuses = [
    AccountDeletionRequestStatuses.PENDING,
    AccountDeletionRequestStatuses.APPROVED,
    AccountDeletionRequestStatuses.AUTO_APPROVED,
]

forbidden_application_status_account_deletion = [
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
]

forbidden_account_status_account_deletion = [
    JuloOneCodes.ACTIVE_IN_GRACE,
    JuloOneCodes.OVERLIMIT,
    JuloOneCodes.SUSPENDED,
    JuloOneCodes.TERMINATED,
    JuloOneCodes.FRAUD_REPORTED,
    JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
    JuloOneCodes.SCAM_VICTIM,
    JuloOneCodes.FRAUD_SOFT_REJECT,
    JuloOneCodes.FRAUD_SUSPICIOUS,
    JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW,
]

forbidden_loan_status_account_deletion = [
    LoanStatusCodes.LENDER_APPROVAL,
    LoanStatusCodes.FUND_DISBURSAL_ONGOING,
    LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
    LoanStatusCodes.FUND_DISBURSAL_FAILED,
]


soft_delete_account_status_account_deletion = [
    JuloOneCodes.INACTIVE,
    JuloOneCodes.ACTIVE_IN_GRACE,
    JuloOneCodes.OVERLIMIT,
    JuloOneCodes.SUSPENDED,
    JuloOneCodes.DEACTIVATED,
    JuloOneCodes.TERMINATED,
    JuloOneCodes.FRAUD_REPORTED,
    JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
    JuloOneCodes.SCAM_VICTIM,
    JuloOneCodes.FRAUD_SOFT_REJECT,
    JuloOneCodes.FRAUD_SUSPICIOUS,
]

soft_delete_application_status_account_deletion = [
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
]


class AccountDeletionStatusChangeReasons:
    REQUEST_REASON = 'account deletion request'
    CANCEL_REASON = 'cancel account deletion request'
    CANCELED_BY_AGENT = 'canceled account deletion request by agent'


class CustomerDataChangeRequestConst:
    class PermissionStatus:
        """
        Eligibility status to submit customer data change request form
        """

        DISABLED = 'disabled'
        ENABLED = 'enabled'
        NOT_ALLOWED = 'not_allowed'

    class SubmissionStatus:
        """
        Status of customer data change request form submission
        """

        SUBMITTED = 'submitted'
        APPROVED = 'approved'
        REJECTED = 'rejected'

        @classmethod
        def approval_choices(cls):
            return (
                (cls.APPROVED, 'Approved'),
                (cls.REJECTED, 'Rejected'),
            )

    class Source:
        """
        Source of customer data change request form submission
        """

        APP = 'app'
        ADMIN = 'admin'
        DBR = 'dbr'

    class NudgeMessage:
        WAITING_FOR_APPROVAL = {
            "type": "warning",
            "message": (
                "Perubahan data pribadi sedang diverifikasi. "
                "Kamu akan menerima notifikasi setelah proses selesai."
            ),
            "closeable": False,
        }

    class ValidationMessage:
        REQUIRED_FIELD_EMPTY = "%s kamu perlu diperbarui"

    class Field:
        LABEL_MAP = {
            'address': 'Alamat Tempat Tinggal',
            'job_type': 'Tipe Pekerjaan',
            'job_industry': 'Bidang Pekerjaan',
            'job_description': 'Posisi Pekerjaan',
            'company_name': 'Nama Perusahaan',
            'company_phone_number': 'Nomor Telepon Perusahaan',
            'payday': 'Tanggal Gajian',
            'monthly_income': 'Total Penghasilan Bulanan',
            'monthly_expenses': 'Total Pengeluaran Rumah Tangga Bulanan',
            'monthly_housing_cost': 'Total Cicilan/Sewa Rumah Bulanan',
            'total_current_debt': 'Total Cicilan Hutang Bulanan',
            'last_education': "Pendidikan Terakhir",
        }
        REQUIRED_FIELD = ["address_kodepos", "last_education"]

    class ErrorMessages:
        TextField = (
            'Pastikan format penulisan kamu hanya mengandung '
            + 'huruf, angka, dan karakter tertentu (.,-@/), ya!'
        )
        AlphaField = 'Pastikan format penulisan kamu hanya mengandung huruf, ya!'

    ALLOWED_APPLICATION_STATUSES = [
        ApplicationStatusCodes.LOC_APPROVED,
        ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
        ApplicationStatusCodes.CUSTOMER_ON_DELETION,
    ]


active_loan_status = [
    LoanStatusCodes.CURRENT,
    LoanStatusCodes.LOAN_1DPD,
    LoanStatusCodes.LOAN_5DPD,
    LoanStatusCodes.LOAN_30DPD,
    LoanStatusCodes.LOAN_60DPD,
    LoanStatusCodes.LOAN_90DPD,
    LoanStatusCodes.LOAN_120DPD,
    LoanStatusCodes.LOAN_150DPD,
    LoanStatusCodes.LOAN_180DPD,
    LoanStatusCodes.LOAN_4DPD,
    LoanStatusCodes.RENEGOTIATED,
    LoanStatusCodes.HALT,
]

loan_status_not_allowed = active_loan_status + forbidden_loan_status_account_deletion


pending_loan_status_codes = tuple(
    set(PaymentStatusCodes.paid_status_codes() + PaymentStatusCodes.paylater_paid_status_codes())
)

forbidden_account_status = [
    AccountConstant.STATUS_CODE.active_in_grace,
    AccountConstant.STATUS_CODE.overlimit,
    AccountConstant.STATUS_CODE.suspended,
    AccountConstant.STATUS_CODE.terminated,
    AccountConstant.STATUS_CODE.fraud_reported,
    AccountConstant.STATUS_CODE.application_or_friendly_fraud,
    AccountConstant.STATUS_CODE.scam_victim,
    AccountConstant.STATUS_CODE.fraud_soft_reject,
    AccountConstant.STATUS_CODE.fraud_suspicious,
]

disabled_feature_setting_account_deletion = [
    "autodebet_reminder_setting",
]

ongoing_account_deletion_request_statuses = [
    AccountDeletionRequestStatuses.PENDING,
    AccountDeletionRequestStatuses.APPROVED,
    AccountDeletionRequestStatuses.AUTO_APPROVED,
]


class InAppAccountDeletionTitleConst:
    APPROVED = 'Akun Berhasil Dihapus'
    REJECTED = 'Permintaan Hapus Akun Ditolak'
    GENERAL_REJECTED = 'Akun tidak dapat dihapus'


class InAppAccountDeletionMessagesConst:
    APPROVED = 'Customer ID {} berhasil dihapus'
    REJECTED = 'Permintaan untuk menghapus Customer ID {} berhasil ditolak'
    CUSTOMER_DEACTIVATED = 'Customer ID {} tidak ditemukan karena telah dihapus'
    ACTIVE_LOAN = 'Terdapat pinjaman aktif'
    FORBIDDEN_ACCOUNT_STATUS = 'Status akun tidak diperbolehkan untuk dihapus'
    FORBIDDEN_APPLICATION_STATUS = 'Status aplikasi tidak diperbolehkan untuk dihapus'
    INVALID_SERIALIZER = 'Silakan periksa input kembali'
    INACTIVE_CUSTOMER = 'Customer ID {} tidak ditemukan'
    REQUEST_NOT_FOUND = 'Request tidak tersedia'
    SURVEY_MUST_BE_FILLED = 'Silahkan isi survey terlebih dahulu'


class ChangePhoneLostAccess:
    class SuccessMessages:
        DEFAULT = (
            "Kami sudah kirimkan email ke {email} terkait permintaan ubah nomor HP kamu. "
            + "Cek di semua folder email kamu, ya!"
        )

    class ErrorMessages:
        TYPE_BOTTOM_SHEET = "type_1"
        TYPE_SNACK_BAR = "type_2"
        DEFAULT = (
            "Maaf, saat ini permintaan ubah nomor hp belum bisa dilakukan. Coba lagi lain kali, ya."
        )
        CREDENTIAL_ERROR = 'Pastikan informasi yang kamu masukkan benar'
        RATE_LIMIT_ERROR = (
            'Permintaan ubah nomor hp sudah mencapai batas maksimum. '
            + 'Coba lagi di hari berikutnya, ya.'
        )

    FORBIDDEN_APPLICATION_STATUS = [
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
    ]

    FORBIDDEN_ACCOUNT_STATUS = [
        JuloOneCodes.DEACTIVATED,
        JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW,
        JuloOneCodes.ACTIVE_IN_GRACE,
        JuloOneCodes.OVERLIMIT,
        JuloOneCodes.SUSPENDED,
        JuloOneCodes.TERMINATED,
        JuloOneCodes.FRAUD_REPORTED,
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
        JuloOneCodes.SCAM_VICTIM,
        JuloOneCodes.FRAUD_SOFT_REJECT,
        JuloOneCodes.FRAUD_SUSPICIOUS,
    ]


class RequestPhoneNumber:
    class PopUpDetail:
        RESET_KEY_EXPIRED = {
            "title": "Link Ubah Nomor Kadaluwarsa",
            "message": "Cek email terbaru dari JULO dan buka link untuk ubah nomor HP kamu, ya!",
        }
        INVALID_RESET_KEY = {
            "title": "Ubah Nomor HP Gagal",
            "message": "Kembali ke aplikasi JULO dan klik Ubah Nomor HP di halaman "
            + "Pusat Bantuan untuk coba lagi, ya!",
        }
        PHONE_NUMBER_EXISTS = {"message": "Pastikan informasi yang kamu masukan benar"}


class AgentDataChange:
    feature_name = 'data_change_by_agent'

    class Field:
        Phone = 'phone'
        Email = 'email'
        BankAccountNumber = 'bank_account_number'

    @classmethod
    def map_ajax_field_change(cls, field):
        if field == 'mobile_phone_1':
            return cls.Field.Phone
        elif field == 'email':
            return cls.Field.Email
        elif field == 'bank_account_number':
            return cls.Field.BankAccountNumber
        else:
            return None


class EmailChange:
    OUTDATED_OLD_VERSION = (
        "Fitur Ubah Email hanya dapat diakses dengan aplikasi versi terbaru."
        "Update JULO dulu, yuk! Untuk info lebih lanjut hubungi CS: \n\n"
        "Telepon: \n"
        "021-5091 9034/021-5091 9035 \n\n"
        "Email: \n"
        "cs@julo.co.id"
    )


# temporary, delete after 21 days after released
ADJUST_AUTO_APPROVE_DATE_RELEASE = datetime.strptime(
    settings.ADJUST_AUTO_APPROVE_DATE_RELEASE, '%Y-%m-%d'
)
DELETION_REQUEST_AUTO_APPROVE_DAY_LIMIT = 20


class CustomerRemovalDeletionTypes:
    # SOFT_DELETE will delete the customer without updating personal data
    SOFT_DELETE = 'soft-delete'

    # HARD_DELETE will delete the customer and update the personal data
    HARD_DELETE = 'hard-delete'


class ExperimentSettingSource:
    GROWTHBOOK = 'Growthbook'


class ExperimentSettingConsts:
    KEY_GROUP_NAME = 'value'
    HASH_VALUE = 'hash_value'
    HASH_ATTRIBUTE = 'hash_attribute'

    class HashValues:
        CUSTOMER_ID = 'customerId'
        DEVICE_ID = 'deviceId'


class CustomerGeolocationConsts:

    LOGIN = 'login'


class AccountDeletionFeatureName:
    SUPPORTED_PRODUCT_LINE_DELETION = 'supported_product_line_deletion'


class CXDocumentType(object):
    PAYDAY_CHANGE_REQUEST = 'payday_customer_change_request'


class ConsentWithdrawal:
    MIN_REASON_LENGTH_INAPP = 40
    MIN_REASON_LENGTH_CRM = 3
    MAX_REASON_LENGTH = 500
    EMAIL_CS = "cs@julo.co.id"

    class RequestStatus:
        REQUESTED = 'requested'
        REJECTED = 'rejected'
        APPROVED = 'approved'
        CANCELLED = 'cancelled'
        REGRANTED = 'regranted'
        AUTO_APPROVED = 'auto_approved'

    forbidden_loan_status = [
        LoanStatusCodes.LENDER_APPROVAL,
        LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.FUND_DISBURSAL_FAILED,
    ]

    forbidden_application_status = [
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
    ]

    forbidden_account_status = [
        JuloOneCodes.ACTIVE_IN_GRACE,
        JuloOneCodes.OVERLIMIT,
        JuloOneCodes.SUSPENDED,
        JuloOneCodes.TERMINATED,
        JuloOneCodes.FRAUD_REPORTED,
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
        JuloOneCodes.SCAM_VICTIM,
        JuloOneCodes.FRAUD_SOFT_REJECT,
        JuloOneCodes.FRAUD_SUSPICIOUS,
        JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW,
    ]

    class FailedRequestStatuses:
        NOT_EXISTS = 'NOT_EXISTS'
        LOANS_ON_DISBURSEMENT = 'LOANS_ON_DISBURSEMENT'
        ACTIVE_LOANS = 'HAS_ACTIVE_LOANS'
        ACCOUNT_NOT_ELIGIBLE = 'ACCOUNT_NOT_ELIGIBLE'
        APPLICATION_NOT_ELIGIBLE = 'APPLICATION_NOT_ELIGIBLE'
        APPLICATION_NOT_FOUND = 'APPLICATION_NOT_FOUND'
        EMPTY_SOURCE = 'EMPTY_SOURCE'
        EMPTY_REASON = 'EMPTY_REASON'
        EMPTY_EMAIL = 'EMPTY_EMAIL'
        EMPTY_DETAIL_REASON = 'EMPTY_DETAIL_REASON'
        INVALID_DETAIL_REASON = 'INVALID_DETAIL_REASON'
        INVALID_LENGTH_DETAIL_REASON_INAPP = 'INVALID_LENGTH_DETAIL_REASON_INPP'
        INVALID_LENGTH_DETAIL_REASON_CRM = 'INVALID_LENGTH_DETAIL_REASON_CRM'
        FAILED_CHANGE_STATUS = 'FAILED_CHANGE_STATUS'
        INVALID_ACTION = "INVALID_ACTION"
        ALREADY_REQUESTED = "ALREADY_REQUESTED"
        CUSTOMER_NOT_EXISTS = "CUSTOMER_NOT_EXISTS"
        ALREADY_WITHDRAWN = "ALREADY_WITHDRAWN"
        REASON_TOO_LONG = "REASON_TOO_LONG"

    class StatusChangeReasons:
        REQUEST_REASON = 'consent withdrawal requested'
        REGRANT_REASON = 'consent withdrawal regranted'
        CANCEL_REASON = 'cancelled consent withdrawal request'
        CANCELED_BY_AGENT = 'cancelled consent withdrawal request by agent'
        AUTO_APPROVE_REASON = 'auto approved consent withdrawal request'
        APPROVE_BY_AGENT = 'approved consent withdrawal request by agent'
        REJECTED_BY_AGENT = 'rejected consent withdrawal request by agent'

    class ResponseMessages:
        APPROVED = 'Permintaan penarikan persetujuan berhasil'
        REJECTED = 'Permintaan penarikan persetujuan ditolak'
        REQUESTED = 'Permintaan penarikan persetujuan sudah diajukan'
        CANCELLED = 'Permintaan penarikan persetujuan berhasil dibatalkan'
        REGRANTED = 'Penarikan persetujuan berhasil dicabut'
        REQUEST_NOT_FOUND = 'Request tidak tersedia'
        INACTIVE_CUSTOMER = 'Customer ID {} tidak ditemukan'
        SURVEY_MUST_BE_FILLED = 'Silahkan isi survey terlebih dahulu'
        USER_NOT_FOUND = 'User tidak ditemukan'
        HAS_ACTIVE_LOANS = 'User memiliki pinjaman yang masih berlangsung (aktif)'
        USER_NOT_ELIGIBLE = 'User tidak diperbolehkan melakukan penarikan persetujuan'
        GENERAL_ERROR_BODY = (
            'Saat ini, kamu belum bisa melakukan penarikan persetujuan, '
            + 'Silakan coba lagi nanti, ya!'
        )
        ACTIVE_LOAN_ERROR_BODY = (
            'Saat ini kamu tidak dapat melakukan penarikan persetujuan karena masih ada '
            + 'tagihan yang sedang berjalan'
        )
        INVALID_LENGTH_DETAIL_REASON_CRM = (
            'Mohon isi detail alasan penarikan persetujuan minimal 3 karakter'
        )
        INVALID_LENGTH_DETAIL_REASON_INAPP = (
            'Mohon isi detail alasan penarikan persetujuan minimal 40 karakter'
        )

    MAPPING_ACTION_ATTRS = {
        "request": {
            "from_status": [
                RequestStatus.REJECTED,
                RequestStatus.CANCELLED,
                RequestStatus.REGRANTED,
            ],
            "to_status": RequestStatus.REQUESTED,
            "log_error": "request_consent_withdrawal",
            "reason": StatusChangeReasons.REQUEST_REASON,
            "account_status": 463,
            "application_status": ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL,
            "forbidden_status": [
                RequestStatus.CANCELLED,
                RequestStatus.REJECTED,
                RequestStatus.REGRANTED,
                RequestStatus.APPROVED,
            ],
            "success_message": ResponseMessages.REQUESTED,
            "email_template": "consent_withdrawal_request",
            "email_subject": "Kamu beneran gak mau jadi pengguna aktif JULO lagi? 🙁",
        },
        "cancel": {
            "from_status": RequestStatus.REQUESTED,
            "to_status": RequestStatus.CANCELLED,
            "log_error": "cancel_consent_withdrawal_request",
            "log_message": 'customer does not have any consent withdrawal request',
            "reason": StatusChangeReasons.CANCEL_REASON,
            "account_status": 463,
            "application_status": ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL,
            "forbidden_status": [
                RequestStatus.CANCELLED,
                RequestStatus.REJECTED,
                RequestStatus.REGRANTED,
                RequestStatus.APPROVED,
            ],
            "success_message": ResponseMessages.CANCELLED,
            "email_template": "consent_withdrawal_cancel",
            "email_subject": (
                "Mantap! Permintaan penarikan persetujuan akunmu berhasil dibatalkan! 🥳"
            ),
        },
        "regrant": {
            "from_status": [RequestStatus.APPROVED, RequestStatus.AUTO_APPROVED],
            "to_status": RequestStatus.REGRANTED,
            "log_error": "regrant_consent_withdrawal_approved",
            "log_message": 'customer does not have any consent withdrawal approved',
            "reason": StatusChangeReasons.REGRANT_REASON,
            "account_status": 464,
            "application_status": ApplicationStatusCodes.CUSTOMER_CONSENT_WITHDRAWED,
            "forbidden_status": [
                RequestStatus.CANCELLED,
                RequestStatus.REJECTED,
                RequestStatus.REGRANTED,
                RequestStatus.REQUESTED,
            ],
            "success_message": ResponseMessages.REGRANTED,
            "email_template": "consent_withdrawal_regrant",
            "email_subject": (
                "Mantap! Permintaan penarikan persetujuan akunmu berhasil dibatalkan! 🥳"
            ),
        },
        "approve": {
            "from_status": RequestStatus.REQUESTED,
            "to_status": RequestStatus.APPROVED,
            "log_error": "approve_consent_withdrawal_request",
            "log_message": 'customer does not have any consent withdrawal request',
            "reason": StatusChangeReasons.APPROVE_BY_AGENT,
            "account_status": 464,
            "application_status": ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL,
            "forbidden_status": [
                RequestStatus.CANCELLED,
                RequestStatus.REJECTED,
                RequestStatus.REGRANTED,
                RequestStatus.APPROVED,
            ],
            "success_message": ResponseMessages.APPROVED,
            "email_template": "consent_withdrawal_approved",
            "email_subject": "Kami sedih akunmu tidak aktif lagi 🙁",
        },
        "auto_approve": {
            "from_status": RequestStatus.REQUESTED,
            "to_status": RequestStatus.AUTO_APPROVED,
            "log_error": "approve_consent_withdrawal_request",
            "log_message": 'customer does not have any consent withdrawal request',
            "reason": StatusChangeReasons.AUTO_APPROVE_REASON,
            "account_status": 464,
            "application_status": ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL,
            "forbidden_status": [
                RequestStatus.CANCELLED,
                RequestStatus.REJECTED,
                RequestStatus.REGRANTED,
                RequestStatus.APPROVED,
            ],
            "success_message": ResponseMessages.APPROVED,
            "email_template": "consent_withdrawal_approved",
            "email_subject": "Kami sedih akunmu tidak aktif lagi 🙁",
        },
        "reject": {
            "from_status": RequestStatus.REQUESTED,
            "to_status": RequestStatus.REJECTED,
            "log_error": "rejected_consent_withdrawal_request",
            "log_message": 'admin rejected consent withdrawal request processs',
            "reason": StatusChangeReasons.REJECTED_BY_AGENT,
            "account_status": 463,
            "application_status": ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL,
            "forbidden_status": [
                RequestStatus.CANCELLED,
                RequestStatus.REJECTED,
                RequestStatus.REGRANTED,
                RequestStatus.APPROVED,
            ],
            "success_message": ResponseMessages.REJECTED,
            "email_template": "consent_withdrawal_rejected",
            "email_subject": (
                "Sayang sekali! Permintaan penarikan persetujuan akunmu belum dapat diproses 😔"
            ),
        },
    }

    class RestrictionMessages:
        TAG_CONSENT_WITHDRAWAL_REQUESTED = 'withdrawal_consent_requested'
        TAG_CONSENT_WITHDRAWAL_APPROVED = 'withdrawal_consent_approved'

        BUTTON_CANCEL_LABEL = 'Batalkan Penarikan Persetujuan'
        BUTTON_CANCEL_ACTION = 'cancel_withdrawal'
        BUTTON_GIVE_LABEL = 'Beri Persetujuan'
        BUTTON_GIVE_ACTION = 'regrant_consent'
        BUTTON_BACK_LABEL = 'Kembali'
        BUTTON_BACK_ACTION = 'cancel'

        DIALOG_HEADER_CANNOT_ACCESS = 'Fitur Tidak Dapat Diakses'
        DIALOG_BODY_CANNOT_ACCESS = (
            "Kamu tidak bisa akses fitur ini selama penarikan persetujuan. "
            "Untuk mengakses fitur kembali, "
            "kamu bisa "
        )

        @classmethod
        def consent_withdrawal_messages(cls):
            return {
                ConsentWithdrawal.RequestStatus.REQUESTED: cls.TAG_CONSENT_WITHDRAWAL_REQUESTED,
                ConsentWithdrawal.RequestStatus.APPROVED: cls.TAG_CONSENT_WITHDRAWAL_APPROVED,
            }

    STATUS_TO_REQUEST_STATUS = {
        ApplicationStatusCodes.CUSTOMER_ON_CONSENT_WITHDRAWAL: RequestStatus.REQUESTED,
        ApplicationStatusCodes.CUSTOMER_CONSENT_WITHDRAWED: RequestStatus.APPROVED,
        JuloOneCodes.CONSENT_WITHDRAWAL_ON_REVIEW: RequestStatus.REQUESTED,
        JuloOneCodes.CONSENT_WITHDRAWED: RequestStatus.APPROVED,
    }
