from builtins import object
from collections import namedtuple

from juloserver.payment_point.constants import TransactionMethodCode

CONTENT_MIME_TYPE_TXT = 'text/plain'
CONTENT_MIME_TYPE_CSV = 'text/csv'
CONTENT_MIME_TYPE_ZIP = 'application/x-zip-compressed'


class ARSwitchingConst(object):
    MS_EXCEL = 'application/vnd.ms-excel'
    MS_EXCEL_WPS = 'application/wps-office.xlsx'
    SPREADSHEET = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    CSV = 'text/csv'
    ALLOWED_CONTENT_TYPE = (MS_EXCEL, MS_EXCEL_WPS, SPREADSHEET, CSV)
    EXCEL = (MS_EXCEL, SPREADSHEET)

    MAX_RETRY_ALERT_AR_SWITCH = 3

    STARTED_AR_SWITCH_STATUS = "started"
    IN_PROGRESS_AR_SWITCH_STATUS = "in progress"
    FINISHED_AR_SWITCH_STATUS = "finished"


class FeatureNameConst(object):
    BSS_CHANNELING_RISK_ACCEPTANCE_CRITERIA = 'bss_channeling_risk_acceptance_criteria'
    FORCE_UPDATE_BSS_CHANNELING_ELIGIBLE_STATUS = 'force_update_bss_channeling_eligible_status'
    CHANNELING_LOAN_CONFIG = 'channeling_loan_configuration'
    CHANNELING_PRIORITY = 'channeling_priority'
    AR_SWITCHING_LENDER = 'ar_switching_lender'
    BSS_CHANNELING_EDUCATION_MAPPING = 'bss_channeling_education_mapping'
    CHANNELING_LOAN_EDITABLE_INELIGIBILITIES = 'channeling_loan_editable_ineligibilities'
    LOAN_WRITE_OFF = 'loan_write_off'
    EXCLUDE_MOTHER_MAIDEN_NAME_FAMA = 'exclude_mother_maiden_name_fama'
    BNI_INTEREST_CONFIG = 'bni_interest_config'
    FILTER_FIELD_CHANNELING = 'filter_field_channeling'
    FORCE_CHANNELING = 'force_channeling'
    BLOCK_REGENERATE_DOCUMENT_AR_SWITCHING = 'block_regenerate_document_ar_switching'
    BSS_MANUAL_CHANNELING_EDUCATION_MAPPING = 'bss_manual_channeling_education_mapping'
    SMF_CHANNELING_RETRY = 'smf_channeling_retry'
    BYPASS_DAILY_LIMIT_THRESHOLD = 'bypass_daily_limit_threshold'
    CREDIT_SCORE_CONVERSION = "credit_score_conversion"


class ChannelingConst(object):
    BJB = "BJB"
    BSS = "BSS"
    FAMA = "FAMA"
    BCAD = "BCAD"
    PERMATA = "PERMATA"
    DBS = "DBS"
    BNI = "BNI"
    SMF = "SMF"
    GENERAL = "GENERAL"
    LIST = (BSS, BJB, FAMA, BCAD, PERMATA, DBS, SMF, BNI)
    CHOICES = (
        (BSS, BSS),
        (BJB, BJB),
        (FAMA, FAMA),
        (BCAD, BCAD),
        (PERMATA, PERMATA),
        (DBS, DBS),
        (SMF, SMF),
        (BNI, BNI),
    )

    MANUAL_CHANNELING_TYPE = "manual"
    HYBRID_CHANNELING_TYPE = "hybrid"
    API_CHANNELING_TYPE = "API"
    LIST_CRM_CHANNELING_TYPE = (MANUAL_CHANNELING_TYPE, HYBRID_CHANNELING_TYPE)

    DEFAULT_TIMESTAMP = "2022-03-24 20:26:00.00+07"
    DEFAULT_INTERVAL = 0
    DEFAULT_VERSION = 0
    FILE_UPLOAD_EXTENSIONS = ['xls', 'xlsx', 'csv']
    EDITABLE_INELIGIBILITES = 'general_editable_ineligibilities'

    INACTIVE_DAY_STRING_FORMAT = '%A'
    INACTIVE_DATE_STRING_FORMAT = '%Y/%m/%d'

    LENDER_FAMA = 'fama_channeling'
    LENDER_DBS = 'dbs_channeling'
    LENDER_SMF = 'smf_channeling'
    LENDER_JTP = 'jtp'


class ChannelingStatusConst(object):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    PENDING = "pending"
    PROCESS = "process"
    SUCCESS = "success"
    REJECT = "reject"
    BUYBACK = "buyback"
    FAILED = "failed"
    RETRY = "retry"
    PREFUND = "prefund"
    ELIGIBILITY_CHOICES = (
        (INELIGIBLE, INELIGIBLE),
        (ELIGIBLE, ELIGIBLE),
    )
    LIST = (
        INELIGIBLE,
        ELIGIBLE,
        PENDING,
        PROCESS,
        SUCCESS,
        REJECT,
        BUYBACK,
        PREFUND,
    )
    CHOICES = (
        (ELIGIBLE, ELIGIBLE),
        (PENDING, PENDING),
        (PROCESS, PROCESS),
        (SUCCESS, SUCCESS),
        (REJECT, REJECT),
        (BUYBACK, BUYBACK),
        (PREFUND, PREFUND),
    )
    TEMPLATE_CHOICES = (
        ("all", "-------------"),
        (INELIGIBLE, INELIGIBLE),
    ) + CHOICES
    STATUS_MAPPING = {True: ELIGIBLE, False: INELIGIBLE}
    REVERSE_STATUS_MAPPING = {ELIGIBLE: True, INELIGIBLE: False}
    COUNT_LIMIT = (
        PENDING,
        PROCESS,
        SUCCESS,
        PREFUND,
    )
    DBS_ALLOW_DISBURSE_STATUS = (PREFUND, PENDING)


class ChannelingApprovalStatusConst(object):
    YES = 'y'
    NO = 'n'


class ChannelingActionTypeConst(object):
    DISBURSEMENT = "disbursement"
    REPAYMENT = "repayment"
    RECONCILIATION = "reconciliation"
    EARLY_PAYOFF = "early_payoff"
    RECAP = "recap"
    CHOICES = (
        (DISBURSEMENT, DISBURSEMENT),
        (REPAYMENT, REPAYMENT),
        (RECONCILIATION, RECONCILIATION),
        (EARLY_PAYOFF, EARLY_PAYOFF),
        (RECAP, RECAP),
    )


class ChannelingLoanApprovalFileConst(object):
    PROCESS_APPROVAL_FILE_DELAY_MINS = 2
    BEING_PROCESSED_MESSAGE = (
        'Your download approval request is being processed. '
        'Please wait for about {} minutes and re-click the button.'
    )
    ERROR_PROCESSED_MESSAGE = (
        'An error occurred while processing your request. Please contact the administrator.'
    )
    DOCUMENT_TYPE = 'channeling_loan_approval_file'


class ChannelingLoanRepaymentFileConst(object):
    DOCUMENT_TYPE = 'channeling_loan_repayment_file'


class ChannelingLoanReconciliationFileConst(object):
    DOCUMENT_TYPE = 'channeling_loan_reconciliation_file'


