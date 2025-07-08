from datetime import timedelta

from django.utils import timezone
from factory import (
    DjangoModelFactory,
    SubFactory,
    LazyAttribute,
)

from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.models import FeatureSetting
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationJ1Factory,
)
from juloserver.promo.constants import (
    PromoCodeTypeConst,
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoPageConst, FeatureNameConst,
)
from juloserver.promo.models import (
    CriteriaControlList,
    PromoCode,
    PromoHistory,
    PromoPage,
    WaivePromo,
    PromoCodeBenefit,
    PromoCodeCriteria,
    PromoCodeUsage,
    PromoCodeAgentMapping,
)


class PromoCodeBenefitFactory(DjangoModelFactory):
    class Meta:
        model = PromoCodeBenefit

    name = 'benefit test name'
    type = PromoCodeBenefitConst.FIXED_CASHBACK
    value = {"amount": 100000}


class PromoCodeCriteriaFactory(DjangoModelFactory):
    class Meta:
        model = PromoCodeCriteria

    name = 'criteria test name'
    type = PromoCodeCriteriaConst.LIMIT_PER_CUSTOMER
    value = {"limit": 1}


class PromoCodeFactory(DjangoModelFactory):
    class Meta(object):
        model = PromoCode

    promo_name = 'test_promo_code'
    promo_code = 'test_promo_code'
    partner = ['All']
    product_line = ['All']
    credit_score = ['All']
    is_active = True
    is_public = False
    promo_benefit = 'cashback'
    cashback_amount = 100000
    start_date = timezone.now()
    end_date = timezone.now() + timedelta(days=30)
    type = PromoCodeTypeConst.APPLICATION
    promo_code_usage_count = 0


class PromoCodeLoanFactory(PromoCodeFactory):
    type = PromoCodeTypeConst.LOAN
    promo_code_benefit = SubFactory(PromoCodeBenefitFactory)


class PromoHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = PromoHistory

    customer = SubFactory(CustomerFactory)


class WaivePromoFactory(DjangoModelFactory):
    class Meta(object):
        model = WaivePromo


class PromoCodeUsageFactory(DjangoModelFactory):
    class Meta(object):
        model = PromoCodeUsage

    promo_code = SubFactory(PromoCodeFactory)
    customer_id = LazyAttribute(lambda o: CustomerFactory().id)
    loan_id = LazyAttribute(lambda o: PromoCodeLoanFactory().id)
    application_id = LazyAttribute(lambda o: ApplicationJ1Factory().id)


class PromoPageFactory(DjangoModelFactory):
    class Meta(object):
        model = PromoPage


    @classmethod
    def tnc_cashback(cls):
        return cls(
            title=PromoPageConst.TNC_CASHBACK,
            content="My life is brilliant, my love is {start_date}"
        )

    @classmethod
    def tnc_installment_discount(cls):
        return cls(
            title=PromoPageConst.TNC_INSTALLMENT_DISCOUNT,
            content="I saw an {end_date}, Of that I'm sure."
        )


class PromoCodeAgentMappingFactory(DjangoModelFactory):
    class Meta(object):
        model = PromoCodeAgentMapping

    promo_code = SubFactory(PromoCodeFactory)
    agent_id = LazyAttribute(lambda o: AgentFactory().id)


class PromoEntryPageFeatureSetting(DjangoModelFactory):
    class Meta(object):
        model = FeatureSetting

    feature_name = FeatureNameConst.PROMO_ENTRY_PAGE
    is_active = True


class CriteriaControlListFactory(DjangoModelFactory):
    class Meta:
        model = CriteriaControlList

    customer_id = LazyAttribute(lambda o: CustomerFactory().id)
    promo_code_criteria = SubFactory(PromoCodeCriteriaFactory)
    is_deleted = False
