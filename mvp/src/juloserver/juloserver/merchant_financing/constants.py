from builtins import object

AXIATA_FEE_RATE = 0.05
MERCHANT_FINANCING_MAXIMUM_ONLINE_DISBURSEMENT = 1000000000

class LoanDurationUnit(object):
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    BI_WEEKLY = "bi-weekly"


class LoanDurationUnitDays(object):
    MONTHLY = 30
    WEEKLY = 7
    BI_WEEKLY = 14


class BulkDisbursementStatus(object):
    QUEUE = 'queue'
    PENDING = 'pending'
    COMPLETED = 'completed'
    FAILED = 'failed'


class ErrorMessageConstant:
    APPLICATION_IS_NOT_MERCHANT_FINANCING = "Application workflow must be merchant financing"
    VALUE_CANNOT_GREATER_THAN_EQUAL = "{0} tidak dapat kurang dari sama dengan 0"
    LOAN_NOT_FOUND = "Loan tidak ditemukan"


class SPHPType(object):
    DOCUMENT = "document"
    WEBVIEW = "webview"


class DocumentType(object):
    SPHP_JULO = 'sphp_julo'
    SPHP_DIGISIGN = 'sphp_digisign'
    SPHP_PRIVY = 'sphp_privy'


class LoanAgreementStatus(object):
    APPROVE = 'approve'
    CANCEL = 'cancel'


class AxiataReportType:
    DISBURSEMENT = 'axiata_disbursement_report'
    REPAYMENT = 'axiata_repayment_report'

    @classmethod
    def all(cls) -> set:
        return {cls.DISBURSEMENT, cls.REPAYMENT}


class MerchantHistoricalTransactionTaskStatuses(object):
    IN_PROGRESS = 'IN PROGRESS'
    VALID = 'VALID'
    INVALID = 'INVALID'

    STATUS_CHOICES = (
        (IN_PROGRESS, IN_PROGRESS),
        (VALID, VALID),
        (INVALID, INVALID)
    )


class MFRegisterUploadDetails:
    KTP_DOC = "ktp_photo"
    SELFIE_PHOTO = "selfie_photo"
    FULLNAME = "fullname"
    MOBILE_PHONE_1 = "mobile_phone_1"
    KTP = "ktp"
    EMAIL = "email"
    GENDER = "gender"
    BIRTH_PLACE = "birth_place"
    DOB = "dob"
    MARITAL_STATUS = "marital_status"
    CLOSE_KIN_NAME = "close_kin_name"
    CLOSE_KIN_MOBILE_PHONE = "close_kin_mobile_phone"
    ADDRESS_PROVINSI = "address_provinsi"
    ADDRESS_KABUPATEN = "address_kabupaten"
    ADDRESS_KECAMATAN = "address_kecamatan"
    ADDRESS_KODEPOS = "address_kodepos"
    ADDRESS_STREET_NUM = "address_street_num"
    BANK_NAME = "bank_name"
    BANK_ACCOUNT_NUMBER = "bank_account_number"
    LOAN_PURPOSE = "loan_purpose"
    MONTHLY_INCOME = "monthly_income"
    MONTHLY_EXPENSES = "monthly_expenses"
    PEGAWAI = "pegawai"
    USAHA = "usaha"
    SELFIE_N_KTP = "selfie_n_ktp"
    APPROVED_LIMIT = "approved_limit"
    APPLICATION_XID = "application_xid"
    LAST_EDUCATION = "last_education"
    HOME_STATUS = "home_status"
    KIN_NAME = "kin_name"
    KIN_MOBILE_PHONE = "kin_mobile_phone"