class ChannelingLenderLoanLedgerConst(object):
    INITIAL_TAG = "initial_tag"
    REPLENISHMENT_TAG = "replenishment_tag"
    RELEASED_BY_DPD_90 = "released_by_90dpd"  # DPD_90
    RELEASED_BY_LENDER = "released_by_lender"  # ARS
    RELEASED_BY_REFINANCING = "released_by_refinancing"
    RELEASED_BY_REPAYMENT = "released_by_repayment"  # Lender withdraw money
    RELEASED_BY_PAID_OFF = "released_by_paid_off"  # User Payment
    RELEASED_BY_CANCELLATION = "released_by_cancellation"
    RELEASED_BY_FACILITY_LIMIT = "released_by_facility_limit"

    TAG_TYPES = (
        (INITIAL_TAG, INITIAL_TAG),
        (REPLENISHMENT_TAG, REPLENISHMENT_TAG),
        (RELEASED_BY_DPD_90, RELEASED_BY_DPD_90),
        (RELEASED_BY_LENDER, RELEASED_BY_LENDER),
        (RELEASED_BY_PAID_OFF, RELEASED_BY_PAID_OFF),
        (RELEASED_BY_REFINANCING, RELEASED_BY_REFINANCING),
        (RELEASED_BY_REPAYMENT, RELEASED_BY_REPAYMENT),
        (RELEASED_BY_CANCELLATION, RELEASED_BY_CANCELLATION),
        (RELEASED_BY_FACILITY_LIMIT, RELEASED_BY_FACILITY_LIMIT),
    )

    WITHDRAWAL = "withdrawal"
    REPAYMENT = "repayment"
    TRANSACTION_TYPE = (
        (WITHDRAWAL, WITHDRAWAL),
        (REPAYMENT, REPAYMENT),
    )
    BATCH_SIZE = 1000


class BJBDocumentHeaderConst(object):
    LIST = (
        "NO REG WEBSCORING",
        "FULL NAME",
        "SHORTNAME",
        "NAMA SEBELUM",
        "KODE ID",
        "NO ID",
        "NPWP",
        "TGL AKHIR KTP",
        "TEMPAT LAHIR",
        "TGL LAHIR",
        "NAMA IBU",
        "STATUS PENDIDIKAN",
        "AGAMA",
        "JENIS KELAMIN",
        "STATUS NIKAH",
        "ALAMAT 1",
        "ALAMAT 2",
        "ALAMAT 3",
        "ALAMAT 4",
        "ALAMAT 5",
        "KODE POS",
        "PEKERJAAN",
        "ALAMAT KERJA 1",
        "ALAMAT KERJA 2",
        "ALAMAT KERJA 3",
        "ALAMAT KERJA 4",
        "ALAMAT KERJA 5",
        "AKTIFITAS TRANSAKSI NORMAL",
        "TUJUAN PINJAMAN",
        "PENGHASILAN",
        "KEGIATAN USAHA",
        "NOMINAL PINJAMAN",
        "JANGKA WAKTU PINJAMAN",
        "NO HP",
        "EMAIL",
        "LOAN START DATE",
        "CONTRACT DATE",
        "RATE",
        "LOAN MATURITY DATE",
        "CHARGE AMOUNT 1",
        "CHARGE AMOUNT 2",
        "CHARGE AMOUNT 3",
        "LOKASI USAHA",
        "LOKASI PROYEK",
        "CONTACT PERSON",
        "GOLONGAN DARAH",
        "NAMA PASANGAN",
        "ID PASANGAN",
        "TGL LAHIR PASANGAN",
        "BEKERJA SEBAGAI",
        "NO PK",
        "REPAYMENT METHOD",
        "BRANCH PENCAIRAN",
        "CIF PENCAIRAN",
        "SUFFIX PENCAIRAN",
        "BRANCH PEMBAYARAN",
        "CIF PEMBAYARAN",
        "SUFFIX PEMBAYARAN",
        "BESAR ANGSURAN",
        "NO PK/PINJAMAN",
        "KODE AO",
        "MINSPO",
        "SEKTOR EKONOMI",
        "SIFAT KREDIT",
        "SUKU BUNGA",
        "USER ADMIN",
        "TANGGAL ANGSURAN",
        "FIRST REPAYMENT",
        "KODE DINAS",
        "KODE CABANG",
        "LOAN TYPE",
        "PENGHASILAN PERTAHUN",
        "INTEREST DAY BASIS",
        "KODE TEMPAT LAHIR",
        "DISETUJUI",
    )
    DEFAULT_VALUE = {
        "KODE ID": "01",
        "AGAMA": "",
        "NPWP": "",
        "TGL AKHIR KTP": "",
        "TEMPAT LAHIR": "",
        "ALAMAT KERJA 1": "",
        "ALAMAT KERJA 2": "",
        "ALAMAT KERJA 3": "",
        "ALAMAT KERJA 4": "",
        "ALAMAT KERJA 5": "",
        "TUJUAN PINJAMAN": "KONSUMTIF",
        "KEGIATAN USAHA": "521100",
        "CHARGE AMOUNT 1": "",
        "CHARGE AMOUNT 2": "",
        "CHARGE AMOUNT 3": "",
        "LOKASI USAHA": "1225",
        "LOKASI PROYEK": "1225",
        "NAMA PASANGAN": "ANANG SUNTORO",
        "ID PASANGAN": "3502170103860002",
        "TGL LAHIR PASANGAN": "0860301",
        "BEKERJA SEBAGAI": "WIRAUSAHA",
        "NO PK": "008/SUY-UMKM/2022",
        "REPAYMENT METHOD": "1",
        "BRANCH PENCAIRAN": "0290",
        "CIF PENCAIRAN": "01NKSK",
        "SUFFIX PENCAIRAN": "001",
        "BRANCH PEMBAYARAN": "",
        "CIF PEMBAYARAN": "",
        "SUFFIX PEMBAYARAN": "",
        "NO PK/PINJAMAN": "008/SUY-UMKM/2022",
        "KODE AO": "L835",
        "MINSPO": "",
        "SEKTOR EKONOMI": "521100",
        "SIFAT KREDIT": "9",
        "USER ADMIN": "K324",
        "KODE DINAS": "0167KUR4",
        "KODE CABANG": "0167",
        "LOAN TYPE": "A73",
        "INTEREST DAY BASIS": "3",
        "KODE TEMPAT LAHIR": "1225",
        "DISETUJUI": "y/n",
    }
    FIELD_MAPPING = {
        "NO REG WEBSCORING": "loan.loan_xid",
        "FULL NAME": "application.fullname",
        "SHORTNAME": "application.first_name_only",
        "NAMA SEBELUM": "application.first_name_only",
        "NO ID": "application.ktp",
        "TGL LAHIR": "application.dob",
        "NAMA IBU": "application.customer_mother_maiden_name",
        "STATUS PENDIDIKAN": "application.last_education",
        "JENIS KELAMIN": "application.gender",
        "STATUS NIKAH": "application.marital_status",
        "ALAMAT 1": "application.address_street_num",
        "ALAMAT 2": "application.address_kelurahan",
        "ALAMAT 3": "application.address_kecamatan",
        "ALAMAT 4": "application.address_kabupaten",
        "ALAMAT 5": "application.address_provinsi",
        "KODE POS": "application.address_kodepos",
        "PEKERJAAN": "application.job_type",
        "AKTIFITAS TRANSAKSI NORMAL": "application.monthly_expenses",
        "PENGHASILAN": "application.monthly_income",
        "NOMINAL PINJAMAN": "loan.loan_amount",
        "JANGKA WAKTU PINJAMAN": "loan.loan_duration",
        "NO HP": "application.mobile_phone_1",
        "EMAIL": "application.email",
        "LOAN START DATE": "loan.sphp_accepted_ts",
        "CONTRACT DATE": "loan.sphp_accepted_ts",
        "RATE": "loan_product.interest_rate",
        "LOAN MATURITY DATE": "last_payment.due_date",
        "CONTACT PERSON": "application.close_kin_mobile_phone",
        "GOLONGAN DARAH": "random_blood_type",
        "BESAR ANGSURAN": "loan.total_installment",
        "SUKU BUNGA": "loan_product.interest_rate",
        "TANGGAL ANGSURAN": "first_payment.due_date",
        "FIRST REPAYMENT": "first_payment.due_date",
        "PENGHASILAN PERTAHUN": "application.yearly_income",
    }
    FUNCTION_MAPPING = {
        "TGL LAHIR": "bjb_format_datetime",
        "STATUS PENDIDIKAN": "get_bjb_education_code",
        "JENIS KELAMIN": "get_bjb_gender_code",
        "STATUS NIKAH": "get_bjb_marital_status_code",
        "AKTIFITAS TRANSAKSI NORMAL": "get_bjb_expenses_code",
        "PENGHASILAN": "get_bjb_income_code",
        "LOAN START DATE": "bjb_format_datetime",
        "CONTRACT DATE": "bjb_format_datetime",
        "LOAN MATURITY DATE": "bjb_format_datetime",
        "TANGGAL ANGSURAN": "bjb_format_day",
        "FIRST REPAYMENT": "bjb_format_datetime",
    }


