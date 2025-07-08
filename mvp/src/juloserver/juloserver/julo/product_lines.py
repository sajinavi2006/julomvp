from builtins import object
from collections import namedtuple
import logging
from dateutil.relativedelta import relativedelta
from .exceptions import JuloException


logger = logging.getLogger(__name__)


class ProductLineNotFound(JuloException):
    pass


class ProductLineCodes(object):

    TURBO = 2
    JTURBO = 2
    MTL1 = 10
    MTL2 = 11
    STL1 = 20
    STL2 = 21
    CTL1 = 30
    CTL2 = 31
    BRI1 = 40
    BRI2 = 41
    GRAB1 = 50
    GRAB2 = 51
    GRAB = 52
    LOC = 60
    GRABF1 = 70
    GRABF2 = 71
    SILVER = 81
    GOLDEN = 82
    PLATINUM = 83
    DIAMOND = 84
    LAKU1 = 90
    LAKU2 = 91
    ICARE1 = 92
    ICARE2 = 93
    AXIATA1 = 94
    AXIATA2 = 95
    PEDE1 = 96
    PEDE2 = 97
    PEDEMTL1 = 101
    PEDEMTL2 = 102
    PEDESTL1 = 103
    PEDESTL2 = 104
    J1 = 1
    RENTEE = 105
    MF = 300
    BUKUWARUNG = 100
    EFISHERY = 400
    JULOVER = 200
    EMPLOYEE_FINANCING = 500
    DAGANGAN = 600
    KOPERASI_TUNAS = 301
    FISHLOG = 302
    DANA = 700
    JULO_STARTER = 2
    EFISHERY_KABAYAN_LITE = 401
    RABANDO = 800
    KOPERASI_TUNAS_45 = 304
    KARGO = 402
    AXIATA_WEB = 305
    AGRARI = 306
    EFISHERY_INTI_PLASMA = 307
    EFISHERY_JAWARA = 308
    PARTNERSHIP_PRE_CHECK = 309
    EFISHERY_KABAYAN_REGULER = 310
    GAJIGESA = 311
    DANA_CASH_LOAN = 701
    MERCHANT_FINANCING_STANDARD_PRODUCT = 315

    DANA_PRODUCT = {DANA, DANA_CASH_LOAN}

    @classmethod
    def all(cls):
        return [cls.MTL1, cls.MTL2,
                cls.STL1, cls.STL2,
                cls.CTL1, cls.CTL2,
                cls.BRI1, cls.BRI2,
                cls.GRAB1, cls.GRAB2,
                cls.GRABF1, cls.GRABF2,
                cls.LOC, cls.GRAB,
                cls.MF]

    @classmethod
    def mtl(cls):
        return [cls.MTL1, cls.MTL2]

    @classmethod
    def stl(cls):
        return [cls.STL1, cls.STL2]

    @classmethod
    def ctl(cls):
        return [cls.CTL1, cls.CTL2]

    @classmethod
    def bri(cls):
        return [cls.BRI1, cls.BRI2]

    @classmethod
    def grab(cls):
        return [cls.GRAB1, cls.GRAB2, cls.GRAB]

    @classmethod
    def loc(cls):
        return [cls.LOC]

    @classmethod
    def grabfood(cls):
        return [cls.GRABF1, cls.GRABF2]

    @classmethod
    def multiple_payment(cls):
        return [cls.MTL1, cls.MTL2, cls.BRI1, cls.BRI2, cls.GRAB1, cls.GRAB2,
                cls.GRABF1, cls.GRABF2, cls.GRAB]

    @classmethod
    def one_payment(cls):
        return [cls.STL1, cls.STL2]

    @classmethod
    def lended_by_bri(cls):
        return [cls.BRI1, cls.BRI2]

    @classmethod
    def lended_by_jtp(cls):
        return [cls.MTL1, cls.MTL2, cls.STL1, cls.STL2, cls.J1, cls.GRAB1, cls.GRAB]

    @classmethod
    def lended_by_grab(cls):
        return [cls.GRAB1, cls.GRAB2, cls.GRAB]

    @classmethod
    def for_selections(cls):
        return [cls.MTL1, cls.STL1, cls.CTL1, cls.BRI1, cls.GRAB1, cls.GRAB]

    @classmethod
    def laku6(cls):
        return [cls.LAKU1, cls.LAKU2]

    @classmethod
    def icare(cls):
        return [cls.ICARE1, cls.ICARE2]

    @classmethod
    def axiata(cls):
        return [cls.AXIATA1, cls.AXIATA2]

    @classmethod
    def lended_axiata(cls):
        return [cls.AXIATA1, cls.AXIATA2]

    @classmethod
    def pede(cls):
        return [cls.PEDEMTL1, cls.PEDEMTL2, cls.PEDESTL1, cls.PEDESTL2]

    @classmethod
    def pedemtl(cls):
        return [cls.PEDEMTL1, cls.PEDEMTL2]

    @classmethod
    def pedestl(cls):
        return [cls.PEDESTL1, cls.PEDESTL2]

    @classmethod
    def turbo(cls):
        """
        Deprecated. Please use jturbo() instead.
        """
        return cls.jturbo()

    @classmethod
    def jturbo(cls):
        return [cls.TURBO]

    @classmethod
    def with_payment_homescreen(cls):
        return [cls.STL1, cls.STL2, cls.MTL1, cls.MTL2, cls.BRI1, cls.BRI2, cls.GRAB1, cls.GRAB2,
                cls.GRABF1, cls.GRABF2, cls.GRAB]

    @classmethod
    def bulk_disbursement(self):
        return self.ctl() + self.bri() + self.grab() + \
            self.grabfood() + self.loc() + self.axiata() + \
                self.icare() + self.laku6() + self.pede()

    @classmethod
    def lended_by_grabfood(cls):
        return [cls.GRABF1, cls.GRABF2]

    @classmethod
    def julo_one(cls):
        return [cls.J1]
    
    @classmethod
    def julo_starter(cls):
        return [cls.JULO_STARTER]

    @classmethod
    def j1(cls):
        return cls.julo_one()

    @classmethod
    def allow_for_agreement(cls):
        return cls.julo_one() + cls.julo_starter()

    @classmethod
    def new_lended_by_jtp(cls):
        return [cls.MTL1, cls.MTL2, cls.STL1, cls.STL2, cls.J1]

    @classmethod
    def normal_product(cls):
        return cls.mtl() + cls.stl() + cls.julo_one() + cls.julo_starter()

    @classmethod
    def merchant_financing(cls):
        return {cls.MF}

    @classmethod
    def manual_process(cls):
        return [cls.BUKUWARUNG, cls.EFISHERY, cls.DAGANGAN,
                cls.KOPERASI_TUNAS, cls.FISHLOG,
                cls.EFISHERY_KABAYAN_LITE, cls.KARGO,
                cls.KOPERASI_TUNAS_45, cls.AGRARI,
                cls.EFISHERY_INTI_PLASMA, cls.EFISHERY_JAWARA,
                cls.EFISHERY_KABAYAN_REGULER, cls.GAJIGESA]

    @classmethod
    def j1_excluded_partner_from_dialer(cls):
        return [cls.BUKUWARUNG]

    @classmethod
    def excluded_merchant_and_non_j1_partners_from_j1_login(cls):
        return [cls.BUKUWARUNG, cls.AXIATA1, cls.AXIATA2,
                cls.MF, cls.EFISHERY, cls.GRAB,
                cls.EMPLOYEE_FINANCING, cls.EFISHERY_KABAYAN_LITE, cls.KARGO,
                cls.KOPERASI_TUNAS, cls.KOPERASI_TUNAS_45, cls.AGRARI,
                cls.EFISHERY_INTI_PLASMA, cls.EFISHERY_JAWARA,
                cls.EFISHERY_KABAYAN_REGULER, cls.GAJIGESA]

    @classmethod
    def included_merchants_in_merchant_login(cls):
        return [cls.BUKUWARUNG, cls.AXIATA1, cls.AXIATA2, cls.MF, cls.EFISHERY,
                cls.EMPLOYEE_FINANCING, cls.EFISHERY_KABAYAN_LITE, cls.KARGO,
                cls.KOPERASI_TUNAS, cls.KOPERASI_TUNAS_45, cls.AGRARI,
                cls.EFISHERY_INTI_PLASMA, cls.EFISHERY_JAWARA,
                cls.EFISHERY_KABAYAN_REGULER, cls.GAJIGESA]

    @classmethod
    def included_merchants_in_merchant_reset_pin(cls):
        return [cls.BUKUWARUNG, cls.AXIATA1, cls.AXIATA2, cls.MF, cls.EFISHERY,
                cls.EMPLOYEE_FINANCING, cls.EFISHERY_KABAYAN_LITE, cls.KARGO,
                cls.KOPERASI_TUNAS, cls.KOPERASI_TUNAS_45, cls.AGRARI,
                cls.EFISHERY_INTI_PLASMA, cls.EFISHERY_JAWARA,
                cls.EFISHERY_KABAYAN_REGULER, cls.GAJIGESA]

    @classmethod
    def julover(cls):
        return [cls.JULOVER]

    @classmethod
    def employee_financing(cls):
        return [cls.EMPLOYEE_FINANCING]

    @classmethod
    def dana(cls):
        return [cls.DANA]

    @classmethod
    def julo_product(cls):
        return [cls.J1, cls.TURBO]

    @classmethod
    def digisign_products(cls):
        return [cls.J1, cls.TURBO, cls.AXIATA_WEB]


