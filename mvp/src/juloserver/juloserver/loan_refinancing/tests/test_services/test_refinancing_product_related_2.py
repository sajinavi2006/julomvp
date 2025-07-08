from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory,
    LoanRefinancingRequestCampaignFactory,
    LoanRefinancingOfferFactory,)

from datetime import datetime

from juloserver.julo.tests.factories import LoanFactory
from juloserver.julo.tests.factories import PaymentFactory
from juloserver.julo.tests.factories import PaymentEventFactory

from juloserver.loan_refinancing.services.refinancing_product_related import (
    get_activated_covid_loan_refinancing_request,
    check_eligibility_of_covid_loan_refinancing,
    get_partially_paid_prerequisite_amount,
    generate_new_principal_and_interest_amount_based_on_covid_month_for_r3,
    get_loan_refinancing_request_r4_spcecial_campaign,
    check_loan_refinancing_request_is_r4_spcecial_campaign_by_loan)
from django.test import override_settings


class TestGetCovidLoanRefinancingRequest(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.loan_refinancing_request = LoanRefinancingRequestFactory()

    def test_get_covid_loan_refinancing_request(self):
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = 'Activated'
        self.loan_refinancing_request.save()
        res = get_activated_covid_loan_refinancing_request(self.loan)
        self.assertEqual(self.loan_refinancing_request.id, res.id)


# @override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCheckEligibilityOfCovidLoanRefinancing(TestCase):
    def setUp(self):
        self.loan_refinancing_request = LoanRefinancingRequestFactory()
        self.loan_refinancing_offer = LoanRefinancingOfferFactory()
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.payment_event = PaymentEventFactory()

    def test_check_eligibility(self):
        paid_date = timezone.localtime(timezone.now()).date() + relativedelta(days=15)
        res = check_eligibility_of_covid_loan_refinancing(self.loan_refinancing_request, paid_date)
        assert res == False
        # total paid amount not 0
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.cdate = datetime.strptime('2000-12-30', "%Y-%m-%d").replace(tzinfo=timezone.utc)
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.save()

        self.payment.loan = self.loan
        self.payment.save()

        self.payment_event.payment = self.payment
        self.payment_event.event_type = 'payment'
        self.payment_event.cdate = datetime.strptime('2001-01-01', "%Y-%m-%d").replace(tzinfo=timezone.utc)
        self.payment_event.event_date = datetime.strptime('2001-01-02', "%Y-%m-%d").replace(tzinfo=timezone.utc)
        self.payment_event.event_payment = 100
        self.payment_event.save()
        paid_date = datetime.strptime('2000-12-30', "%Y-%m-%d").date()
        res = check_eligibility_of_covid_loan_refinancing(self.loan_refinancing_request, paid_date)
        assert res == False
        self.loan_refinancing_request.prerequisite_amount = 1000
        self.loan_refinancing_request.save()
        res = check_eligibility_of_covid_loan_refinancing(self.loan_refinancing_request, paid_date)
        assert res == False


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestGetPartiallyPaidPrerequisiteAmount(TestCase):
    def setUp(self):
        self.loan_refinancing_request = LoanRefinancingRequestFactory()
        self.loan = LoanFactory()

    def test_get_partial_paid_prerequisite_amount(self):
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.product_type = 'test'
        self.loan_refinancing_request.prerequisite_amount = 100
        self.loan_refinancing_request.save()

        res = get_partially_paid_prerequisite_amount(self.loan)
        self.assertEqual(res,0)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestGenerateCovidPrincipalInterestAmountForR3(TestCase):
    def setUp(self):
        self.loan_refinancing_request = LoanRefinancingRequestFactory()
        self.loan = LoanFactory()

    def test_generate_covid_principal_interest_amount_for_r3(self):
        mock_dict = {
            'principal': 'test_principal',
            'interest': 'test_interest',
            'due': 'test_due'
        }
        res = generate_new_principal_and_interest_amount_based_on_covid_month_for_r3\
            (2,1,'test_month',mock_dict)
        assert res == (75000, 0, 0, 75000)
        # index out of range(tenure_extension)
        res = generate_new_principal_and_interest_amount_based_on_covid_month_for_r3\
            (1,2,'test_month',mock_dict)
        assert res == ('test_due', 'test_principal', 'test_interest', 0)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestGetLoanRefinancingRequestR4SpecialCampaign(TestCase):
    def setUp(self):
        self.loan_refinancing_request_campaign = LoanRefinancingRequestCampaignFactory()
        self.loan = LoanFactory()

    def test_get_loan_ref_req_r4_special_campaign(self):
        self.loan_refinancing_request_campaign.loan_id = self.loan.id
        self.loan_refinancing_request_campaign.campaign_name = 'r4_spec_feb_mar_20'
        self.loan_refinancing_request_campaign.expired_at = '2099-12-30'
        self.loan_refinancing_request_campaign.status = 'Success'
        self.loan_refinancing_request_campaign.save()
        res = get_loan_refinancing_request_r4_spcecial_campaign([self.loan.id])
        self.assertEqual(res,[self.loan_refinancing_request_campaign])


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCheckLoanRefinancingRequestR4SpecialCampaign(TestCase):
    def setUp(self):
        self.loan_refinancing_request_campaign = LoanRefinancingRequestCampaignFactory()
        self.loan = LoanFactory()

    def test_check_loan_ref_req_r4_special_campaign(self):
        self.loan_refinancing_request_campaign.loan_id = self.loan.id
        self.loan_refinancing_request_campaign.campaign_name = 'r4_spec_feb_mar_20'
        self.loan_refinancing_request_campaign.expired_at = '2099-12-30'
        self.loan_refinancing_request_campaign.status = 'Success'
        self.loan_refinancing_request_campaign.save()
        res = check_loan_refinancing_request_is_r4_spcecial_campaign_by_loan(self.loan.id)
        assert res == True