class BSSChannelingConst(object):
    PRODUCT = "JULOBSS001"
    USER = "JULOBSS001"
    COMPANYID = "JULOBSS001"
    LOAN_PREFIX = "506160"
    LOAN_PREFIX_MANUAL = "506380"
    DATE_STRING_FORMAT = "%Y-%m-%d %H:%M:%S"
    LENDER_NAME = 'bss_channeling'

    NOT_OK_STATUS = "not ok"
    OK_STATUS = "ok"

    SUCCESS_STATUS_CODE = "00"
    DATA_FAILED_STATUS_CODE = "10"
    SCHEDULE_FAILED_STATUS_CODE = "20"
    BANK_FAILED_STATUS_CODE = "30"
    ONPROGRESS_STATUS_CODE = "40"
    UNDEFINED_STATUS_CODE = "99"

    TRANSFER_OUT_SUCCESS_STATUS_CODE = "00"
    TRANSFER_OUT_PENDING_STATUS_CODE = "01"
    TRANSFER_OUT_FAILED_STATUS_CODE = "02"

    EFFECTIVERATE = "33"
    FAILED_STATUS_CODES = (
        DATA_FAILED_STATUS_CODE,
        SCHEDULE_FAILED_STATUS_CODE,
        BANK_FAILED_STATUS_CODE,
    )

    BSS_CUSTOMER_DATA_KEY = {
        "zipcode": "customerdata[custzip]",
        "birthplace": "customerdata[birthplace]",
        "fullname": "customerdata[fullname]",
        "custname": "customerdata[custname]",
        "phoneno": "customerdata[phoneno]",
        "mobileno": "customerdata[mobileno]",
        "birthdate": "customerdata[birthdate]",
        "mothername": "customerdata[mmn]",
    }
    BSS_SANITIZE_DATA = [
        "fullname",
        "custname",
        "phoneno",
        "mobileno",
        "mothername",
        "birthplace",
    ]


class FAMAChannelingConst(object):
    PARTNER_CODE = "JTF"
    PARTNER_NAME = "JULO"

    SFTP_DISBURSEMENT_APPROVAL_DIRECTORY_PATH = 'Disbursement/Report'
    SFTP_REPAYMENT_APPROVAL_DIRECTORY_PATH = 'Repayment/Report'
    SFTP_RECONCILIATION_APPROVAL_DIRECTORY_PATH = 'Reconciliation/Report'

    DISBURSEMENT = "disbursement"
    REPAYMENT = "repayment"
    RECONCILIATION = "reconciliation"

    FILE_TYPE = {
        DISBURSEMENT: SFTP_DISBURSEMENT_APPROVAL_DIRECTORY_PATH,
        REPAYMENT: SFTP_REPAYMENT_APPROVAL_DIRECTORY_PATH,
        RECONCILIATION: SFTP_RECONCILIATION_APPROVAL_DIRECTORY_PATH,
    }

    FTC_NEW = "New"
    FTC_REPEATED = "Repeated"

    # status reject in every line of the approval txt file
    APPROVAL_STATUS_REJECT = 'Reject'

    MAX_CONSTRUCT_DISBURSEMENT_TIMES = 3
    MAX_GET_NEW_REPAYMENT_APPROVAL_TIMES = 3

    FILENAME_DATE_FORMAT = "%Y%m%d"
    BATCH_SIZE = 1000
    COUNTDOWN_RETRY_IN_SECONDS = 60 * 60


class FAMALoanTypeConst(object):
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