ProductLine = namedtuple(
    'ProductLine',
    [
        'product_line_code',
        'product_line_type',
        'min_amount',
        'max_amount',
        'min_duration',
        'max_duration',
        'min_interest_rate',
        'max_interest_rate',
        'payment_frequency',
        'late_dates',
        'amount_increment',
        'min_credit_score',
        'max_credit_score',
        'bypassed_binary_checks'
    ]
)


ProductLines = (

    ProductLine(
        product_line_code=ProductLineCodes.MTL1,
        product_line_type="MTL1",
        min_amount=2000000,
        max_amount=8000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.04,
        max_interest_rate=0.06,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.MTL2,
        product_line_type="MTL2",
        min_amount=2000000,
        max_amount=8000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.04,
        max_interest_rate=0.06,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.STL1,
        product_line_type="STL1",
        min_amount=500000,
        max_amount=1000000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0.10,
        max_interest_rate=0.10,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=10), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=100000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.STL2,
        product_line_type="STL2",
        min_amount=500000,
        max_amount=1000000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0.10,
        max_interest_rate=0.10,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=10), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=100000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    # Dummy for BFI Product Line for production waiting from YOGI to define
    ProductLine(
        product_line_code=ProductLineCodes.CTL1,
        product_line_type="CTL1",
        min_amount=0,
        max_amount=0,
        min_duration=0,
        max_duration=0,
        min_interest_rate=0,
        max_interest_rate=0,
        payment_frequency="Monthly",
        late_dates=[],
        amount_increment=0,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[
            'application_date_of_birth',
            'job_not_black_listed',
            'form_partial_location',
            'scraped_data_existence',
            'form_partial_income',
            'saving_margin',
            'fraud_form_partial_device',
            'fraud_device',
            'fraud_form_partial_hp_own',
            'fraud_form_partial_hp_kin',
            'fraud_hp_spouse',
            'email_delinquency_24_months',
            'sms_delinquency_24_months',
        ]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.CTL2,
        product_line_type="CTL2",
        min_amount=0,
        max_amount=0,
        min_duration=0,
        max_duration=0,
        min_interest_rate=0,
        max_interest_rate=0,
        payment_frequency="Monthly",
        late_dates=[],
        amount_increment=0,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[
            'application_date_of_birth',
            'job_not_black_listed',
            'form_partial_location',
            'scraped_data_existence',
            'form_partial_income',
            'saving_margin',
            'fraud_form_partial_device',
            'fraud_device',
            'fraud_form_partial_hp_own',
            'fraud_form_partial_hp_kin',
            'fraud_hp_spouse',
            'email_delinquency_24_months',
            'sms_delinquency_24_months',
        ]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.BRI1,
        product_line_type="BRI1",
        min_amount=500000,
        max_amount=5000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.04,
        max_interest_rate=0.04,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=3), 1),
            (relativedelta(days=10), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.BRI2,
        product_line_type="BRI2",
        min_amount=500000,
        max_amount=5000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.04,
        max_interest_rate=0.04,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=3), 1),
            (relativedelta(days=10), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.GRAB1,
        product_line_type="GRAB1",
        min_amount=1000000,
        max_amount=2000000,
        min_duration=20,
        max_duration=25,
        min_interest_rate=0.00,
        max_interest_rate=0.00,
        payment_frequency="Daily",
        late_dates=[],
        amount_increment=100000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.GRAB2,
        product_line_type="GRAB2",
        min_amount=1000000,
        max_amount=2000000,
        min_duration=20,
        max_duration=25,
        min_interest_rate=0.00,
        max_interest_rate=0.00,
        payment_frequency="Daily",
        late_dates=[],
        amount_increment=100000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.LOC,
        product_line_type='LOC',
        min_amount=300000,
        max_amount=300000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0.00,
        max_interest_rate=0.00,
        payment_frequency='Monthly',
        late_dates=[],
        amount_increment=300000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.GRABF1,
        product_line_type="GRABF1",
        min_amount=2000000,
        max_amount=5000000,
        min_duration=4,
        max_duration=6,
        min_interest_rate=0.032,
        max_interest_rate=0.08,
        payment_frequency="Weekly",
        late_dates=[],
        amount_increment=0,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.GRABF2,
        product_line_type="GRABF2",
        min_amount=2000000,
        max_amount=5000000,
        min_duration=4,
        max_duration=6,
        min_interest_rate=0.032,
        max_interest_rate=0.08,
        payment_frequency="Weekly",
        late_dates=[],
        amount_increment=0,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.LAKU1,
        product_line_type="LAKU1",
        min_amount=1000000,
        max_amount=8000000,
        min_duration=12,
        max_duration=12,
        min_interest_rate=0.02,
        max_interest_rate=0.04,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.LAKU2,
        product_line_type="LAKU2",
        min_amount=1000000,
        max_amount=8000000,
        min_duration=12,
        max_duration=12,
        min_interest_rate=0.02,
        max_interest_rate=0.04,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.ICARE1,
        product_line_type="ICARE1",
        min_amount=2000000,
        max_amount=8000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.025,
        max_interest_rate=0.025,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.ICARE2,
        product_line_type="ICARE2",
        min_amount=2000000,
        max_amount=8000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.025,
        max_interest_rate=0.025,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.AXIATA1,
        product_line_type="AXIATA1",
        min_amount=1000000,
        max_amount=10000000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0.00,
        max_interest_rate=0.00,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.0,
        max_credit_score=0.0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.AXIATA2,
        product_line_type="AXIATA2",
        min_amount=1000000,
        max_amount=10000000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0.00,
        max_interest_rate=0.00,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.0,
        max_credit_score=0.0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.PEDE1,
        product_line_type="PEDE1",
        min_amount=2000000,
        max_amount=8000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.04,
        max_interest_rate=0.06,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.PEDE2,
        product_line_type="PEDE2",
        min_amount=500000,
        max_amount=1000000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0.10,
        max_interest_rate=0.10,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=10), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=100000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.PEDEMTL1,
        product_line_type="PEDEMTL1",
        min_amount=2000000,
        max_amount=8000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.04,
        max_interest_rate=0.06,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.PEDEMTL2,
        product_line_type="PEDEMTL2",
        min_amount=2000000,
        max_amount=8000000,
        min_duration=3,
        max_duration=6,
        min_interest_rate=0.04,
        max_interest_rate=0.06,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.PEDESTL1,
        product_line_type="PEDESTL1",
        min_amount=500000,
        max_amount=1000000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0.10,
        max_interest_rate=0.10,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=10), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=100000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.PEDESTL2,
        product_line_type="PEDESTL2",
        min_amount=500000,
        max_amount=1000000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0.10,
        max_interest_rate=0.10,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=10), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=100000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.J1,
        product_line_type="J1",
        min_amount=0,
        max_amount=0,
        min_duration=2,
        max_duration=12,
        min_interest_rate=0.36,
        max_interest_rate=0.96,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.MF,
        product_line_type="MF",
        min_amount=2000000,
        max_amount=40000000,
        min_duration=3,
        max_duration=60,
        min_interest_rate=0.027,
        max_interest_rate=0.04,
        payment_frequency="Daily",
        late_dates=[],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.RENTEE,
        product_line_type="rentee",
        min_amount=0,
        max_amount=0,
        min_duration=12,
        max_duration=12,
        min_interest_rate=0.36,
        max_interest_rate=0.36,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.1,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.EFISHERY,
        product_line_type="EF",
        min_amount=2000000,
        max_amount=20000000,
        min_duration=30,
        max_duration=90,
        min_interest_rate=0.012,
        max_interest_rate=0.012,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.BUKUWARUNG,
        product_line_type="BW",
        min_amount=2000000,
        max_amount=50000000,
        min_duration=30,
        max_duration=30,
        min_interest_rate=0.03,
        max_interest_rate=0.035,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.JULOVER,
        product_line_type="JULOVER",
        min_amount=300000,
        max_amount=20000000,
        min_duration=1,
        max_duration=4,
        min_interest_rate=0,
        max_interest_rate=0,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.DAGANGAN,
        product_line_type="DAGANGAN",
        min_amount=1000000,
        max_amount=10000000,
        min_duration=14,
        max_duration=14,
        min_interest_rate=0.015,
        max_interest_rate=0.02,
        payment_frequency="Daily",
        late_dates=[
            (relativedelta(days=4), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.KOPERASI_TUNAS,
        product_line_type="KOPERASI_TUNAS",
        min_amount=1000000,
        max_amount=20000000,
        min_duration=1,
        max_duration=3,
        min_interest_rate=0.03,
        max_interest_rate=0.05,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=8), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.FISHLOG,
        product_line_type="FISHLOG",
        min_amount=200000000,
        max_amount=2000000000,
        min_duration=2,
        max_duration=3,
        min_interest_rate=0.011,
        max_interest_rate=0.011,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.EFISHERY_KABAYAN_LITE,
        product_line_type="EFISHERY_KABAYAN_LITE",
        min_amount=1000000,
        max_amount=50000000,
        min_duration=1,
        max_duration=6,
        min_interest_rate=0.012,
        max_interest_rate=0.05,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.RABANDO,
        product_line_type="RABANDO",
        min_amount=1000000,
        max_amount=50000000,
        min_duration=30,
        max_duration=90,
        min_interest_rate=0.028,
        max_interest_rate=0.04,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.KOPERASI_TUNAS_45,
        product_line_type="KOPERASI_TUNAS_45",
        min_amount=1000000,
        max_amount=50000000,
        min_duration=45,
        max_duration=45,
        min_interest_rate=0.0325,
        max_interest_rate=0.0325,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.KARGO,
        product_line_type="kargo",
        min_amount=1000000,
        max_amount=50000000,
        min_duration=1,
        max_duration=1,
        min_interest_rate=0,
        max_interest_rate=0,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.AXIATA_WEB,
        product_line_type="AXIATA WEB",
        min_amount=1000000,
        max_amount=2000000000,
        min_duration=30,
        max_duration=360,
        min_interest_rate=0.012,
        max_interest_rate=0.012,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=8), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.JULO_STARTER,
        product_line_type='J-STARTER',
        min_amount=0,
        max_amount=0,
        min_duration=2,
        max_duration=12,
        min_interest_rate=0.36,
        max_interest_rate=0.96,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=500000,
        min_credit_score=0.1,
        max_credit_score=0.5,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.AGRARI,
        product_line_type="AGRARI",
        min_amount=1000000,
        max_amount=30000000,
        min_duration=30,
        max_duration=90,
        min_interest_rate=0.025,
        max_interest_rate=0.025,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.EFISHERY_INTI_PLASMA,
        product_line_type="EFISHERY_INTI_PLASMA",
        min_amount=200000000,
        max_amount=2000000000,
        min_duration=30,
        max_duration=180,
        min_interest_rate=0.011,
        max_interest_rate=0.011,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.EFISHERY_JAWARA,
        product_line_type="EFISHERY_JAWARA",
        min_amount=200000000,
        max_amount=1000000000,
        min_duration=30,
        max_duration=180,
        min_interest_rate=0.011,
        max_interest_rate=0.011,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.EFISHERY_KABAYAN_REGULER,
        product_line_type="EFISHERY_KABAYAN_REGULER",
        min_amount=1000000,
        max_amount=200000000,
        min_duration=30,
        max_duration=180,
        min_interest_rate=0.012,
        max_interest_rate=0.012,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
    ProductLine(
        product_line_code=ProductLineCodes.GAJIGESA,
        product_line_type="GAJIGESA",
        min_amount=1000000,
        max_amount=2000000000,
        min_duration=1,
        max_duration=365,
        min_interest_rate=0.336,
        max_interest_rate=0.336,
        payment_frequency="Monthly",
        late_dates=[
            (relativedelta(days=5), 1),
            (relativedelta(days=30), 1),
            (relativedelta(days=60), 1),
            (relativedelta(days=90), 1),
            (relativedelta(days=120), 1),
            (relativedelta(days=150), 1),
            (relativedelta(days=180), 1),
        ],
        amount_increment=0,
        min_credit_score=0,
        max_credit_score=0,
        bypassed_binary_checks=[]
    ),
)


class ProductLineManager(object):

    @classmethod
    def get_or_none(cls, code):
        for product_line in ProductLines:
            if product_line.product_line_code == code:
                logger.debug({
                    'product_line': 'found',
                    'product_line_code': product_line.product_line_code
                })
                return product_line
        logger.warn({
            'product_line': 'not_found',
            'product_line_code': code
        })
        return None

    @classmethod
    def is_data_consistent(cls, code, amount, duration):
        product_line = cls.get_or_none(code)
        if not product_line:
            return False
        if amount < product_line.min_amount or amount > product_line.max_amount:
            return False
        if duration < product_line.min_duration or duration > product_line.max_duration:
            return False
        return True
