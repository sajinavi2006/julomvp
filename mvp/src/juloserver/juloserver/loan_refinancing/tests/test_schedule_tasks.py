import mock

from datetime import timedelta

from django.utils import timezone
from django.test.testcases import TestCase

from juloserver.julo.tests.factories import LoanFactory
from .factories import (
    LoanRefinancingRequestFactory,
    LoanRefinancingOfferFactory,
    LoanRefinancingRequestCampaignFactory
)
from ..services.loan_related import *

from ..constants import CovidRefinancingConst

from juloserver.loan_refinancing.tasks.schedule_tasks import (
    set_expired_refinancing_request,
    set_expired_refinancing_request_subtask,
    set_expired_refinancing_request_from_requested_status_with_campaign
)


FORM_VIEWED = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit
OFFER_GENERATED = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
EMAIL_SENT = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email

APPROVED = CovidRefinancingConst.STATUSES.approved
REQUESTED = CovidRefinancingConst.STATUSES.requested
REJECTED = CovidRefinancingConst.STATUSES.rejected
ACTIVATED = CovidRefinancingConst.STATUSES.activated
EXPIRED = CovidRefinancingConst.STATUSES.expired
PROPOSED = CovidRefinancingConst.STATUSES.proposed
INACTIVE = CovidRefinancingConst.STATUSES.inactive
OFFER_SELECTED = CovidRefinancingConst.STATUSES.offer_selected