class FAMADocumentHeaderConst(object):
    PRODUCT_HEADER = {
        "Partner_Code": FAMAChannelingConst.PARTNER_CODE,
        "Partner_Name": FAMAChannelingConst.PARTNER_NAME,
        "Date_File": "datefile",
        "Record_Number": "record_number",
    }
    NON_PRODUCT_HEADER = {
        **PRODUCT_HEADER,
        "Sum_Amount": "sum_amount",
    }
    SPAREFIELD_NUMBER = 10

    PRODUCT = "PRODUCT"
    APPLICATION = "APPLICATION"
    LOAN = "LOAN"
    PAYMENT = "PAYMENT"
    REPAYMENT = "REPAYMENT"
    RECONCILIATION = "RECONCILIATION"
    SUM_AMOUNT = "Sum_Amount"

    LIST = (
        PRODUCT,
        APPLICATION,
        LOAN,
        PAYMENT,
    )
    FILENAME_MAP = {
        PRODUCT: "Product",
        APPLICATION: "Application",
        LOAN: "Contract",
        PAYMENT: "Loan_Schedule",
        REPAYMENT: "Payment",
        RECONCILIATION: "Reconciliation",
    }

    SKIP_CHECKER = (
        "Partner_Code",
        "Partner_Name",
        "Identity_Type",
        "NPWP",
        "Nationality",
        "Country",
        "Source of Fund",
        "MiddleName",
        "LastName",
        "NIKPasangan",
        "DOBPasangan",
        "Customer_Segment",
        "Nama Emergency",
        "Hubungan Emergency",
        "Phone Emergency",
        "Currency",
        "Down_Payment",
        "Admin_Fee",
        "Transfer_Fee",
        "Branch Code",
        "Kategori Portofolio",
        "Orientasi Penggunaan",
        "Sektor Ekonomi",
        "Kolektibilitas",
        "Occupation_Code",
        "Job_Title",
        "Company_Industry",
        "Loan Purposes",
        "Jenis Penggunaan",
        "Late_Charge_Amount",
        "Early_payment_Fee",
        "Annual_Fee_Amount",
        "OverPayment",
    )
    DATE_FORMAT_FIELD = (
        "Contract_Date",
        "Last_Contract_Date",
        "Partner_First_Due_Date",
        "Partner_Last_Due_Date",
        "First_Due_Date",
        "Last_Due_Date",
        "Disburse Date",
        "Due_Date",
        "Cust Initial Open Date",
        "DOB",
        "Payment_Date",
        "Posting_Date",
        "Reconciliation_Date",
    )
    DATI_FIELD = {
        "Dati2_Code",
        "Company_Dati2_Code",
        "Res_Dati2_Code",
        "Lokasi Penggunaan",
    }

    SANITIZE_FIELD = (
        "Customer_Name",
        "Identity_Customer_Name",
        "POB",
        "FirstName",
        "Mother_Name",
        "Company_Name",
        "NamaPasangan",
    )

    PRODUCT_FIELD = {
        "Account_ID": "loan.loan_xid",
        "Commodity _Category_Code": "transaction_method['comodity_code']",
        "Producer": "transaction_method['producer']",
        "Goods_Type": "transaction_method['goods_type']",
        "TYPE LOAN": "transaction_method['type_loan']",
    }
    APPLICATION_FIELD = {
        "Application_ID": "loan.loan_xid",
        "Customer_Name": "application.fullname",
        "Identity_Customer_Name": "application.fullname",
        "Identity_Type": "KTP",
        "Identity_No": "application.ktp",
        "NPWP": "",
        "Gender": "application.gender",
        "DOB": "application.dob",
        "POB": "application.birth_place or application.address_kabupaten",
        "Mother_Name": "application.customer_mother_maiden_name",
        "Nationality": "WNI",
        "Country": "ID",
        "Address": "application.address_street_num",
        "Kelurahan": "application.address_kelurahan",
        "Kecamatan": "application.address_kecamatan",
        "Kota_Kabupaten": "application.address_kabupaten",
        "Provinsi": "application.address_provinsi",
        "Zip_Code": "application.address_kodepos",
        "Dati2_Code": "application.address_kabupaten",
        "Email_Address": "application.email",
        "MobilePhone_No": "application.mobile_phone_1",
        "Phone_Number": "application.mobile_phone_1",
        "Title": "application.last_education",
        "Marital_Status": "application.marital_status",
        "Jumlah_Tangungan": "application.dependent or 0",
        "Company_Name": "application.company_name",
        "Company_Address": "application.company_address or application.address_street_num",
        "Company_Kelurahan": "application.address_kelurahan",
        "Company_Kecamatan": "application.address_kecamatan",
        "Company_Kota_Kabupaten": "application.address_kabupaten",
        "Company_Provinsi": "application.address_provinsi",
        "Company_Zip_Code": "application.work_kodepos or application.address_kodepos",
        "Company_Dati2_Code": "application.address_kabupaten",
        "Yearly_Income": "application.monthly_income*12",
        "Company_Industry": "OTH",
        "Occupation_Code": "",
        "Job_Title": "ZZZ",
        "Length_of_Work": "application.length_of_work_in_year",
        "Res_Address": "application.address_street_num",
        "Res_Kelurahan": "application.address_kelurahan",
        "Res_Kecamatan": "application.address_kecamatan",
        "Res_Kota_Kabupaten": "application.address_kabupaten",
        "Res_Provinsi": "application.address_provinsi",
        "Res_Zip_Code": "application.address_kodepos",
        "Res_Dati2_Code": "application.address_kabupaten",
        "Workplace telephone number": "application.mobile_phone_1",
        "Source of Fund": "1",
        "Cust Initial Open Date": "application_190.cdate",
        "SalutationCode": "application.gender_salutation",
        "FirstName": "application.first_name_only",
        "MiddleName": "",
        "LastName": "",
        "NamaPasangan": "application.spouse_name",
        "NIKPasangan": "",
        "DOBPasangan": "",
        "Customer_Segment": "Premium",
        "Kode Status Pendidikan": "application.last_education",
        "Nama Emergency": "",
        "Hubungan Emergency": "",
        "Phone Emergency": "",
        "Credit Score": "b_score",
    }
    LOAN_FIELD = {
        "Application_ID": "loan.loan_xid",
        "Contract_ID": "loan.loan_xid",
        "Contract_Date": "loan.fund_transfer_ts",
        "Last_Contract_ID": "last_loan_xid",
        "Last_Contract_Date": "last_loan_transfer_ts",
        "Account_ID": "loan.loan_xid",
        "Currency": "IDR",
        "Partner_Principla_Balance": "partner_principal_balance",
        "Partner_Interest_Rate": "loan_product.interest_rate",
        "Partner_Interest_Amount": "channeling_loan_status.channeling_interest_amount",
        "Partner_Tenor": "loan.loan_duration",
        "Partner_Instalment": "channeling_payment.original_outstanding_amount",
        "Partner_Jumlah_Hari": "loan_total_days",
        "Partner_Flag_Periode": "flag_periode",
        "Partner_First_Due_Date": "first_payment.due_date",
        "Partner_Last_Due_Date": "last_payment.due_date",
        "Principla_Balance": "partner_principal_balance",
        "Interest_Rate": "channeling_loan_status.channeling_interest_percentage*360*100",
        "Interest_Amount": "interest_amount_line",
        "Tenor": "loan.loan_duration",
        "Instalment": "channeling_payment.original_outstanding_amount",
        "Jumlah_Hari": "loan_total_days",
        "Flag_Periode": "flag_periode",
        "Outstanding_Amount": "outstanding_amount_line",
        "First_Due_Date": "first_payment.due_date",
        "Last_Due_Date": "last_payment.due_date",
        "Down_Payment": "0",
        "Admin_Fee": "0",
        "Provision_Fee": "0",
        "Transfer_Fee": "0",
        "Loan Purposes": "Kredit Konsumsi",
        "Disburse Date": "loan.fund_transfer_ts",
        "Branch Code": "1101",
        "Kategori Portofolio": "36",
        "Jenis Penggunaan": "3",
        "Orientasi Penggunaan": "3",
        "Sektor Ekonomi": "003900",
        "Lokasi Penggunaan": "application.address_kabupaten",
        "Kolektibilitas": "1",
        "DPD": "dpd",
    }
    PAYMENT_FIELD = {
        "Account_ID": "loan.loan_xid",
        "Currency": "IDR",
        "Term_Payment": "payment.payment_number",
        "Due_Date": "payment.due_date",
        "Interest_Amount": "interest_amount",
        "Principal_Amount": "principal_amount",
        "Instalment_Amount": "instalment_amount",
    }
    REPAYMENT_FIELD = {
        "Account_ID": "loan.loan_xid",
        "Currency": "IDR",
        "Payment_Type": "payment_event",
        "Payment_Date": "payment_event.event_date",
        "Posting_Date": "timezone.localtime(timezone.now())",
        "Partner_Payment_ID": "payment_event.payment_receipt",
        "Interest_Amount": "payment_type[field]",
        "Principal_Amount": "payment_type[field]",
        "Instalment_Amount": "payment_type[field]",
        "Payment_Amount": "payment_type[field]",
        "OverPayment": "0",
        "Term_Payment": "payment.payment_number",
        "Late_Charge_Amount": "0",
        "Early_payment_Fee": "0",
        "Annual_Fee_Amount": "0",
    }

    RECONCILIATION_FIELD = {
        "Account_ID": "loan.loan_xid",
        "Currency": "IDR",
        "Reconciliation_Date": "timezone.localtime(timezone.now())",
        "Posting_Date": "timezone.localtime(timezone.now())",
        "Collectability": "dpd",
        "Outstanding_Amount": "outstanding_amount",
        "DPD": "dpd",
        "Principal_Due": "principal_due",
        "Interest_Due": "interest_due",
        "Outstanding_Principal": "outstanding_principal",
        "Outstanding_Interest": "outstanding_interest",
    }
    FUNCTION_MAPPING = {
        "Marital_Status": "get_fama_marital_status_code",
        "Kode Status Pendidikan": "get_fama_education_code",
        "Interest_Rate": "format_two_digit",
        "Provision_Fee": "format_two_digit",
        "Partner_Interest_Rate": "format_two_digit",
        "Partner_Interest_Amount": "format_two_digit",
        "MobilePhone_No": "format_phone",
        "Phone_Number": "format_phone",
        "Workplace telephone number": "format_phone",
        "Title": "get_fama_title_code",
        "Gender": "get_fama_gender",
        "Payment_Type": "get_fama_payment_type",
        "Collectability": "get_collectability",
        "Admin_Fee": "format_two_digit",
        "Partner_Instalment": "format_two_digit",
        "Instalment": "format_two_digit",
        "Partner_Principla_Balance": "format_two_digit",
        "Principla_Balance": "format_two_digit",
        "Account_ID": "get_account_id_with_prefix",
        "Application_ID": "get_account_id_with_prefix",
        "Contract_ID": "get_account_id_with_prefix",
    }


class TransactionMethodConst(object):
    TRANSACTION_METHOD_CODES = [
        *TransactionMethodCode.cash(),
        *TransactionMethodCode.payment_point(),
    ]


class BSSMaritalStatusConst(object):
    LIST = {
        'Lajang': '1',
        'Menikah': '2',
        'Cerai': '3',
        'Janda / duda': '3',
    }


class BSSEducationConst(object):
    LIST = {
        "TK": "00",
        "SD": "00",
        "SLTP": "00",
        "SLTA": "00",
        "Diploma": "99",
        "S1": "04",
        "S2": "05",
        "S3": "06",
    }
    LIST_CHANNELING_MANUAL = (
        {
            "TK": "00",
            "SD": "00",
            "SLTP": "00",
            "SLTA": "00",
            "": "99",
            "D1": "01",
            "D2": "02",
            "D3": "03",
            "S1": "04",
            "S2": "05",
            "S3": "06",
        },
    )


class ChannelingLoanDatiConst(object):
    DEFAULT_NOT_FOUND_AREA = "DI LUAR INDONESIA"
    DEFAULT_NOT_FOUND_CODE = "9999"


