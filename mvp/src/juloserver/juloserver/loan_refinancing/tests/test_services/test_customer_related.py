from datetime import datetime, timedelta

from django.utils import timezone
from mock import patch, MagicMock
from django.test import TestCase

from juloserver.loan_refinancing.services.customer_related import get_refinancing_status_display
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory, LoanRefinancingRequestCampaignFactory,
    LoanRefinancingOfferFactory)
from juloserver.loan_refinancing.constants import Campaign, CovidRefinancingConst
from juloserver.julo.utils import display_rupiah
from babel.dates import format_date


class TestCustomerRelatedService(TestCase):
    def setUp(self):
        self.loan_ref_req = LoanRefinancingRequestFactory(product_type="R4")

    def test_get_refinancing_status_display(self):
        self.loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
        self.loan_ref_req.save()

        result = get_refinancing_status_display(self.loan_ref_req)
        self.assertEqual(result, 'Proactive Email Sent')

        self.loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit
        self.loan_ref_req.save()

        result = get_refinancing_status_display(self.loan_ref_req)
        self.assertEqual(result, 'Proactive Form Viewed')

        self.loan_ref_req.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
        self.loan_ref_req.save()

        result = get_refinancing_status_display(self.loan_ref_req)
        self.assertEqual(result, 'Offer Generated')

        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_ref_req.form_submitted_ts = datetime.now()
        status_date_str = self.loan_ref_req.get_status_ts().strftime('%d-%m-%Y')
        self.loan_ref_req.save()

        result = get_refinancing_status_display(self.loan_ref_req)
        self.assertEqual(
            result,
            "%s Offer Selected, %s" % (self.loan_ref_req.product_type.upper(), status_date_str),
        )

        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.approved
        status_date_str = self.loan_ref_req.get_status_ts().strftime('%d-%m-%Y')
        self.loan_ref_req.save()

        result = get_refinancing_status_display(self.loan_ref_req)
        self.assertEqual(
            result,
            "%s Offer Approved, %s" % (self.loan_ref_req.product_type.upper(), status_date_str),
        )

        self.loan_ref_req.status = CovidRefinancingConst.STATUSES.activated
        self.loan_ref_req.offer_activated_ts = datetime.now() + timedelta(days=1)
        status_date_str = self.loan_ref_req.get_status_ts().strftime('%d-%m-%Y')
        self.loan_ref_req.save()

        result = get_refinancing_status_display(self.loan_ref_req)
        self.assertEqual(
            result,
            "%s Offer Activated, %s" % (self.loan_ref_req.product_type.upper(), status_date_str),
        )