class MFDisbursementUploadDetails(object):
    IS_SUCCESS = 'is_success'
    APPLICATION_XID = 'application_xid'
    NO = 'no'
    BUSINESS_NAME = 'business_name'
    NAME = 'name'
    PHONE_NUMBER = 'phone_number'
    DATE_REQUEST_DISBURSEMENT = 'date_request_disbursement'
    TIME_REQUEST = 'time_request'
    LOAN_AMOUNT_REQUEST = 'loan_amount_request'
    STATUS = 'status'
    REASON = 'reason'
    DATE_DISBURSEMENT = 'date_disbursement'
    AMOUNT_DISBURSEMENT = 'amount_disbursement'
    LOAN_DURATION = 'loan_duration'
    ORIGINATION_FEE_PCT = 'origination_fee_pct'
    AMOUNT_DUE = 'amount_due'
    DUE_DATE = 'due_date'
    DATE_SUBMIT_DISBURSEMENT = 'date_submit_disbursement'
    INTEREST_RATE = 'interest_rate'
    NAME_IN_BANK = 'name_in_bank'
    BANK_NAME = 'bank_name'
    BANK_ACCOUNT_NUMBER = 'bank_account_number'
    DISTRIBUTOR_MOBILE_NUMBER = 'distributor_mobile_number'
    MESSAGE = 'message'
    TENOR_TYPE = 'loan_duration_type'


MF_REGISTER_HEADERS = [
    "KTP doc",
    "Selfie doc",
    "Name",
    "Phone#",
    "KTP #",
    "Alamat email",
    "Jenis Kelamin",
    "Tempat Lahir",
    "Tanggal Lahir",
    "Status Pernikahan",
    "Nama Ibu Kandung / spouse (if married)",
    "No hp orang tua / spouse (if married)",
    "Nama Propinsi",
    "Nama Kota/Kabupaten",
    "Kelurahan",
    "Kode Pos Rumah",
    "Detail Alamat",
    "Nama Bank",
    "No rek bank",
    "Tujuan pinjaman",
    "Omset penjualan perbulan",
    "Pengeluaran perbulan",
    "Jumlah pegawai",
    "Tipe usaha",
    "Foto Selfie + KTP",
    "Approved Limit",
    "Application XID",
    "pendidikan terakhir",
    "nama kontak darurat",
    "nomor kontak darurat",
    "status domisili",
    "Message"
]

MF_DISBURSEMENT_RABANDO_HEADERS = [
    MFDisbursementUploadDetails.IS_SUCCESS,
    MFDisbursementUploadDetails.APPLICATION_XID,
    MFDisbursementUploadDetails.NO,
    MFDisbursementUploadDetails.BUSINESS_NAME,
    MFDisbursementUploadDetails.NAME,
    MFDisbursementUploadDetails.PHONE_NUMBER,
    MFDisbursementUploadDetails.DATE_REQUEST_DISBURSEMENT,
    MFDisbursementUploadDetails.TIME_REQUEST,
    MFDisbursementUploadDetails.LOAN_AMOUNT_REQUEST,
    MFDisbursementUploadDetails.STATUS,
    MFDisbursementUploadDetails.REASON,
    MFDisbursementUploadDetails.DATE_DISBURSEMENT,
    MFDisbursementUploadDetails.AMOUNT_DISBURSEMENT,
    MFDisbursementUploadDetails.LOAN_DURATION,
    MFDisbursementUploadDetails.ORIGINATION_FEE_PCT,
    MFDisbursementUploadDetails.AMOUNT_DUE,
    MFDisbursementUploadDetails.DUE_DATE,
    MFDisbursementUploadDetails.DATE_SUBMIT_DISBURSEMENT,
    MFDisbursementUploadDetails.INTEREST_RATE,
    MFDisbursementUploadDetails.NAME_IN_BANK,
    MFDisbursementUploadDetails.BANK_NAME,
    MFDisbursementUploadDetails.BANK_ACCOUNT_NUMBER,
    MFDisbursementUploadDetails.DISTRIBUTOR_MOBILE_NUMBER,
    MFDisbursementUploadDetails.TENOR_TYPE,
    MFDisbursementUploadDetails.MESSAGE,
]