class FAMAOccupationMappingConst(object):
    LIST = {
        "Admin / Finance / HR,Admin": "006",
        "Admin / Finance / HR,Akuntan / Finance": "001",
        "Admin / Finance / HR,HR": "006",
        "Admin / Finance / HR,Office Boy": "035",
        "Admin / Finance / HR,Sekretaris": "006",
        "Admin / Finance / HR,Lainnya": "006",
        "Design / Seni,Design Grafis": "023",
        "Design / Seni,Pelukis": "025",
        "Design / Seni,Photographer": "025",
        "Design / Seni,Lainnya": "025",
        "Entertainment / Event,DJ / Musisi": "025",
        "Entertainment / Event,Event Organizer": "025",
        "Entertainment / Event,Kameraman": "025",
        "Entertainment / Event,Penyanyi / Penari / Model": "025",
        "Entertainment / Event,Produser / Sutradara": "025",
        "Entertainment / Event,Lainnya": "025",
        "Hukum / Security / Politik,Anggota Pemerintahan": "036",
        "Hukum / Security / Politik,Hakim / Jaksa / Pengacara": "020",
        "Hukum / Security / Politik,Notaris": "020",
        "Hukum / Security / Politik,Ormas": "037",
        "Hukum / Security / Politik,Pemuka Agama": "037",
        "Hukum / Security / Politik,Satpam": "099",
        "Hukum / Security / Politik,TNI / Polisi": "010",
        "Hukum / Security / Politik,Lainnya": "014",
        "Kesehatan,Apoteker": "019",
        "Kesehatan,Dokter": "019",
        "Kesehatan,Perawat": "019",
        "Kesehatan,Teknisi Laboratorium": "019",
        "Kesehatan,Lainnya": "019",
        "Konstruksi / Real Estate,Arsitek / Tehnik Sipil": "004",
        "Konstruksi / Real Estate,Interior Designer": "023",
        "Konstruksi / Real Estate,Mandor": "099",
        "Konstruksi / Real Estate,Pemborong": "099",
        "Konstruksi / Real Estate,Proyek Manager / Surveyor": "099",
        "Konstruksi / Real Estate,Real Estate Broker": "099",
        "Konstruksi / Real Estate,Tukang Bangunan": "099",
        "Konstruksi / Real Estate,Lainnya": "099",
        "Media,Kameraman": "099",
        "Media,Penulis / Editor": "099",
        "Media,Wartawan": "099",
        "Media,Lainnya": "099",
        "Pabrik / Gudang,Buruh Pabrik / Gudang": "032",
        "Pabrik / Gudang,Kepala Pabrik / Gudang": "032",
        "Pabrik / Gudang,Teknisi Mesin": "032",
        "Pabrik / Gudang,Lainnya": "032",
        "Pendidikan,Dosen": "009",
        "Pendidikan,Guru": "009",
        "Pendidikan,Instruktur / Pembimbing Kursus": "009",
        "Pendidikan,Kepala Sekolah": "009",
        "Pendidikan,Tata Usaha": "009",
        "Pendidikan,Lainnya": "009",
        "Perawatan Tubuh,Fashion Designer": "099",
        "Perawatan Tubuh,Gym / Fitness": "099",
        "Perawatan Tubuh,Pelatih / Trainer": "099",
        "Perawatan Tubuh,Salon / Spa / Panti Pijat": "099",
        "Perawatan Tubuh,Lainnya": "025",
        "Perbankan,Back-office": "006",
        "Perbankan,Bank Teller": "006",
        "Perbankan,CS Bank": "002",
        "Perbankan,Credit Analyst": "007",
        "Perbankan,Kolektor": "099",
        "Perbankan,Resepsionis": "099",
        "Perbankan,Lainnya": "099",
        "Sales / Marketing,Account Executive / Manager": "004",
        "Sales / Marketing,Salesman": "005",
        "Sales / Marketing,SPG": "005",
        "Sales / Marketing,Telemarketing": "005",
        "Sales / Marketing,Lainnya": "099",
        "Service,Customer Service": "002",
        "Service,Kasir": "099",
        "Service,Kebersihan": "099",
        "Service,Koki": "099",
        "Service,Pelayan / Pramuniaga": "099",
        "Service,Lainnya": "099",
        "Tehnik / Computer,Engineer / Ahli Tehnik": "006",
        "Tehnik / Computer,Penulis Teknikal": "006",
        "Tehnik / Computer,Programmer / Developer": "006",
        "Tehnik / Computer,R&D / Ilmuwan / Peneliti": "006",
        "Tehnik / Computer,Warnet": "099",
        "Tehnik / Computer,Otomotif": "099",
        "Tehnik / Computer,Lainnya": "099",
        "Transportasi,Supir / Ojek": "031",
        "Transportasi,Agen Perjalanan": "031",
        "Transportasi,Kurir / Ekspedisi": "031",
        "Transportasi,Pelaut / Staff Kapal / Nahkoda Kapal": "030",
        "Transportasi,Pilot / Staff Penerbangan": "029",
        "Transportasi,Sewa Kendaraan": "031",
        "Transportasi,Masinis / Kereta Api": "031",
        "Transportasi,Lainnya": "099",
        "Staf Rumah Tangga,Babysitter / Perawat": "035",
        "Staf Rumah Tangga,Pembantu Rumah Tangga": "035",
        "Staf Rumah Tangga,Supir": "035",
        "Staf Rumah Tangga,Tukang Kebun": "035",
        "Staf Rumah Tangga,Lainnya": "035",
        "Perhotelan, Customer Service": "021",
        "Perhotelan, Kebersihan": "021",
        "Perhotelan, Koki": "021",
        "Perhotelan, Room Service / Pelayan": "021",
        "Perhotelan, Lainnya": "021",
        "DEFAULT_VALUE": "099",
    }


class MartialStatusConst(object):
    MENIKAH = "Menikah"
    LAJANG = "Lajang"
    CERAI = "Cerai"
    JANDA_DUDA = "Janda / duda"
    MARRIED = "Married"
    SINGLE = "Single"
    DIVORCED = "Divorced"
    DIVORCE_LIST = (CERAI, JANDA_DUDA)


class FAMAEducationConst(object):
    LIST = {
        "Tidak ada gelar": "00",
        "Diploma": "03",
        "Diploma 1": "01",
        "Diploma 2": "02",
        "Diploma 3": "03",
        "S1": "04",
        "S2": "05",
        "S3": "06",
    }


class LoanTaggingConst(object):
    DEFAULT_MARGIN = 10000000
    DEFAULT_LOAN_QUERY_BATCH_SIZE = 1000
    DEFAULT_LENDERS = ['jtp']

    LENDERS_MATCH_FOR_LENDER_OSP_ACCOUNT = {
        'BSS': ['jtp', 'helicap'],
        'FAMA': ['jtp', 'helicap'],
        'Lend East': ['jh'],
        'Helicap': ['jh'],
    }


class GeneralIneligible:
    """
    General Ineligibilites for loan channeling
    """

    Condition = namedtuple("Condition", 'name message')

    LOAN_NOT_FOUND = Condition("LOAN_NOT_FOUND", "Loan not found")
    ZERO_INTEREST_LOAN_NOT_ALLOWED = Condition(
        "ZERO_INTEREST_LOAN_NOT_ALLOWED", "Loan zero interest not allowed"
    )
    LOAN_TRANSACTION_TYPE_NOT_ALLOWED = Condition(
        "LOAN_TRANSACTION_TYPE_NOT_ALLOWED",
        "Loan transaction type not allowed",
    )
    HAVENT_PAID_OFF_A_LOAN = Condition(
        "HAVENT_PAID_OFF_LOAN",
        "User didn't paid off a loan",
    )
    HAVENT_PAID_OFF_AN_INSTALLMENT = Condition(
        "HAVENT_PAID_OFF_AN_INSTALLMENT",
        "User hasn't paid off an installment yet",
    )
    ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT = Condition(
        "ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT",
        "Account status already entered status that > 420 before",
    )
    AUTODEBIT_INTEREST_BENEFIT = Condition(
        "AUTODEBIT_INTEREST_BENEFIT",
        "Account cannot be channeling due to autodebet interest benefit",
    )
    LOAN_HAS_INTEREST_BENEFIT = Condition(
        "LOAN_HAS_INTEREST_BENEFIT",
        "Loan has interest benefit",
    )
    LOAN_FROM_PARTNER = Condition("LOAN_FROM_PARTNER", "Loan from partner")
    LOAN_ADJUSTED_RATE = Condition("LOAN_ADJUSTED_RATE", "Loan adjusted rate not allowed")
    CHANNELING_TARGET_MISSING = Condition(
        "CHANNELING_TARGET_MISSING",
        "channeling target missing, please configure in admin page",
    )


