from datetime import timedelta

from juloserver.partnership.constants import PartnershipFundingFacilities

ALGORITHM_JWT_TYPE = 'HS256'
ACCESS_TOKEN_LIFETIME = timedelta(hours=6)
REFRESH_TOKEN_LIFETIME = timedelta(days=30)
PARTNERSHIP_PREFIX_IDENTIFIER = 888
PARTNERSHIP_SUFFIX_EMAIL = '@julopartner.com'
PARTNERSHIP_MF_AXIATA_BANK_NAME = 'AXIATA_PARTNERSHIP_MF'
EMAIL_SENDER_FOR_AXIATA = 'ops.axiata@julo.co.id'
AXIATA_ALLOWED_DOCUMENT_EXTENSION_FORMAT = {
    '.pdf',
    '.jpeg',
    '.png',
    '.csv',
    '.xls',
    '.xlsx',
    '.doc',
    '.docx',
    '.jpg',
}
AXIATA_ALLOWED_IMAGE_EXTENSION_FORMAT = {
    '.jpeg',
    '.png',
    '.img',
    '.pdf',
    '.jpg',
}
# Initate size as a 4194304 byte = 4 MB
MF_WEB_APP_CRM_UPLOAD_DOCUMENT_MAX_SIZE = 1024 * 1024 * 4
MF_WEB_APP_UPLOAD_ACTION_CHOICES = {
    ("Register", ("Register")),
}
MF_WEB_APP_REGISTER_UPLOAD_HEADER = [
    "proposed_limit",
    "product_line",
    "customer_name",
    "education",
    "nik_number",
    "nib_number",
    "company_name",
    "total_revenue_per_year",
    "business_category",
    "handphone_number",
    "email_borrower",
    "date_of_birth",
    "place_of_birth",
    "marital_status",
    "gender",
    "address",
    "provinsi",
    "kabupaten",
    "zipcode",
    "user_type",
    "kin_name",
    "kin_mobile_phone",
    "home_status",
    "certificate_number",
    "certificate_date",
    "business_entity",
    "npwp",
    "note",
]
EDUCATION = {
    'SD',
    'SLTP',
    'SLTA',
    'DIPLOMA',
    'S1',
    'S2',
    'S3',
}

MF_WEB_APP_LOAN_UPLOAD_HEADER = [
    "nik",
    "distributor",
    "funder",
    "type",
    "loan_request_date",
    "interest_rate",
    "provision_fee",
    "financing_amount",
    "financing_tenure",
    "instalment_number",
    "invoice_number",
]
MAX_LOAN_AXIATA = 2000000000
MIN_LOAN_AXIATA = 300000
MAX_LOAN_DURATION_AXIATA = 360
AXIATA_MAX_LATE_FEE_APPLIED = 5
FIXED_DPD = 5

MF_WEB_APP_DISBURSEMENT_UPLOAD_HEADER = {
    "loan_xid",
}

MF_WEB_APP_REPAYMENT_UPLOAD_HEADER = {
    "nik",
    "paid_amount",
    "paid_date",
}

MF_WEB_APP_REPAYMENT_PER_LOAN_UPLOAD_HEADER = {
    "loan_xid",
    "paid_amount",
    "paid_principal",
    "paid_provision",
    "paid_interest",
    "paid_latefee",
    "paid_date",
}


