from __future__ import division

import random
import string
from builtins import object, range
from datetime import date, datetime, timedelta
from typing import Dict

from dashboard.models import CRMSetting
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models import signals
from django.utils import timezone
from factory import (
    Iterator,
    LazyAttribute,
    SelfAttribute,
    SubFactory,
    post_generation,
)
from factory.django import DjangoModelFactory, mute_signals
from faker import Faker
from past.utils import old_div

from juloserver.account.models import CurrentCreditMatrix
from juloserver.ana_api.models import (
    PdChurnModelResult,
    ZeroInterestExclude,
    FDCLoanDataUpload,
    CustomerHighLimitUtilization,
)
from juloserver.apiv2.models import PdBscoreModelResult
from juloserver.apiv3.models import (
    CityLookup,
    DistrictLookup,
    ProvinceLookup,
    SubDistrictLookup,
)
from juloserver.application_form.models.agent_assisted_submission import AgentAssistedWebToken
from juloserver.application_form.models import (
    IdfyCallBackLog,
    IdfyVideoCall,
    ApplicationPhoneRecord,
)
from juloserver.application_form.models.ktp_ocr import (
    OcrKtpResult,
    OcrKtpMetaDataValue,
    OcrKtpMetaDataAttribute,
    OcrKtpMetaData,
)
from juloserver.collection_hi_season.models import (
    CollectionHiSeasonCampaignCommsSetting,
    CollectionHiSeasonCampaignParticipant,
)
from juloserver.collectionbucket.models import CollectionRiskVerificationCallList
from juloserver.core.utils import JuloFakerProvider
from juloserver.disbursement.models import DailyDisbursementScoreLimit
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.fdc.models import InitialFDCInquiryLoanData
from juloserver.followthemoney.constants import LenderTransactionTypeConst
from juloserver.followthemoney.models import (
    LenderCurrent,
    LenderTransactionType,
)
from juloserver.julo.banks import BankCodes
from juloserver.julo.models import (
    PTP,
    AccountingCutOffDate,
    AddressGeolocation,
    AffordabilityHistory,
    Application,
    ApplicationExperiment,
    ApplicationFieldChange,
    ApplicationHistory,
    ApplicationInfoCardSession,
    ApplicationNote,
    ApplicationScrapeAction,
    ApplicationUpgrade,
    AppVersion,
    AppVersionHistory,
    AutodialerSession,
    AwsFaceRecogLog,
    Bank,
    BankApplication,
    BankLookup,
    BankStatementSubmit,
    BankStatementSubmitBalance,
    BcaTransactionRecord,
    BlacklistCustomer,
    CampaignSetting,
    CashbackTransferTransaction,
    ChangeReason,
    CommsBlocked,
    CommsProviderLookup,
    CootekRobocall,
    CreditMatrix,
    CreditMatrixProductLine,
    CreditMatrixRepeat,
    CreditScore,
    Customer,
    CustomerAppAction,
    CustomerCampaignParameter,
    CustomerRemoval,
    CustomerWalletHistory,
    Device,
    DeviceGeolocation,
    DeviceIpHistory,
    DeviceScrapedData,
    DigisignConfiguration,
    DigitalSignatureFaceResult,
    DisbursementTransaction,
    Document,
    DokuTransaction,
    EarlyPaybackOffer,
    EmailHistory,
    Experiment,
    ExperimentAction,
    ExperimentSetting,
    ExperimentTestGroup,
    FacebookData,
    FaceRecognition,
    FaqCheckout,
    FaqFeature,
    FaqItem,
    FaqSection,
    FDCActiveLoanChecking,
    FDCInquiry,
    FDCInquiryCheck,
    FDCInquiryLoan,
    FDCRiskyHistory,
    FeatureSetting,
    FraudHotspot,
    FraudModelExperiment,
    FrontendView,
    GlobalPaymentMethod,
    HelpCenterItem,
    HelpCenterSection,
    HighScoreFullBypass,
    Image,
    ITIConfiguration,
    JobType,
    JuloContactDetail,
    KycRequest,
    LenderBalance,
    LenderBalanceEvent,
    LenderDisburseCounter,
    LenderProductCriteria,
    LenderServiceRate,
    Loan,
    LoanHistory,
    LoanPurpose,
    Mantri,
    MasterAgreementTemplate,
    MobileFeatureSetting,
    MobileOperator,
    Offer,
    Onboarding,
    OnboardingEligibilityChecking,
    OtpRequest,
    Partner,
    PartnerBankAccount,
    PartnerLoan,
    PartnerOriginationData,
    PartnerProperty,
    PartnerPurchaseItem,
    PartnerReferral,
    PartnerReportEmail,
    PaybackTransaction,
    Payment,
    PaymentEvent,
    PaymentMethod,
    PaymentMethodLookup,
    PredictiveMissedCall,
    ProductCustomerCriteria,
    ProductLine,
    ProductLineLoanPurpose,
    ProductLookup,
    RedisWhiteListUploadHistory,
    RefereeMapping,
    ReferralSystem,
    RepaymentTransaction,
    RobocallTemplate,
    ScrapingButton,
    SecurityNote,
    SepulsaProduct,
    SepulsaTransaction,
    SignatureMethodHistory,
    SiteMapJuloWeb,
    Skiptrace,
    SkiptraceResultChoice,
    SmsHistory,
    StatusLabel,
    StatusLookup,
    SuspiciousDomain,
    UserFeedback,
    VariableStorage,
    VoiceCallRecord,
    VoiceRecord,
    VPNDetection,
    Workflow,
    XidLookup,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.loan_selloff.models import LoanSelloff, LoanSelloffBatch
from juloserver.partnership.constants import PartnershipTypeConstant
from juloserver.partnership.models import (
    PartnershipApplicationData,
    PartnershipCustomerData,
    PartnershipCustomerDataOTP,
    PartnershipSessionInformation,
    PartnershipFeatureSetting,
)
from juloserver.partnership.services.web_services import generate_token_partnership
from juloserver.partnership.tests.factories import PartnershipTypeFactory
from juloserver.portal.object.product_profile.tests.test_product_profile_services import (
    ProductProfileFactory,
)
from juloserver.pusdafil.models import PusdafilUpload
from juloserver.tokopedia.models import TokoScoreResult
from juloserver.urlshortener.models import ShortenedUrl
from juloserver.integapiv1.models import (
    EscrowPaymentMethod,
    EscrowPaymentMethodLookup,
)
from juloserver.autodebet.models import AutodebetIdfyVideoCall
from juloserver.loan.models import LoanDelayDisbursementFee
from juloserver.pin.models import RegisterAttemptLog

fake = Faker()
fake.add_provider(JuloFakerProvider)

UNIGUE_NUMBER = 1000


def unique_number():
    global UNIGUE_NUMBER
    UNIGUE_NUMBER += 1
    return UNIGUE_NUMBER


def random_nik():
    initial_digit = fake.random_int(min=1, max=6)
    first_5_digit = fake.numerify(text='#%#%#')
    birth_date = fake.random_int(min=1, max=31)
    month_date = fake.random_int(min=1, max=12)
    year_date = fake.random_int(min=10, max=22)
    birth_date = f"0{birth_date}" if birth_date < 10 else birth_date
    month_date = f"0{month_date}" if month_date < 10 else month_date
    bod = f"{birth_date}{month_date}{year_date}"
    last_4_digit = fake.numerify(text='###%')
    return(f"{initial_digit}{first_5_digit}{bod}{last_4_digit}")


class AuthUserFactory(DjangoModelFactory):
    class Meta(object):
        model = settings.AUTH_USER_MODEL

    username = LazyAttribute(lambda o: fake.random_username())


class CrmSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = CRMSetting

    role_select = 'admin_full'
    role_default = 'admin_full'
    user = SubFactory(AuthUserFactory)


class ProductLineFactory(DjangoModelFactory):
    class Meta(object):
        model = ProductLine
        django_get_or_create = ('product_line_code',)

    product_line_code = LazyAttribute(lambda o: unique_number())
    product_line_type = "STLFake"
    min_amount = 1000000
    max_amount = 1000000
    min_duration = 1
    max_duration = 1
    min_interest_rate = 0.10
    max_interest_rate = 0.10
    payment_frequency = "monthly"

    @classmethod
    def julover(cls):
        return cls(
            product_line_code=ProductLineCodes.JULOVER,
            product_line_type='JULOVER',
            min_amount=300000,
            max_amount=20000000,
            min_duration=1,
            max_duration=4,
            min_interest_rate=0,
            max_interest_rate=0,
            payment_frequency='Monthly',
        )


class CustomerFactory(DjangoModelFactory):
    class Meta(object):
        model = Customer

    user = SubFactory(AuthUserFactory)

    fullname = LazyAttribute(lambda o: fake.name())
    email = LazyAttribute(lambda o: fake.random_email())
    is_email_verified = False
    phone = LazyAttribute(lambda o: fake.phone_number())
    is_phone_verified = False
    country = ''
    self_referral_code = ''
    email_verification_key = 'email_verification_key'
    email_key_exp_date = datetime.today()
    reset_password_key = ''
    reset_password_exp_date = None
    nik = None
    product_line = SubFactory(ProductLineFactory)
    dob = date(1996, 10, 3)
    gender = "Wanita"
    monthly_income = 4000000
    address_street_num = LazyAttribute(lambda o: fake.address())
    address_provinsi = "Gorontalo"
    address_kabupaten = "Bogor"
    address_kecamatan = "Tanah Sareal"
    address_kelurahan = "Kedung Badak"
    address_kodepos = "16164"
    spouse_name = LazyAttribute(lambda o: fake.name())
    spouse_mobile_phone = "0811144247"


class ChurnUserFactory(DjangoModelFactory):
    class Meta(object):
        model = PdChurnModelResult
    id = LazyAttribute(lambda o: fake.random_int(10000, 999999))
    predict_date = datetime.today().date()
    customer_id = LazyAttribute(lambda o: fake.random_int(10000, 999999))
    model_version = 'Odin v1.0.0'
    pchurn = 0.989
    experiment_group = 'random_A'


class ZeroInterestExcludeFactory(DjangoModelFactory):
    class Meta(object):
        model = ZeroInterestExclude
    id = LazyAttribute(lambda o: fake.random_int(10000, 999999))
    customer_id = LazyAttribute(lambda o: fake.random_int(10000, 999999))


class StatusLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = 'julo.StatusLookup'
        django_get_or_create = ('status_code',)

    status_code = 310


class FacebookDataFactory(DjangoModelFactory):
    class Meta(object):
        model = FacebookData
    application = Iterator(Application.objects.filter(facebook_data__isnull=True))
    facebook_id = 0
    fullname = LazyAttribute(lambda o: fake.name())
    email = LazyAttribute(lambda o: fake.random_email())
    dob = '1989-02-19'
    gender = 'female'
    friend_count = 999
    open_date = '2012-02-19'


class DeviceFactory(DjangoModelFactory):
    class Meta(object):
        model = Device

    customer = SubFactory(CustomerFactory)

    gcm_reg_id = LazyAttribute(
        lambda o: ''.join(
            random.choice('abcdefGHIKLM0123456789') for _ in range(32)
        )
    )
    android_id = LazyAttribute(
        lambda o: ''.join(
            random.choice(string.hexdigits) for _ in range(16)
        )
    )
    imei = LazyAttribute(
        lambda o: ''.join(
            random.choice(string.digits) for _ in range(15)
        )
    )
    ios_id = LazyAttribute(lambda o: "".join(random.choice(string.hexdigits) for _ in range(16)))
    device_model_name = "Testing Device"


class PartnerFactory(DjangoModelFactory):
    class Meta(object):
        model = Partner

    user = SubFactory(AuthUserFactory)
    name = LazyAttribute(lambda o: fake.name())
    email = LazyAttribute(lambda o: fake.random_email())
    phone = "08777890987"
    type = "lender"
    is_active = False


class LenderFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderCurrent

    lender_name = "ska"
    poc_name = fake.name()
    poc_email = LazyAttribute(lambda o: fake.random_email())
    poc_phone = LazyAttribute(lambda o: fake.phone_number())
    service_fee = 0.1


class PartnerPurchaseItemFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerPurchaseItem

    partner = SubFactory(PartnerFactory)
    contract_number = LazyAttribute(lambda o: fake.name())
    device_name = LazyAttribute(lambda o: fake.name())


class PaymentMethodLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentMethodLookup

    name = "CIMB NIAGA"
    code = BankCodes.CIMB_NIAGA


class PartnerFactory(DjangoModelFactory):
    class Meta(object):
        model = Partner

    user = SubFactory(AuthUserFactory)
    name = LazyAttribute(lambda o: fake.name())
    email = LazyAttribute(lambda o: fake.random_email())
    phone = "08777890987"
    type = "lender"
    is_active = False

    @classmethod
    def mock_julover(cls):
        return cls(
            name=PartnerConstant.JULOVERS,
            email='julovers@julofinance.com',
            type=PartnershipTypeFactory(
                partner_type_name=PartnershipTypeConstant.MOCK,
            ),
        )


class ShortenedUrlFactory(DjangoModelFactory):
    class Meta(object):
        model = ShortenedUrl

    short_url = "https://bit.ly/FAKE"
    full_url = settings.LOAN_APPROVAL_SMS_URL


class PartnerPurchaseItemFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerPurchaseItem

    partner = SubFactory(PartnerFactory)
    contract_number = LazyAttribute(lambda o: fake.name())
    device_name = LazyAttribute(lambda o: fake.name())


class PaymentMethodLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentMethodLookup

    name = "CIMB NIAGA"
    code = BankCodes.CIMB_NIAGA

class PaymentEventFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentEvent

    event_date = date.today()
    event_due_amount = 20000
    event_type = "PROMO"
    can_reverse = True

class PusdafilUploadFactory(DjangoModelFactory):
    class Meta(object):
        model = PusdafilUpload

    name = ""
    identifier = 0
    retry_count = 0
    status = ""
    error = {}
    upload_data = {}


class WorkflowFactory(DjangoModelFactory):
    class Meta(object):
        model = Workflow
        django_get_or_create = ('name',)

    name = 'NoWorkflow'


class OnboardingFactory(DjangoModelFactory):
    class Meta(object):
        model = Onboarding

    description = "Test"
    status = True


class ApplicationFactory(DjangoModelFactory):
    class Meta(object):
        model = Application

    customer = SubFactory(CustomerFactory)
    device = SubFactory(DeviceFactory)

    application_status = SubFactory(StatusLookupFactory)
    product_line = SubFactory(ProductLineFactory)
    workflow = SubFactory(WorkflowFactory)
    onboarding = SubFactory(OnboardingFactory)
    name_bank_validation = SubFactory(NameBankValidationFactory)

    loan_amount_request = 2000000
    loan_duration_request = 4
    loan_purpose = 'PENDIDIKAN'
    loan_purpose_desc = 'Biaya pendidikan'
    marketing_source = 'Facebook'
    referral_code = ''
    is_own_phone = True
    fullname = LazyAttribute(lambda o: fake.name())
    dob = date(1996, 10, 3)
    gender = 'Wanita'
    ktp = '3271065902890002'
    address_street_num = LazyAttribute(lambda o: fake.address())
    address_provinsi = 'Gorontalo'
    address_kabupaten = 'Bogor'
    address_kecamatan = 'Tanah Sareal'
    address_kelurahan = 'Kedung Badak'
    address_kodepos = '16164'
    occupied_since = '2014-02-01'
    home_status = ''
    landlord_mobile_phone = ''
    mobile_phone_1 = '081218926858'
    has_whatsapp_1 = True
    mobile_phone_2 = ''
    has_whatsapp_2 = ''
    email = LazyAttribute(lambda o: fake.random_email())
    bbm_pin = ''
    twitter_username = ''
    instagram_username = ''
    marital_status = ''
    dependent = 3
    spouse_name = LazyAttribute(lambda o: fake.name())
    spouse_dob = '1990-02-02'
    spouse_mobile_phone = '0811144247'
    spouse_has_whatsapp = True
    kin_name = LazyAttribute(lambda o: fake.name())
    kin_dob = '1990-02-02'
    kin_gender = 'Pria'
    kin_mobile_phone = '08777788929'
    kin_relationship = ''
    job_type = 'Pegawai swasta'
    job_industry = 'Admin / Finance / HR'
    job_function = ''
    job_description = 'Admin / Finance / HR'
    company_name = ''
    company_phone_number = ''
    work_kodepos = ''
    job_start = '2015-11-02'
    monthly_income = 4000000
    income_1 = 3500000
    income_2 = 500000
    income_3 = 200000
    last_education = 'SMA'
    college = ''
    major = ''
    graduation_year = '2007'
    gpa = '2.84'
    has_other_income = True
    other_income_amount = 200000
    other_income_source = ''
    monthly_housing_cost = 1000000
    monthly_expenses = 2000000
    total_current_debt = 230000
    vehicle_type_1 = 'Sepeda Motor'
    vehicle_ownership_1 = 'Mencicil'
    bank_name = 'BCA'
    bank_branch = 'sudirman'
    bank_account_number = '1234567890'
    is_term_accepted = True
    is_verification_agreed = True
    is_document_submitted = None
    is_sphp_signed = None
    sphp_exp_date = '2017-09-08'
    application_xid = LazyAttribute(lambda o: fake.random_int(10000, 999999))
    app_version = ''
    is_fdc_risky = False
    payday = 7

    @classmethod
    def julover(cls):
        return cls(
            product_line=SubFactory(ProductLineFactory, product_line_code=ProductLineCodes.JULOVER),
        )

    @classmethod
    def grab(cls):
        return cls(
            product_line=SubFactory(ProductLineFactory, product_line_code=ProductLineCodes.GRAB),
        )


@mute_signals(signals.pre_save)
class ApplicationJ1Factory(ApplicationFactory):
    partner = None
    account = SubFactory('juloserver.account.tests.factories.AccountFactory')
    application_status = SubFactory(StatusLookupFactory, status_code=190)
    product_line = SubFactory(ProductLineFactory, product_line_code=ProductLineCodes.J1)
    workflow = SubFactory(WorkflowFactory, name='JuloOneWorkflow')


@mute_signals(signals.post_save)
class AddressGeolocationFactory(DjangoModelFactory):
    class Meta(object):
        model = AddressGeolocation

    application = SubFactory(ApplicationJ1Factory)
    latitude = 0.0
    longitude = 0.0


class ProductLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = ProductLookup

    product_line = LazyAttribute(
        lambda o: random.choice(ProductLine.objects.all()))

    product_code = LazyAttribute(lambda o: unique_number())
    product_name = 'I.480-O.050-L.050-C1.010-C3.010-M'
    interest_rate = 0.48
    origination_fee_pct = 0.05
    late_fee_pct = 0.05
    cashback_initial_pct = 0.01
    cashback_payment_pct = 0.01
    is_active = True


class OfferFactory(DjangoModelFactory):
    class Meta(object):
        model = Offer

    application = SubFactory(ApplicationFactory)
    product = LazyAttribute(lambda o: random.choice(ProductLookup.objects.all()))

    offer_number = 1
    loan_amount_offer = 8000000
    loan_duration_offer = 3
    installment_amount_offer = 2666667
    is_accepted = True
    offer_accepted_ts = datetime.now()
    offer_exp_date = date.today() + timedelta(days=3)
    first_installment_amount = 2666667
    first_payment_date = date.today() + relativedelta(months=1)


class PaymentFactory(DjangoModelFactory):
    class Meta(object):
        model = Payment

    loan = SubFactory('juloserver.julo.tests.factories.LoanFactory')
    payment_status = SubFactory(StatusLookupFactory, status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)

    payment_number = 1
    due_date = LazyAttribute(lambda o: fake.date())
    due_amount = 3000000
    installment_principal = 2900000
    installment_interest = 100000

    paid_date = None
    paid_amount = 0
    redeemed_cashback = 0
    cashback_earned = 0
    paid_interest = 0
    paid_principal = 0
    paid_late_fee = 0
    late_fee_amount = 55000


class PaymentMethodFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentMethod

    payment_method_code = 123
    payment_method_name = "Payment Method"
    bank_code = 123
    loan = SubFactory('juloserver.julo.tests.factories.LoanFactory')
    line_of_credit = None
    virtual_account = 123456789
    customer = SubFactory(CustomerFactory)
    is_primary = True
    is_shown = True
    is_preferred = False
    sequence = 1


class EscrowPaymentMethodLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = EscrowPaymentMethodLookup

    payment_method_code = 123


class EscrowPaymentMethodFactory(DjangoModelFactory):
    class Meta(object):
        model = EscrowPaymentMethod

    escrow_payment_gateway = None
    escrow_payment_method_lookup = SubFactory(EscrowPaymentMethodLookupFactory)
    virtual_account = 123456789


class LenderProductCriteriaFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderProductCriteria

    partner = SubFactory(PartnerFactory)
    lender = SubFactory(LenderFactory)
    type = "Product List"
    product_profile_list = []
    min_amount = None
    max_amount = None
    min_duration = None
    max_duration = None
    min_interest_rate = None
    max_interest_rate = None
    min_origination_fee = None
    max_origination_fee = None
    min_late_fee = None
    max_late_fee = None
    min_cashback_initial = None
    max_cashback_initial = None
    min_cashback_payment = None
    max_cashback_payment = None


class CleanLoanFactory(DjangoModelFactory):
    class Meta(object):
        model = Loan

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)
    partner = SubFactory(PartnerFactory)
    offer = SubFactory(OfferFactory)
    loan_status = SubFactory(
        StatusLookupFactory,
        status_code=Iterator([StatusLookup.CURRENT_CODE, StatusLookup.LOAN_180DPD_CODE]),
    )
    product = LazyAttribute(lambda o: random.choice(ProductLookup.objects.all()))

    application_xid = None
    loan_amount = 9000000
    loan_duration = 4
    first_installment_amount = LazyAttribute(
        lambda obj: obj.installment_amount + 5000
    )
    installment_amount = LazyAttribute(
        lambda obj: old_div(obj.loan_amount, obj.loan_duration)
    )
    cashback_earned_total = 0
    initial_cashback = 0
    loan_disbursement_amount = 0
    fund_transfer_ts = datetime.today() + timedelta(days=3)
    julo_bank_name = 'CIMB NIAGA'
    julo_bank_branch = 'TEBET'
    julo_bank_account_number = '12345678'
    cycle_day = 13
    cycle_day_change_date = None
    cycle_day_requested = None
    cycle_day_requested_date = None


