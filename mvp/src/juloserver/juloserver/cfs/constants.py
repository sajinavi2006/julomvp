from juloserver.account.constants import AccountConstant
from juloserver.apiv2.models import EtlJob
from juloserver.autodebet.constants import AutodebetStatuses
from juloserver.google_analytics.constants import GAEvent
from juloserver.payment_point.constants import TransactionMethodCode

MULTIPLIER_CUSTOMER_J_SCORE = 0.5


class CustomerCfsAction:
    CREATE = 1
    UPDATE = 2


class CfsActionId:
    REFERRAL = 1
    CONNECT_BANK = 2
    CONNECT_BPJS = 3
    UPLOAD_UTILITIES_BILL = 4
    UPLOAD_SALARY_SLIP = 5
    UPLOAD_BANK_STATEMENT = 6
    VERIFY_PHONE_NUMBER_1 = 7
    VERIFY_PHONE_NUMBER_2 = 8
    VERIFY_FAMILY_PHONE_NUMBER = 10
    VERIFY_OFFICE_PHONE_NUMBER = 11
    VERIFY_ADDRESS = 12
    SHARE_TO_SOCIAL_MEDIA = 13
    BCA_AUTODEBET = 14
    UPLOAD_CREDIT_CARD = 15


class CfsProgressStatus:
    START = 1
    PENDING = 2
    UNCLAIMED = 3
    CLAIMED = 4
    FAILED = 5

    @classmethod
    def creatable_statuses(cls):
        return (
            cls.CLAIMED,
            cls.FAILED,
        )

    @classmethod
    def updatable_statuses(cls):
        return (
            cls.START,
            cls.PENDING,
            cls.UNCLAIMED,
        )

    @classmethod
    def status_pair_valid(cls, action_id):
        return ACTION_MAP_STATUS_PAIR[action_id]


class CfsActionType:
    RECURRING = "recurring"
    UNLIMITED = "unlimited"
    ONETIME = "onetime"


class CfsEtlJobStatus:
    AVAILABLE_FOR_BANK = (
        EtlJob.AUTH_SUCCESS,
        EtlJob.SCRAPE_FAILED,
        EtlJob.LOAD_SUCCESS,
        EtlJob.LOAD_FAILED,
    )


class ImageUploadType:
    PAYSTUB = "paystub"
    BANK_STATEMENT = "bank_statement"
    UTILITIES_BILL = "utilities_bill"
    CREDIT_CARD = "credit_card"


class PhoneRelatedType:
    FAMILY_PHONE_NUMBER = 1
    OFFICE_PHONE_NUMBER = 2


class PhoneContactType:
    PARENT = 'Orang tua'
    SIBLINGS = 'Saudara kandung'
    COUPLE = 'Pasangan'
    FAMILY = 'Famili lainnya'


class EtlJobType:
    NORMAL = "normal"
    CFS = "cfs"


class ShareSocialMediaAppName:
    INSTAGRAM = 'instagram'
    FACEBOOK = 'facebook'
    TWITTER = 'twitter'
    WHATSAPP = 'whatsapp'
    TELEGRAM = 'telegram'
    TIKTOK = 'tiktok'
    LINKEDIN = 'linkedin'
    LINE = 'line'


class AddressVerification:
    DISTANCE_MAX = 1


class GoogleAnalyticsActionTracking:
    MULAI = 1
    APPROVE = 2
    REFUSE = 3
    KLAIM = 4


class TierId:
    STARTER = 1
    ADVANCED = 2
    PRO = 3
    CHAMPION = 4


class VerifyStatus:
    APPROVE = 1
    REFUSE = 2


class VerifyAction:
    APPROVE = 'Approve'
    REFUSE = 'Refuse'


MAP_VERIFY_STATUS_WITH_ACTION_SENT_MOENGAGE = {
    VerifyStatus.APPROVE: 'approved',
    VerifyStatus.REFUSE: 'refused',
}


MAP_VERIFY_ACTION_WITH_VERIFY_STATUS = {
    VerifyAction.APPROVE: VerifyStatus.APPROVE,
    VerifyAction.REFUSE: VerifyStatus.REFUSE
}


