from factory import SubFactory
from factory.declarations import LazyAttribute
from factory.django import DjangoModelFactory
from faker import Faker
from django.utils import timezone
from datetime import timedelta

from juloserver.julo.tests.factories import (
    CustomerFactory,
    LoanFactory,
    FeatureSettingFactory,
    SkiptraceResultChoiceFactory,
    AuthUserFactory,
    ApplicationFactory,
)
from juloserver.grab.models import (
    GrabCustomerData,
    GrabLoanData,
    GrabLoanInquiry,
    GrabAPILog,
    GrabProgramInterest,
    GrabProgramFeatureSetting,
    GrabSkiptraceHistory,
    GrabReferralWhitelistProgram,
    GrabCustomerReferralWhitelistHistory,
    GrabReferralCode,
    GrabIntelixCScore,
    PaymentGatewayApiLog,
    PaymentGatewayCustomerData,
    PaymentGatewayBankCode,
    GrabLoanOffer,
    PaymentGatewayLogIdentifier,
    PaymentGatewayApiLogArchival,
    GrabPromoCode,
    GrabLoanPromoCode,
    GrabPaymentPlans,
    EmergencyContactApprovalLink,
    GrabTempLoanNoCscore,
    GrabFeatureSetting,
)

fake = Faker()


class GrabCustomerDataFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabCustomerData

    customer = SubFactory(CustomerFactory)


class GrabLoanInquiryFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabLoanInquiry

    grab_customer_data = SubFactory(GrabCustomerDataFactory)
    weekly_instalment_amount = 100000


class GrabLoanDataFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabLoanData

    loan = SubFactory(LoanFactory)
    selected_amount = LazyAttribute(lambda o: fake.random_int(0, 20000000))
    selected_tenure = LazyAttribute(lambda o: fake.random_int(1, 180))
    selected_fee = 0
    selected_interest = 4
    selected_instalment_amount = 0
    grab_loan_inquiry = SubFactory(GrabLoanInquiryFactory)
    program_id = "TEST_PROGRAM_ID"


class GrabAPILogFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabAPILog

    http_status_code = 200


class GrabProgramInterestFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabProgramInterest

    program_id = "TEST_PROGRAM_ID"
    interest = 4


class GrabProgramFeatureSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabProgramFeatureSetting

    feature_setting = SubFactory(FeatureSettingFactory)
    program_id = SubFactory(GrabProgramInterestFactory)
    is_active = True


class GrabSkiptraceHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabSkiptraceHistory

    agent = SubFactory(AuthUserFactory)
    agent_name = 'unittest'
    call_result = SubFactory(SkiptraceResultChoiceFactory)
    application = SubFactory(ApplicationFactory)
    application_status = 180
    old_application_status = 180
    loan_status = 234
    payment_status = 324
    notes = 'test Skiptrace'
    start_ts = timezone.now()
    end_ts = timezone.now() + timedelta(seconds=10)


class GrabReferralWhitelistProgramFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabReferralWhitelistProgram

    start_time = timezone.localtime(timezone.now() - timedelta(days=10))
    is_active = True


class GrabCustomerReferralWhitelistHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabCustomerReferralWhitelistHistory

    grab_referral_whitelist_program = SubFactory(GrabReferralWhitelistProgramFactory)


class GrabReferralCodeFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabReferralCode


class GrabIntelixCScoreFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabIntelixCScore


class PaymentGatewayApiLogFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentGatewayApiLog

    customer_id = fake.random_int(min=1)
    application_id = fake.random_int(min=1)


class PaymentGatewayCustomerDataFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentGatewayCustomerData


class PaymentGatewayBankCodeFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentGatewayBankCode


class GrabLoanOfferFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabLoanOffer


class PaymentGatewayLogIdentifierFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentGatewayLogIdentifier


class PaymentGatewayApiLogArchivalFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentGatewayApiLogArchival

    customer_id = fake.random_int(min=1)
    application_id = fake.random_int(min=1)
    cdate = timezone.now()
    udate = timezone.now()


class GrabPromoCodeFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabPromoCode

class GrabLoanPromoCodeFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabLoanPromoCode

class GrabPaymentPlansFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabPaymentPlans


class GrabTempLoanNoCscoreFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabTempLoanNoCscore


class EmergencyContactApprovalLinkFactory(DjangoModelFactory):
    class Meta(object):
        model = EmergencyContactApprovalLink


class GrabFeatureSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = GrabFeatureSetting

    is_active = True
