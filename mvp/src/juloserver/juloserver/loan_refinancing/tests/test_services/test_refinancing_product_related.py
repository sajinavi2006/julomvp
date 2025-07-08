from mock import patch, MagicMock
from django.test import TestCase
from juloserver.loan_refinancing.services.notification_related import (
    CovidLoanRefinancingEmail, CovidLoanRefinancingSMS, CovidLoanRefinancingPN)
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory, LoanRefinancingRequestCampaignFactory,
    LoanRefinancingOfferFactory)
from juloserver.loan_refinancing.constants import Campaign
from juloserver.julo.utils import display_rupiah
from babel.dates import format_date
from datetime import datetime, timedelta
from juloserver.julo.tests.factories import LoanFactory
from juloserver.loan_refinancing.services.refinancing_product_related import \
    get_covid_loan_refinancing_request


class TestGetCovidLoanRefinancingRequest(TestCase):
    def test_get_covid_loan_refinancing_request(self):
        loan = LoanFactory()
        loan_ref_req_check = LoanRefinancingRequestFactory(
            loan=loan, status='Approved')
        loan_ref_req = get_covid_loan_refinancing_request(loan)
        self.assertEqual(loan_ref_req.id, loan_ref_req_check.id)
