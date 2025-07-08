from builtins import object


class LenderStatus(object):
    UNPROCESSED = "unprocessed"
    IN_PROGRESS = "in_progress"
    TERMINATED = "terminated"
    ACTIVE = "active"
    INACTIVE = "inactive"
    LIST = [UNPROCESSED, IN_PROGRESS, TERMINATED, ACTIVE, INACTIVE, ]
    CHOICE = (
        ('', '---------'),
        (UNPROCESSED, UNPROCESSED),
        (IN_PROGRESS, IN_PROGRESS),
        (TERMINATED, TERMINATED),
        (ACTIVE, ACTIVE),
        (INACTIVE, INACTIVE),
    )
    DONE_STATUS = [TERMINATED, ACTIVE, INACTIVE, ]
    PROCESS_STATUS = [UNPROCESSED, IN_PROGRESS, ]
    LIVE_STATUS = [ACTIVE, INACTIVE, ]


class BusinessType(object):
    BANK = "bank"
    KOPERASI = "koperasi"
    MULTI_FINANCE = "multi_finance"
    PERUSAHAAN_UMUM = "perusahaan_umum"
    I2I = "i2i"
    SEKURITAS = "sekuritas"
    CREDIT_FUND = "credit_fund"
    INDIVIDU = "individu"
    OTHER = "other"
    LIST = [
        BANK, KOPERASI, MULTI_FINANCE, PERUSAHAAN_UMUM,
        I2I, SEKURITAS, CREDIT_FUND, INDIVIDU, OTHER,
    ]
    CHOICE = (
        ('', '---------'),
        (BANK, BANK),
        (KOPERASI, KOPERASI),
        (MULTI_FINANCE, MULTI_FINANCE),
        (PERUSAHAAN_UMUM, PERUSAHAAN_UMUM),
        (I2I, I2I),
        (SEKURITAS, SEKURITAS),
        (CREDIT_FUND, CREDIT_FUND),
        (INDIVIDU, INDIVIDU),
        (OTHER, OTHER),
    )


class SourceOfFund(object):
    EKUITAS = "ekuitas"
    PINJAMAN = "pinjaman"
    DANA_INVESTASI = "dana_investasi"
    DANA_PRIBADI = "dana_pribadi"
    LAINNYA = "lainnya"
    LIST = [EKUITAS, PINJAMAN, DANA_INVESTASI, DANA_PRIBADI, LAINNYA, ]
    CHOICE = (
        ('', '---------'),
        (EKUITAS, EKUITAS),
        (PINJAMAN, PINJAMAN),
        (DANA_INVESTASI, DANA_INVESTASI),
        (DANA_PRIBADI, DANA_PRIBADI),
        (LAINNYA, LAINNYA),
    )


class DocumentType(object):
    NPWP = "npwp"
    AKTA = "akta"
    TDP = "tdp"
    SIUP = "siup"
    NIB = "nib"
    SK_MENTERI = "sk_menteri"
    SKDP = "skdp"
    TRAIN_TICKET = "train_ticket"
    LIST = [NPWP, AKTA, TDP, SIUP, NIB, SK_MENTERI, SKDP, TRAIN_TICKET, ]


class BankAccountType(object):
    RDL = "rdl"
    DEPOSIT_VA = "deposit_va"
    DISBURSEMENT_VA = "disbursement_va"
    REPAYMENT_VA = "repayment_va"
    WITHDRAWAL = "withdrawal"
    LIST = [RDL, DEPOSIT_VA, DISBURSEMENT_VA, REPAYMENT_VA, WITHDRAWAL, ]
    VA = [DEPOSIT_VA, DISBURSEMENT_VA, REPAYMENT_VA, ]
    CHOICE = (
        ('', '---------'),
        (RDL, RDL),
        (DEPOSIT_VA, DEPOSIT_VA),
        (DISBURSEMENT_VA, DISBURSEMENT_VA),
        (REPAYMENT_VA, REPAYMENT_VA),
        (WITHDRAWAL, WITHDRAWAL),
    )


class BankAccountStatus(object):
    ACTIVE = 'active'
    INACTIVE = 'inactive'


class LenderWithdrawalStatus(object):
    REQUESTED = 'requested'
    PENDING = 'pending'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CHOICES = (
        (PENDING, PENDING),
        (REQUESTED, REQUESTED),
        (FAILED, FAILED),
        (COMPLETED, COMPLETED),
    )


class LenderTransactionTypeConst(object):
    DEPOSIT = 'deposit'
    WITHDRAWAL = 'withdrawal'
    DISBURSEMENT = 'disbursement'
    REPAYMENT = 'repayment'
    PLATFORM_FEE = 'platform_fee'
    BALANCE_ADJUSTMENT = 'balance_adjustment'
    TAX_DEDUCTION = 'tax_deduction'
    RECONCILE = 'reconcile'
    CHANNELING = 'channeling'
    CHANNELING_BUYBACK = 'channeling_buyback'
    CHANNELING_PREFUND_REJECT = 'channeling_prefund_reject'


class SnapshotType(object):
    TRANSACTION = 'transaction'
    RECONCILE = 'eod_reconcile'
    WRITE_OFF = 'eod_write_off'
    RESET_BALANCE = 'reset_balance'


class LoanWriteOffPeriodConst(object):
    WO_90 = 90
    WO_180 = 180


