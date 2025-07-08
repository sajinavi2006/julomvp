from builtins import object
from juloserver.julo.statuses import ApplicationStatusCodes
from django.conf import settings
from juloserver.portal.object.bulk_upload.constants import MerchantFinancingCSVUploadPartner

csv_upload_partners = []
for attribute_name in dir(MerchantFinancingCSVUploadPartner):
    if not attribute_name.startswith("__"):  # Ignore internal attributes
        attribute_value = getattr(MerchantFinancingCSVUploadPartner, attribute_name)
        csv_upload_partners.append(attribute_value)

LIST_PARTNER = csv_upload_partners
LIST_PARTNER_EXCLUDE_PEDE = LIST_PARTNER

PARTNER_LAKU6 = 'laku6'
PARTNER_PEDE = 'pede'
CALLBACK_LAKU6 = settings.LAKU6_CALLBACK
TOKEN_LAKU6 = settings.LAKU6_TOKEN

CALLBACK_URL_PEDE = settings.PEDE_CALLBACK_URL

EXPIRED_STATUS = [
    ApplicationStatusCodes.OFFER_EXPIRED,
    ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED
]


class CreditMatrixPartner(object):
    B_MINUS_THRESHOLD = 0.80
    B_PLUS_THRESHOLD = 0.85
    A_MINUS_THRESHOLD = 0.90

    INTEREST_BY_SCORE = {
        'A-': 0.06,
        'B+': 0.07,
        'B-': 0.08,
        'C': 0.08
    }

    PEDE_INTEREST_BY_SCORE = {
        'A-': 0.06,
        'B+': 0.07,
        'B-': 0.08,
        'C': 0.08
    }

    CREDIT_LIMIT_BY_SCORE = {
        'A-': 8000000,
        'B+': 6000000,
        'B-': 4000000,
        'C': 0
    }

    MAX_LOAN_AMOUNT_BY_SCORE = {
        'A-': 8000000,
        'B+': 6000000,
        'B-': 4000000,
        'C': 0
    }

    MAX_LOAN_DURATION_BY_SCORE = {
        'A-': 6,
        'B+': 5,
        'B-': 4,
        'C': 0
    }


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
        'blacklist_customer_check'
    ]


class JuloPEDEMicro(object):
    MIN_AMOUNT = 500000
    MAX_AMOUNT = 1000000


class ProductMatrixPartner(object):
    DOWNPAYMENT = {
        'SILVER': 500000,
        'GOLD': 500000,
        'PLATINUM': 1000000,
        'DIAMOND': 2000000
    }

    POST_PAID = {
        'SILVER': 570000,
        'GOLD': 730000,
        'PLATINUM': 1300000,
        'DIAMOND': 2440000
    }

    ERAFONE_FEE = 77000

    INSURANCE_PURCHASED = 0.60

    @classmethod
    def insurance(cls, loan_amount):
        # if loan_amount <= 4500000:
        #     insurances = 250000
        # elif loan_amount <= 9000000:
        #     insurances = 450000
        # elif loan_amount <= 1300000:
        #     insurances = 650000
        # elif loan_amount <= 1800000:
        #     insurances = 899000
        # else:
        #     insurances = 1150000

        # return insurances * cls.INSURANCE_PURCHASED
        # change insurances default cause this task: https://juloprojects.atlassian.net/browse/ON-727
        default_insurances = 175000 * cls.INSURANCE_PURCHASED

        return default_insurances

    @classmethod
    def loan_principal(cls, loan_amount, package):
        loan_amount = int(loan_amount)
        insurance_by_loan = cls.insurance(loan_amount)
        return loan_amount + cls.POST_PAID[package] + cls.ERAFONE_FEE + insurance_by_loan - cls.DOWNPAYMENT[package]


partner_messages = {
    'application_date_of_birth': ('Anda belum dapat mengajukan pinjaman untuk saat ini karena belum memenuhi kriteria umur yang di tentukan.'),

    'form_partial_location': 'Produk pinjaman lain belum tersedia di daerah Anda.',

    'form_partial_income': ('Anda belum dapat mengajukan pinjaman untuk saat ini karena belum memenuhi kriteria '
                             'pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.'),
    
    'saving_margin': ('Anda belum dapat mengajukan pinjaman untuk saat ini karena belum memenuhi kriteria '
                             'pinjaman yang ada. Silakan coba kembali 6 bulan mendatang.'),

    'fraud_form_partial_device': ('Anda belum dapat mengajukan pinjaman karena menggunakan HP yang sudah terdaftar. '
                                  'Silahkan login kembali menggunakan HP pribadi Anda.'),
    
    'fraud_check': ('Anda belum dapat mengajukan pinjaman karena menggunakan HP yang sudah terdaftar. '
                                  'Silahkan login kembali menggunakan HP pribadi Anda.'),

    'fraud_form_partial_hp_own': ('Anda belum dapat mengajukan pinjaman karena menggunakan nomor HP yang sudah terdaftar. '
                                  'Silahkan coba kembali menggunakan nomor HP pribadi Anda atau login menggunakan akun '
                                  'yang sudah terdaftar.'),

    'not_meet_criteria': 'Anda belum dapat mengajukan pinjaman tanpa agunan karena belum memenuhi kriteria pinjaman yang ada.',

    'A_minus_score': 'Poin kredit Anda sangat bagus! Silakan selesaikan pengajuannya. Tinggal sedikit lagi!',

    'B_plus_score': 'Poin kredit Anda bagus! Silakan selesaikan pengajuannya. Tinggal sedikit lagi!',

    'B_minus_score': 'Poin kredit Anda cukup! Silakan selesaikan pengajuannya. Tinggal sedikit lagi!',

    'grab_default': 'Pilih produk pinjaman Grab & selesaikan pengajuan. Pasti CAIR!',

    'scraped_data_existence': ('Terdapat kendala dalam proses registrasi Anda. Mohon verifikasi ulang data Anda dengan'
                               ' menekan tombol di bawah ini.'),
}