MF_DISBURSEMENT_HEADERS = [
    MFDisbursementUploadDetails.IS_SUCCESS,
    MFDisbursementUploadDetails.APPLICATION_XID,
    MFDisbursementUploadDetails.NO,
    MFDisbursementUploadDetails.BUSINESS_NAME,
    MFDisbursementUploadDetails.NAME,
    MFDisbursementUploadDetails.PHONE_NUMBER,
    MFDisbursementUploadDetails.DATE_REQUEST_DISBURSEMENT,
    MFDisbursementUploadDetails.TIME_REQUEST,
    MFDisbursementUploadDetails.LOAN_AMOUNT_REQUEST,
    MFDisbursementUploadDetails.STATUS,
    MFDisbursementUploadDetails.REASON,
    MFDisbursementUploadDetails.DATE_DISBURSEMENT,
    MFDisbursementUploadDetails.AMOUNT_DISBURSEMENT,
    MFDisbursementUploadDetails.LOAN_DURATION,
    MFDisbursementUploadDetails.ORIGINATION_FEE_PCT,
    MFDisbursementUploadDetails.AMOUNT_DUE,
    MFDisbursementUploadDetails.DUE_DATE,
    MFDisbursementUploadDetails.DATE_SUBMIT_DISBURSEMENT,
    MFDisbursementUploadDetails.INTEREST_RATE,
    MFDisbursementUploadDetails.TENOR_TYPE,
    MFDisbursementUploadDetails.MESSAGE,
]

PARTNER_MF_REGISTER_UPLOAD_MAPPING_FIELDS = [
    ("KTP doc", MFRegisterUploadDetails.KTP_DOC),
    ("Selfie doc", MFRegisterUploadDetails.SELFIE_PHOTO),
    ("Name", MFRegisterUploadDetails.FULLNAME),
    ("Phone#", MFRegisterUploadDetails.MOBILE_PHONE_1),
    ("KTP #", MFRegisterUploadDetails.KTP),
    ("Alamat email", MFRegisterUploadDetails.EMAIL),
    ("Jenis Kelamin", MFRegisterUploadDetails.GENDER),
    ("Tempat Lahir", MFRegisterUploadDetails.BIRTH_PLACE),
    ("Tanggal Lahir", MFRegisterUploadDetails.DOB),
    ("Status Pernikahan", MFRegisterUploadDetails.MARITAL_STATUS),
    ("Nama Ibu Kandung / spouse (if married)", MFRegisterUploadDetails.CLOSE_KIN_NAME),
    ("No hp orang tua / spouse (if married)", MFRegisterUploadDetails.CLOSE_KIN_MOBILE_PHONE),
    ("Nama Propinsi", MFRegisterUploadDetails.ADDRESS_PROVINSI),
    ("Nama Kota/Kabupaten", MFRegisterUploadDetails.ADDRESS_KABUPATEN),
    ("Kelurahan", MFRegisterUploadDetails.ADDRESS_KECAMATAN),
    ("Kode Pos Rumah", MFRegisterUploadDetails.ADDRESS_KODEPOS),
    ("Detail Alamat", MFRegisterUploadDetails.ADDRESS_STREET_NUM),
    ("Nama Bank", MFRegisterUploadDetails.BANK_NAME),
    ("No rek bank", MFRegisterUploadDetails.BANK_ACCOUNT_NUMBER),
    ("Tujuan pinjaman", MFRegisterUploadDetails.LOAN_PURPOSE),
    ("Omset penjualan perbulan", MFRegisterUploadDetails.MONTHLY_INCOME),
    ("Pengeluaran perbulan", MFRegisterUploadDetails.MONTHLY_EXPENSES),
    ("Jumlah pegawai", MFRegisterUploadDetails.PEGAWAI),
    ("Tipe usaha", MFRegisterUploadDetails.USAHA),
    ("Foto Selfie + KTP", MFRegisterUploadDetails.SELFIE_N_KTP),
    ("Approved Limit", MFRegisterUploadDetails.APPROVED_LIMIT),
    ("pendidikan terakhir", MFRegisterUploadDetails.LAST_EDUCATION),
    ("nama kontak darurat", MFRegisterUploadDetails.KIN_NAME),
    ("nomor kontak darurat", MFRegisterUploadDetails.KIN_MOBILE_PHONE),
    ("status domisili", MFRegisterUploadDetails.HOME_STATUS)
]