class TestScheduleTasks(TestCase):

    def setUp(self):
        self.loan = LoanFactory()
        self.user = self.loan.customer.user
        self.application = self.loan.application
        self.loan_refinancing_request = LoanRefinancingRequestFactory(loan=self.loan)
        self.loan_refinancing_offer = LoanRefinancingOfferFactory(
            loan_refinancing_request=self.loan_refinancing_request,
            is_accepted=True
        )
        self.loan_refinancing_request_campaign = LoanRefinancingRequestCampaignFactory(
            loan_refinancing_request=self.loan_refinancing_request
        )
        patcher = mock.patch('juloserver.loan_refinancing.tasks.schedule_tasks.set_expired_refinancing_request_subtask')
        self.mock_set_expired_refinancing_request_subtask = patcher.start()
        self.mock_set_expired_refinancing_request_subtask.delay.side_effect = set_expired_refinancing_request_subtask
        self.addCleanup(patcher.stop)

    def test_set_expired_refinancing_request_no_data(self):
        set_expired_refinancing_request()
        self.mock_set_expired_refinancing_request_subtask.assert_not_called()


    def test_set_expired_refinancing_request_id_not_found(self):
        re = set_expired_refinancing_request_subtask(999)
        assert re == False


    def test_set_expired_refinancing_request_check_status(self):
        r1 = LoanRefinancingRequestFactory(loan=self.loan, status=FORM_VIEWED)
        r2 = LoanRefinancingRequestFactory(loan=self.loan, status=OFFER_GENERATED)
        r3 = LoanRefinancingRequestFactory(loan=self.loan, status=APPROVED)
        r4 = LoanRefinancingRequestFactory(loan=self.loan, status=EMAIL_SENT)
        r5 = LoanRefinancingRequestFactory(loan=self.loan, status=REQUESTED)
        r6 = LoanRefinancingRequestFactory(loan=self.loan, status=REJECTED)
        r7 = LoanRefinancingRequestFactory(loan=self.loan, status=ACTIVATED)
        r8 = LoanRefinancingRequestFactory(loan=self.loan, status=EXPIRED)
        r9 = LoanRefinancingRequestFactory(loan=self.loan, status=PROPOSED)
        r10 = LoanRefinancingRequestFactory(loan=self.loan, status=INACTIVE)
        r11 = LoanRefinancingRequestFactory(loan=self.loan, status=OFFER_SELECTED)
        self.mock_set_expired_refinancing_request_subtask.delay.side_effect = mock.MagicMock()
        set_expired_refinancing_request()
        self.mock_set_expired_refinancing_request_subtask.assert_has_calls([
            mock.call.delay(r1.pk),
            mock.call.delay(r2.pk),
            mock.call.delay(r3.pk),
            mock.call.delay(r4.pk),
            mock.call.delay(r11.pk)], any_order=True)

    @mock.patch('juloserver.loan_refinancing.services.loan_related.expire_loan_refinancing_request')
    def test_set_expired_refinancing_request_with_form_viewed_status_not_expired(self, mock_expire_loan_refinancing_request):
        self.loan_refinancing_request.status = FORM_VIEWED
        request_date = timezone.localtime(timezone.now()-timedelta(days=5)).date()
        self.loan_refinancing_request.request_date = request_date
        self.loan_refinancing_request.expire_in_days = 1
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request()
        mock_expire_loan_refinancing_request.assert_not_called()

    def test_set_expired_refinancing_request_with_form_viewed_status_expired(self):
        self.loan_refinancing_request.status = FORM_VIEWED
        request_date = timezone.localtime(timezone.now()-timedelta(days=35)).date()
        self.loan_refinancing_request.request_date = request_date
        self.loan_refinancing_request.expire_in_days = 1
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request()
        self.loan_refinancing_request.refresh_from_db()
        assert self.loan_refinancing_request.status == EXPIRED

    @mock.patch('juloserver.loan_refinancing.services.loan_related.expire_loan_refinancing_request')
    def test_set_expired_refinancing_request_with_email_sent_status_not_expired(self, mock_expire_loan_refinancing_request):
        self.loan_refinancing_request.status = EMAIL_SENT
        request_date = timezone.localtime(timezone.now()-timedelta(days=30)).date()
        self.loan_refinancing_request.request_date = request_date
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request()
        mock_expire_loan_refinancing_request.assert_not_called()

    def test_set_expired_refinancing_request_with_email_sent_status_expired(self):
        self.loan_refinancing_request.status = EMAIL_SENT
        request_date = timezone.localtime(timezone.now()-timedelta(days=35)).date()
        self.loan_refinancing_request.request_date = request_date
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request()
        self.loan_refinancing_request.refresh_from_db()
        assert self.loan_refinancing_request.status == EXPIRED

    @mock.patch('juloserver.loan_refinancing.services.loan_related.expire_loan_refinancing_request')
    def test_set_expired_refinancing_request_with_offer_generated_status_not_expired(self, mock_expire_loan_refinancing_request):
        self.loan_refinancing_request.status = OFFER_GENERATED
        self.loan_refinancing_request.form_submitted_ts = timezone.localtime(timezone.now()-timedelta(days=10))
        self.loan_refinancing_request.expire_in_days = 1
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request()
        mock_expire_loan_refinancing_request.assert_not_called()

    def test_set_expired_refinancing_request_with_offer_generated_status_expired(self):
        self.loan_refinancing_request.status = OFFER_GENERATED
        self.loan_refinancing_request.form_submitted_ts = timezone.localtime(timezone.now()-timedelta(days=11))
        self.loan_refinancing_request.expire_in_days = 1
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request()
        self.loan_refinancing_request.refresh_from_db()
        assert self.loan_refinancing_request.status == EXPIRED

    @mock.patch('juloserver.loan_refinancing.services.loan_related.expire_loan_refinancing_request')
    def test_set_expired_refinancing_request_with_approved_status_not_expired(self, mock_expire_loan_refinancing_request):
        self.loan_refinancing_request.status = APPROVED
        self.loan_refinancing_offer.offer_accepted_ts = timezone.localtime(timezone.now()-timedelta(days=10))
        self.loan_refinancing_request.expire_in_days = 10
        self.loan_refinancing_offer.save()
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request()
        mock_expire_loan_refinancing_request.assert_not_called()

    def test_set_expired_refinancing_request_with_approved_status_expired(self):
        self.loan_refinancing_request.status = APPROVED
        self.loan_refinancing_offer.offer_accepted_ts = timezone.localtime(timezone.now()-timedelta(days=11))
        self.loan_refinancing_request.expire_in_days = 10
        self.loan_refinancing_request.save()
        self.loan_refinancing_offer.save()
        re = set_expired_refinancing_request()
        self.loan_refinancing_request.refresh_from_db()
        assert self.loan_refinancing_offer.is_accepted == True
        assert self.loan_refinancing_request.status == EXPIRED

    @mock.patch('juloserver.loan_refinancing.services.loan_related.expire_loan_refinancing_request')
    def test_set_expired_refinancing_request_with_offer_selected_status_not_expired(self, mock_expire_loan_refinancing_request):
        self.loan_refinancing_request.status = OFFER_SELECTED
        self.loan_refinancing_offer.offer_accepted_ts = timezone.localtime(timezone.now()-timedelta(days=10))
        self.loan_refinancing_request.expire_in_days = 10
        self.loan_refinancing_offer.save()
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request()
        mock_expire_loan_refinancing_request.assert_not_called()

    def test_set_expired_refinancing_request_with_offer_selected_status_expired(self):
        self.loan_refinancing_request.status = OFFER_SELECTED
        self.loan_refinancing_offer.offer_accepted_ts = timezone.localtime(timezone.now()-timedelta(days=11))
        self.loan_refinancing_request.expire_in_days = 10
        self.loan_refinancing_request.save()
        self.loan_refinancing_offer.save()
        re = set_expired_refinancing_request()
        self.loan_refinancing_request.refresh_from_db()
        assert self.loan_refinancing_offer.is_accepted == True
        assert self.loan_refinancing_request.status == EXPIRED

    def test_set_expired_refinancing_request_from_requested_status_with_campaign(self):
        self.loan_refinancing_request_campaign.expired_at = timezone.localtime(timezone.now()-timedelta(days=5)).date()
        self.loan_refinancing_request.status = REQUESTED
        self.loan_refinancing_request_campaign.save()
        self.loan_refinancing_request.save()
        re = set_expired_refinancing_request_from_requested_status_with_campaign()
        self.loan_refinancing_request.refresh_from_db()
        assert self.loan_refinancing_request.status == EXPIRED
