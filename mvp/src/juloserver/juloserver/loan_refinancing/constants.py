from builtins import object
from enum import IntEnum
from argparse import Namespace
from datetime import datetime
from django.conf import settings


class LoanRefinancingConst(object):
    ELIGIBLE_DPD = (30, 60)
    LOAN_REFINANCING_FEATURE_SETTING = 'loan_refinancing_threshold'
    LOAN_REFINANCING_EMAIL_EXPIRATION_DAYS = 14
    LOAN_REFINANCING_TENURE_EXTENSION_CHOICES = {
        3: 5,
        4: 6,
        5: 8,
        6: 9
    }
    FIRST_LOAN_REFINANCING_INSTALLMENT = 0
    LOAN_REFINANCING_WAIVE_LATE_FEE_TYPE = 'refinancing_latefee_discount'
    LOAN_REFINANCING_FIRST_PAYMENT_DPD = 5
    LOAN_REFINANCING_FIRST_DUE_DATE_ADDITION = 5
    LOAN_REFINANCING_DUE_DATE_MIN_DELTA_DAYS = 20
    REFINANCING_CUSTOMER_WALLET_DEDUCTION = 'refinancing_deduction'
    LOAN_REFINANCING_ADMIN_FEE_TYPE = 'admin_fee'
    MAPPING_LOAN_REFINANCING_MAIN_REASON = {
        'jualan/order sepi': 'jualan / order sepi',
        'tetap bekerja, gaji minim': 'bekerja gaji minim',
        'masalah keluarga/perceraian': 'masalah keluarga / perceraian'
    }
    R3_ADMIN_FEE = 75000


class LoanRefinancingStatus(IntEnum):
    INACTIVE = 0
    REQUEST = 1
    ACTIVE = 2
    PAID_OFF = 3