PARTNER_MF_DISBURSEMENT_UPLOAD_MAPPING_FIELDS = [
    ("Application XID", MFDisbursementUploadDetails.APPLICATION_XID),
    ("No", MFDisbursementUploadDetails.NO),
    ("Business Name", MFDisbursementUploadDetails.BUSINESS_NAME),
    ("Name", MFDisbursementUploadDetails.NAME),
    ("Phone number", MFDisbursementUploadDetails.PHONE_NUMBER),
    ("Date of Request Disbursement", MFDisbursementUploadDetails.DATE_REQUEST_DISBURSEMENT),
    ("Time of Request", MFDisbursementUploadDetails.TIME_REQUEST),
    ("Amount Requested (Rp)", MFDisbursementUploadDetails.LOAN_AMOUNT_REQUEST),
    ("Status", MFDisbursementUploadDetails.STATUS),
    ("Reason", MFDisbursementUploadDetails.REASON),
    ("Date of Disburse", MFDisbursementUploadDetails.DATE_DISBURSEMENT),
    ("Amount Disbursed", MFDisbursementUploadDetails.AMOUNT_DISBURSEMENT),
    ("Tenor", MFDisbursementUploadDetails.LOAN_DURATION),
    ("All-in fee", MFDisbursementUploadDetails.ORIGINATION_FEE_PCT),
    ("Amount due", MFDisbursementUploadDetails.AMOUNT_DUE),
    ("Due date", MFDisbursementUploadDetails.DUE_DATE),
    ("Date of Submitting disbursal receipt", MFDisbursementUploadDetails.DATE_SUBMIT_DISBURSEMENT),
    ("Interest Rate", MFDisbursementUploadDetails.INTEREST_RATE),
    ("Name in bank", MFDisbursementUploadDetails.NAME_IN_BANK),
    ("Bank name", MFDisbursementUploadDetails.BANK_NAME),
    ("Bank account number", MFDisbursementUploadDetails.BANK_ACCOUNT_NUMBER),
    ("Distributor mobile number", MFDisbursementUploadDetails.DISTRIBUTOR_MOBILE_NUMBER),
]


class MFStandardProductUploadDetails(object):
    NIK = 'nik'
    DISTRIBUTOR = 'distributor'
    FUNDER = 'funder'
    TYPE = 'type'
    LOAN_REQUEST_DATE = 'loan_request_date'
    INTEREST_RATE = 'interest_rate'
    PROVISION_RATE = 'provision_fee'
    FINANCING_AMOUNT = 'financing_amount'
    FINANCING_TENURE = 'financing_tenure'
    INSTALLMENT_NUMBER = 'installment_number'
    INVOICE_NUMBER = 'invoice_number'
    IS_SUCCESS = 'is_success'
    MESSAGE = 'message'
    INVOICE_LINK = 'invoice_link'
    GIRO_LINK = 'giro_link'
    SKRTP_LINK = 'skrtp_link'
    MERCHANT_PHOTO_LINK = 'merchant_photo_link'


MF_STANDARD_LOAN_UPLOAD_HEADERS = [
    MFStandardProductUploadDetails.IS_SUCCESS,
    MFStandardProductUploadDetails.NIK,
    MFStandardProductUploadDetails.DISTRIBUTOR,
    MFStandardProductUploadDetails.FUNDER,
    MFStandardProductUploadDetails.TYPE,
    MFStandardProductUploadDetails.LOAN_REQUEST_DATE,
    MFStandardProductUploadDetails.INTEREST_RATE,
    MFStandardProductUploadDetails.PROVISION_RATE,
    MFStandardProductUploadDetails.FINANCING_AMOUNT,
    MFStandardProductUploadDetails.FINANCING_TENURE,
    MFStandardProductUploadDetails.INSTALLMENT_NUMBER,
    MFStandardProductUploadDetails.INVOICE_NUMBER,
    MFStandardProductUploadDetails.INVOICE_LINK,
    MFStandardProductUploadDetails.GIRO_LINK,
    MFStandardProductUploadDetails.SKRTP_LINK,
    MFStandardProductUploadDetails.MERCHANT_PHOTO_LINK,
    MFStandardProductUploadDetails.MESSAGE,
]


