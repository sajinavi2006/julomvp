"""
constants.py
"""

ACTION_CHOICES = (
    ("Register", ("Register")),
    ("Approval", ("Approval")),
    ("Disbursement", ("Disbursement")),
    ("Rejection", ("Rejection")),
    ("Repayment", ("Repayment"))
)

ICARE_LABEL = (
    ("[axiata] create application then change status code to 163 "),
    "approve to set loan info and payment then change status code to 177",
    "after manual disbursement then change status to 180",
    "if fail binary / not approved then change status to 135",
    "[axiata] after repayment generate report",
)

TEMPLATE_PATH = (
    'excel/icare_template/register.xlsx',
    'excel/icare_template/approve.xlsx',
    'excel/icare_template/disbursement.xlsx',
    'excel/icare_template/reject.xlsx',
    'excel/icare_template/repayment_upload.xlsx'
)

HALT_RESUME_TEMPLATE_PATH = (
    'excel/loan_halt_or_resume/grab_halt_resume_template.xlsx',
    'excel/loan_halt_or_resume/grab_halt_resume_template.xlsx',
)

LOAN_RESTRUCTURING_TEMPLATE_PATH = (
    'excel/grab_loan_restructuring/grab_loan_restructuring_template.xlsx',
    'excel/grab_loan_restructuring/grab_loan_restructuring_template.xlsx',
)

LOAN_EARLY_WRITE_OFF_TEMPLATE_PATH = (
    'excel/grab_early_write_off/early_write_off_template.xlsx',
    'excel/grab_early_write_off/early_write_off_template.xlsx',
)

GRAB_REFERRAL_TEMPLATE_PATH = (
    'excel/grab_referral_program/grab_referral_program.xlsx',
    'excel/grab_referral_program/grab_referral_program.xlsx',
)

AXIATA_MAPPING = {
    'acceptance date': "acceptance_date",
    'application date': "partner_application_date",
    'account no.': "account_number",
    'disbursement date': "disbursement_date",
    'time stamp': "disbursement_time",
    'ip address': "ip_address",
    'first payment date': "first_payment_date",
    'score grade': "partner_score_grade",
    'insurance fee': "insurance_fee",
    'funder': "funder",
    'product line': "partner_product_line",
    'customer name': "fullname",
    'id no.': "ktp",
    'branding name': "brand_name",
    'company name': "company_name",
    'company registration no.': "company_registration_number",
    'business category': "business_category",
    'type of business': "type_of_business",
    'phone number': "phone_number",
    'email': "email",
    'date of birth': "dob",
    'place of birth': "birth_place",
    'marital status': "marital_status",
    'gender': "gender",
    'address': "address_street_num",
    'shops number': "shops_number",
    'distributor': "distributor",
    'partner id': "partner_id",
    'profit/interest rate': "interest_rate",
    'financing amount': "loan_amount",
    'financing tenure': "loan_duration",
    'time unit': "loan_duration_unit",
    'monthly instalment': "monthly_installment",
    'final monthly instalment': "final_monthly_installment",
    'invoice no': "invoice_id",
    'biaya admin': "admin_fee",
    'provisi': "origination_fee",
    'provinsi': "address_provinsi",
    'kabupaten': "address_kabupaten",
    'kecamatan': "address_kecamatan",
    'kelurahan': "address_kelurahan",
    'kodepos': "address_kodepos",
    'loan purpose': "loan_purpose",
    'registration id': "axiata_temporary_data_id",
    'jenis pengguna': "user_type",
    'income': "income",
    'education': "last_education",
    'status domisili': "home_status",
    'nomor akta': "certificate_number",
    'tanggal akta terakhir': "certificate_date",
    'npwp': "npwp",
    'nama kontak darurat': "kin_name",
    'nomor kontak darurat': "kin_mobile_phone",
}

DATE_FORMAT = [
    'acceptance_date',
    'partner_application_date',
    'disbursement_date',
    'first_payment_date',
]

GENDER = {
    'male': "Pria",
    'female': "Wanita"

}

MARITAL_STATUS = {
    'single': 'Lajang',
    'married': 'Menikah',
    'divorced': 'Cerai',
    'widow': 'Janda / duda'
}