MAP_IMAGE_UPLOAD_TYPE_WITH_ACTION = {
    ImageUploadType.PAYSTUB: CfsActionId.UPLOAD_SALARY_SLIP,
    ImageUploadType.BANK_STATEMENT: CfsActionId.UPLOAD_BANK_STATEMENT,
    ImageUploadType.UTILITIES_BILL: CfsActionId.UPLOAD_UTILITIES_BILL,
    ImageUploadType.CREDIT_CARD: CfsActionId.UPLOAD_CREDIT_CARD,
}


MAP_PHONE_RELATED_TYPE_WITH_ACTION = {
    PhoneRelatedType.FAMILY_PHONE_NUMBER: CfsActionId.VERIFY_FAMILY_PHONE_NUMBER,
    PhoneRelatedType.OFFICE_PHONE_NUMBER: CfsActionId.VERIFY_OFFICE_PHONE_NUMBER,
}


MAP_CFS_ACTION_WITH_GOOGLE_ANALYTICS_EVENT = {
    CfsActionId.CONNECT_BANK: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_CONNECT_BANK,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_CONNECT_BANK,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_CONNECT_BANK
    },
    CfsActionId.CONNECT_BPJS: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_CONNECT_BPJS,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_CONNECT_BPJS,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_CONNECT_BPJS
    },
    CfsActionId.UPLOAD_UTILITIES_BILL: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_BUKTI_TAGIHAN,
        GoogleAnalyticsActionTracking.APPROVE: GAEvent.CFS_APPROVE_BUKTI_TAGIHAN,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_BUKTI_TAGIHAN,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_BUKTI_TAGIHAN
    },
    CfsActionId.UPLOAD_SALARY_SLIP: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_BUKTI_GAJI,
        GoogleAnalyticsActionTracking.APPROVE: GAEvent.CFS_APPROVE_BUKTI_GAJI,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_BUKTI_GAJI,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_BUKTI_GAJI
    },
    CfsActionId.UPLOAD_BANK_STATEMENT: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_BUKTI_MUTASI,
        GoogleAnalyticsActionTracking.APPROVE: GAEvent.CFS_APPROVE_BUKTI_MUTASI,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_BUKTI_MUTASI,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_BUKTI_MUTASI
    },
    CfsActionId.UPLOAD_CREDIT_CARD: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_BUKTI_MUTASI,
        GoogleAnalyticsActionTracking.APPROVE: GAEvent.CFS_APPROVE_BUKTI_MUTASI,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_BUKTI_MUTASI,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_BUKTI_MUTASI
    },
    CfsActionId.VERIFY_PHONE_NUMBER_1: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_PHONE_VERIFICATION,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_PHONE_VERIFICATION,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_PHONE_VERIFICATION
    },
    CfsActionId.VERIFY_PHONE_NUMBER_2: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_OTHER_PHONE,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_OTHER_PHONE,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_OTHER_PHONE_VERIFICATION
    },
    CfsActionId.VERIFY_FAMILY_PHONE_NUMBER: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_FAMILY_NUMBER,
        GoogleAnalyticsActionTracking.APPROVE: GAEvent.CFS_APPROVE_FAMILY_NUMBER,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_FAMILY_NUMBER,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_FAMILY_NUMBER
    },
    CfsActionId.VERIFY_OFFICE_PHONE_NUMBER: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_COMPANY_NUMBER,
        GoogleAnalyticsActionTracking.APPROVE: GAEvent.CFS_APPROVE_COMPANY_NUMBER,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_COMPANY_NUMBER,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_COMPANY_NUMBER
    },
    CfsActionId.VERIFY_ADDRESS: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_ADDRESS_VERIFICATION,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_ADDRESS_VERIFICATION,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_ADDRESS_VERIFICATION
    },
    CfsActionId.SHARE_TO_SOCIAL_MEDIA: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_SHARE_SOCIAL_MEDIA,
        GoogleAnalyticsActionTracking.REFUSE: GAEvent.CFS_REFUSE_SHARE_SOCIAL_MEDIA,
        GoogleAnalyticsActionTracking.KLAIM: GAEvent.CFS_KLAIM_SHARE_SOCIAL_MEDIA
    },
    CfsActionId.BCA_AUTODEBET: {
        GoogleAnalyticsActionTracking.MULAI: GAEvent.CFS_MULAI_BCA_AUTODEBET,
    }
}


class CfsActionPointsActivity:
    # these numbers corresponding to the primary key
    TRANSACT = 1
    EARLY_REPAYMENT = 2
    ON_TIME_REPAYMENT = 3
    GRACE_REPAYMENT = 4
    B1_REPAYMENT = 5
    B2_REPAYMENT = 6
    B3_REPAYMENT = 7
    B4_REPAYMENT = 8
    WO = 9
    FRAUDSTER = 10