MF_STANDARD_PRODUCT_UPLOAD_MAPPING_FIELDS = [
    ("nik", MFStandardProductUploadDetails.NIK),
    ("distributor", MFStandardProductUploadDetails.DISTRIBUTOR),
    ("funder", MFStandardProductUploadDetails.FUNDER),
    ("type", MFStandardProductUploadDetails.TYPE),
    ("loan_request_date", MFStandardProductUploadDetails.LOAN_REQUEST_DATE),
    ("interest_rate", MFStandardProductUploadDetails.INTEREST_RATE),
    ("provision_fee", MFStandardProductUploadDetails.PROVISION_RATE),
    ("financing_amount", MFStandardProductUploadDetails.FINANCING_AMOUNT),
    ("financing_tenure", MFStandardProductUploadDetails.FINANCING_TENURE),
    ("installment_number", MFStandardProductUploadDetails.INSTALLMENT_NUMBER),
    ("invoice_number", MFStandardProductUploadDetails.INVOICE_NUMBER),
]


class FeatureNameConst(object):
    AXIATA_BULK_UPLOAD = 'axiata_bulk_upload'


MF_CSV_UPLOAD_ADJUST_LIMIT_HEADERS = (
    "application_xid",
    "limit_upgrading",
    "message"
)


class MFAdjustLimitUploadDetails:
    APPLICATION_XID = 'application_xid'
    LIMIT_UPGRADING = "limit_upgrading"


PARTNER_MF_ADJUST_LIMIT_UPLOAD_MAPPING_FIELDS = [
    ("application_xid", MFAdjustLimitUploadDetails.APPLICATION_XID),
    ("limit_upgrading", MFAdjustLimitUploadDetails.LIMIT_UPGRADING),
]


class MFFeatureSetting:
    MAX_3_PLATFORM_FEATURE_NAME = "max_3_platform_feature"
    MF_MANUAL_SIGNATURE = 'merchant_financing_manual_signature'
    STANDARD_PRODUCT_API_CONTROL = "partnership_mf_api_control"
    MF_STANDARD_ASYNC_CONFIG = 'mf_standard_async_config'
    MF_STANDARD_RESUBMISSION_ASYNC_CONFIG = 'mf_standard_resubmission_async_config'
    MF_STANDARD_APPROVE_REJECT_ASYNC_CONFIG = 'mf_standard_approve_reject_async_config'
    MF_STANDARD_PRICING = 'merchant_financing_standard_pricing'


class ResponseErrorType(object):
    """
    This constants represents the error will showing on FE
    """

    ALERT = 'alert'
    TOAST = 'toast'


class MFStandardRole(object):
    PARTNER_AGENT = 'partner_agent'
    AGENT = 'agent'


MF_STANDARD_REGISTER_UPLOAD_HEADER = [
    "Proposed Limit",
    "Kode Distributor",
    "Nama Borrower",
    "No HP Borrower",
    "Status Pernikahan",
    "Jenis Kelamin",
    "Tempat Lahir",
    "Tanggal Lahir",
    "Status Domisili",
    "Nama spouse",
    "No HP spouse",
    "Nama Ibu Kandung",
    "No hp orang tua",
    "Nama Propinsi",
    "Nama Kota/Kabupaten",
    "Kelurahan",
    "Kecamatan",
    "Kode Pos Rumah",
    "Detail Alamat Individual",
    "Nama Bank",
    "No rek bank",
    "Tujuan pinjaman",
    "Omset penjualan perbulan",
    "Pengeluaran perbulan",
    "Jumlah pegawai",
    "Tipe usaha",
    "No KTP",
    "Pendidikan terakhir",
    "No NPWP",
    "Alamat email",
    "Jenis pengguna",
    "Jenis badan usaha",
    "Nomor Akta",
    "Tanggal Akta",
]


