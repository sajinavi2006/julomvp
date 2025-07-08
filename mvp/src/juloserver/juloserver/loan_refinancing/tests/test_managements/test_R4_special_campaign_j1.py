import pytest
from datetime import datetime
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.core import management
from django.test import TestCase
from mock import patch
from django.conf import settings
from juloserver.julo.tests.factories import (
    LoanFactory,
    ApplicationFactory,
    PaymentFactory,
)
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequestCampaign,
    LoanRefinancingRequest
)
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
    CheckoutRequestFactory
)


class TestR4SpecialCampaignJ1(TestCase):
    def setUp(self):
        self.today = timezone.localtime(timezone.now())
        self.account = AccountFactory(id=1463)
        self.loan = LoanFactory(
            account=self.account
        )
        self.expired_date = datetime.strptime("2100-08-01", '%Y-%m-%d').date()
        self.loan_ref_req = LoanRefinancingRequestFactory(
            account=self.account, status="Requested", expire_in_days=10)
        self.application = ApplicationFactory(
            monthly_income=12000,
            monthly_expenses=10000,
            account=self.account
        )
        self.account_payment1 = AccountPaymentFactory(
            due_date=self.today.date() - relativedelta(days=35),
            account=self.account
        )
        self.account_payment2 = AccountPaymentFactory(
            due_date=self.today.date() - relativedelta(days=35),
            account=self.account
        )
        self.checkout = CheckoutRequestFactory(
            account_id=self.account
        )
        self.payment1 = PaymentFactory(account_payment=self.account_payment1)
        self.payment2 = PaymentFactory(account_payment=self.account_payment2)

    def test_customer_doesnt_have_active_loan(self):
        self.loan.loan_status_id = 219
        self.loan.save()
        rs = management.call_command(
            'collection_offer_R4_for_special_cohort_j1',
            file=settings.BASE_DIR +
                 '/juloserver/loan_refinancing/tests/test_managements/assets/R1R2R3R4-special-sample.csv')
        loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.filter(
            account_id=self.account.id
        ).order_by('-id').first()
        self.assertEqual(loan_ref_req_campaign.extra_data['reason'],
                         'Invalid doesnt have active loan')

    def test_loan_refinancing_request_with_invalid_request_status(self):
        self.loan.loan_status_id = 220
        self.loan.save()
        self.loan_ref_req.status = 'Approved'
        self.loan_ref_req.save()
        rs = management.call_command(
            'collection_offer_R4_for_special_cohort_j1',
            file=settings.BASE_DIR +
                 '/juloserver/loan_refinancing/tests/test_managements/assets/R1R2R3R4-special-sample.csv')
        loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.filter(
            account_id=self.account.id
        ).order_by('-id').first()
        self.assertIsNotNone(loan_ref_req_campaign)
        self.assertEqual(loan_ref_req_campaign.extra_data['reason'],
                         'Invalid loan refinancing request status')

    @pytest.mark.skip(reason="Wrong test implementation")
    @patch('juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort_j1.CovidLoanRefinancingPN')
    @patch('juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort_j1.CovidLoanRefinancingEmail')
    def test_change_on_going_refinancing_to_expired_and_checkout_to_cancel(self, mock_email, mock_pn):
        # change the ongoing refinancing request of  Email Sent, Form Viewed,
        # Offer Generated to Expired
        # also update checkout to cancel if exist with active status
        self.loan_ref_req.status = "Email Sent"
        self.loan_ref_req.save()
        rs = management.call_command(
            'collection_offer_R4_for_special_cohort_j1',
            file=settings.BASE_DIR +
                 '/juloserver/loan_refinancing/tests/test_managements/assets/R1R2R3R4-special-sample.csv')
        loan_ref_req_check = LoanRefinancingRequest.objects.get(id=self.loan_ref_req.id)
        self.checkout.refresh_from_db()
        self.assertEqual(loan_ref_req_check.expire_in_days, 0)
        self.assertEqual(loan_ref_req_check.status, 'Expired')
        self.assertEqual(self.checkout.status, 'canceled')
        mock_email().send_approved_email.assert_called_once()
        mock_pn().send_approved_pn.assert_called_once()

        # check loan refinancing request created
        loan_ref_request = LoanRefinancingRequest.objects.filter(account_id=self.account.id).order_by(
            '-id').first()
        self.assertIsNotNone(loan_ref_request)
        self.assertEqual(loan_ref_request.expire_in_days,
                         (self.expired_date-timezone.now().date()).days)
        self.assertEqual(loan_ref_request.status, "Approved")