class BSSDataField:
    @classmethod
    def customer_address(cls):
        return [
            "customerdata[custaddress]",
            "customerdata[custkel]",
            "customerdata[custkec]",
            "customerdata[custcity]",
            "customerdata[custprov]",
            "customerdata[custzip]",
            "customerdata[custaddresshome]",
            "customerdata[custkelhome]",
            "customerdata[custkechome]",
            "customerdata[custcityhome]",
            "customerdata[custprovhome]",
            "customerdata[custziphome]",
        ]


class FAMATitleConst(object):
    LIST = {
        "D1": "DIP",
        "D2": "DIP",
        "D3": "DIP",
        "S1": "GRD",
        "S2": "GRD",
        "S3": "PGD",
    }


class PermataChannelingConst(object):
    PARTNER_CODE = "JTF"
    PARTNER_NAME = "JULO"
    PARTNER_RECONCILIATION_CODE = "017"

    SFTP_APPROVAL_DIRECTORY_PATH = "Inbox"

    FILE_TYPE_DISBURSEMENT = "disbursement"
    ACCEPTED_DISBURSEMENT_FILENAME_PREFIX = "Laporan Realisasi Pencairan Bank"
    ACCEPTED_DISBURSEMENT_LOAN_XID_PATTERN = r'\d{9,}'
    REJECTED_DISBURSEMENT_FILENAME_PREFIX = "Laporan Reject Cair"
    REJECTED_DISBURSEMENT_LOAN_ROW_INDEX = 14
    REJECTED_DISBURSEMENT_LOAN_COLUMN_INDEX = 1

    FILE_TYPE_REPAYMENT = "repayment"
    REPAYMENT_FILENAME_PREFIX = "Laporan Realisasi Pembayaran Angsuran"

    FILE_TYPE_EARLY_PAYOFF = "early_payoff"
    EARLY_PAYOFF_FILENAME_PREFIX = "Laporan Pelunasan Dipercepat"


