from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch
from mock_django.query import QuerySetMock

from juloserver.julo.tests.factories import LoanFactory
from juloserver.account.tests.factories import AccountFactory
from .factories import (
    LoanRefinancingRequestFactory,
    CovidRefinancingFeatureSettingFactory,
    LoanRefinancingOfferFactory,
    CollectionOfferExtensionConfigurationFactory)
from ..services.offer_related import (
    reorder_recommendation,
    generated_default_offers,
    reorder_recommendation_by_status,
    get_proactive_offers,
    get_existing_accepted_offer
)
from ..constants import CovidRefinancingConst
from juloserver.loan_refinancing.models import LoanRefinancingRequest


class TestOfferServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.account = AccountFactory()
        cls.loan = LoanFactory(account=cls.account)
        CovidRefinancingFeatureSettingFactory()
        cls.user = cls.loan.customer.user
        application = cls.loan.application
        application.product_line_id = 10
        application.save()
        cls.application = application
        cls.loan_refinancing_request = LoanRefinancingRequestFactory(
            loan=cls.loan,
            request_date=timezone.localtime(timezone.now()).date()
        )
        cls.loan_refinancing_offer = LoanRefinancingOfferFactory()

    def setUp(self):
        CollectionOfferExtensionConfigurationFactory(
            product_type='R1',
            remaining_payment=2,
            max_extension=3,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )
        CollectionOfferExtensionConfigurationFactory(
            product_type='R1',
            remaining_payment=6,
            max_extension=4,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )
        CollectionOfferExtensionConfigurationFactory(
            product_type='R1',
            remaining_payment=4,
            max_extension=4,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )
        self.loan_refinancing_request.new_income = 5000000
        self.loan_refinancing_request.new_expense = 1000000
        self.loan_refinancing_request.save()
        self.loan.refresh_from_db()
        self.loan_refinancing_request.refresh_from_db()
        self.loan_refinancing_offer.refresh_from_db()

    def test_reorder_recommendation(self):
        LoanRefinancingOfferFactory(
            loan_refinancing_request=self.loan_refinancing_request,
            is_latest=True,
            is_proactive_offer=True,
            recommendation_order=2
        )
        LoanRefinancingOfferFactory(
            loan_refinancing_request=self.loan_refinancing_request,
            is_latest=True,
            is_proactive_offer=True,
            recommendation_order=1
        )
        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.is_proactive_offer = True
        self.loan_refinancing_offer.recommendation_order = 0
        self.loan_refinancing_offer.save()
        self.loan_refinancing_request.refresh_from_db()
        reorder_recommendation(self.loan_refinancing_request)
        self.loan_refinancing_offer.refresh_from_db()
        self.assertEqual(1, self.loan_refinancing_offer.recommendation_order)

    @patch('juloserver.loan_refinancing.services.offer_related.Payment.objects')
    def test_generated_default_offers(self, mocked_object):
        mocked_object.filter.return_value.first.return_value = self.loan.payment_set.first()

        generated_default_offers(self.loan_refinancing_request, 'R1')
        last_offer = self.loan_refinancing_request.loanrefinancingoffer_set.last()
        self.assertEqual('R1', last_offer.product_type)

    def test_reorder_recommendation_by_status(self):
        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.save()

        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.inactive
        self.loan_refinancing_request.save()
        reorder_recommendation_by_status(CovidRefinancingConst.GRAVEYARD_STATUS)
        self.assertEqual(1, self.loan_refinancing_request.loanrefinancingoffer_set.count())

    def test_get_proactive_offers(self):
        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R4'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.is_proactive_offer = True
        self.loan_refinancing_offer.recommendation_order = 1
        self.loan_refinancing_offer.prerequisite_amount = '500000'
        self.loan_refinancing_offer.save()

        new_offer = LoanRefinancingOfferFactory()
        new_offer.loan_refinancing_request = self.loan_refinancing_request
        new_offer.product_type = 'R4'
        new_offer.is_latest = True
        new_offer.is_proactive_offer = True
        new_offer.recommendation_order = 2
        new_offer.prerequisite_amount = '1000000'
        new_offer.save()
        self.assertEqual(2, get_proactive_offers(self.loan_refinancing_request).count())

    def test_get_existing_accepted_offer(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.activated

        refinancing_req_qs = LoanRefinancingRequest.objects.filter(loan=self.loan)
        existing_offers_list = get_existing_accepted_offer(refinancing_req_qs)
        self.assertIsNot(existing_offers_list, [])