class LoanFactory(CleanLoanFactory):
    @post_generation
    def create_payments(self, create, extracted, **kwargs):
        payment_status = StatusLookupFactory.create(status_code=PaymentStatusCodes.PAYMENT_NOT_DUE)
        for i in range(1, self.loan_duration + 1):
            due_date = self.fund_transfer_ts + relativedelta(months=i)
            installment = old_div(self.loan_amount, self.loan_duration)
            interest_amount = installment * 0.1
            principal_amount = installment - interest_amount
            PaymentFactory.create(
                loan=self,
                due_date=due_date,
                due_amount=installment,
                installment_interest=interest_amount,
                installment_principal=principal_amount,
                payment_number=i,
                payment_status=payment_status
            )


class PartnerReferralFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerReferral

    customer = SubFactory(CustomerFactory)
    partner = SubFactory(PartnerFactory)
    cust_fullname = LazyAttribute(lambda o: fake.name())
    cust_dob = "2000-09-02"
    cust_nik = "3271065902890002"
    # cust_npwp = "0004.2345.2901.0005"
    cust_email = LazyAttribute(lambda o: fake.random_email())
    mobile_phone = "08777890987"

    account_tenure_mth = None
    past_gmv = None
    past_purchase_count = None
    partner_account_id = None
    kyc_indicator = None
    is_android_user = True
    pre_exist = False

class OtpRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = OtpRequest

    customer = SubFactory(CustomerFactory)
    request_id = "555551234"
    otp_token = "123456"
    otp_service_type = "sms"
    is_used = False
    action_type = 'login'


class PaymentEventFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentEvent

    payment = SubFactory(PaymentFactory)
    event_payment = 0
    event_type = 'payment'
    event_date = datetime.today()
    added_by = SubFactory(AuthUserFactory)
    event_due_amount = 0
    cdate = datetime.today()


class DisbursementTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = DisbursementTransaction

    partner = SubFactory(PartnerFactory)
    customer = SubFactory(CustomerFactory)
    loan = SubFactory(LoanFactory)
    lender_disbursed = 0
    borrower_received = 0
    julo_provision_received = 0
    lender_provision_received = 0
    total_provision_received = 0
    lender_balance_before = 0
    lender_balance_after = 0

class RepaymentTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = RepaymentTransaction

    partner = SubFactory(PartnerFactory)
    customer = SubFactory(CustomerFactory)
    loan = SubFactory(LoanFactory)
    payment = SubFactory(PaymentFactory)
    payment_event = SubFactory(PaymentEventFactory)
    repayment_source = 'borrower_bank'
    borrower_repaid = 0
    due_amount_before = 0
    due_amount_after = 0
    lender_received = 0
    julo_fee_received = 0
    borrower_repaid_principal = 0
    borrower_repaid_interest = 0
    borrower_repaid_late_fee = 0
    lender_received_principal = 0
    lender_received_interest = 0
    lender_received_late_fee = 0
    julo_fee_received_principal = 0
    julo_fee_received_interest = 0
    julo_fee_received_late_fee = 0
    lender_received_amount = 0
    lender_balance_before = 0
    lender_balance_after = 0
    event_date = datetime.today()
    added_by = SubFactory(AuthUserFactory)


class LenderBalanceFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderBalance

    partner = SubFactory(PartnerFactory)
    total_deposit = 0
    total_withdrawal = 0
    total_disbursed_principal = 0
    total_received_principal = 0
    total_received_interest = 0
    total_received_late_fee = 0
    total_received_provision = 0
    total_received = 0
    total_paidout_principal = 0
    total_paidout_interest = 0
    total_paidout_late_fee = 0
    total_paidout_provision = 0
    total_paidout = 0
    outstanding_principal = 0


class LenderBalanceEventFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderBalanceEvent

    lender_balance = SubFactory(LenderBalanceFactory)
    amount = 0
    before_amount = 0
    after_amount = 0
    type = ''

class LenderServiceRateFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderServiceRate

    partner = SubFactory(PartnerFactory)
    provision_rate = 0.50
    principal_rate = 0.98
    interest_rate = 0.98
    late_fee_rate = 0.50

class LenderDisburseCounterFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderDisburseCounter

    partner = SubFactory(PartnerFactory)
    actual_count = 0
    rounded_count = 0


class DocumentFactory(DjangoModelFactory):
    class Meta(object):
        model = Document

    document_source = 2002916257
    url = 'cust_1000014907/application_2000014849/perjanjian_pinjaman-1001001513.pdf'
    document_type = 'lender_sphp'
    service = 'oss'
    filename = 'perjanjian_pinjaman-1001001513.pdf'
    application_xid = 6


class MobileFeatureSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = MobileFeatureSetting

    feature_name = 'digisign_mode'
    is_active = True
    parameters = {}


class ProvinceLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = ProvinceLookup

    is_active = True


class CityLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = CityLookup

    province = SubFactory(ProvinceLookupFactory)
    is_active = True


class DistrictLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = DistrictLookup

    city = SubFactory(CityLookupFactory)
    is_active = True


class SubDistrictLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = SubDistrictLookup

    district = SubFactory(DistrictLookupFactory)
    is_active = True


class RobocallTemplateFactory(DjangoModelFactory):
    class Meta(object):
        model = RobocallTemplate

    text = 'Nasabah JULO <name_with_title>, Kami ingatkan kembali ' \
           'janji bayar Anda untuk angsuran ke <payment_number> ' \
           'sejumlah <due_amount>. Harap bayar sesuai janji sebelum ' \
           'data Anda masuk dalam daftar hitam, terimakasih'
    is_active = True
    template_category = 'PROMO'
    template_name = 'voice_payment_reminder_2'
    start_date = datetime.now()


class EarlyPaybackOfferFactory(DjangoModelFactory):
    class Meta(object):
        model = EarlyPaybackOffer

    application = SubFactory(ApplicationFactory)
    loan = SubFactory(LoanFactory)
    is_fdc_risky = True
    cycle_number = 1
    promo_date = date.today()
    dpd = 10
    email_status = 'send_to_sendgrid'
    paid_off_indicator = False


class EmailHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = EmailHistory

    customer = SubFactory(CustomerFactory)
    payment = SubFactory(PaymentFactory)
    application = SubFactory(ApplicationFactory)
    status = 'open'
    sg_message_id = '0tP8UYRCS0S5iKV55WP9nQ'
    to_email = 'ari@julofinance.com'
    subject = 'promo 30% diskon'
    template_code = 'email_early_payback_1'
    message_content = 'diskon'
    partner = SubFactory(PartnerFactory)
    cdate = datetime.today()


class FDCRiskyHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = FDCRiskyHistory

    application = SubFactory(ApplicationFactory)
    loan = SubFactory(LoanFactory)
    dpd = 1
    is_fdc_risky = True


class CampaignSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = CampaignSetting

    campaign_name = 'RISKY_CUSTOMER_EARLY_PAYOFF'
    is_active = True
    description = 'campaign'


class CustomerCampaignParameterFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerCampaignParameter

    customer = SubFactory(CustomerFactory)
    campaign_setting = SubFactory(CampaignSettingFactory)
    effective_date = date.today()


class FeatureSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = FeatureSetting

    feature_name = ''
    is_active = True
    parameters = {}


class HighScoreFullBypassFactory(DjangoModelFactory):
    class Meta(object):
        model = HighScoreFullBypass


class CashbackTransferTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = CashbackTransferTransaction

    customer_id = 0
    application_id = 0
    transfer_amount = 0
    redeem_amount = 0


class PTPFactory(DjangoModelFactory):
    class Meta(object):
        model = PTP

    payment = SubFactory(PaymentFactory)
    loan = SubFactory(LoanFactory)
    agent_assigned = SubFactory(AuthUserFactory)
    ptp_amount = 1000000
    ptp_date = date.today() - timedelta(days=1)


class ApplicationHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationHistory

    application_id = 0
    status_old = 0
    status_new = 0
    cdate = datetime.now()


class ApplicationNoteFactory(DjangoModelFactory):
    class Meta:
        model = ApplicationNote

    application_id = 0


class SecurityNoteFactory(DjangoModelFactory):
    class Meta:
        model = SecurityNote

    customer = SubFactory(CustomerFactory)


class BcaTransactionRecordFactory(DjangoModelFactory):
    class Meta(object):
        model = BcaTransactionRecord

    transaction_date = '2020-12-30'
    amount = 0


class BankFactory(DjangoModelFactory):
    class Meta(object):
        model = Bank


class CustomerWalletHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerWalletHistory

    customer = SubFactory(CustomerFactory)
    wallet_balance_accruing = 10000000


class CreditScoreFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditScore
        django_get_or_create = ('application_id', )

    score = 'C'
    message = ''
    products_str = "[]"
    application_id = 0
    score_tag = ''


class AwsFaceRecogLogFactory(DjangoModelFactory):
    class Meta(object):
        model = AwsFaceRecogLog

    is_quality_check_passed = True
    application_id = 0
    raw_response = {
        'FaceRecordsStatus': True,
        'UnindexedFaces': True
    }
    brightness_threshold = 0
    sharpness_threshold = 0


class KycRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = KycRequest

    application_id = 0
    expiry_time = datetime.now()


class BankApplicationFactory(DjangoModelFactory):
    class Meta(object):
        model = BankApplication

    application_id = 0
    uker_name = ''


class PartnerLoanFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerLoan

    application_id = 0
    partner_id = 0
    approval_status = 'Approved'
    loan_amount = 0
    agreement_number = ''


class LoanSelloffBatchFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanSelloffBatch

    parameter = ''
    pct_of_parameter = 0.0
    vendor = ''


class LoanSelloffFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanSelloff

    loan_id = 0
    loan_selloff_batch = SubFactory(LoanSelloffBatchFactory)


class MantriFactory(DjangoModelFactory):
    class Meta(object):
        model = Mantri


class ExperimentFactory(DjangoModelFactory):
    class Meta(object):
        model = Experiment

    code = LazyAttribute(lambda o: fake.word)
    status_old = 0
    status_new = 0
    date_start = '2020-12-01 00:00:00+00'
    date_end = '2020-12-30 00:00:00+00'


class ExperimentActionFactory(DjangoModelFactory):
    class Meta(object):
        model = ExperimentAction

    experiment = SubFactory(ExperimentFactory)
    type = 'test'
    value = 0


class ExperimentSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = ExperimentSetting

    code = 'any_code'
    name = LazyAttribute(lambda o: fake.word)
    criteria = {'application': '#nth:-1:4,6,8'}
    is_active = True
    start_date = '2020-12-01 00:00:00+00'
    end_date = '2021-12-01 00:00:00+00'


class SignatureMethodHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = SignatureMethodHistory
    application_id = 0
    signature_method = 'Digisign'
    is_used = True


class ImageFactory(DjangoModelFactory):
    class Meta(object):
        model = Image
    image_source = 0
    image_type = 'selfie'
    url = 'example.com/test.jpg'
    thumbnail_url = 'example.com/thumbnail.jpg'


class VoiceRecordFactory(DjangoModelFactory):
    class Meta(object):
        model = VoiceRecord
    application_id = 0
    service = 'oss'


class DeviceScrapedDataFactory(DjangoModelFactory):
    class Meta(object):
        model = DeviceScrapedData
    application_id = 0
    url = ''
    file_type = 'jpg'


class CustomerAppActionFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerAppAction

    customer_id = 0
    action = 'rescrape'


class AppVersionFactory(DjangoModelFactory):
    class Meta(object):
        model = AppVersion


