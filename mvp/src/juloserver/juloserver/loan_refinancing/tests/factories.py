from builtins import range
from builtins import object
from factory.django import DjangoModelFactory
from faker import Faker
from factory import SubFactory
from factory import LazyAttribute
from factory import post_generation
from django.utils import timezone

from juloserver.apiv2.models import LoanRefinancingScore
from juloserver.julo.models import Loan, FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import LoanFactory, ApplicationFactory, PaymentFactory
from ..constants import LoanRefinancingStatus
from ..models import (
    LoanRefinancingMainReason,
    LoanRefinancingSubReason,
    LoanRefinancing,
    LoanRefinancingRequest,
    LoanRefinancingOffer,
    WaiverRequest,
    CollectionOfferExtensionConfiguration,
    WaiverRecommendation, WaiverPaymentRequest, WaiverApproval, WaiverPaymentApproval,
    LoanRefinancingRequestCampaign)

fake = Faker()


class LoanRefinancingSubReasonFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanRefinancingSubReason

    reason = LazyAttribute(lambda o: fake.name())
    loan_refinancing_main_reason = LazyAttribute(
        lambda o: fake.random.choice(LoanRefinancingMainReason.objects.all())
    )
    is_active = True


class LoanRefinancingMainReasonFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanRefinancingMainReason

    reason = LazyAttribute(lambda o: fake.name())
    is_active = True

    @post_generation
    def create_sub_reasons(self, create, extracted, **kwargs):
        for i in range(1, 5):
            LoanRefinancingSubReasonFactory.create(
                loan_refinancing_main_reason=self)


class LoanRefinancingFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanRefinancing

    loan = SubFactory(LoanFactory)
    original_tenure = 4
    tenure_extension = 6
    new_installment = 1000000
    refinancing_request_date = LazyAttribute(lambda o: fake.date_of_birth())
    refinancing_active_date = LazyAttribute(lambda o: fake.date_of_birth())
    status = LoanRefinancingStatus.REQUEST
    total_latefee_discount = 100000
    loan_level_dpd = 60
    additional_reason = 'placeholder_reason'
    loan_refinancing_main_reason = SubFactory(LoanRefinancingMainReasonFactory)
    loan_refinancing_sub_reason = SubFactory(LoanRefinancingSubReasonFactory)


class CovidRefinancingFeatureSettingFactory(DjangoModelFactory):
    class Meta(object):
        model = FeatureSetting

    feature_name = FeatureNameConst.COVID_REFINANCING
    is_active = True
    parameters = {
        'email_expire_in_days': 10,
        'tenure_extension_rule': {'MTL_3': 2, 'MTL_4': 2, 'MTL_5': 3, 'MTL_6': 3}
    }


class LoanRefinancingRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanRefinancingRequest
    loan = SubFactory(LoanFactory)


class LoanRefinancingOfferFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanRefinancingOffer
    loan_refinancing_request = SubFactory(LoanRefinancingRequestFactory)
    prerequisite_amount = 10000


class WaiverRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverRequest
    loan = SubFactory(LoanFactory)
    agent_name = "agent1"
    program_name = "r5"
    is_covid_risky = True
    outstanding_amount = 100000
    requested_waiver_amount = 50000
    ptp_amount = 50000


class WaiverPaymentRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverPaymentRequest

    waiver_request = SubFactory(WaiverRequestFactory)
    payment = SubFactory(PaymentFactory)
    outstanding_late_fee_amount = 100000
    outstanding_interest_amount = 200000
    outstanding_principal_amount = 2000000
    total_outstanding_amount = 2300000
    requested_late_fee_waiver_amount = 100000
    requested_interest_waiver_amount = 200000
    requested_principal_waiver_amount = 0
    total_requested_waiver_amount = 300000
    remaining_late_fee_amount = 100000
    remaining_interest_amount = 200000
    remaining_principal_amount = 2000000
    total_remaining_amount = 2300000
    is_paid_off_after_ptp = True


class CollectionOfferExtensionConfigurationFactory(DjangoModelFactory):
    class Meta(object):
        model = CollectionOfferExtensionConfiguration

    product_type = 'R1'
    remaining_payment = 1
    max_extension = 2
    date_start = timezone.localtime(timezone.now()).date()
    date_end = timezone.localtime(timezone.now()).date()


class WaiverRecommendationFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverRecommendation

    bucket_name = "current"
    program_name = "R1"
    is_covid_risky = False
    partner_product = "normal"
    late_fee_waiver_percentage = 20
    interest_waiver_percentage = 20
    principal_waiver_percentage = 20


class LoanRefinancingScoreFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanRefinancingScore

    application_id = 1
    loan = SubFactory(LoanFactory)
    rem_installment = 0
    ability_score = 1
    willingness_score = 2.2
    is_covid_risky = False
    bucket = 'current'
    oldest_payment_num = 0


class WaiverApprovalFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverApproval

    approved_program = "R6"
    paid_ptp_amount = 6000000
    decision = 'Approved'
    approved_interest_waiver_percentage = 70
    approved_late_fee_waiver_percentage = 60
    approved_remaining_amount = 1500000
    waiver_request = SubFactory(WaiverRequestFactory)
    approved_waiver_amount = 3000000
    approved_waiver_validity_date = "2020-08-10"
    approved_principal_waiver_percentage = 80
    decision_ts = timezone.now().date()


class WaiverPaymentApprovalFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverPaymentApproval

    waiver_approval = SubFactory(WaiverRequest)
    approved_late_fee_waiver_amount = 80000
    approved_interest_waiver_amount = 70000
    approved_principal_waiver_amount = 45646
    remaining_principal_amount = 335960
    remaining_interest_amount = 357956
    remaining_late_fee_amount = 4487686
    total_approved_waiver_amount = 4540676
    total_remaining_amount = 536547
    payment = SubFactory(PaymentFactory)
    outstanding_principal_amount = 8372652
    total_outstanding_amount = 904850934
    outstanding_late_fee_amount = 34546
    outstanding_interest_amount = 2354765


class LoanRefinancingRequestCampaignFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanRefinancingRequestCampaign

    loan_refinancing_request = SubFactory(LoanRefinancingRequestFactory)
    loan_id = 0