class ActionPointsReason:
    ACTION_POINTS = "action_points"
    ACTION_EXPIRED = "action_expired"

    @classmethod
    def get_action_points_reasons(cls):
        return (
            cls.ACTION_POINTS,
            cls.ACTION_EXPIRED
        )


class ActionPointsBucket:
    B1_DPD = {'from': 5, 'to': 30}
    B2_DPD = {'from': 31, 'to': 60}
    B3_DPD = {'from': 61, 'to': 90}
    B4_DPD = {'from': 91, 'to': 180}


class CfsStatus:
    ACTIVE = 1
    INACTIVE = 2
    BLOCKED = 3


MAP_ACCOUNT_STATUS_WITH_CFS_STATUS = {
    AccountConstant.STATUS_CODE.active: CfsStatus.ACTIVE,
    AccountConstant.STATUS_CODE.active_in_grace: CfsStatus.ACTIVE,
    AccountConstant.STATUS_CODE.inactive: CfsStatus.INACTIVE,
    AccountConstant.STATUS_CODE.deactivated: CfsStatus.INACTIVE,
    AccountConstant.STATUS_CODE.terminated: CfsStatus.INACTIVE,
    AccountConstant.STATUS_CODE.overlimit: CfsStatus.BLOCKED,
    AccountConstant.STATUS_CODE.suspended: CfsStatus.BLOCKED,
    AccountConstant.STATUS_CODE.fraud_reported: CfsStatus.BLOCKED,
    AccountConstant.STATUS_CODE.application_or_friendly_fraud: CfsStatus.BLOCKED,
    AccountConstant.STATUS_CODE.scam_victim: CfsStatus.BLOCKED,
}

MAP_CFS_ACTION_WITH_TRANSACTION_NOTE = {
    CfsActionId.REFERRAL: 'Cashback Undang Teman',
    CfsActionId.CONNECT_BANK: 'Cashback Tambah Akun Bank',
    CfsActionId.CONNECT_BPJS: 'Cashback Tambah Akun BPJS',
    CfsActionId.UPLOAD_UTILITIES_BILL: 'Cashback Tambah Bukti Tagihan Kebutuhan',
    CfsActionId.UPLOAD_SALARY_SLIP: 'Cashback Tambah Slip Gaji',
    CfsActionId.UPLOAD_BANK_STATEMENT: 'Cashback Tambah Bukti Mutasi Rekening',
    CfsActionId.VERIFY_ADDRESS: 'Cashback Tambah Alamat',
    CfsActionId.VERIFY_PHONE_NUMBER_1: 'Cashback Verifikasi Ulang Nomor HP',
    CfsActionId.VERIFY_PHONE_NUMBER_2: 'Cashback Tambah Nomor HP Lainnya',
    CfsActionId.VERIFY_OFFICE_PHONE_NUMBER: 'Cashback Tambah Telepon Kantor',
    CfsActionId.VERIFY_FAMILY_PHONE_NUMBER: 'Cashback Tambah Nomor HP kerabat',
    CfsActionId.SHARE_TO_SOCIAL_MEDIA: 'Cashback Bagi ke Sosial Media',
    CfsActionId.UPLOAD_CREDIT_CARD: 'Cashback Upload Kartu Kredit',
}


MAP_AUTODEBET_STATUS_WITH_CFS_STATUS = {
    AutodebetStatuses.PENDING_REGISTRATION: CfsProgressStatus.PENDING,
    AutodebetStatuses.FAILED_REGISTRATION: CfsProgressStatus.START,
    AutodebetStatuses.REGISTERED: CfsProgressStatus.CLAIMED,
}


STATUS_PAIR_VERIFY_BY_AGENT = [
    (CfsProgressStatus.PENDING, CfsProgressStatus.UNCLAIMED),
    (CfsProgressStatus.UNCLAIMED, CfsProgressStatus.CLAIMED),
    (CfsProgressStatus.PENDING, CfsProgressStatus.START),
    (CfsProgressStatus.START, CfsProgressStatus.PENDING)
]

STATUS_PAIR_MISSION_VERIFIED = [
    (CfsProgressStatus.UNCLAIMED, CfsProgressStatus.CLAIMED)
]