class ProductCustomerCriteriaFactory(DjangoModelFactory):
    class Meta(object):
        model = ProductCustomerCriteria

    product_profile = SubFactory(ProductProfileFactory)


class FraudModelExperimentFactory(DjangoModelFactory):
    class Meta(object):
        model = FraudModelExperiment

    application = SubFactory(ApplicationFactory)
    customer = SubFactory(CustomerFactory)


class ApplicationExperimentFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationExperiment

    application = SubFactory(ApplicationFactory)
    experiment = SubFactory(ExperimentFactory)


class CreditMatrixFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditMatrix
    min_threshold = 0.95
    max_threshold = 1
    score = u'A-'
    score_tag = u'A- : 0.95 - 1'
    parameter = u'job_industry:banking or repeat_time:>3'
    priority = u'1'
    is_premium_area = True
    is_salaried = True
    version = 2
    credit_matrix_type = "julo_repeat"
    message = "matrix"

    @classmethod
    def goldfish(cls, app: Application):
        field_param = 'feature:is_goldfish'
        data = dict(
            min_threshold=0,
            max_threshold=1,
            parameter=field_param,
            credit_matrix_type='julo1',
            transaction_type='self',
        )
        matrix = cls.new(
            app=app,
            data=data,
        )
        return matrix

    @classmethod
    def semi_good(cls, app: Application):
        field_param = 'feature:is_semi_good'
        data = dict(
            min_threshold=0,
            max_threshold=1,
            score='C+',
            parameter=field_param,
            credit_matrix_type='julo1',
            transaction_type='self',
        )
        matrix = cls.new(
            app=app,
            data=data,
        )
        return matrix

    @classmethod
    def new(cls, app: Application, data: Dict):
        matrix = cls(
            **data
        )
        CreditMatrixProductLineFactory(
            credit_matrix=matrix,
            product=app.product_line,
            max_duration=8,
            min_duration=1,
        )
        CurrentCreditMatrixFactory(credit_matrix=matrix)
        return matrix


class CurrentCreditMatrixFactory(DjangoModelFactory):
    class Meta:
        model = CurrentCreditMatrix

    credit_matrix = SubFactory(CreditMatrixFactory)
    transaction_type = 'self'

class CreditMatrixProductLineFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditMatrixProductLine

    interest = 0.1
    min_loan_amount = 0
    max_loan_amount = 1
    max_duration = 1


class CreditMatrixRepeatFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditMatrixRepeat

    provision = 0.03
    max_tenure = 2
    min_tenure = 1
    interest = 0.02


class ITIConfigurationFactory(DjangoModelFactory):
    class Meta(object):
        model = ITIConfiguration

    iti_version = 1
    min_threshold = 1
    max_threshold = 2
    min_income = 99
    max_income = 100


class FDCInquiryFactory(DjangoModelFactory):
    class Meta(object):
        model = FDCInquiry

    application_id = 0
    customer_id = 0
    inquiry_reason = '1 - Applying loan via Platform'
    status = "Found"


class FDCActiveLoanCheckingFactory(DjangoModelFactory):
    class Meta(object):
        model = FDCActiveLoanChecking

    customer = SubFactory(CustomerFactory)


class InitialFDCInquiryLoanDataFactory(DjangoModelFactory):
    class Meta(object):
        model = InitialFDCInquiryLoanData

    fdc_inquiry = SubFactory(FDCInquiryFactory)
    initial_outstanding_loan_count_x100 = 0
    initial_outstanding_loan_amount_x100 = 0


class FDCInquiryCheckFactory(DjangoModelFactory):
    class Meta(object):
        model = FDCInquiryCheck

    min_threshold = 0
    max_threshold = 0


class FDCInquiryLoanFactory(DjangoModelFactory):
    class Meta(object):
        model = FDCInquiryLoan

    fdc_inquiry_id = 0
    dpd_max = 0


class DeviceGeolocationFactory(DjangoModelFactory):
    class Meta(object):
        model = DeviceGeolocation
    device_id = 0
    latitude = 0.0
    longitude = 0.0


class AppVersionHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = AppVersionHistory
    build_number = 0
    version_name = 'v0.0'
    is_critical = False


class GlobalPaymentMethodFactory(DjangoModelFactory):
    class Meta(object):
        model = GlobalPaymentMethod

    feature_name = 'BCA'


class PaymentMethodLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentMethodLookup

    name = 'Bank BCA'


class DigitalSignatureFaceResultFactory(DjangoModelFactory):
    class Meta(object):
        model = DigitalSignatureFaceResult

    is_used_for_registration = True
    is_passed = True


class FaceRecognitionFactory(DjangoModelFactory):
    class Meta(object):
        model = FaceRecognition

    feature_name = 'face_recognition'
    is_active = True


class ApplicationScrapeActionFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationScrapeAction

    application_id = 0


class SmsHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = SmsHistory

    customer = SubFactory(CustomerFactory)


class CommsProviderLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = CommsProviderLookup
        django_get_or_create = ('provider_name',)

    provider_name = 'Test Provider'


class ScrapingButtonFactory(DjangoModelFactory):
    class Meta(object):
        model = ScrapingButton

    name = ''
    type = ''


class MobileOperatorFactory(DjangoModelFactory):
    class Meta(object):
        model = MobileOperator


class SepulsaProductFactory(DjangoModelFactory):
    class Meta(object):
        model = SepulsaProduct

    @classmethod
    def dana_400rb(cls):
        return cls(
            product_id='1593',
            product_name="DANA 400 RB",
            product_nominal=400_000,
            type="e-wallet",
            category="DANA",
            partner_price=400_550,
            customer_price=440_605,
            is_active=True,
            customer_price_regular=400_550,
            is_not_blocked=True,
        )

    @classmethod
    def shopeepay_20k(cls):
        return cls(
            product_id='2239',
            product_name="Saldo ShopeePay 20.000",
            product_nominal=20_000,
            type="e-wallet",
            category="ShopeePay",
            partner_price=20_900,
            customer_price=22_990,
            is_active=True,
            customer_price_regular=20_900,
            is_not_blocked=True,
        )

    @classmethod
    def gopay_500rb(cls):
        return cls(
            product_id='1179',
            product_name="GOPAY 500 RB",
            product_nominal=50_000,
            type="e-wallet",
            category="GoPay",
            partner_price=501_000,
            customer_price=551_100,
            is_active=True,
            customer_price_regular=501_000,
            is_not_blocked=True,
        )

    @classmethod
    def ovo_100rb(cls):
        return cls(
            product_id='1162',
            product_name="OVO 100 RB",
            product_nominal=100_000,
            type="e-wallet",
            category="OVO",
            partner_price=101_100,
            customer_price=111_210,
            is_active=True,
            customer_price_regular=101_100,
            is_not_blocked=True,
        )

    @classmethod
    def ewallet_open_payment(cls):
        return cls(
            product_id='1213',
            product_name="ewallet_open_payment",
            product_nominal=500,
            type="ewallet_open_payment",
            category="DANA",
            partner_price=500,
            customer_price=500,
            is_active=True,
            customer_price_regular=500,
            is_not_blocked=True,
        )


class SepulsaTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = SepulsaTransaction

    product = SubFactory(SepulsaProductFactory)
    customer = SubFactory(CustomerFactory)


class StatusLabelFactory(DjangoModelFactory):
    class Meta(object):
        model = StatusLabel

    status = 0


class SkiptraceFactory(DjangoModelFactory):
    class Meta(object):
        model = Skiptrace


class FaqSectionFactory(DjangoModelFactory):
    class Meta(object):
        model = FaqSection


class FaqItemFactory(DjangoModelFactory):
    class Meta(object):
        model = FaqItem

    section = SubFactory(FaqSectionFactory)


class JuloContactDetailFactory(DjangoModelFactory):
    class Meta(object):
        model = JuloContactDetail


class FrontendViewFactory(DjangoModelFactory):
    class Meta(object):
        model = FrontendView


class DigisignConfigurationFactory(DjangoModelFactory):
    class Meta(object):
        model = DigisignConfiguration


class ReferralSystemFactory(DjangoModelFactory):
    class Meta(object):
        model = ReferralSystem

    name = 'PromoReferral'
    caskback_amount = 40000
    product_code = [1, 2]
    partners = ['tokopedia', 'julo']
    is_active = True
    activate_referee_benefit = True
    referee_cashback_amount = 20000
    extra_params = {}


class UserFeedbackFactory(DjangoModelFactory):
    class Meta(object):
        model = UserFeedback

    rating = 1
    application_id = 0


class SkiptraceResultChoiceFactory(DjangoModelFactory):
    class Meta(object):
        model = SkiptraceResultChoice

    weight = 1


class AccountingCutOffDateFactory(DjangoModelFactory):
    class Meta(object):
        model = AccountingCutOffDate
    accounting_period = datetime(2020, 9, 1, 0, 0)
    cut_off_date = datetime(2020, 10, 15, 0, 0)


class AffordabilityHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = AffordabilityHistory

    application = SubFactory(ApplicationFactory)
    application_status = SubFactory(StatusLookupFactory)
    affordability_type = ''
    affordability_value = 10000000


class PartnerOriginationDataFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerOriginationData
    id = 1
    origination_fee = 0.01


class PaybackTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = PaybackTransaction

    transaction_id = LazyAttribute(
        lambda o: ''.join(
            random.choice(string.hexdigits) for _ in range(16)
        )
    )
    customer = SubFactory(CustomerFactory)
    payment = SubFactory(PaymentFactory)
    loan = SubFactory(LoanFactory)
    payment_method = SubFactory(PaymentMethodFactory)
    payback_service = 'faspay'
    amount = 3000000
    transaction_date = timezone.now()


class DokuTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = DokuTransaction

    transaction_date = datetime(2020, 12, 1, 0, 0, 0, 0)
    amount = 100
    transaction_type = ''
    is_processed = False


class PartnerReportEmailFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerReportEmail

    partner = SubFactory(PartnerFactory)


class LoanPurposeFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanPurpose

    version = '1'
    purpose = 'bayar utang'


class BankLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = BankLookup


class ProductLineLoanPurposeFactory(DjangoModelFactory):
    class Meta(object):
        model = ProductLineLoanPurpose

    product_line = SubFactory(ProductLineFactory)
    loan_purpose = SubFactory(LoanPurposeFactory)


class CommsBlockedFactory(DjangoModelFactory):

    class Meta(object):
        model = CommsBlocked

    loan = SubFactory(LoanFactory)
    block_until = -1

class LoanHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanHistory

    loan = SubFactory(LoanFactory)
    status_old = 0
    status_new = 0
    cdate = datetime.now()


class VPNDetectionFactory(DjangoModelFactory):
    class Meta(object):
        model = VPNDetection

    ip_address = '111.111.11.111'
    is_vpn_detected = False
    extra_data = {}


class SiteMapContentFactory(DjangoModelFactory):
    class Meta(object):
        model = SiteMapJuloWeb

    label_name = 'Tempat wisata di ancol'
    label_url = 'https://www.traveloka.com/id-id/activities/indonesia/area/ancol-102973'


class XidLookupFactory(DjangoModelFactory):
    class Meta(object):
        model = XidLookup

    xid = LazyAttribute(lambda o: unique_number())
    is_used_application = False


class AutodialerSessionFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodialerSession

    application = SubFactory(ApplicationFactory)
    status = SelfAttribute('application.application_status_id')


class PredictiveMissedCallFactory(DjangoModelFactory):
    class Meta(object):
        model = PredictiveMissedCall

    application = SubFactory(ApplicationFactory)
    application_status = SelfAttribute('application.application_status')
    auto_call_result_status = 'answered'
    is_agent_called = False


class ExperimentSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = ExperimentSetting

    code = 'RegistrationExperiment',
    name = 'Experiment KTP vs Phone Number Input',
    type = 'Registration',
    start_date = datetime.now()
    end_date = datetime.now() + timedelta(days=50)
    schedule = "",
    is_active = False,
    is_permanent = False,
    criteria={"crm_tag": False, "min_apk_version": "0.0.1"}


class ExperimentTestGroupFactory(DjangoModelFactory):
    class Meta(object):
        model = ExperimentTestGroup


class VoiceCallRecordFactory(DjangoModelFactory):
    class Meta:
        model = VoiceCallRecord

    uuid = LazyAttribute(lambda o: unique_number())


class CootekRobocallFactory(DjangoModelFactory):
    class Meta:
        model = CootekRobocall


class JobTypeFactory(DjangoModelFactory):
    class Meta:
        model = JobType

    is_salaried = True
    job_type = ''


class PartnershipCustomerDataFactory(DjangoModelFactory):
    class Meta:
        model = PartnershipCustomerData

    customer = SubFactory(CustomerFactory)
    partner = SubFactory(PartnerFactory)
    phone_number = f"0852{fake.random_number(digits=9)}"
    otp_status = PartnershipCustomerData.VERIFIED
    email = LazyAttribute(lambda o: fake.random_email())
    token = LazyAttribute(lambda o: generate_token_partnership())
    nik = LazyAttribute(lambda o: random_nik())


class PartnershipCustomerDataOTPFactory(DjangoModelFactory):
    class Meta:
        model = PartnershipCustomerDataOTP


class PartnershipApplicationDataFactory(DjangoModelFactory):
    class Meta:
        model = PartnershipApplicationData

    partnership_customer_data = SubFactory(PartnershipCustomerData)
    email = LazyAttribute(lambda o: fake.random_email())
    mobile_phone_1 = LazyAttribute(lambda o: fake.phone_number())


class PartnershipSessionInformationFactory(DjangoModelFactory):
    class Meta:
        model = PartnershipSessionInformation


class PartnerPropertyFactory(DjangoModelFactory):
    class Meta:
        model = PartnerProperty

    partner = SubFactory(PartnerFactory)