class WebAppErrorMessage:
    SUCCESSFUL = 'Berhasil'
    SUCCESSFUL_LOGIN = 'Anda berhasil masuk'
    SUCCESSFUL_REGISTER = 'Pendaftaran berhasil'
    SUCCESSFUL_LOGOUT = 'Anda berhasil keluar'
    INVALID_FIELD_FORMAT = 'Format tidak sesuai'
    INVALID_LOGIN_WEB_APP = 'Pastikan NIK dan password sesuai'
    INVALID_LOGIN_DASHBOARD = 'Pastikan username dan password sesuai'
    INVALID_NIK = "NIK tidak terdaftar"
    INVALID_REGISTER = 'NIK, email atau Password tidak sesuai'
    INVALID_AUTH = 'Autentikasi diperlukan'
    INVALID_TOKEN = 'Token tidak valid'
    INVALID_PARTNER_NAME = "Partner tidak ditemukan"
    INVALID_REQUIRED_PARTNER_NAME = "nama partner diperlukan"
    INVALID_ACCESS_PARTNER = "Akses Partner Tidak ditemukan"
    INVALID_OTP = "Gagal Memverifikasi OTP"
    INVALID_TOKEN_FORGOT_PASSWORD = 'Gagal Memverifikasi Token'
    INVALID_PASSWORD_NOT_MATCH = 'Kata sandi tidak cocok. Pastikan Kata sandi anda sesuai'
    INVALID_LOAN_XID = "Pinjaman tidak ditemukan"
    FAILURE_DATA_FETCH = 'Gagal mendapatkan data'
    SUCCESSFUL_OTP = "Berhasil Memverifikasi OTP"
    SUCCESSFUL_VERIFY_RESET_KEY = 'Verifikasi Token Ber hasil'
    SUCCESSFUL_UPDATE_PASSWORD = 'Ubah Kata sandi Berhasil'
    FAILURE_FILE_UPLOAD = 'Upload dokumen gagal'
    FAILURE_FORGOT_PASSWORD = 'Gagal melakukan proses reset password'
    FAILURE_TOKEN_FORGOT_PASSWORD = 'Terjadi Kesalahan, token anda tidak valid'
    SUCCESS_DOCUMENT_DELETE = 'Dokumen berhasil dihapus'
    FAILURE_UPLOAD_DATA = 'Gagal mengunggah data'
    ACCESS_NOT_ALLOWED = 'Akses tidak diizinkan'
    PAGE_NOT_FOUND = 'Halaman tidak valid'
    DISTRIBUTOR_NOT_FOUND = 'Distributor tidak ditemukan'
    DISTRIBUTOR_IN_USED = 'Data Distributor sedang aktif digunakan dalam transaksi'
    MERCHANT_NOT_FOUND = 'Merchant data tidak ditemukan'
    APPLICATION_NOT_FOUND = 'Application tidak ditemukan'
    APPLICATION_STATUS_NOT_VALID = 'Status Application tidak valid'
    NOT_ALLOWED_IMAGE_SIZE = "File tidak boleh lebih besar dari 2 MB"


class MFWebAppUploadAsyncStateType:
    MERCHANT_FINANCING_WEB_APP_REGISTER = "MERCHANT_FINANCING_WEB_APP_REGISTER"
    MF_STANDARD_PRODUCT_MERCHANT_REGISTRATION = "MF_STANDARD_PRODUCT_MERCHANT_REGISTRATION"


class MFWebAppLoanStatus:
    IN_PROGRESS = "in_progress"
    ACTIVE = "active"
    DONE = "done"


class MFDashboardLoanStatus:
    REQUEST = "request"
    DRAFT = "draft"
    APPROVED = "approved"
    NEED_SKRTP = "need-skrtp"
    VERIFY = "verify"
    REJECTED = "rejected"
    PAID_OFF = "paid-off"


class MFWebMaxPlatformCheckStatus:
    IN_PROGRESS = "IN_PROGRESS"
    FAIL = "FAIL"
    DONE = "DONE"


class MFLoanTypes:
    SCF = PartnershipFundingFacilities.SUPPLY_CHAIN_FINANCING
    IF = PartnershipFundingFacilities.INVOICE_FINANCING


class MFStdDocumentTypes:
    INVOICE = "mf_std_invoice"
    BILYET = "mf_std_bilyet"
    SKRTP = "mf_std_manual_skrtp"


class MFStdImageTypes:
    MERCHANT_PHOTO = "mf_std_merchant_photo"


class MFWebAppUploadStateTaskStatus:
    COMPLETED = 'completed'
    PARTIAL_COMPLETED = 'partial_completed'
    IN_PROGRESS = 'in_progress'
    FAILED = 'failed'


class MFStandardMerchantStatus:
    APPROVED = 'approved'
    DOCUMENT_RESUBMIT = 'document-resubmit'
    IN_PROGRESS = 'in-progress'
    REJECTED = 'rejected'
    DOCUMENT_REQUIRED = 'document-required'


class MFStandardUserType:
    LEMBAGA = 'lembaga'
    PERORANGAN = 'perorangan'


class MFStandardMappingApplicationStatus:
    APPROVED = 'Pengajuan Disetujui'
    IN_PROGRESS = 'Pengajuan Diproses'
    UPLOAD_DOCUMENT = 'Upload Dokumen'
    REJECTED = 'Pengajuan Ditolak'
    DOCUMENT_RESUBMITTED = 'Upload Ulang Dokumen'


class MFStandardApplicationStatus:
    APPROVED = 'approved'
    REJECTED = 'rejected'
    WAITING_DOCUMENT = 'waiting_document'


class MFStandardApplicationType:
    PENDING = 'pending'
    RESOLVED = 'resolved'


class MFStandardImageType:
    KTP = 'ktp'
    KTP_SELFIE = 'ktp_selfie'
    NPWP = 'npwp'
    NIB = 'nib'
    AGENT_MERCHANT_SELFIE = 'agent_with_merchant_selfie'
    COMPANY_PHOTO = 'company_photo'


class MFStandardDocumentType:
    CASHFLOW_REPORT = 'cashflow_report'