class CovidRefinancingConst(object):
    COVID_PERIOD_BEGIN = datetime.strptime('2020-04-01', '%Y-%m-%d').date()

    CHANNELS = Namespace(**{'proactive': 'Proactive',
                            'reactive': 'Reactive'})

    CSV_HEADER_LIST = [
        'email_address',
        'loan_id',
        'covid_product',
        'tenure_extension',
        'new_income',
        'new_expense',
        'new_employment_status',
        'new_affordability'
    ]

    J1_CSV_HEADER_LIST = [
        'email_address',
        'account_id',
        'covid_product',
        'tenure_extension',
        'new_income',
        'new_expense',
        'new_employment_status',
        'new_affordability'
    ]

    STATUSES = Namespace(**{'requested': 'Requested',
                            'approved': 'Approved',
                            'rejected': 'Rejected',
                            'activated': 'Activated',
                            'expired': 'Expired',
                            'proposed': 'Proposed',
                            'inactive': 'Inactive',
                            'offer_selected': 'Offer Selected',
                            'offer_generated': 'Offer Generated'
                            })

    NEW_PROACTIVE_STATUSES = Namespace(**{'proposed_email': 'Email Sent',
                                          'proposed_submit': 'Form Viewed',
                                          'proposed_offer': 'Offer Generated'})

    STATUSES_TIPS_LABEL = {
        '-': 'TAWARKAN Keringanan Pinjaman dengan mengisi Pertanyaan Interview.',
        'Email Sent': 'TAWARKAN Keringanan Pinjaman dengan mengisi Pertanyaan Interview. '
                      'Customer mendapatkan penawaran via Email tapi belum membuka formulir.',
        'Form Viewed': 'TAWARKAN Keringanan Pinjaman dengan mengisi Pertanyaan Interview. '
                       'Customer sudah membuka formulir tapi belum mengisi.',
        'Offer Generated': 'TAWARKAN Keringanan Pinjaman sesuai rekomendasi / negosiasi. '
                           'Customer sudah mengisi formulir tapi belum memilih produk keringanan.',
        'Offer Selected': 'FOLLOW UP agar menyetujui keringanan yang dipilih '
                          'dan KONFIRMASI jadwal pembayaran. '
                          'Customer sudah memilih keringanan yang diinginkan.',
        'Approved': 'FOLLOW UP terkait jadwal pembayaran untuk mengaktifkan keringanan. '
                    'Customer sudah memilih keringanan yang diinginkan',
        'Activated': 'Customer sudah mendapatkan keringanan. '
                     'TAWARKAN Keringanan Pinjaman kembali dengan mengisi Pertanyaan Interview.',

    }
    SELECTED_OFFER_LABELS = {
        'R1': 'Cicilan Lebih Ringan (R1)',
        'R2': 'Bayar Bunga (R2)',
        'R3': 'Penundaan Hutang (R3)',
        'R4': 'Pelunasan Dengan Diskon (R4) ',
        'R5': 'Penghapusan Denda (R5)',
        'R6': 'Penghapusan Denda Dan Bunga (R6)',

    }

    PROACTIVE_CONFIRMATION_EMAIL_STATUSES = (
        STATUSES.offer_selected,
        STATUSES.approved,
    )

    ALL_CONFIRMATION_EMAIL_STATUSES = (
        STATUSES.offer_selected,
        NEW_PROACTIVE_STATUSES.proposed_email,
    )

    @classmethod
    def web_view_statuses(cls):
        return [
            cls.NEW_PROACTIVE_STATUSES.proposed_email,
            cls.NEW_PROACTIVE_STATUSES.proposed_submit,
            cls.NEW_PROACTIVE_STATUSES.proposed_offer,
            cls.STATUSES.offer_selected,
            cls.STATUSES.approved,
        ]

    PROACTIVE_STATUS_EXPIRATION_IN_DAYS = {
        NEW_PROACTIVE_STATUSES.proposed_submit: 30,
        NEW_PROACTIVE_STATUSES.proposed_email: 30,
        NEW_PROACTIVE_STATUSES.proposed_offer: 10,
    }

    URL = settings.CALLBACK_BASE_URL + '/api/loan_refinancing/v1/'

    PRODUCTS = Namespace(
        **{
            'r1': 'R1',
            'r2': 'R2',
            'r3': 'R3',
            'r4': 'R4',
            'r5': 'R5',
            'r6': 'R6',
            'p1': 'P1',
            'p2': 'P2',
            'p3': 'P3',
            'p4': 'P4',
            'gpw': 'General Paid Waiver',
        }
    )

    @classmethod
    def proactive_products(cls):
        return [
            cls.PRODUCTS.p1,
            cls.PRODUCTS.p2,
            cls.PRODUCTS.p3,
        ]

    NEW_REASON = ('Dirumahkan gaji minim',
                  'Bekerja gaji minim',
                  'Dirumahkan tanpa gaji',
                  'Jualan / Order Sepi',
                  'PHK')

    BUCKET_BASED_EXTENSION_LIMIT = {0: 1,
                                    1: 1,
                                    2: 1,
                                    3: 2,
                                    4: 2,
                                    5: 2,
                                    6: 2}

    BUCKET_BASED_R4_PARAMS = {
        0: {'late_fee_waiver': 0,
            'interest_waiver': 0.5,
            'principal_waiver': 0,
            'validity_in_days': 20
            },
        1: {'late_fee_waiver': 1,
            'interest_waiver': 0.7,
            'principal_waiver': 0,
            'validity_in_days': 20
            },
        2: {'late_fee_waiver': 1,
            'interest_waiver': 0.8,
            'principal_waiver': 0,
            'validity_in_days': 20
            },
        3: {'late_fee_waiver': 1,
            'interest_waiver': 0.9,
            'principal_waiver': 0,
            'validity_in_days': 20
            },
        4: {'late_fee_waiver': 1,
            'interest_waiver': 1,
            'principal_waiver': 0.1,
            'validity_in_days': 20
            },
        5: {'late_fee_waiver': 1,
            'interest_waiver': 1,
            'principal_waiver': 0.2,
            'validity_in_days': 20
            }
    }
    PROACTIVE_URL = settings.CALLBACK_BASE_URL + '/api/loan_refinancing/v1/covid_approval/'

    @classmethod
    def reactive_products(cls):
        return [
            cls.PRODUCTS.r1,
            cls.PRODUCTS.r2,
            cls.PRODUCTS.r3,
        ]

    REACTIVE_OFFER_STATUS_AVAILABLE_FOR_GENERATE_OFFER = (
        STATUSES.proposed,
        STATUSES.requested,
        NEW_PROACTIVE_STATUSES.proposed_email,
        NEW_PROACTIVE_STATUSES.proposed_submit,
    )

    REACTIVE_OFFER_STATUS_ACTIVATED = (
        STATUSES.activated,
    )

    REACTIVE_OFFER_STATUS_SELECTED_OR_APPROVED = (
        STATUSES.approved,
        STATUSES.offer_selected,
    )

    NEED_VALIDATE_FOR_MULTIPLE_REQUEST_STATUSES = (
        STATUSES.approved,
        STATUSES.offer_selected,
        STATUSES.activated,
        STATUSES.expired,
        STATUSES.inactive,
        STATUSES.rejected,
    )

    @classmethod
    def waiver_products(cls):
        return [
            cls.PRODUCTS.r4,
            cls.PRODUCTS.r5,
            cls.PRODUCTS.r6,
        ]

    GENERATE_WAIVER_STATUSES = {
        STATUSES.offer_selected,
        STATUSES.approved,
        STATUSES.activated,
        STATUSES.expired,
        STATUSES.inactive,
    }

    JUNE_PROMO_ELIGIBLE_STATUSES = {
        STATUSES.offer_generated,
        STATUSES.offer_selected,
        STATUSES.approved,
        STATUSES.activated
    }

    MULTI_OFFER_CHANGE_TO_EXPIRED_STATUSES = {
        STATUSES.offer_selected,
        STATUSES.approved
    }

    BUCKET_BASED_DEFAULT_PARAMS_R4 = {
        0: {'late_fee_waiver': 0,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        1: {'late_fee_waiver': 100,
            'interest_waiver': 100,
            'principal_waiver': 30,
            'validity_in_days': 10
            },
        2: {'late_fee_waiver': 100,
            'interest_waiver': 100,
            'principal_waiver': 20,
            'validity_in_days': 10
            },
        3: {'late_fee_waiver': 100,
            'interest_waiver': 90,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        4: {'late_fee_waiver': 100,
            'interest_waiver': 100,
            'principal_waiver': 10,
            'validity_in_days': 10
            },
        5: {'late_fee_waiver': 100,
            'interest_waiver': 100,
            'principal_waiver': 20,
            'validity_in_days': 10
            }
    }

    BUCKET_BASED_DEFAULT_PARAMS_R5 = {
        0: {'late_fee_waiver': 0,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        1: {'late_fee_waiver': 0,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        2: {'late_fee_waiver': 20,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        3: {'late_fee_waiver': 50,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        4: {'late_fee_waiver': 100,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        5: {'late_fee_waiver': 100,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            }
    }

    BUCKET_BASED_DEFAULT_PARAMS_R6 = {
        0: {'late_fee_waiver': 0,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        1: {'late_fee_waiver': 0,
            'interest_waiver': 0,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        2: {'late_fee_waiver': 100,
            'interest_waiver': 10,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        3: {'late_fee_waiver': 100,
            'interest_waiver': 40,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        4: {'late_fee_waiver': 100,
            'interest_waiver': 50,
            'principal_waiver': 0,
            'validity_in_days': 10
            },
        5: {'late_fee_waiver': 100,
            'interest_waiver': 100,
            'principal_waiver': 0,
            'validity_in_days': 10
            }
    }

    BUCKET_BASED_DEFAULT_PARAMS = {
        PRODUCTS.r4: BUCKET_BASED_DEFAULT_PARAMS_R4,
        PRODUCTS.r5: BUCKET_BASED_DEFAULT_PARAMS_R5,
        PRODUCTS.r6: BUCKET_BASED_DEFAULT_PARAMS_R6,
    }

    RECO_TABLE = {
        'R4_0_late_fee_waiver_no_normal': 0,
        'R4_0_interest_fee_waiver_no_normal': 0,
        'R4_0_principal_waiver_no_normal': 0,
        'R4_0_late_fee_waiver_yes_normal': 0,
        'R4_0_interest_fee_waiver_yes_normal': 0,
        'R4_0_principal_waiver_yes_normal': 0,
        'R4_1_late_fee_waiver_no_normal': 100,
        'R4_1_interest_fee_waiver_no_normal': 100,
        'R4_1_principal_waiver_no_normal': 0,
        'R4_1_late_fee_waiver_yes_normal': 100,
        'R4_1_interest_fee_waiver_yes_normal': 100,
        'R4_1_principal_waiver_yes_normal': 0,
        'R4_2_late_fee_waiver_no_normal': 100,
        'R4_2_interest_fee_waiver_no_normal': 100,
        'R4_2_principal_waiver_no_normal': 0,
        'R4_2_late_fee_waiver_yes_normal': 100,
        'R4_2_interest_fee_waiver_yes_normal': 100,
        'R4_2_principal_waiver_yes_normal': 20,
        'R4_3_late_fee_waiver_no_normal': 100,
        'R4_3_interest_fee_waiver_no_normal': 100,
        'R4_3_principal_waiver_no_normal': 0,
        'R4_3_late_fee_waiver_yes_normal': 100,
        'R4_3_interest_fee_waiver_yes_normal': 100,
        'R4_3_principal_waiver_yes_normal': 30,
        'R4_4_late_fee_waiver_no_normal': 100,
        'R4_4_interest_fee_waiver_no_normal': 100,
        'R4_4_principal_waiver_no_normal': 10,
        'R4_4_late_fee_waiver_yes_normal': 100,
        'R4_4_interest_fee_waiver_yes_normal': 100,
        'R4_4_principal_waiver_yes_normal': 40,
        'R4_5_late_fee_waiver_no_normal': 100,
        'R4_5_interest_fee_waiver_no_normal': 100,
        'R4_5_principal_waiver_no_normal': 20,
        'R4_5_late_fee_waiver_yes_normal': 100,
        'R4_5_interest_fee_waiver_yes_normal': 100,
        'R4_5_principal_waiver_yes_normal': 50,
        'R5_0_late_fee_waiver_no_normal': 0,
        'R5_0_late_fee_waiver_yes_normal': 50,
        'R5_1_late_fee_waiver_no_normal': 10,
        'R5_1_late_fee_waiver_yes_normal': 50,
        'R5_2_late_fee_waiver_no_normal': 20,
        'R5_2_late_fee_waiver_yes_normal': 100,
        'R5_3_late_fee_waiver_no_normal': 50,
        'R5_3_late_fee_waiver_yes_normal': 100,
        'R5_4_late_fee_waiver_no_normal': 100,
        'R5_4_late_fee_waiver_yes_normal': 100,
        'R5_5_late_fee_waiver_no_normal': 100,
        'R5_5_late_fee_waiver_yes_normal': 100,
        'R6_0_late_fee_waiver_no_normal': 0,
        'R6_0_late_fee_waiver_yes_normal': 100,
        'R6_0_interest_fee_waiver_no_normal': 0,
        'R6_0_interest_fee_waiver_yes_normal': 20,
        'R6_1_late_fee_waiver_no_normal': 100,
        'R6_1_interest_fee_waiver_no_normal': 0,
        'R6_1_late_fee_waiver_yes_normal': 100,
        'R6_1_interest_fee_waiver_yes_normal': 20,
        'R6_2_late_fee_waiver_no_normal': 100,
        'R6_2_interest_fee_waiver_no_normal': 10,
        'R6_2_late_fee_waiver_yes_normal': 100,
        'R6_2_interest_fee_waiver_yes_normal': 40,
        'R6_3_late_fee_waiver_no_normal': 100,
        'R6_3_interest_fee_waiver_no_normal': 40,
        'R6_3_late_fee_waiver_yes_normal': 100,
        'R6_3_interest_fee_waiver_yes_normal': 60,
        'R6_4_late_fee_waiver_no_normal': 100,
        'R6_4_interest_fee_waiver_no_normal': 50,
        'R6_4_late_fee_waiver_yes_normal': 100,
        'R6_4_interest_fee_waiver_yes_normal': 100,
        'R6_5_late_fee_waiver_no_normal': 100,
        'R6_5_interest_fee_waiver_no_normal': 100,
        'R6_5_late_fee_waiver_yes_normal': 100,
        'R6_5_interest_fee_waiver_yes_normal': 100,
        'R5_0_late_fee_waiver_yes_laku6': 100,
        'R5_1_late_fee_waiver_yes_laku6': 100,
        'R5_2_late_fee_waiver_yes_laku6': 100,
        'R5_3_late_fee_waiver_yes_laku6': 100,
        'R5_4_late_fee_waiver_yes_laku6': 100,
        'R5_5_late_fee_waiver_yes_laku6': 100,
        'R5_0_late_fee_waiver_yes_pede': 100,
        'R5_1_late_fee_waiver_yes_pede': 100,
        'R5_2_late_fee_waiver_yes_pede': 100,
        'R5_3_late_fee_waiver_yes_pede': 100,
        'R5_4_late_fee_waiver_yes_pede': 100,
        'R5_5_late_fee_waiver_yes_pede': 100,
        'R5_0_late_fee_waiver_yes_icare': 100,
        'R5_1_late_fee_waiver_yes_icare': 100,
        'R5_2_late_fee_waiver_yes_icare': 100,
        'R5_3_late_fee_waiver_yes_icare': 100,
        'R5_4_late_fee_waiver_yes_icare': 100,
        'R5_5_late_fee_waiver_yes_icare': 100,
        'R6_0_late_fee_waiver_yes_laku6': 100,
        'R6_0_interest_fee_waiver_yes_laku6': 100,
        'R6_1_late_fee_waiver_yes_laku6': 100,
        'R6_1_interest_fee_waiver_yes_laku6': 20,
        'R6_2_late_fee_waiver_yes_laku6': 100,
        'R6_2_interest_fee_waiver_yes_laku6': 100,
        'R6_3_late_fee_waiver_yes_laku6': 100,
        'R6_3_interest_fee_waiver_yes_laku6': 100,
        'R6_4_late_fee_waiver_yes_laku6': 100,
        'R6_4_interest_fee_waiver_yes_laku6': 100,
        'R6_5_late_fee_waiver_yes_laku6': 100,
        'R6_5_interest_fee_waiver_yes_laku6': 100,
        'R6_0_late_fee_waiver_yes_pede': 100,
        'R6_0_interest_fee_waiver_yes_pede': 100,
        'R6_1_late_fee_waiver_yes_pede': 100,
        'R6_1_interest_fee_waiver_yes_pede': 20,
        'R6_2_late_fee_waiver_yes_pede': 100,
        'R6_2_interest_fee_waiver_yes_pede': 100,
        'R6_3_late_fee_waiver_yes_pede': 100,
        'R6_3_interest_fee_waiver_yes_pede': 100,
        'R6_4_late_fee_waiver_yes_pede': 100,
        'R6_4_interest_fee_waiver_yes_pede': 100,
        'R6_5_late_fee_waiver_yes_pede': 100,
        'R6_5_interest_fee_waiver_yes_pede': 100,
        'R6_0_late_fee_waiver_yes_icare': 100,
        'R6_0_interest_fee_waiver_yes_icare': 100,
        'R6_1_late_fee_waiver_yes_icare': 100,
        'R6_1_interest_fee_waiver_yes_icare': 100,
        'R6_2_late_fee_waiver_yes_icare': 100,
        'R6_2_interest_fee_waiver_yes_icare': 100,
        'R6_3_late_fee_waiver_yes_icare': 100,
        'R6_3_interest_fee_waiver_yes_icare': 100,
        'R6_4_late_fee_waiver_yes_icare': 100,
        'R6_4_interest_fee_waiver_yes_icare': 100,
        'R6_5_late_fee_waiver_yes_icare': 100,
        'R6_5_interest_fee_waiver_yes_icare': 100,
        'R4_0_late_fee_waiver_yes_laku6': 100,
        'R4_0_interest_fee_waiver_yes_laku6': 100,
        'R4_0_principal_waiver_yes_laku6': 0,
        'R4_1_late_fee_waiver_yes_laku6': 100,
        'R4_1_interest_fee_waiver_yes_laku6': 100,
        'R4_1_principal_waiver_yes_laku6': 0,
        'R4_2_late_fee_waiver_yes_laku6': 100,
        'R4_2_interest_fee_waiver_yes_laku6': 100,
        'R4_2_principal_waiver_yes_laku6': 0,
        'R4_3_late_fee_waiver_yes_laku6': 100,
        'R4_3_interest_fee_waiver_yes_laku6': 100,
        'R4_3_principal_waiver_yes_laku6': 0,
        'R4_4_late_fee_waiver_yes_laku6': 100,
        'R4_4_interest_fee_waiver_yes_laku6': 100,
        'R4_4_principal_waiver_yes_laku6': 70,
        'R4_5_late_fee_waiver_yes_laku6': 100,
        'R4_5_interest_fee_waiver_yes_laku6': 100,
        'R4_5_principal_waiver_yes_laku6': 0,
        'R4_0_late_fee_waiver_yes_pede': 100,
        'R4_0_interest_fee_waiver_yes_pede': 100,
        'R4_0_principal_waiver_yes_pede': 0,
        'R4_1_late_fee_waiver_yes_pede': 100,
        'R4_1_interest_fee_waiver_yes_pede': 100,
        'R4_1_principal_waiver_yes_pede': 0,
        'R4_2_late_fee_waiver_yes_pede': 100,
        'R4_2_interest_fee_waiver_yes_pede': 100,
        'R4_2_principal_waiver_yes_pede': 0,
        'R4_3_late_fee_waiver_yes_pede': 100,
        'R4_3_interest_fee_waiver_yes_pede': 100,
        'R4_3_principal_waiver_yes_pede': 0,
        'R4_4_late_fee_waiver_yes_pede': 100,
        'R4_4_interest_fee_waiver_yes_pede': 100,
        'R4_4_principal_waiver_yes_pede': 70,
        'R4_5_late_fee_waiver_yes_pede': 100,
        'R4_5_interest_fee_waiver_yes_pede': 100,
        'R4_5_principal_waiver_yes_pede': 0,
        'R4_0_late_fee_waiver_yes_icare': 100,
        'R4_0_interest_fee_waiver_yes_icare': 100,
        'R4_0_principal_waiver_yes_icare': 0,
        'R4_1_late_fee_waiver_yes_icare': 100,
        'R4_1_interest_fee_waiver_yes_icare': 100,
        'R4_1_principal_waiver_yes_icare': 0,
        'R4_2_late_fee_waiver_yes_icare': 100,
        'R4_2_interest_fee_waiver_yes_icare': 100,
        'R4_2_principal_waiver_yes_icare': 50,
        'R4_3_late_fee_waiver_yes_icare': 100,
        'R4_3_interest_fee_waiver_yes_icare': 100,
        'R4_3_principal_waiver_yes_icare': 50,
        'R4_4_late_fee_waiver_yes_icare': 100,
        'R4_4_interest_fee_waiver_yes_icare': 100,
        'R4_4_principal_waiver_yes_icare': 80,
        'R4_5_late_fee_waiver_yes_icare': 100,
        'R4_5_interest_fee_waiver_yes_icare': 100,
        'R4_5_principal_waiver_yes_icare': 0,
        'R5_0_late_fee_waiver_no_laku6': 100,
        'R5_1_late_fee_waiver_no_laku6': 100,
        'R5_2_late_fee_waiver_no_laku6': 100,
        'R5_3_late_fee_waiver_no_laku6': 100,
        'R5_4_late_fee_waiver_no_laku6': 100,
        'R5_5_late_fee_waiver_no_laku6': 100,
        'R5_0_late_fee_waiver_no_pede': 100,
        'R5_1_late_fee_waiver_no_pede': 100,
        'R5_2_late_fee_waiver_no_pede': 100,
        'R5_3_late_fee_waiver_no_pede': 100,
        'R5_4_late_fee_waiver_no_pede': 100,
        'R5_5_late_fee_waiver_no_pede': 100,
        'R5_0_late_fee_waiver_no_icare': 100,
        'R5_1_late_fee_waiver_no_icare': 100,
        'R5_2_late_fee_waiver_no_icare': 100,
        'R5_3_late_fee_waiver_no_icare': 100,
        'R5_4_late_fee_waiver_no_icare': 100,
        'R5_5_late_fee_waiver_no_icare': 100,
        'R6_0_late_fee_waiver_no_laku6': 100,
        'R6_0_interest_fee_waiver_no_laku6': 100,
        'R6_1_late_fee_waiver_no_laku6': 100,
        'R6_1_interest_fee_waiver_no_laku6': 20,
        'R6_2_late_fee_waiver_no_laku6': 100,
        'R6_2_interest_fee_waiver_no_laku6': 100,
        'R6_3_late_fee_waiver_no_laku6': 100,
        'R6_3_interest_fee_waiver_no_laku6': 100,
        'R6_4_late_fee_waiver_no_laku6': 100,
        'R6_4_interest_fee_waiver_no_laku6': 100,
        'R6_5_late_fee_waiver_no_laku6': 100,
        'R6_5_interest_fee_waiver_no_laku6': 100,
        'R6_0_late_fee_waiver_no_pede': 100,
        'R6_0_interest_fee_waiver_no_pede': 100,
        'R6_1_late_fee_waiver_no_pede': 100,
        'R6_1_interest_fee_waiver_no_pede': 20,
        'R6_2_late_fee_waiver_no_pede': 100,
        'R6_2_interest_fee_waiver_no_pede': 100,
        'R6_3_late_fee_waiver_no_pede': 100,
        'R6_3_interest_fee_waiver_no_pede': 100,
        'R6_4_late_fee_waiver_no_pede': 100,
        'R6_4_interest_fee_waiver_no_pede': 100,
        'R6_5_late_fee_waiver_no_pede': 100,
        'R6_5_interest_fee_waiver_no_pede': 100,
        'R6_0_late_fee_waiver_no_icare': 100,
        'R6_0_interest_fee_waiver_no_icare': 100,
        'R6_1_late_fee_waiver_no_icare': 100,
        'R6_1_interest_fee_waiver_no_icare': 100,
        'R6_2_late_fee_waiver_no_icare': 100,
        'R6_2_interest_fee_waiver_no_icare': 100,
        'R6_3_late_fee_waiver_no_icare': 100,
        'R6_3_interest_fee_waiver_no_icare': 100,
        'R6_4_late_fee_waiver_no_icare': 100,
        'R6_4_interest_fee_waiver_no_icare': 100,
        'R6_5_late_fee_waiver_no_icare': 100,
        'R6_5_interest_fee_waiver_no_icare': 100,
        'R4_0_late_fee_waiver_no_laku6': 100,
        'R4_0_interest_fee_waiver_no_laku6': 100,
        'R4_0_principal_waiver_no_laku6': 0,
        'R4_1_late_fee_waiver_no_laku6': 100,
        'R4_1_interest_fee_waiver_no_laku6': 100,
        'R4_1_principal_waiver_no_laku6': 0,
        'R4_2_late_fee_waiver_no_laku6': 100,
        'R4_2_interest_fee_waiver_no_laku6': 100,
        'R4_2_principal_waiver_no_laku6': 0,
        'R4_3_late_fee_waiver_no_laku6': 100,
        'R4_3_interest_fee_waiver_no_laku6': 100,
        'R4_3_principal_waiver_no_laku6': 0,
        'R4_4_late_fee_waiver_no_laku6': 100,
        'R4_4_interest_fee_waiver_no_laku6': 100,
        'R4_4_principal_waiver_no_laku6': 70,
        'R4_5_late_fee_waiver_no_laku6': 100,
        'R4_5_interest_fee_waiver_no_laku6': 100,
        'R4_5_principal_waiver_no_laku6': 0,
        'R4_0_late_fee_waiver_no_pede': 100,
        'R4_0_interest_fee_waiver_no_pede': 100,
        'R4_0_principal_waiver_no_pede': 0,
        'R4_1_late_fee_waiver_no_pede': 100,
        'R4_1_interest_fee_waiver_no_pede': 100,
        'R4_1_principal_waiver_no_pede': 0,
        'R4_2_late_fee_waiver_no_pede': 100,
        'R4_2_interest_fee_waiver_no_pede': 100,
        'R4_2_principal_waiver_no_pede': 0,
        'R4_3_late_fee_waiver_no_pede': 100,
        'R4_3_interest_fee_waiver_no_pede': 100,
        'R4_3_principal_waiver_no_pede': 0,
        'R4_4_late_fee_waiver_no_pede': 100,
        'R4_4_interest_fee_waiver_no_pede': 100,
        'R4_4_principal_waiver_no_pede': 70,
        'R4_5_late_fee_waiver_no_pede': 100,
        'R4_5_interest_fee_waiver_no_pede': 100,
        'R4_5_principal_waiver_no_pede': 0,
        'R4_0_late_fee_waiver_no_icare': 100,
        'R4_0_interest_fee_waiver_no_icare': 100,
        'R4_0_principal_waiver_no_icare': 0,
        'R4_1_late_fee_waiver_no_icare': 100,
        'R4_1_interest_fee_waiver_no_icare': 199,
        'R4_1_principal_waiver_no_icare': 0,
        'R4_2_late_fee_waiver_no_icare': 100,
        'R4_2_interest_fee_waiver_no_icare': 100,
        'R4_2_principal_waiver_no_icare': 50,
        'R4_3_late_fee_waiver_no_icare': 100,
        'R4_3_interest_fee_waiver_no_icare': 100,
        'R4_3_principal_waiver_no_icare': 50,
        'R4_4_late_fee_waiver_no_icare': 100,
        'R4_4_interest_fee_waiver_no_icare': 100,
        'R4_4_principal_waiver_no_icare': 80,
        'R4_5_late_fee_waiver_no_icare': 100,
        'R4_5_interest_fee_waiver_no_icare': 100,
        'R4_5_principal_waiver_no_icare': 0,
    }

    @classmethod
    def all_statuses(cls):
        return list(cls.STATUSES.__dict__.values()) + \
               list(cls.NEW_PROACTIVE_STATUSES.__dict__.values())

    OFFER_GENERATED_AVAILABLE_PRODUCT = (PRODUCTS.r1, PRODUCTS.r4)

    GRAVEYARD_STATUS = (STATUSES.inactive, STATUSES.expired)

    COMMS_CHANNELS = Namespace(**{'email': 'Email',
                                  'pn': 'PN',
                                  'sms': 'SMS'})

    TEMPLATE_CODE_ACTIVATION = Namespace(**{'sms': 'after_activation_offer_sms',
                                            'email': 'after_activation_offer_email',
                                            'pn': 'after_activation_offer_pn'})

    @classmethod
    def waiver_without_r4(cls):
        return [
            cls.PRODUCTS.r5,
            cls.PRODUCTS.r6,
        ]

    EXCLUDED_WAIVER_STATUS_FROM_EXPIRED = (
        STATUSES.expired,
        STATUSES.activated,
        STATUSES.inactive,
    )

    LOAN_REFINANCING_ON_PROCESSED = (
        STATUSES.requested,
        STATUSES.approved,
        STATUSES.proposed,
        STATUSES.offer_selected,
        STATUSES.offer_generated,
        NEW_PROACTIVE_STATUSES.proposed_email,
        NEW_PROACTIVE_STATUSES.proposed_submit,
        NEW_PROACTIVE_STATUSES.proposed_offer,
    )

    BLOCKING_CASHBACK_AUTODEDUCTION = (
        STATUSES.requested,
        STATUSES.offer_generated,
        STATUSES.offer_selected,
        STATUSES.approved,
    )

    BLOCKING_POINT_AUTODEDUCTION = (
        STATUSES.requested,
        STATUSES.offer_generated,
        STATUSES.offer_selected,
        STATUSES.approved,
    )

    BANNED_PROVINCE = (
        'bali', 'nusa tenggara timur', 'nusa tenggara barat',
    )

    BANNED_CITY = (
        'lombok barat', 'lombok tengah', 'lombok timur', 'lombok utara',
    )

    ALLOWED_JOB_INDUSTRY = (
        'kesehatan', 'teknik/computer', 'banking',
    )

    BANNED_JOB_TYPE = (
        'freelance', 'ibu rumah tangga', 'pengusaha',
    )

    BANNED_JOB_DESCRIPTION = (
        'agen perjalanan', 'sewa kendaraan', 'supir / ojek', 'koki', 'mandor',
        'pelayan / pramuniaga', 'photographer', 'pilot / staff penerbangan', 'salesman',
        'spg', 'tukang bangunan', 'buruh pabrik / gudang', 'otomotif', 'warnet',
    )

    BLOCKED_BY_LENDER = ['bss_channeling']


class GeneralWebsiteConst(object):

    MOBILE_PHONE_REGEX = '^08+?\d{8,12}$'

    STATUSES = Namespace(**{
        'eligible': [
            'Approved',
            'Offer Generated',
            'Offer Selected',
            'Email Sent',
            'Form Viewed'
        ],
        'not_eligible': ['Activated', 'Expired']
    })

    REASONS = {
        'Approved': "offer approved",
        'Offer Generated': "offer generated",
        'Offer Selected': "offer selected",
        'Email Sent': "email sent",
        'Form Viewed': "form viewed",
        'Activated': "offer activated",
        'Expired': "offer expired",
    }


class MultipleRefinancingLimitConst(object):
    R1 = 1
    R2_R3 = 3


WAIVER_COLL_HEAD_APPROVER_GROUP = 'waiver_collection_head_approver'
WAIVER_FRAUD_APPROVER_GROUP = 'waiver_fraud_approver'
WAIVER_OPS_TL_APPROVER_GROUP = 'waiver_ops_team_leader_approver'
WAIVER_SPV_APPROVER_GROUP = 'waiver_supervisor_approver'
WAIVER_B1_CURRENT_APPROVER_GROUP = 'waiver_b1_approver'
WAIVER_B2_APPROVER_GROUP = 'waiver_b2_approver'
WAIVER_B3_APPROVER_GROUP = 'waiver_b3_approver'
WAIVER_B4_APPROVER_GROUP = 'waiver_b4_approver'
WAIVER_B5_APPROVER_GROUP = 'waiver_b5_approver'
WAIVER_B6_APPROVER_GROUP = 'waiver_b6_approver'
COLLECTION_TEAM_LEADER = 'collection_team_leader'
COLLECTION_AREA_CORDINATOR = 'collection_area_coordinator'

NEW_WAIVER_APPROVER_GROUPS = [
    WAIVER_B1_CURRENT_APPROVER_GROUP,
    WAIVER_B2_APPROVER_GROUP,
    WAIVER_B3_APPROVER_GROUP,
    WAIVER_B4_APPROVER_GROUP,
    WAIVER_B5_APPROVER_GROUP,
    WAIVER_B6_APPROVER_GROUP,
    WAIVER_SPV_APPROVER_GROUP,
    WAIVER_COLL_HEAD_APPROVER_GROUP,
    WAIVER_OPS_TL_APPROVER_GROUP,
    WAIVER_FRAUD_APPROVER_GROUP,
    COLLECTION_TEAM_LEADER,
    COLLECTION_AREA_CORDINATOR,
]

TOP_LEVEL_WAIVER_APPROVERS = [  WAIVER_COLL_HEAD_APPROVER_GROUP,
                                WAIVER_FRAUD_APPROVER_GROUP,
                                WAIVER_OPS_TL_APPROVER_GROUP,
                                WAIVER_SPV_APPROVER_GROUP
                              ]

WAIVER_BUCKET_LIST = ('Current', 1, 2, 3, 4, 5)


class ApprovalLayerConst(object):
    TL = 'TL'
    SPV = 'Spv'
    COLLS_HEAD = 'Colls Head'
    OPS_HEAD = 'Ops Head'


class WaiverApprovalDecisions(object):
    REJECTED = 'rejected'
    APPROVED = 'approved'


class Campaign(object):
    R4_SPECIAL_FEB_MAR_20 = 'r4_spec_feb_mar_20'
    R4_SPEC_MAY_JUN_21 = 'r4_spec_may_jun_21'
    R4_NATARU_21 = 'r4_nataru_21'
    R4_RAMADHAN_22 = 'r4_ramadhan_22'
    R4_17INDEPENDENCEDAY_22 = 'r4_17independenceday_22'
    R4_OCTOBERINITIATIVE_22 = 'r4_octoberinitiative_22'
    R4_NOVEMBERINITIATIVE_22 = 'R4_novemberinitiative_22'
    R123_NOVEMBERINITIATIVE_22 = 'R123_novemberinitiative_22'
    R4_NATARUINITIATIVE_22 = 'R4_nataruinitiative_22'
    R56_NATARUINITIATIVE_22 = 'R56_nataruinitiative_22'
    COHORT_CAMPAIGN_NAME = 'r4_special_bde_24'
    R1_SOS_REFINANCING_23 = 'r1_sos_refinancing_23'
    COHORT_CAMPAIGN_DPD_181_PLUS = 'r4_promo_dpd181_aug_24'


B5_EMAIL_TEMPLATE_MAPPING = {
    'emailsent_offer_first_email': 'emailsent_offer_first_email_b5',
    'emailsent_open_offer_first_email': 'emailsent_open_offer_first_email_b5',
    'emailsent_open_offer_second_email': 'emailsent_open_offer_second_email_b5',
    'formviewed_offer_first_email': 'formviewed_offer_first_email_b5',
    'offergenerated_first_email': 'offergenerated_first_email_b5',
    'offerselected_third_email': 'offerselected_third_email_b5',
    'offerselected_second_email': 'offerselected_second_email_b5',
    'offerselected_first_email_R4': 'offerselected_first_email_R4_b5',
    'approved_third_email_R4': 'approved_third_email_R4_b5',
    'approved_third_email_R5R6': 'approved_third_email_R5R6_b5',
    'approved_second_email_R4': 'approved_second_email_R4_b5',
    'approved_second_email_R5R6': 'approved_second_email_R5R6_b5',
    'approved_first_email_R4': 'approved_first_email_R4_b5',
    'approved_first_email_R5R6': 'approved_first_email_R5R6_b5',
    'activated_offer_waiver_paidoff_email': 'activated_offer_waiver_paidoff_email_b5',
    'activated_offer_waiver_notpaidoff_pn': 'activated_offer_waiver_notpaidoff_pn_b5',
    'immediate_multiple_ptp_payment': 'immediate_multiple_ptp_payment_b5',
    'payment_date_1_multiple_ptp_1_day': 'payment_date_1_multiple_ptp_1_day_b5',
    'payment_date_1_multiple_ptp_on_day': 'payment_date_1_multiple_ptp_on_day_b5',
    'payment_date_2_multiple_ptp_1_day': 'payment_date_2_multiple_ptp_1_day_b5',
    'payment_date_2_multiple_ptp_on_day': 'payment_date_2_multiple_ptp_on_day_b5',
    'payment_date_3_multiple_ptp_1_day': 'payment_date_3_multiple_ptp_1_day_b5',
    'payment_date_3_multiple_ptp_on_day': 'payment_date_3_multiple_ptp_on_day_b5',
    'multiple_ptp_1_day_expiry_date': 'multiple_ptp_1_day_expiry_date_b5',
    'multiple_ptp_on_expiry_date': 'multiple_ptp_on_expiry_date_b5',
    'multiple_ptp_after_expiry_date': 'multiple_ptp_after_expiry_date_b5',
}


B5_SPECIAL_EMAIL_TEMPLATES = {
    'activated_offer_waiver_paidoff_email': 'activated_offer_waiver_paidoff_email_b5',
    'activated_offer_waiver_notpaidoff_pn': 'activated_offer_waiver_notpaidoff_pn_b5',
}


B5_SMS_TEMPLATE_MAPPING = {
    'emailsent_offer_first_sms': 'emailsent_offer_first_sms_b5',
    'emailsent_open_offer_first_sms': 'emailsent_open_offer_first_sms_b5',
    'formviewed_offer_first_sms': 'formviewed_offer_first_sms_b5',
    'offergenerated_first_sms': 'offergenerated_first_sms_b5',
    'offerselected_third_sms_R1R2R3R4': 'offerselected_third_sms_R1R2R3R4_b5',
    'offerselected_second_sms_R1R2R3R4': 'offerselected_second_sms_R1R2R3R4_b5',
    'offerselected_first_sms_R1R2R3R4': 'offerselected_first_sms_R1R2R3R4_b5',
    'approved_offer_third_sms': 'approved_offer_third_sms_b5',
    'approved_offer_second_sms': 'approved_offer_second_sms_b5',
    'approved_offer_first_sms': 'approved_offer_first_sms_b5'
}


class CampaignEmoticon(object):
    WINK = u'\U0001F609'
    MONEYWING = u'\U0001F4B8'
    PARTYPOPPER = u'\U0001F389'
    ROTATINGLIGHT = u'\U0001F6A8'


class CohortCampaignEmail(object):
    # for R4 directly send on blast
    SUBJECT_R4_1 = 'Diskon Meriah Cuan, Mei Berlimpah Cuan Hadir Untukmu! 🚀'
    TEMPLATE_CODE_R4_1 = 'bde2024_may_2024_cohort_email1_r4'
    # for R4 reminder minus 2
    SUBJECT_R4_2 = 'Yakin Mau Lewatkan Diskon Meriah Cuan? 🎉'
    TEMPLATE_CODE_R4_2 = 'bde2024_may_2024_cohort_email2_r4'
    # for R4 reminder minus 1
    SUBJECT_R4_3 = 'Hari Terakhirmu untuk Lunasi Tagihan dengan Diskon! 🚨'
    TEMPLATE_CODE_R4_3 = 'bde2024_may_2024_cohort_email3_r4'
    # other refinancing its mean except R4
    # for other refinancing directly send on blast
    SUBJECT_OTHER_REFINANCING_1 = 'PROGRAM BERKAH untuk Ringankan Tagihanmu!'
    TEMPLATE_CODE_OTHER_REFINANCING_1 = 'ramadhan1_march_2023_cohort_email_r6'
    # for other refinancing reminder minus 2
    SUBJECT_OTHER_REFINANCING_2 = 'Yakin Mau Lewatkan PROGRAM BERKAH untuk Ringankan Tagihanmu?'
    TEMPLATE_CODE_OTHER_REFINANCING_2 = 'ramadhan2_march_2023_cohort_email_r6'
    # for other refinancing reminder minus 1
    SUBJECT_OTHER_REFINANCING_3 = 'Kesempatan Terakhir Gunakan PROGRAM BERKAH untuk Ringankan Tagihanmu!'
    TEMPLATE_CODE_OTHER_REFINANCING_3 = 'ramadhan3_march_2023_cohort_email_r6'


class CohortCampaignPN(object):
    BASE_IMAGE_URL = 'https://julocampaign.julo.co.id/promo_may_2024/'
    # for R4 directly send on blast
    SUBJECT_R4_1 = 'Selamat, Kamu Dapat Diskon Meriah Cuan!'
    MESSAGE_R4_1 = 'Kamu bisa lunasi tagihanmu jauh lebih ringan dalam sekali bayar, lho. Cek kotak masuk/spam email kamu!'
    TEMPLATE_CODE_R4_1 = 'bde2024_may_2024_cohort_pn1_r4'
    IMAGE_URL_R4_1 = 'Refinancing%20Meriah%20Cuan/R4/PN/PN%20Diskon%20Meriah%20Cuan%20-%20R4-1.png'
    # for R4 reminder minus 2
    SUBJECT_R4_2 = 'Diskon Meriah Cuan Tinggal 2 Hari Lagi!  {}'.format(
        CampaignEmoticon.PARTYPOPPER
    )
    MESSAGE_R4_2 = 'Emang boleh sekali bayar tagihan yang sangat ringan langsung lunas? Yuk, cek kotak masuk/spam email kamu!'
    TEMPLATE_CODE_R4_2 = 'bde2024_may_2024_cohort_pn2_r4'
    IMAGE_URL_R4_2 = 'Refinancing%20Meriah%20Cuan/R4/PN/PN%20Diskon%20Meriah%20Cuan%20-%20R4-2.png'
    # for R4 reminder minus 1
    SUBJECT_R4_3 = 'Diskon Meriah Cuan Besok Berakhir! {}'.format(CampaignEmoticon.ROTATINGLIGHT)
    MESSAGE_R4_3 = 'Tanpa bunga dan denda serta potongan, tagihan lunas dalam sekali bayar! Cek kotak masuk/spam emailmu.'
    TEMPLATE_CODE_R4_3 = 'bde2024_may_2024_cohort_pn3_r4'
    IMAGE_URL_R4_3 = 'Refinancing%20Meriah%20Cuan/R4/PN/PN%20Diskon%20Meriah%20Cuan%20-%20R4-3.png'
    # other refinancing its mean except R4
    # for other refinancing directly send on blast
    SUBJECT_OTHER_REFINANCING_1 = 'PROGRAM BERKAH, Ringankan Tagihanmu'
    MESSAGE_OTHER_REFINANCING_1 = 'Yuk, cek inbox dan spam email sekarang untuk info lengkapnya! {}'.format(CampaignEmoticon.WINK)
    TEMPLATE_CODE_OTHER_REFINANCING_1 = 'ramadhan1_march_2023_cohort_pn_r6'
    IMAGE_URL_OTHER_REFINANCING_1 = ''
    # for other refinancing reminder minus 2
    SUBJECT_OTHER_REFINANCING_2 = 'PROGRAM BERKAH Tinggal 2 Hari Lagi!'
    MESSAGE_OTHER_REFINANCING_2 = 'Atasi tunggakan tagihanmu dengan program ini. Cek inbox dan spam emailmu, ya! {}'.format(CampaignEmoticon.WINK)
    TEMPLATE_CODE_OTHER_REFINANCING_2 = 'ramadhan2_march_2023_cohort_pn_r6'
    IMAGE_URL_OTHER_REFINANCING_2 = ''
    # for other refinancing reminder minus 1
    SUBJECT_OTHER_REFINANCING_3 = 'PROGRAM BERKAH besok berakhir. Yuk, manfaatkan sekarang!'
    MESSAGE_OTHER_REFINANCING_3 = 'Cek inbox dan spam emailmu sekarang, ya. Semudah itu untuk ringankan tagihanmu! {}'.format(CampaignEmoticon.WINK)
    TEMPLATE_CODE_OTHER_REFINANCING_3 = 'ramadhan3_march_2023_cohort_pn_r6'
    IMAGE_URL_OTHER_REFINANCING_3 = ''
