LATEST_REFERRAL_MAPPING_ID = 'latest_referral_mapping_id'
MAPPING_COUNT_START_DATE = '2023-08-01'
MIN_REFEREE_GET_BONUS = 1
REFERRAL_DEFAULT_LEVEL = 'Basic'
REFERRAL_BENEFIT_EXPIRY_DAYS = 30


class ReferralCodeMessage:
    UNAVAILABLE_REFERRAL_CODE = "Mohon maaf, kode referral sedang dalam perbaikan"

    class ERROR:
        INVALID = "Kode sudah tidak berlaku"
        WRONG = "Kode yang kamu masukkan salah"  # doesn't exist
        LIMIT = "Kode mencapai batas maksimum. Cashback tidak berlaku."


class FeatureNameConst(object):
    SHAREABLE_REFERRAL_IMAGE = 'shareable_referral_image'
    REFERRAL_BENEFIT_LOGIC = 'referral_benefit_logic'
    REFERRAL_LEVEL_BENEFIT_CONFIG = 'referral_level_benefit_config'
    WHITELIST_NEW_REFERRAL_CUST = 'whitelist_new_referral_cust'
    ADDITIONAL_INFO = 'referral_additional_info'
    TOP_REFERRAL_CASHBACKS = 'top_referral_cashbacks'


class ReferralBenefitConst:
    CASHBACK = 'cashback'
    POINTS = 'points'

    CHOICES = (
        (CASHBACK, 'Cashback'),
        (POINTS, 'Points'),
    )


class ReferralLevelConst:
    CASHBACK = 'cashback'
    POINTS = 'points'
    PERCENTAGE = 'percentage'

    CHOICES = (
        (CASHBACK, 'Cashback'),
        (POINTS, 'Points'),
        (PERCENTAGE, 'Percentage')
    )

    AVAILABLE_LEVEL_BENEFIT_MAPPING = {
        CASHBACK: [CASHBACK, PERCENTAGE],
        POINTS: [POINTS, PERCENTAGE],
    }


class ReferralPersonTypeConst:
    REFERRER = 'referrer'
    REFEREE = 'referee'

    CHOICES = (
        (REFERRER, 'referrer'),
        (REFEREE, 'referee')
    )


class ReferralRedisConstant:
    REFEREE_CODE_USED_COUNT = 'referral.referee_code_used_count.{}'
    REFEREE_ALREADY_APPROVED_COUNT = 'referral.referee_already_approved_count.{}'
    COUNTING_REFEREES_DISBURSEMENT_KEY = 'referral.counting_referees_disbursement.{}'
    TOTAL_REFERRAL_BONUS_AMOUNT_KEY = 'referral.total_referral_bonus_amount.{}'
    REDIS_CACHE_TTL_DAY = 86400 * 7  # total seconds in week
    TOP_REFERRAL_CASHBACKS = "top_referral_cashbacks"