PARTNER_PILOT_UPLOAD_ACTION_CHOICES = {
    ("Register", ("Register")),
    ("Disbursement", ("Disbursement")),
    ("Upgrade", ("Upgrade")),
    ("Adjust Limit", ("Adjust Limit")),
}

PARTNER_PILOT_UPLOAD_ACTION_KEY = (
    ("Register", ("Register")),
    ("Disbursement", ("Disbursement")),
    ("Upgrade", ("Upgrade")),
    ("Adjust Limit", ("Adjust Limit")),
)

MERCHANT_FINANCING_UPLOAD_MAPPING_FIELDS = [
    ("KTP doc", "ktp_photo"),
    ("Selfie doc", "selfie_photo"),
    ("Name", "fullname"),
    ("Phone#", "mobile_phone_1"),
    ("KTP #", "ktp"),
    ("Alamat email", "email"),
    ("Jenis Kelamin", "gender"),
    ("Tempat Lahir", "birth_place"),
    ("Tanggal Lahir", "dob"),
    ("Status Pernikahan", "marital_status"),
    ("Nama Ibu Kandung / spouse (if married)", "close_kin_name"),
    ("No hp orang tua / spouse (if married)", "close_kin_mobile_phone"),
    ("Foto Selfie + KTP", "selfie_n_ktp"),
    ("Nama Propinsi", "address_provinsi"),
    ("Nama Kota/Kabupaten", "address_kabupaten"),
    ("Kelurahan", "address_kecamatan"),
    ("Kode Pos Rumah", "address_kodepos"),
    ("Detail Alamat", "address_street_num"),
    ("Nama Bank", "bank_name"),
    ("No rek bank", "bank_account_number"),
    ("Tujuan pinjaman", "loan_purpose"),
    ("Omset penjualan perbulan", "monthly_income"),
    ("Pengeluaran perbulan", "monthly_expenses"),
    ("Jumlah pegawai", "pegawai"),
    ("Tipe usaha", "usaha"),
    ("Approved Limit", "approved_limit"),
    ("Percentage", "provision")
]

PARTNER_PILOT_DISBURSEMENT_UPLOAD_MAPPING_FIELDS = [
    ("Application XID", "application_xid"),
    ("No", "no"),
    ("Business Name", "business_name"),
    ("Name", "name"),
    ("Phone number", "phone_number"),
    ("Date of Request Disbursement", "date_request_disbursement"),
    ("Time of Request", "time_request"),
    ("Amount Requested (Rp)", "loan_amount_request"),
    ("Status", "status"),
    ("Reason", "reason"),
    ("Date of Disburse", "date_disbursement"),
    ("Amount Disbursed", "amount_disbursement"),
    ("Tenor", "loan_duration"),
    ("All-in fee", "origination_fee_pct"),
    ("Amount due", "amount_due"),
    ("Due date", "due_date"),
    ("Date of Submitting disbursal receipt", "date_submit_disbursement"),
    ("Interest Rate", "interest_rate"),
]

PARTNER_PILOT_UPLOAD_HEADERS = (
    'KTP doc',
    'Selfie doc',
    'Name',
    'Phone#',
    'KTP #',
    'Alamat email',
    'Jenis Kelamin',
    'Tempat Lahir',
    'Tanggal Lahir',
    'Status Pernikahan',
    'Nama Ibu Kandung / spouse (if married)',
    'No hp orang tua / spouse (if married)',
    'Nama Propinsi',
    'Nama Kota/Kabupaten',
    'Kelurahan',
    'Kode Pos Rumah',
    'Detail Alamat',
    'Nama Bank',
    'No rek bank',
    'Tujuan pinjaman',
    'Omset penjualan perbulan',
    'Pengeluaran perbulan',
    'Jumlah pegawai',
    'Tipe usaha',
    'Foto Selfie + KTP',
    'Approved Limit',
    'Application XID'
)

MF_CSV_UPLOAD_UPGRADE_HEADERS = (
    'application_xid',
    'limit_upgrading'
)


