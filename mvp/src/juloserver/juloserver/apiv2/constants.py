from builtins import object

from juloserver.loan_refinancing.constants import CovidRefinancingConst


class ErrorCode(object):
    CUSTOMER_REAPPLY = 'CR-01'


class ErrorMessage(object):
    CUSTOMER_REAPPLY = '{}{}{}'.format(
        'Mohon Maaf Status Anda saat ini tidak dapat',
        ' mengajukan pinjaman,',
        ' silahkan hubungi customer service JULO',
    )
    GENERAL = 'Mohon maaf, terjadi kendala dalam proses pengajuan. Silakan coba beberapa saat lagi.'
    PHONE_NUMBER_MISMATCH = 'Nomor HP tidak valid'


class CreditMatrix2(object):
    MTL_PROBABILITY_THRESHOLD = 0.84
    STL_PROBABILITY_THRESHOLD = 0.82


# this is latest constant for creditMatrix
# current version is 24
class CreditMatrixV19(object):
    B_MINUS_LOW_THRESHOLD = 0.69
    B_MINUS_HIGH_THRESHOLD = 0.79
    B_PLUS_THRESHOLD = 0.88
    A_MINUS_THRESHOLD = 0.93
    B_MINUS_HIGH_TAG = 'B- high'
    B_MINUS_LOW_TAG = 'B- low'

    INTEREST_BY_SCORE = {'A-': 0.04, 'B+': 0.05, 'B-': 0.06, 'C': 0.04}

    MAX_LOAN_AMOUNT_BY_SCORE = {'A-': 8000000, 'B+': 7000000, 'B-': 5000000, 'C': 8000000}

    B_MINUS_MAX_LOAN_AMOUNT_BY_TAG = {
        B_MINUS_HIGH_TAG: 5000000,
        B_MINUS_LOW_TAG: 4000000,
    }

    MAX_LOAN_DURATION_BY_SCORE = {'A-': 6, 'B+': 6, 'B-': 4, 'C': 6}

    BINARY_CHECK_SHORT = [
        'fraud_form_partial_device',
        'fraud_device',
        'fraud_form_partial_hp_own',
        'fraud_form_partial_hp_kin',
        'fraud_hp_spouse',
        'job_not_black_listed',
        'application_date_of_birth',
        'form_partial_income',
        'saving_margin',
        'form_partial_location',
        'scraped_data_existence',
        'email_delinquency_24_months',
        'sms_delinquency_24_months',
        'special_event',
        'fdc_inquiry_check',
        'loan_purpose_description_black_list',
        'known_fraud',
        'fraud_email',
        'fraud_ktp',
    ]

    BINARY_CHECK_LONG = [
        'basic_savings',
        'debt_to_income_40_percent',
        'experiment_iti_ner_sms_email',
        'sms_grace_period_3_months',
        'job_term_gt_3_month',
        'monthly_income_gt_3_million',
        'monthly_income',
        'own_phone',
        'fraud_form_full',
        'fraud_form_full_bank_account_number',
        'blacklist_customer_check',
        'grab_application_check',
    ]


class CreditMatrixWebApp(object):
    B_MINUS_THRESHOLD = 0.79
    B_PLUS_THRESHOLD = 0.88
    A_MINUS_THRESHOLD = 0.94

    INTEREST_BY_SCORE = {'A-': 0.04, 'B+': 0.05, 'B-': 0.06, 'C': 0.04}

    MAX_LOAN_AMOUNT_BY_SCORE = {'A-': 5000000, 'B+': 4000000, 'B-': 3000000, 'C': 0}

    MAX_LOAN_DURATION_BY_SCORE = {'A-': 6, 'B+': 5, 'B-': 4, 'C': 0}


class PromoDate(object):
    # for June hi Season
    JUNE22_PROMO_BANNER_START_DATE = '2022-06-18'
    JUNE22_PROMO_BANNER_END_DATE = '2022-07-02'

    JUNE22_PROMO_START_DUE_DATE = '2022-06-25'
    JUNE22_PROMO_END_DUE_DATE = '2022-07-04'

    JUNE22_PROMO_EMAIL_START_DATE = '2022-06-19'
    JUNE22_PROMO_EMAIL_END_DATE = '2022-06-28'

    JUNE22_PROMO_PN1_START_DATE = '2022-06-20'
    JUNE22_PROMO_PN1_END_DATE = '2022-06-29'

    JUNE22_PROMO_PN2_START_DATE = '2022-06-22'
    JUNE22_PROMO_PN2_END_DATE = '2022-07-01'


class PromoType(object):

    JUNE22_CASH_PROMO = 'promo-cash-june22.html'
    RUNNING_PROMO = JUNE22_CASH_PROMO