class PermataDocumentHeaderConst:
    DISBURSEMENT_CIF = "CIF"
    DISBURSEMENT_SLIK = "SLIK"
    DISBURSEMENT_FIN = "FIN"
    DISBURSEMENT_SIPD = "SIPD"
    DISBURSEMENT_AGUN = "AGUN"
    PAYMENT_CHANNELING = "Payment"
    RECONCILIATION_CHANNELING = "Rekon"
    RECOVERY_CHANNELING = "Recovery"

    PERMATA_CHANNELING_DISBURSEMENT = [
        DISBURSEMENT_CIF,
        DISBURSEMENT_SLIK,
        DISBURSEMENT_FIN,
        DISBURSEMENT_SIPD,
        DISBURSEMENT_AGUN,
    ]

    # skip all hardcoded value
    SKIP_CHECKER = {
        "ALAMAT_DEB2",
        "KODE_RECOVERY",
    }

    PERMATA_DISBURSEMENT_CHANNELING = {
        DISBURSEMENT_CIF: {
            "LOAN_ID": "permata_disbursement_cif.loan_id",
            "NAMA": "permata_disbursement_cif.nama",
            "NAMA_REKANAN": "permata_disbursement_cif.nama_rekanan",
            "NAMA_CABANG": "permata_disbursement_cif.nama_cabang",
            "ALAMAT_CBG1": "permata_disbursement_cif.alamat_cbg1",
            "ALAMAT_CBG2": "permata_disbursement_cif.alamat_cbg2",
            "KOTA": "permata_disbursement_cif.kota",
            "USAHA": "permata_disbursement_cif.usaha",
            "ALAMAT_DEB1": "permata_disbursement_cif.alamat_deb1",
            "ALAMAT_DEB2": "",
            "KOTA_DEB": "permata_disbursement_cif.kota_deb",
            "NPWP": "permata_disbursement_cif.npwp",
            "KTP": "permata_disbursement_cif.ktp",
            "TGL_LAHIR": "permata_disbursement_cif.tgl_lahir",
            "TGL_NOVASI": "permata_disbursement_cif.tgl_novasi",
            "TMPTLAHIR": "permata_disbursement_cif.tmpt_lahir",
            "CODERK": "permata_disbursement_cif.coderk",
            "NOREKENING": "permata_disbursement_cif.no_rekening",
            "TGLPROSES": "permata_disbursement_cif.tgl_proses",
            "KELURAHAN": "permata_disbursement_cif.kelurahan",
            "KECAMATAN": "permata_disbursement_cif.kecamatan",
            "KODEPOS": "permata_disbursement_cif.kode_pos",
            "STATUSACC": "permata_disbursement_cif.status_acc",
            "NAMAIBU": "permata_disbursement_cif.nama_ibu",
            "PEKERJAAN": "permata_disbursement_cif.pekerjaan",
            "USAHADIMANABKRJ": "permata_disbursement_cif.usaha_dimana_bkrj",
            "NAMAALIAS": "permata_disbursement_cif.nama_alias",
            "STATUS": "permata_disbursement_cif.status",
            "KETSTATUS": "permata_disbursement_cif.ket_status",
            "GOLDEB": "permata_disbursement_cif.customer_grouping",
            "PASPORT": "permata_disbursement_cif.pasport",
            "KODEAREA": "permata_disbursement_cif.kodearea",
            "TELEPON": "permata_disbursement_cif.telepon",
            "JNSKELAMIN": "permata_disbursement_cif.jenis_kelamin",
            "SANDIPKRJ": "permata_disbursement_cif.sandi_pkrj",
            "TEMPATBEKERJA": "permata_disbursement_cif.tempat_bekerja",
            "BIDANGUSAHA": "permata_disbursement_cif.bidang_usaha",
            "AKTEAWAL": "permata_disbursement_cif.akte_awal",
            "TGLAKTEAWAL": "permata_disbursement_cif.tgl_akte_awal",
            "AKTEAKHIR": "permata_disbursement_cif.akte_akhir",
            "TGLAKTEAKHIR": "permata_disbursement_cif.tgl_akte_akhir",
            "TEMPATBERDIRI": "permata_disbursement_cif.tgl_berdiri",
            "DATIDEBITUR": "permata_disbursement_cif.dati_debitur",
            "HP": "permata_disbursement_cif.hp",
            "DATILAHIR": "permata_disbursement_cif.dati_lahir",
            "TMPTLHRDATI": "permata_disbursement_cif.tmpt_lhr_dati",
            "NAMALENGKAP": "permata_disbursement_cif.nama_lengkap",
            "ALAMAT": "permata_disbursement_cif.alamat",
            "TLPRUMAH": "permata_disbursement_cif.tlp_rumah",
            "KODE_JENIS_PENGGUNAAN_LBU": "permata_disbursement_cif.kode_jenis_penggunaan_lbu",
            "KODE_JENIS_PENGGUNAAN_SID": "permata_disbursement_cif.kode_jenis_penggunaan_sid",
            "KODE_GOLONGAN_KREDIT_UMKM_LBU_SID": (
                "permata_disbursement_cif.kode_golongan_kredit_umkm_lbu_sid"
            ),
            "KODE_KATEGORI_PORTFOLIO_LBU": "permata_disbursement_cif.kode_kategori_portfolio_lbu",
            "CREDIT_SCORING": "permata_disbursement_cif.credit_scoring",
        },
        DISBURSEMENT_SLIK: {
            "LOAN_ID": "permata_disbursement_slik.loan_id",
            "ALAMAT_TEMPAT_BEKERJA": "permata_disbursement_slik.alamat_tempat_bekerja",
            "YEARLY_INCOME": "permata_disbursement_slik.yearly_income",
            "JUMLAH_TANGGUNGAN": "permata_disbursement_slik.jumlah_tanggungan",
            "STATUS_PERKAWINAN_DEBITUR": "permata_disbursement_slik.status_perkawinan_debitur",
            "NOMOR_KTP_PASANGAN": "permata_disbursement_slik.nomor_ktp_pasangan",
            "NAMA_PASANGAN": "permata_disbursement_slik.nama_pasangan",
            "TANGGAL_LAHIR_PASANGAN": "permata_disbursement_slik.tanggal_lahir_pasangan",
            "PERJANJIAN_PISAH_HARTA": "permata_disbursement_slik.perjanjian_pisah_harta",
            "FASILITAS_KREDIT_PEMBAYARAN": "permata_disbursement_slik.fasilitas_kredit",
            "TAKE_OVER_DARI": "permata_disbursement_slik.take_over_dari",
            "KODE_JENIS_PENGGUNAAN": "permata_disbursement_slik.kode_jenis_pengguna",
            "KODE_BIDANG_USAHA_SLIK": "permata_disbursement_slik.kode_bisa_usaha_slik",
            "ALAMAT_EMAIL_DEBITUR_PERORANGAN": "permata_disbursement_slik.email",
            "ALAMAT_SESUAI_DOMISILI": "permata_disbursement_slik.alamat_sesuai_domisili",
            "KATEGORI_DEBITUR_UMKM": "permata_disbursement_slik.kategori_debitur_umkm",
            "DESKRIPSI_JENIS_PENGGUNAAN_KREDIT": (
                "permata_disbursement_slik.deskripsi_jenis_pengguna_kredit"
            ),
            "PEMBIAYAAN_PRODUKTIF": "permata_disbursement_slik.pembiayaan_produktif",
            "MONTHLY INCOME": "permata_disbursement_slik.monthly_income",
        },
        DISBURSEMENT_FIN: {
            "NOPIN": "permata_disbursement_fin.no_pin",
            "TGLPK": "permata_disbursement_fin.tgl_pk",
            "TGLVALID": "permata_disbursement_fin.tgl_valid",
            "TGLANGS1": "permata_disbursement_fin.tgl_angs1",
            "JMLHANGS": "permata_disbursement_fin.jmlh_angs",
            "COST": "permata_disbursement_fin.cost",
            "COSTBANK": "permata_disbursement_fin.cost_bank",
            "ADDM": "permata_disbursement_fin.addm",
            "ANGDEB ": "permata_disbursement_fin.ang_deb",
            "ANGSBANK": "channeling_payment_due_amount",
            "BUNGA": "permata_disbursement_fin.bunga",
            "BUNGABANK": "permata_disbursement_fin.bunga_bank",
            "KONDISIAGUN": "permata_disbursement_fin.kondisi_agun",
            "NILAIAGUN": "permata_disbursement_fin.nilai_agun",
            "PTASURAN": "permata_disbursement_fin.ptasuran",
            "ALAMATASUR1": "permata_disbursement_fin.alamat_asur1",
            "ALAMATASUR2": "permata_disbursement_fin.alamat_asur2",
            "KOTASUR": "permata_disbursement_fin.kota_sur",
            "TGLPROSES": "permata_disbursement_fin.tgl_proses",
            "PREMIASUR": "permata_disbursement_fin.premi_asur",
            "PEMBYRPREMI": "permata_disbursement_fin.pembyr_premi",
            "ASURCASH": "permata_disbursement_fin.asur_cash",
            "INCOME": "permata_disbursement_fin.income",
            "NAMAIBU": "permata_disbursement_fin.nama_ibu",
            "SELISIHBUNGA": "permata_disbursement_fin.selisih_bunga",
            "KODEPAKET": "permata_disbursement_fin.kode_paket",
            "BIAYALAIN": "permata_disbursement_fin.biaya_lain",
            "CARABIAYA": "permata_disbursement_fin.cara_biaya",
            "PERIODEBYR": "permata_disbursement_fin.periode_byr",
            "POKOKAWALPK": "permata_disbursement_fin.pokok_awal_pk",
            "TENORAWAL": "permata_disbursement_fin.tenor_awal",
            "NOPK": "permata_disbursement_fin.no_pk",
            "NETDPCASH": "permata_disbursement_fin.net_dp_cash",
            "ASURJIWATTL": "permata_disbursement_fin.asur_jiwa_ttl",
            "ASURJIWACASH": "permata_disbursement_fin.asur_jiwa_cash",
        },
        DISBURSEMENT_SIPD: {
            "NOPIN": "permata_disbursement_sipd.no_pin",
            "NAMA_REKANAN": "permata_disbursement_sipd.nama_rekanan",
            "ALAMATBPR1": "permata_disbursement_sipd.alamat_bpr1",
            "ALAMATBPR2": "permata_disbursement_sipd.alamat_bpr2",
            "KOTA": "permata_disbursement_sipd.kota",
            "BUKTIKEPEMILIKAN": "permata_disbursement_sipd.bukti_kepemilikan",
            "NO_JAMINAN": "permata_disbursement_sipd.no_jaminan",
            "TGL": "permata_disbursement_sipd.tgl",
            "NAMAPEMILIK": "permata_disbursement_sipd.nama_pemilik",
            "JUMLAH": "permata_disbursement_sipd.jumlah",
            "NORANGKA": "permata_disbursement_sipd.no_rangka",
            "NOMESIN": "permata_disbursement_sipd.no_mesin",
        },
        DISBURSEMENT_AGUN: {
            "NOPIN": "permata_disbursement_agun.no_pin",
            "MERK": "permata_disbursement_agun.merk",
            "JENIS": "permata_disbursement_agun.jenis",
            "MODEL": "permata_disbursement_agun.model",
            "NOPOL": "permata_disbursement_agun.nopol",
            "NORANG": "permata_disbursement_agun.norang",
            "NOMES": "permata_disbursement_agun.nomes",
            "WARNA": "permata_disbursement_agun.warna",
            "TAHUNMOBIL": "permata_disbursement_agun.tahun_mobil",
            "TAHUNRAKIT": "permata_disbursement_agun.tahun_rakit",
            "CILINDER": "permata_disbursement_agun.clinder",
            "KELOMPOK": "permata_disbursement_agun.kelompok",
            "PENGGUNAAN": "permata_disbursement_agun.penggunaan",
            "NILAISCORE": "permata_disbursement_agun.nilai_score",
            "TEMPATSIMPAN": "permata_disbursement_agun.tempat_simpan",
        },
    }

    PERMATA_CHANNELING = {
        RECONCILIATION_CHANNELING: {
            "NOPIN": "permata_reconciliation.nopin",
            "ANGSURAN_KE": "permata_reconciliation.angsuran_ke",
            "OS_POKOK": "permata_reconciliation.os_pokok",
            "NAMA": "permata_reconciliation.nama",
            "DPD": "permata_reconciliation.dpd",
        },
        PAYMENT_CHANNELING: {
            "LOAN_ID": "permata_payment.loan_id",
            "NAMA": "permata_payment.nama",
            "TANGGAL_BAYAR_END": "permata_payment.tgl_bayar_end_user",
            "NILAI_ANGSURAN": "permata_payment.nilai_angsuran",
            "DENDA": "permata_payment.denda",
            "DISKON_DENDA": "permata_payment.diskon_denda",
            "TANGGAL_TERIMA_MF": "permata_payment.tgl_terima_mf",
        },
    }

    PERMATA_CHANNELING_LENGTH = {
        DISBURSEMENT_CIF: {
            "LOAN_ID": 17,
            "NAMA": 32,
            "NAMA_REKANAN": 30,
            "NAMA_CABANG": 32,
            "ALAMAT_CBG1": 25,
            "ALAMAT_CBG2": 25,
            "KOTA": 15,
            "USAHA": 25,
            "ALAMAT_DEB1": 25,
            "ALAMAT_DEB2": 25,
            "KOTA_DEB": 15,
            "NPWP": 20,
            "KTP": 30,
            "TGL_LAHIR": 10,
            "TGL_NOVASI": 17,
            "TMPTLAHIR": 25,
            "CODERK": 1,
            "NOREKENING": 15,
            "TGLPROSES": 10,
            "KELURAHAN": 25,
            "KECAMATAN": 25,
            "KODEPOS": 7,
            "STATUSACC": 1,
            "NAMAIBU": 17,
            "PEKERJAAN": 5,
            "USAHADIMANABKRJ": 5,
            "NAMAALIAS": 32,
            "STATUS": 4,
            "KETSTATUS": 50,
            "GOLDEB": 3,
            "PASPORT": 50,
            "KODEAREA": 4,
            "TELEPON": 8,
            "JNSKELAMIN": 1,
            "SANDIPKRJ": 4,
            "TEMPATBEKERJA": 30,
            "BIDANGUSAHA": 4,
            "AKTEAWAL": 30,
            "TGLAKTEAWAL": 10,
            "AKTEAKHIR": 30,
            "TGLAKTEAKHIR": 10,
            "TEMPATBERDIRI": 25,
            "DATIDEBITUR": 4,
            "HP": 15,
            "DATILAHIR": 6,
            "TMPTLHRDATI": 25,
            "NAMALENGKAP": 50,
            "ALAMAT": 60,
            "TLPRUMAH": 20,
            "KODE_JENIS_PENGGUNAAN_LBU": 1,
            "KODE_JENIS_PENGGUNAAN_SID": 2,
            "KODE_GOLONGAN_KREDIT_UMKM_LBU_SID": 2,
            "KODE_KATEGORI_PORTFOLIO_LBU": 2,
            "CREDIT_SCORING": 3,
        },
        DISBURSEMENT_SLIK: {
            "LOAN_ID": 17,
            "ALAMAT_TEMPAT_BEKERJA": 150,
            "YEARLY_INCOME": 12,
            "JUMLAH_TANGGUNGAN": 2,
            "STATUS_PERKAWINAN_DEBITUR": 1,
            "NOMOR_KTP_PASANGAN": 16,
            "NAMA_PASANGAN": 150,
            "TANGGAL_LAHIR_PASANGAN": 10,
            "PERJANJIAN_PISAH_HARTA": 1,
            "FASILITAS_KREDIT_PEMBAYARAN": 3,
            "TAKE_OVER_DARI": 6,
            "KODE_JENIS_PENGGUNAAN": 1,
            "KODE_BIDANG_USAHA_SLIK": 6,
            "ALAMAT_EMAIL_DEBITUR_PERORANGAN": 150,
            "ALAMAT_SESUAI_DOMISILI": 150,
            "KATEGORI_DEBITUR_UMKM": 2,
            "DESKRIPSI_JENIS_PENGGUNAAN_KREDIT": 50,
            "PEMBIAYAAN_PRODUKTIF": 1,
            "MONTHLY INCOME": 12,
        },
        DISBURSEMENT_FIN: {
            "NOPIN": 17,
            "TGLPK": 10,
            "TGLVALID": 10,
            "TGLANGS1": 10,
            "JMLHANGS": 3,
            "COST": 12,
            "COSTBANK": 12,
            "ADDM": 1,
            "ANGDEB ": 12,
            "ANGSBANK": 12,
            "BUNGA": 8,
            "BUNGABANK": 8,
            "KONDISIAGUN": 1,
            "NILAIAGUN": 12,
            "PTASURAN": 25,
            "ALAMATASUR1": 25,
            "ALAMATASUR2": 25,
            "KOTASUR": 15,
            "TGLPROSES": 10,
            "PREMIASUR": 12,
            "PEMBYRPREMI": 1,
            "ASURCASH": 12,
            "INCOME": 10,
            "NAMAIBU": 10,
            "SELISIHBUNGA": 10,
            "KODEPAKET": 3,
            "BIAYALAIN": 12,
            "CARABIAYA": 1,
            "PERIODEBYR": 2,
            "POKOKAWALPK": 12,
            "TENORAWAL": 3,
            "NOPK": 25,
            "NETDPCASH": 16,
            "ASURJIWATTL": 19,
            "ASURJIWACASH": 16,
        },
        DISBURSEMENT_SIPD: {
            "NOPIN": 17,
            "NAMA_REKANAN": 20,
            "ALAMATBPR1": 25,
            "ALAMATBPR2": 25,
            "KOTA": 15,
            "BUKTIKEPEMILIKAN": 4,
            "NO_JAMINAN": 15,
            "TGL": 10,
            "NAMAPEMILIK": 30,
            "JUMLAH": 1,
            "NORANGKA": 22,
            "NOMESIN": 15,
        },
        DISBURSEMENT_AGUN: {
            "NOPIN": 17,
            "MERK": 3,
            "JENIS": 3,
            "MODEL": 15,
            "NOPOL": 10,
            "NORANG": 22,
            "NOMES": 15,
            "WARNA": 10,
            "TAHUNMOBIL": 4,
            "TAHUNRAKIT": 4,
            "CILINDER": 10,
            "KELOMPOK": 1,
            "PENGGUNAAN": 1,
            "NILAISCORE": 11,
            "TEMPATSIMPAN": 4,
        },
        RECOVERY_CHANNELING: {
            "LOAN_ID": 17,
            "NAMA": 50,
            "TANGGAL_RECOVERY": 10,
            "NILAI_RECOVERY": 12,
            "KODE_RECOVERY": 1,
        },
        RECONCILIATION_CHANNELING: {
            "NOPIN": 17,
            "ANGSURAN_KE": 3,
            "OS_POKOK": 12,
            "NAMA": 50,
            "DPD": 3,
        },
        PAYMENT_CHANNELING: {
            "LOAN_ID": 17,
            "NAMA": 50,
            "TANGGAL_BAYAR_END": 10,
            "NILAI_ANGSURAN": 12,
            "DENDA": 12,
            "DISKON_DENDA": 12,
            "TANGGAL_TERIMA_MF": 10,
        },
    }

    FUNCTION_MAPPING = {}

    DATE_FORMAT_FIELD = {
        "TGL_LAHIR",
        "TGL_NOVASI",
        "TGLPROSES",
        "TGLAKTEAWAL",
        "TGLAKTEAKHIR",
        "TGLPK",
        "TGLVALID",
        "TGLANGS1",
        "TGL",
        "TANGGAL_BAYAR_END",
        "TANGGAL_TERIMA_MF",
    }