class MerchantFinancingCSVUploadPartner:
    BUKUWARUNG = 'BukuWarung'
    EFISHERY = 'efishery'
    DAGANGAN = 'Dagangan'
    KOPERASI_TUNAS = 'koperasi tunas'
    FISHLOG = 'fishlog'
    EFISHERY_KABAYAN_LITE = 'efishery kabayan lite'
    RABANDO = 'Rabando'
    KARGO = 'kargo'
    KOPERASI_TUNAS_45 = 'koperasi tunas 45'
    AGRARI = 'agrari'
    EFISHERY_INTI_PLASMA = 'efishery inti plasma'
    EFISHERY_JAWARA = 'efishery jawara'
    EFISHERY_KABAYAN_REGULER = 'efishery kabayan reguler'
    GAJIGESA = 'gaji gesa'
    VENTENY = 'venteny'
    DEMO_MFSP_DUMMY_PARTNER = 'demo_mfsp_dummy_partner'
    CARDEKHO = 'cardekho'


MerchantFinancingSKRTPNewTemplate = []
for attribute_name in dir(MerchantFinancingCSVUploadPartner):
    if not attribute_name.startswith("__"):
        attribute_value = getattr(MerchantFinancingCSVUploadPartner, attribute_name)
        MerchantFinancingSKRTPNewTemplate.append(attribute_value)


MERCHANT_FINANCING_PRODUCT_LINE_CODE = {
    'BukuWarung': 'BW',
    'efishery': 'EF',
    'Dagangan': 'DAGANGAN',
    'KOPERASI_TUNAS': 'KOPERASI_TUNAS',
    'FISHLOG': 'FISHLOG',
    'EFISHERY_KABAYAN_LITE': 'EFISHERY_KABAYAN_LITE',
    'RABANDO': 'RABANDO',
    'KARGO': 'KARGO',
    'KOPERASI_TUNAS': 'KOPERASI_TUNAS_45',
}

LOAN_HALT_ACTION_CHOICES = (
    ("Halt", "Halt"),
    ("Resume", "Resume"),
)

LOAN_RESTRUCTURING_ACTION_CHOICES = (
    ("Restructure", "Restructure"),
    ("Revert", "Revert")
)

LOAN_HALT_LABEL = (
    "Loan halt Key",
    "Loan Resume Key"
)

LOAN_RESTRUCTURING_LABEL = (
    "Loan Restructuring Key",
    "Loan Restructuring Revert Key"
)

LOAN_EARLY_WRITE_OFF_ACTION_CHOICES = (
    ("Early Write Off", "Early Write Off"),
    ("Revert", "Revert")
)

GRAB_REFERRAL_ACTION_CHOICES = (
    ("Referral", "Referral"),
    ("Referral w/o updating whitelist", "Referral w/o updating whitelist"),
)

LOAN_EARLY_WRITE_OFF_LABEL = (
    "Loan Early Write Off Key",
    "Loan Early Write Off Revert Key"
)

GRAB_REFERRAL_LABEL = (
    "Referral and create new whitelist",
    "Referral without updating Whitelist"
)

MF_REGISTER_KEY = PARTNER_PILOT_UPLOAD_ACTION_KEY[0][0]
MF_DISBURSEMENT_KEY = PARTNER_PILOT_UPLOAD_ACTION_KEY[1][0]
MF_ADJUST_LIMIT_KEY = PARTNER_PILOT_UPLOAD_ACTION_KEY[3][0]


class MerchantFinancingCSVUploadPartnerDueDateType(object):
    MONTHLY = 'monthly'
    END_OF_TENOR = 'end of tenor'


MerchantFinancingCsvAdjustLimitPartner = [
    MerchantFinancingCSVUploadPartner.EFISHERY,
    MerchantFinancingCSVUploadPartner.DAGANGAN,
    MerchantFinancingCSVUploadPartner.KOPERASI_TUNAS,
    MerchantFinancingCSVUploadPartner.FISHLOG,
    MerchantFinancingCSVUploadPartner.RABANDO,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
    MerchantFinancingCSVUploadPartner.KOPERASI_TUNAS_45,
    MerchantFinancingCSVUploadPartner.AGRARI,
    MerchantFinancingCSVUploadPartner.EFISHERY_INTI_PLASMA,
    MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA
]

MerchantFinancingCsvUpgradePartner = [
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_LITE,
    MerchantFinancingCSVUploadPartner.EFISHERY_KABAYAN_REGULER,
    MerchantFinancingCSVUploadPartner.EFISHERY_JAWARA
]


class FeatureNameConst(object):
    MTL_CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC = 'mtl_check_other_active_platforms_using_fdc'