class CreditMatrixType(object):
    JULO_ONE = "julo1"
    JULO_ONE_IOS = "julo1_ios"
    JULO = "julo"
    JULO_REPEAT = "julo_repeat"
    WEBAPP = "webapp"
    JULO1_ENTRY_LEVEL = 'julo1_entry_level'
    JULO1_LIMIT_EXP = 'julo1_limit_exp'
    JULO_STARTER = 'j-starter'
    JULO1_LEADGEN = 'julo1_leadgen'

    CREDIT_MATRIX_CHOICES = [
        (JULO, JULO),
        (JULO_REPEAT, JULO_REPEAT),
        (WEBAPP, WEBAPP),
        (JULO_ONE, JULO_ONE),
        (JULO1_ENTRY_LEVEL, JULO1_ENTRY_LEVEL),
        (JULO1_LIMIT_EXP, JULO1_LIMIT_EXP),
        (JULO_STARTER, JULO_STARTER),
        (JULO_ONE_IOS, JULO_ONE_IOS),
        (JULO1_LEADGEN, JULO1_LEADGEN),
    ]


class FDCFieldsName(object):
    TIDAK_LANCAR = 'Tidak Lancar (30 sd 90 hari)'
    MACET = 'Macet (>90)'
    LANCAR = 'Lancar (<30 hari)'

    # New categorized by day
    LANCAR_CONF = {'days': 0, 'name': 'lancar'}
    DALAM_PERHATIAN_KHUSUS_CONF = {'days': [1, 30], 'name': 'dalam_perhatian_khusus'}
    KURANG_LANCAR_CONF = {'days': [31, 60], 'name': 'kurang_lancar'}
    DIRAGUKAN_CONF = {'days': [61, 90], 'name': 'diragukan'}
    MACET_CONF = {'days': 91, 'name': 'macet'}


# June 2022
JUNE22_HIGHSEASON_BASE_URL = 'https://julocampaign.julo.co.id/promo_jun_2022/'
JUNE22_PROMO_BANNER_DICT = {
    'android': {
        '2022-06-22': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2022%20Juni.png',
        '2022-06-23': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2023%20Juni.png',
        '2022-06-24': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2024%20Juni.png',
        '2022-06-25': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2025%20Juni.png',
        '2022-06-26': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2026%20Juni.png',
        '2022-06-27': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2027%20Juni.png',
        '2022-06-28': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2028%20Juni.png',
        '2022-06-29': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2029%20Juni.png',
        '2022-06-30': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2030%20Juni.png',
        '2022-07-01': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%201%20Juli.png',
    },
    'android_j1': {
        '2022-06-22': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2022%20Juni.png',
        '2022-06-23': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2023%20Juni.png',
        '2022-06-24': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2024%20Juni.png',
        '2022-06-25': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2025%20Juni.png',
        '2022-06-26': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2026%20Juni.png',
        '2022-06-27': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2027%20Juni.png',
        '2022-06-28': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2028%20Juni.png',
        '2022-06-29': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2029%20Juni.png',
        '2022-06-30': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%2030%20Juni.png',
        '2022-07-01': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20In-App%20-%201%20Juli.png',
    },
    'email': {
        '2022-06-22': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2022%20Juni.png',
        '2022-06-23': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2023%20Juni.png',
        '2022-06-24': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2024%20Juni.png',
        '2022-06-25': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2025%20Juni.png',
        '2022-06-26': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2026%20Juni.png',
        '2022-06-27': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2027%20Juni.png',
        '2022-06-28': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2028%20Juni.png',
        '2022-06-29': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2029%20Juni.png',
        '2022-06-30': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%2030%20Juni.png',
        '2022-07-01': JUNE22_HIGHSEASON_BASE_URL
        + 'KIlau%20juNI%20MELESAT%20-%20Highseason%20Juni%20-%20Email-PN%20-%201%20Juli.png',
    },
}

JUNE22_PROMO_ELIGIBLE_STATUSES = {
    CovidRefinancingConst.STATUSES.offer_generated,
    CovidRefinancingConst.STATUSES.offer_selected,
    CovidRefinancingConst.STATUSES.approved,
    CovidRefinancingConst.STATUSES.activated,
}


class PaymentMethodCategoryConst(object):
    PAYMENT_METHOD_VA = [
        "Bank BCA",
        "PERMATA Bank",
        "Bank MANDIRI",
        "Bank BRI",
        "Bank MAYBANK",
        "Bank CIMB Niaga",
        "Bank BNI",
    ]

    PAYMENT_METHOD_E_WALLET = [
        "OVO",
        "Gopay",
    ]

    PAYMENT_METHOD_ANOTHER_METHOD = [
        "INDOMARET",
        "ALFAMART",
    ]

    PAYMENT_METHOD_VA_PRIORITY = {
        "Bank BCA": 1,
        "Bank BRI": 2,
        "Bank MANDIRI": 3,
        "PERMATA Bank": 4,
        "Bank MAYBANK": 5,
    }


class DropdownResponseCode:
    PRODUCT_NOT_FOUND = 'product_not_found'
    UP_TO_DATE = 'up_to_date'
    NEW_DATA = 'new_data'