class MFComplianceRegisterUpload:
    PROPOSED_LIMIT = "proposed_limit"
    DISTRIBUTOR_CODE = "distributor_code"
    FULLNAME = "fullname"
    MOBILE_PHONE_1 = "mobile_phone_1"
    MARITAL_STATUS = "marital_status"
    GENDER = "gender"
    BIRTH_PLACE = "birth_place"
    DOB = "dob"
    HOME_STATUS = "home_status"
    SPOUSE_NAME = "spouse_name"
    SPOUSE_MOBILE_PHONE = "spouse_mobile_phone"
    KIN_NAME = "kin_name"
    KIN_MOBILE_PHONE = "kin_mobile_phone"
    ADDRESS_PROVINSI = "address_provinsi"
    ADDRESS_KABUPATEN = "address_kabupaten"
    ADDRESS_KELURAHAN = "address_kelurahan"
    ADDRESS_KECAMATAN = "address_kecamatan"
    ADDRESS_KODEPOS = "address_kodepos"
    ADDRESS_STREET_NUM = "address_street_num"
    BANK_NAME = "bank_name"
    BANK_ACCOUNT_NUMBER = "bank_account_number"
    LOAN_PURPOSE = "loan_purpose"
    MONTHLY_INCOME = "monthly_income"
    MONTHLY_EXPENSES = "monthly_expenses"
    PEGAWAI = "pegawai"
    BUSINESS_TYPE = "business_type"
    KTP = "ktp"
    LAST_EDUCATION = "last_education"
    NPWP = "npwp"
    EMAIL = "email"
    USER_TYPE = "user_type"
    BUSINESS_ENTITY = "business_entity"
    CERTIFICATE_NUMBER = "certificate_number"
    CERTIFICATE_DATE = "certificate_date"
    FILE_UPLOAD_KEY = "file_upload"
    KTP_IMAGE = "ktp_image"
    SELFIE_KTP_IMAGE = "selfie_ktp_image"
    AGENT_MERCHANT_IMAGE = "agent_merchant_image"
    NPWP_IMAGE = "npwp_image"
    NIB_IMAGE = "nib_image"
    BUSINESS_ENTITY_IMAGE = "business_entity_image"
    CASHFLOW_REPORT = "cashflow_report"


MF_COMPLIANCE_REGISTER_UPLOAD_MAPPING_FIELDS = [
    ("Proposed Limit", MFComplianceRegisterUpload.PROPOSED_LIMIT),
    ("Kode Distributor", MFComplianceRegisterUpload.DISTRIBUTOR_CODE),
    ("Nama Borrower", MFComplianceRegisterUpload.FULLNAME),
    ("No HP Borrower", MFComplianceRegisterUpload.MOBILE_PHONE_1),
    ("Status Pernikahan", MFComplianceRegisterUpload.MARITAL_STATUS),
    ("Jenis Kelamin", MFComplianceRegisterUpload.GENDER),
    ("Tempat Lahir", MFComplianceRegisterUpload.BIRTH_PLACE),
    ("Tanggal Lahir", MFComplianceRegisterUpload.DOB),
    ("Status Domisili", MFComplianceRegisterUpload.HOME_STATUS),
    ("Nama spouse", MFComplianceRegisterUpload.SPOUSE_NAME),
    ("No HP spouse", MFComplianceRegisterUpload.SPOUSE_MOBILE_PHONE),
    ("Nama Ibu Kandung", MFComplianceRegisterUpload.KIN_NAME),
    ("No hp orang tua", MFComplianceRegisterUpload.KIN_MOBILE_PHONE),
    ("Nama Propinsi", MFComplianceRegisterUpload.ADDRESS_PROVINSI),
    ("Nama Kota/Kabupaten", MFComplianceRegisterUpload.ADDRESS_KABUPATEN),
    ("Kelurahan", MFComplianceRegisterUpload.ADDRESS_KELURAHAN),
    ("Kecamatan", MFComplianceRegisterUpload.ADDRESS_KECAMATAN),
    ("Kode Pos Rumah", MFComplianceRegisterUpload.ADDRESS_KODEPOS),
    ("Detail Alamat Individual", MFComplianceRegisterUpload.ADDRESS_STREET_NUM),
    ("Nama Bank", MFComplianceRegisterUpload.BANK_NAME),
    ("No rek bank", MFComplianceRegisterUpload.BANK_ACCOUNT_NUMBER),
    ("Tujuan pinjaman", MFComplianceRegisterUpload.LOAN_PURPOSE),
    ("Omset penjualan perbulan", MFComplianceRegisterUpload.MONTHLY_INCOME),
    ("Pengeluaran perbulan", MFComplianceRegisterUpload.MONTHLY_EXPENSES),
    ("Jumlah pegawai", MFComplianceRegisterUpload.PEGAWAI),
    ("Tipe usaha", MFComplianceRegisterUpload.BUSINESS_TYPE),
    ("No KTP", MFComplianceRegisterUpload.KTP),
    ("Pendidikan terakhir", MFComplianceRegisterUpload.LAST_EDUCATION),
    ("No NPWP", MFComplianceRegisterUpload.NPWP),
    ("Alamat email", MFComplianceRegisterUpload.EMAIL),
    ("Jenis pengguna", MFComplianceRegisterUpload.USER_TYPE),
    ("Jenis badan usaha", MFComplianceRegisterUpload.BUSINESS_ENTITY),
    ("Nomor Akta", MFComplianceRegisterUpload.CERTIFICATE_NUMBER),
    ("Tanggal Akta", MFComplianceRegisterUpload.CERTIFICATE_DATE),
]

