from builtins import object
from faker import Faker
from datetime import date
from factory import LazyAttribute, SubFactory
from factory.django import DjangoModelFactory
from juloserver.digisign.constants import DigisignFeeTypeConst
from juloserver.julo.models import CreditMatrixRepeatLoan
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import (
    TransactionMethod,
    TransactionCategory,
)
from juloserver.loan.models import (
    LoanAdditionalFee,
    LoanAdditionalFeeType,
    LoanPrizeChance,
    SphpContent,
    TransactionModelCustomer,
    TransactionRiskyDecision,
    TransactionRiskyCheck,
    LoanZeroInterest,
    LoanDbrLog,
    LoanJuloCare,
    LoanTransactionDetail,
)
from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
)
from juloserver.loan.constants import DBRConst, LoanDigisignFeeConst

fake = Faker()


class TransactionMethodFactory(DjangoModelFactory):
    class Meta(object):
        model = TransactionMethod

    method = LazyAttribute(lambda o: fake.name())
    fe_display_name = LazyAttribute(lambda o: fake.name())
    background_icon_url = LazyAttribute(lambda o: fake.name())
    foreground_icon_url = LazyAttribute(lambda o: fake.name())
    foreground_locked_icon_url = LazyAttribute(lambda o: fake.name())

    @classmethod
    def ecommerce(cls):
        return cls(
            method=TransactionMethodCode.E_COMMERCE.name,
            id=TransactionMethodCode.E_COMMERCE.code,
        )

    @classmethod
    def water(cls):
        return cls(
            method=TransactionMethodCode.PDAM.name,
            id=TransactionMethodCode.PDAM.code,
        )

    @classmethod
    def train_ticket(cls):
        return cls(
            method=TransactionMethodCode.TRAIN_TICKET.name,
            id=TransactionMethodCode.TRAIN_TICKET.code,
        )

    @classmethod
    def healthcare(cls):
        return cls(
            method=TransactionMethodCode.HEALTHCARE.name,
            id=TransactionMethodCode.HEALTHCARE.code,
        )

    @classmethod
    def education(cls):
        return cls(
            method=TransactionMethodCode.EDUCATION.name,
            id=TransactionMethodCode.EDUCATION.code,
        )

    @classmethod
    def jfinancing(cls):
        return cls(
            method=TransactionMethodCode.JFINANCING.name,
            id=TransactionMethodCode.JFINANCING.code,
        )

    @classmethod
    def qris_1(cls):
        return cls(
            method=TransactionMethodCode.QRIS_1.name,
            id=TransactionMethodCode.QRIS_1.code,
        )


class TransactionCategoryFactory(DjangoModelFactory):
    class Meta(object):
        model = TransactionCategory

    name = LazyAttribute(lambda o: fake.name())
    fe_display_name = LazyAttribute(lambda o: fake.name())
    order_number = 1


class SphpContentFactory(DjangoModelFactory):
    class Meta(object):
        model = SphpContent

    sphp_variable = 'loan_type'
    message = LazyAttribute(lambda o: fake.name())


class TransactionRiskyDecisionFactory(DjangoModelFactory):
    class Meta(object):
        model = TransactionRiskyDecision

    decision_name = "OTP Needed"


class TransactionRiskyCheckFactory(DjangoModelFactory):
    class Meta(object):
        model = TransactionRiskyCheck

    loan = SubFactory(LoanFactory)
    is_vpn_detected = False
    decision = SubFactory(TransactionRiskyDecisionFactory)


class LoanPrizeChanceFactory(DjangoModelFactory):
    class Meta:
        model = LoanPrizeChance

    customer_id = 1
    loan_id = 1
    chances = fake.random_int(min=1, max=10)


class LoanZeroInterestFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanZeroInterest

    loan = SubFactory(LoanFactory)
    original_loan_amount = 2000000
    original_monthly_interest_rate = 0
    adjusted_provision_rate = 0.50


class LoanDbrLogFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanDbrLog

    application = SubFactory(ApplicationFactory)
    loan_amount = 1000000
    duration = 3
    monthly_income = 5000000
    monthly_installment = 0
    source = DBRConst.LOAN_CREATION
    log_date = date.today()


class LoanJuloCareFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanJuloCare

    insurance_premium = 8500


class CreditMatrixRepeatLoanFactory(DjangoModelFactory):
    class Meta(object):
        model = CreditMatrixRepeatLoan


class LoanAdditionalFeeTypeFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanAdditionalFeeType

    @classmethod
    def digisign(cls):
        return cls(
            name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE,
        )

    @classmethod
    def digisign_dukcapil(cls):
        return cls(
            name=LoanDigisignFeeConst.REGISTRATION_DUKCAPIL_FEE_TYPE,
        )

    @classmethod
    def digisign_fr(cls):
        return cls(
            name=LoanDigisignFeeConst.REGISTRATION_FR_FEE_TYPE,
        )

    @classmethod
    def digisign_liveness(cls):
        return cls(
            name=LoanDigisignFeeConst.REGISTRATION_LIVENESS_FEE_TYPE,
        )


class LoanAdditionalFeeFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanAdditionalFee

    fee_type = SubFactory(LoanAdditionalFeeType)


class TransactionModelCustomerFactory(DjangoModelFactory):
    class Meta(object):
        model = TransactionModelCustomer


class LoanTransactionDetailFactory(DjangoModelFactory):
    class Meta:
        model = LoanTransactionDetail

    loan_id = -1
    detail = {}