STATUS_PAIR_VERIFY_ADDRESS = [
    (CfsProgressStatus.START, CfsProgressStatus.UNCLAIMED),
    (CfsProgressStatus.UNCLAIMED, CfsProgressStatus.CLAIMED),
    (CfsProgressStatus.START, CfsProgressStatus.FAILED),
]

STATUS_PAIR_BCA_AUTODEBET = [
    (CfsProgressStatus.PENDING, CfsProgressStatus.START),
    (CfsProgressStatus.START, CfsProgressStatus.PENDING),
    (CfsProgressStatus.PENDING, CfsProgressStatus.CLAIMED),
]

ACTION_MAP_STATUS_PAIR = {
    CfsActionId.CONNECT_BANK: STATUS_PAIR_VERIFY_BY_AGENT,
    CfsActionId.CONNECT_BPJS: STATUS_PAIR_VERIFY_BY_AGENT,
    CfsActionId.UPLOAD_UTILITIES_BILL: STATUS_PAIR_VERIFY_BY_AGENT,
    CfsActionId.UPLOAD_SALARY_SLIP: STATUS_PAIR_VERIFY_BY_AGENT,
    CfsActionId.UPLOAD_CREDIT_CARD: STATUS_PAIR_VERIFY_BY_AGENT,
    CfsActionId.UPLOAD_BANK_STATEMENT: STATUS_PAIR_VERIFY_BY_AGENT,
    CfsActionId.VERIFY_FAMILY_PHONE_NUMBER: STATUS_PAIR_VERIFY_BY_AGENT,
    CfsActionId.VERIFY_OFFICE_PHONE_NUMBER: STATUS_PAIR_VERIFY_BY_AGENT,

    CfsActionId.VERIFY_PHONE_NUMBER_1: STATUS_PAIR_MISSION_VERIFIED,
    CfsActionId.VERIFY_PHONE_NUMBER_2: STATUS_PAIR_MISSION_VERIFIED,
    CfsActionId.SHARE_TO_SOCIAL_MEDIA: STATUS_PAIR_MISSION_VERIFIED,

    CfsActionId.VERIFY_ADDRESS: STATUS_PAIR_VERIFY_ADDRESS,
    CfsActionId.BCA_AUTODEBET: STATUS_PAIR_BCA_AUTODEBET,
}


class EasyIncomeConstant:
    FEATURE_SETTING_KEY = 'easy_income_feature_setting_cache_key_for_redis'
    TOKEN_AFTER_HOURS_KEY_IN_FEATURE_SETTING = 'expire_after_hours'
    FEATURE_SETTING_WHITELIST_CREDIT_CARD = 'easy_income_whitelist_credit_card'


class FeatureNameConst(object):
    CFS_UPLOAD_IMAGE_SIZE = 'upload_image_size'


class CFSTierTransactionCodeMapping:
    MAP_TRANSACTION_METHOD_WITH_CFS_TIER = {
        TransactionMethodCode.SELF.code: 'tarik_dana',
        TransactionMethodCode.OTHER.code: 'transfer_dana',
        TransactionMethodCode.QRIS.code: 'qris',
        TransactionMethodCode.E_COMMERCE.code: 'ecommerce',
        TransactionMethodCode.DOMPET_DIGITAL.code: 'dompet_digital',
        TransactionMethodCode.CREDIT_CARD.code: 'julo_card',
        TransactionMethodCode.PASCA_BAYAR.code: 'pasca_bayar',
        TransactionMethodCode.LISTRIK_PLN.code: 'listrik_pln',
        TransactionMethodCode.BPJS_KESEHATAN.code: 'bpjs_kesehatan',
        TransactionMethodCode.TRAIN_TICKET.code: 'tiket_kereta',
        TransactionMethodCode.PDAM.code: 'pdam',
        TransactionMethodCode.EDUCATION.code: 'education',
        TransactionMethodCode.BALANCE_CONSOLIDATION.code: 'balance_consolidation',
    }
    DEFAULT_CFS_TRANSACTION_METHOD = 'ppob'


class AssignmentVerificationDataListViewConstants:
    TIMEOUT = 5000  # ms


class CfsMissionWebStatus:
    START = 'start'
    IN_PROGRESS = 'in_progress'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class MissionUploadType:
    UPLOAD_BANK_STATEMENT = 'upload_bank_statement'
    UPLOAD_SALARY_SLIP = 'upload_salary_slip'
    UPLOAD_CREDIT_CARD = 'upload_credit_card'