class GroupFactory(DjangoModelFactory):
    class Meta:
        model = Group


class CollectionHiSeasonCampaignParticipantFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionHiSeasonCampaignParticipant


class CollectionHiSeasonCampaignCommsSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionHiSeasonCampaignCommsSetting


class FaqCheckoutFactory(DjangoModelFactory):
    class Meta(object):
        model = FaqCheckout


class MasterAgreementTemplateFactory(DjangoModelFactory):
    class Meta(object):
        model = MasterAgreementTemplate

    product_name = "J1"
    is_active = True
    parameters = "<p></p>"


class PartnerBankAccountFactory(DjangoModelFactory):
    class Meta(object):
        model = PartnerBankAccount


class BlacklistCustomerFactory(DjangoModelFactory):

    class Meta(object):
        model = BlacklistCustomer


class FaqCheckoutFactory(DjangoModelFactory):
    class Meta(object):
        model = FaqCheckout


class ApplicationFieldChangeFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationFieldChange

    field_name ='mobile_phone_1'
    old_value ='081235475698'
    new_value ='081235475695'
    application = SubFactory(ApplicationFactory)
    agent = SubFactory(AuthUserFactory)


class FruadHotspotFactory(DjangoModelFactory):
    class Meta(object):
        model = FraudHotspot

    latitude = 0
    longitude = 0
    radius = 0


class OnboardingEligibilityCheckingFactory(DjangoModelFactory):
    class Meta(object):
        model = OnboardingEligibilityChecking

    customer = SubFactory(CustomerFactory)
    fdc_inquiry_id = 0


class RefereeMappingFactory(DjangoModelFactory):
    class Meta(object):
        model = RefereeMapping

    referrer = SubFactory(CustomerFactory)
    referee = SubFactory(CustomerFactory)


class CustomerRemovalFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerRemoval


class DeviceIpHistoryFactory(DjangoModelFactory):
    class Meta:
        model = DeviceIpHistory

    customer = SubFactory(CustomerFactory)
    ip_address = '127.0.0.1'
    count = 1


class ChangeReasonFactory(DjangoModelFactory):
    class Meta(object):
        model = ChangeReason


class ApplicationUpgradeFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationUpgrade


class ApplicationInfoCardSessionFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationInfoCardSession


class SuspiciousDomainFactory(DjangoModelFactory):
    class Meta(object):
        model = SuspiciousDomain


class FDCLoanDataUploadFactory(DjangoModelFactory):

    class Meta(object):
        model = FDCLoanDataUpload


class IdfyVideoCallFactory(DjangoModelFactory):
    class Meta(object):
        model = IdfyVideoCall

class IdfyCallBackLogFactory(DjangoModelFactory):
    class Meta(object):
        model = IdfyCallBackLog


class HelpCenterSectionFactory(DjangoModelFactory):
    class Meta(object):
        model = HelpCenterSection


class HelpCenterItemFactory(DjangoModelFactory):
    class Meta(object):
        model = HelpCenterItem


class FaqFeatureFactory(DjangoModelFactory):
    class Meta(object):
        model = FaqFeature

    title = 'Cashback itu apa?'
    visible = True
    section_name = 'cashback_new_scheme'


class TokoScoreResultFactory(DjangoModelFactory):
    class Meta(object):
        model = TokoScoreResult

class VariableStorageFactory(DjangoModelFactory):
    class Meta(object):
        model = VariableStorage


class OcrKtpResultFactory(DjangoModelFactory):
    class Meta(object):
        model = OcrKtpResult


class BankStatementSubmitFactory(DjangoModelFactory):
    class Meta(object):
        model = BankStatementSubmit


class BankStatementSubmitBalanceFactory(DjangoModelFactory):
    class Meta(object):
        model = BankStatementSubmitBalance

    bank_statement_submit = SubFactory(BankStatementSubmitFactory)
class CollectionRiskVerificationCallListFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionRiskVerificationCallList

    customer = SubFactory(CustomerFactory)
    is_verified = False
    is_connected = False
    is_passed_minus_11 = False
    is_paid_first_installment = False


class CustomerHighLimitUtilizationFactory(DjangoModelFactory):
    class Meta(object):
        model = CustomerHighLimitUtilization

    is_high = True


class ProductLockInAppBottomSheetFSFactory(DjangoModelFactory):
    class Meta(object):
        model = FeatureSetting

    feature_name = 'product_lock_in_app_bottom_sheet'
    is_active = True
    parameters = {
        "004_A": {
            "title": "Kamu Belum Bisa Transaksi",
            "body": "Kamu terdeteksi telat membayar tagihan di JULO dan aplikasi lainnya. \n"
                    "Lunasi tagihan di JULO dan aplikasi lainnya dan tunggu maks. "
                    "30 hari agar bisa mulai transaksi lagi, ya!",
            "button": "Mengerti",
        }
    }


class OcrKtpMetaDataAttributeFactory(DjangoModelFactory):
    class Meta(object):
        model = OcrKtpMetaDataAttribute


class OcrKtpMetaDataValueFactory(DjangoModelFactory):
    class Meta(object):
        model = OcrKtpMetaDataValue


class OcrKtpMetaDataFactory(DjangoModelFactory):
    class Meta(object):
        model = OcrKtpMetaData


class AutodebetIdfyVideoCallFactory(DjangoModelFactory):
    class Meta(object):
        model = AutodebetIdfyVideoCall


class AgentAssistedWebTokenFactory(DjangoModelFactory):
    class Meta(object):
        model = AgentAssistedWebToken


class ApplicationPhoneRecordFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationPhoneRecord


class LoanDelayDisbursementFeeFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanDelayDisbursementFee

    # override
    delay_disbursement_premium_fee = 3_000
    delay_disbursement_premium_rate = 0.03
    policy_id = "JULO_DELAYED_DISBURSEMENT_POLICY_ID"
    status = "ACTIVE"
    cashback = 25_000
    threshold_time = 600  # seconds
    agreement_timestamp = datetime.now()
    loan = SubFactory(LoanFactory)
    cdate = datetime.now()


class RedisWhiteListUploadHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = RedisWhiteListUploadHistory


class RegisterAttemptLogFactory(DjangoModelFactory):
    class Meta(object):
        model = RegisterAttemptLog

    attempt = 1

class DailyDisbursementScoreLimitFactory(DjangoModelFactory):
    class Meta(object):
        model = DailyDisbursementScoreLimit

    score_type = 'bscore'
    total_amount = 100000
    limit_date = datetime.now()

class PdBscoreModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdBscoreModelResult


class PartnershipFeatureSettingFactory(DjangoModelFactory):
    class Meta:
        model = PartnershipFeatureSetting

    feature_name = ''
    is_active = True
    parameters = {}


class LenderTransactionTypeFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderTransactionType

    transaction_type = LenderTransactionTypeConst.DEPOSIT