class PermataEarlyPayoffConst:
    TGL_BAYAR_ENDUSER = "TGL_BAYAR_ENDUSER"
    TANGGAL_TERIMA_REKANAN = "TANGGAL_TERIMA_REKANAN"

    # key is field name; first value of tuple is csv header column, second value is length of output
    CSV_MAPPING_FIELD = {
        "LOAN_ID": ("loan_id", 17),
        "NAMA_ENDUSER": ("nama_end_user", 25),
        TGL_BAYAR_ENDUSER: ("tgl_bayar_end_user", 10),
        "NILAI_POKOK": ("nilai_pokok", 12),
        "BUNGA": ("bunga", 12),
        "NOMINAL_DENDA_DIBAYAR": ("nominal_denda_dibayar", 12),
        "PENALTY": ("penalty", 12),
        "DISKON_DENDA": ("diskon_denda", 12),
        TANGGAL_TERIMA_REKANAN: ("tgl_terima_rekanan", 10),
        "DISKON_BUNGA": ("diskon_bunga", 12),
    }

    # key is field name; first value of tuple is input format, second value is output format
    DATETIME_IN_OUT_FORMAT_MAPPING = {
        TGL_BAYAR_ENDUSER: ("%b %d, %Y", "%d/%m/%Y"),
        TANGGAL_TERIMA_REKANAN: ("%b %d, %Y, %I:%M %p", "%d/%m/%Y"),
    }