class LoanAgreementType(object):
    GENERAL = "general"
    SUMMARY = "summary"
    SUMMARY_DANA = "summary_dana"
    SUMMARY_AXIATA = "summary_axiata"
    SUMMARY_DANA_CASH_LOAN = "summary_dana_cash_loan"
    SKRTP = 'skrtp'
    RIPLAY = 'riplay'
    DIGISIGN_SKRTP = 'digisign_skrtp'
    JULOVERS_SPHP = 'julovers_sphp'
    SPF_SKRTP = 'spf_skrtp'
    SPF_RIPLAY = 'spf_riplay'
    MASTER_AGREEMENT = 'master_agreement'
    QRIS_SKRTP = 'qris_skrtp'

    LIST = (
        GENERAL,
        SUMMARY,
        SUMMARY_DANA,
        SUMMARY_AXIATA,
        SKRTP,
        SUMMARY_DANA_CASH_LOAN,
        SPF_SKRTP,
        SPF_RIPLAY,
        MASTER_AGREEMENT,
        QRIS_SKRTP,
    )
    LIST_TYPES_UPDATE = [
        (SUMMARY, 'Summary'),
        (GENERAL, 'General'),
        (SKRTP, 'SKRTP'),
        (SUMMARY_DANA, 'Summary Dana'),
        (SUMMARY_AXIATA, 'Summary Axiata'),
        (JULOVERS_SPHP, 'Julovers sphp'),
        (SUMMARY_DANA_CASH_LOAN, 'Summary Dana Cash Loan'),
        (RIPLAY, 'RIPLAY'),
        (SPF_SKRTP, 'Smartphone Financing SKRTP'),
        (SPF_RIPLAY, 'Smartphone Financing RIPLAY'),
        (MASTER_AGREEMENT, 'Master Agreement'),
        (QRIS_SKRTP, 'QRIS SKRTP'),
    ]
    LIST_SHOWING_ON_UI = [SKRTP, RIPLAY, DIGISIGN_SKRTP]

    TYPE_SPHP = "sphp"
    TYPE_RIPLAY = "riplay"
    TYPE_SKRTP = "skrtp"
    TYPE_DIGISIGN_SKRTP = "digisign_skrtp"
    TEXT_RIPLAY = "Ringkasan Informasi Produk dan Layannan"
    TEXT_SKRTP = "Surat Konfirmasi Rincian Transaksi Pendanaan"
    TEXT_SPHP = "Surat Perjanjian Hutang Piutang"
    QRIS_DOCUMENT_TYPES = [MASTER_AGREEMENT]


class LoanAgreementExtensionType:
    HTML = 'html'
    PDF = 'pdf'


class BankHolidayDays(object):
    HOLIDAY_PERIOD = (
        'Saturday',
        'Sunday')


class LenderRepaymentTransactionStatus(object):
    PENDING = 'PENDING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    UNPROCESSED = 'UNPROCESSED'


class LateFeeDefault(object):
    MTL_LATEFEE = 55000
    STL_LATEFEE = 50000


class LenderRepaymentTransferType(object):
    MANUAL = 'manual'
    AUTO = 'auto'


class LenderReversalTransactionConst(object):
    PENDING = 'pending'
    COMPLETED = 'completed'
    FAILED = 'failed'
    REQUESTED = 'requested'
    FIRST_STEP = 1
    SECOND_STEP = 2
    DEDUCTION_TYPE = 'deduction'
    ADDITION_TYPE = 'addition'
    SAME_LENDER_TRX_STEP = None
    INTER_LENDER_TRX_STEP = 2
    LENDER_TO_JTF_STEP = 1


class LenderBalanceManualUpdate(object):
    MASTER_LENDER = "jtp"
    LENDER_LIST = ["gfin", "jh", "pascal", "bss_channeling", "ska"]
    LENDER_NOTIFICATION_LIST = ["jtp", "jh", "pascal"]
    BSS_LENDER_LIST = ["gfin", "ska"]
    ESCROW_LENDER_LIST = ["jh", "pascal"]
    ESCROW_MINIMUM_BALANCE = 500000000


class LenderNameByPartner(object):
    GRAB = {"gfin", "ska", "ska2", "visionet_2", "visionet_1"}


class LenderInterestTax(object):
    TAX_LIST = {
        'jtp': 15,
        'ska': 15,
        'jh': 10,
        'pascal': 10,
    }
    MESSAGE = "% dari total bunga yang dibayarkan pada pendana"


class ReassignLenderProductLine(object):
    PRODUCT_LINE_CODE_INCLUDE = {1, 2}


class DocumentTypes:
    SKRTP_JULO = 'skrtp_julo'


class PusdafilLenderProcessStatusConst:
    SUCCESS = 'success'
    FAILED = 'failed'
    PARTIAL_FAILED = 'partial_failed'


LOCK_ON_REDIS_WITH_EX_TIME = 'lock_on_redis_with_ex_time'
REDIS_LOCK_IN_TIME = 60 * 60  # 1h


class RedisLockWithExTimeType:
    APPROVED_LOAN_ON_LENDER_DASHBOARD = 'approved_loan_on_lendder_dashboard'

    @classmethod
    def list_key_name(cls):
        return [cls.APPROVED_LOAN_ON_LENDER_DASHBOARD]

    @classmethod
    def key_name_exists(cls, key_name):
        return key_name in cls.list_key_name()


class LenderName:
    JTP = 'jtp'
    BLUEFINC = 'blue_finc_lender'
    LEGEND_CAPITAL = 'legend_capital_lender'


class MasterAgreementTemplateName:
    QRIS_J1 = 'QRIS_J1'