ADDITIONAL_MF_COMPLIANCE_REGISTER_UPLOAD_MAPPING_FIELDS = [
    ("File Upload", MFComplianceRegisterUpload.FILE_UPLOAD_KEY),
    ("Foto KTP", MFComplianceRegisterUpload.KTP_IMAGE),
    ("Foto Selfie KTP", MFComplianceRegisterUpload.SELFIE_KTP_IMAGE),
    ("Foto Agent Merchant", MFComplianceRegisterUpload.AGENT_MERCHANT_IMAGE),
    ("Foto NPWP", MFComplianceRegisterUpload.NPWP_IMAGE),
    ("Foto NIB", MFComplianceRegisterUpload.NIB_IMAGE),
    ("Foto Tempat Usaha", MFComplianceRegisterUpload.BUSINESS_ENTITY_IMAGE),
    ("Laporan Arus Kas", MFComplianceRegisterUpload.CASHFLOW_REPORT),
]

ADDITIONAL_MF_STANDARD_REGISTER_UPLOAD_HEADER = [
    "File Upload",
    "Foto KTP",
    "Foto Selfie KTP",
    "Foto Agent Merchant",
    "Foto NPWP",
    "Foto NIB",
    "Foto Tempat Usaha",
    "Laporan Arus Kas",
]


class MerchantRiskAssessmentStatus:
    ACTIVE = 'active'
    PENDING = 'pending'
    EXPIRED = 'expired'
    INACTIVE = 'inactive'
    CHOICES = (
        (ACTIVE, 'active'),
        (PENDING, 'pending'),
        (EXPIRED, 'expired'),
        (INACTIVE, 'inactive'),
    )


class MFStandardRejectReason:
    BLACKLIST = {"name": "black_list_customer", "label": "Blacklist"}
    FRAUD_NIK = {"name": "fraud_nik", "label": "NIK terdeteksi fraud"}
    FRAUD_PHONE = {"name": "fraud_phone_number", "label": "No. HP terdeteksi fraud"}
    DELINQUENT_NIK = {"name": "delinquent_nik", "label": "NIK terdeteksi gagal bayar"}
    DELINQUENT_PHONE = {"name": "delinquent_phone", "label": "No. HP terdeteksi gagal bayar"}
    CLEAR = {"name": "clear", "label": "Baik"}


class LenderAxiata:
    JTP = "jtp"
    SMF = "saison_modern_finance_lender"


class FunderAxiata:
    JTP = "jtp"
    SMF = "smf"
