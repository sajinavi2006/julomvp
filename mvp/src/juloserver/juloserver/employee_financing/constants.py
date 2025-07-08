from juloserver.partnership.constants import EFWebFormType
YES_NO_UNKNOWN_CHOICES = (
    ('Yes', 'Yes'),
    ('No', 'No'),
    ('Unknown', 'Unknown')
)

EMPLOYMENT_CHOICES = (
    ('Fulltime', 'Fulltime'),
    ('Contract', 'Contract')
)

EF_PILOT_UPLOAD_HEADERS = (
    'register_partner_application',
    'company_id',
    'fullname',
    'email',
    'jenis kelamin',
    'tempat lahir',
    'phone number',
    'ktp photo',
    'ktp selfie',
    'dob',
    'address',
    'province',
    'kabupaten',
    'kecamatan',
    'Kelurahan',
    'kodepos',
    'nama orang tua',
    'nomor hp orang tua',
    'nama pasangan',
    'nomor hp pasangan',
    'mulai perkerjaan',
    'tanggal gajian',
    'nama bank',
    'nomor rekening bank',
    'approved limit',
    'interest',
    'provision fee',
    'late fee',
    'max tenor bulan'
)

EF_PILOT_UPLOAD_MAPPING_FIELDS = [
    ("nik", "ktp"),
    ("company_id", "company_id"),
    ("fullname", "fullname"),
    ("email", "email"),
    ("jenis kelamin", "gender"),
    ("tempat lahir", "birth_place"),
    ("phone number", "mobile_phone_1"),
    ("ktp photo", "ktp_photo"),
    ("ktp selfie", "ktp_selfie"),
    ("dob", "dob"),
    ("address", "address_street_num"),
    ("province", "address_provinsi"),
    ("kabupaten", "address_kabupaten"),
    ("kecamatan", "address_kecamatan"),
    ("kelurahan", "address_kelurahan"),
    ("kodepos", "address_kodepos"),
    ("nama orang tua", "close_kin_name"),
    ("nomor hp orang tua", "close_kin_mobile_phone"),
    ("nama pasangan", "spouse_name"),
    ("nomor hp pasangan", "spouse_mobile_phone"),
    ("mulai perkerjaan", "job_start"),
    ("tanggal gajian", "payday"),
    ("nama bank", "bank_name"),
    ("nomor rekening bank", "bank_account_number"),
    ("approved limit", "loan_amount_request"),
    ("interest", "interest"),
    ("provision fee", "provision_fee"),
    ("late fee", "late_fee"),
    ("max tenor bulan", "loan_duration_request"),
    ("penghasilan per bulan", "monthly_income")
]

EF_PILOT_DISBURSEMENT_UPLOAD_MAPPING_FIELDS = [
    ("ktp", "ktp"),
    ("application xid", "application_xid"),
    ("disbursement request date", "date_request_disbursement"),
    ("email", "email"),
    ("amount request", "loan_amount_request"),
    ("tenor selected", "loan_duration"),
    ("max tenor", "max_tenor"),
    ("interest", "interest_rate"),
    ("provision fee", "origination_fee_pct"),
    ("late fee", "late_fee")
]

EF_PRE_APPROVAL_UPLOAD_MAPPING_FIELDS = [
    ("ktp number", "ktp"),
    ("company_id", "company_id"),
    ("fullname", "fullname"),
    ("email", "email"),
    ("mulai perkerjaan", "job_start"),
    ("selesai contract", "contract_end"),
    ("dob", "dob"),
    ("tanggal gajian", "payday"),
    ("total penghasilan per bulan", "monthly_income"),
    ("nama bank", "bank_name"),
    ("nomor rekening bank", "bank_account_number")
]

EF_VALID_CONTENT_TYPES_UPLOAD = [
    'text/csv',
    'application/vnd.ms-excel',
    'text/x-csv',
    'application/csv',
    'application/x-csv',
    'text/comma-separated-values',
    'text/x-comma-separated-values',
    'text/tab-separated-values'
]

EF_PILOT_UPLOAD_ACTION_CHOICES = {
    ("Register", ("Register")),
    ("Disbursement", ("Disbursement")),
    ("Repayment", ("Repayment")),
}


class EmploymentStatus:
    FULLTIME = 'Fulltime'
    CONTRACT = 'Contract'


class ProcessEFStatus:
    COMPANY_NOT_FOUND = 'Company tidak ditemukan'
    BANK_NAME_NOT_FOUND = 'Nama bank tidak ditemukan'


EMPLOYEE_FINANCING_REGISTER = 'Register'
EMPLOYEE_FINANCING_DISBURSEMENT = 'Disbursement'
EMPLOYEE_FINANCING_REPAYMENT = 'Repayment'
WEB_FORM_ALGORITHM_JWT_TYPE = 'HS256'


class ErrorMessageConstEF(object):
    INVALID_TOKEN = 'Token tidak valid atau token kadaluwarsa'
    INVALID_TO_FILL_COLUMN = 'tidak valid untuk mengisi kolom ini'


IMAGE_EXTENSION_FORMAT = {'png', 'jpg', 'jpeg', 'webp', 'tiff', 'tif', 'bmp'}
WEB_FORM_TYPE = (
    (EFWebFormType.APPLICATION, 'application'),
    (EFWebFormType.DISBURSEMENT, 'disbursement')
)

SEND_FORM_URL_TO_EMAIL_ACTION_CHOICES = {
    ("Application", ("Application")),
    ("Disbursement", ("Disbursement")),
}
