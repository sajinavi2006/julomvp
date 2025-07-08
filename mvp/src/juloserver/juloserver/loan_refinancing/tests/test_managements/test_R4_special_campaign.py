from datetime import datetime
from django.core import management
from django.test import TestCase
from django.utils import timezone
from mock import patch, MagicMock
# from django.test.testcases import TestCase
from juloserver.loan_refinancing.management.commands import collection_offer_R4_for_special_cohort
from django.conf import settings
from juloserver.julo.tests.factories import LoanFactory
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.loan_refinancing.models import (
    LoanRefinancingRequestCampaign, LoanRefinancingRequest, LoanRefinancingOffer, WaiverRequest)
from juloserver.julo.models import Payment, Loan
from juloserver.payback.models import WaiverTemp


class TestR4SpecialCampaign(TestCase):
    def setUp(self):
        self.loan = LoanFactory(id=3456)
        self.expired_date = datetime.strptime("2100-09-15", '%Y-%m-%d').date()

    @patch('juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort.CovidLoanRefinancingSMS')
    @patch('juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort.CovidLoanRefinancingPN')
    @patch('juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort.CovidLoanRefinancingEmail')
    def test_read_data(self, mock_email, mock_pn, mock_sms):
        # loan status not in eligible status
        self.loan.loan_status_id = 210
        self.loan.save()
        rs = management.call_command(
            'collection_offer_R4_for_special_cohort',
            file=settings.BASE_DIR +
                 '/juloserver/loan_refinancing/tests/test_managements/assets/R4-special-sample.csv')
        loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.filter(
            loan_id=self.loan.id
        ).first()
        self.assertIsNotNone(loan_ref_req_campaign)
        self.assertEqual(loan_ref_req_campaign.extra_data['reason'],
                         'Invalid loan status code 210')

        # already exist a loan refinancing request on going status
        self.loan.loan_status_id = 220
        self.loan.save()
        loan_ref_req = LoanRefinancingRequestFactory(
            loan=self.loan, status="Approved", expire_in_days=10)
        rs = management.call_command(
            'collection_offer_R4_for_special_cohort',
            file=settings.BASE_DIR +
                 '/juloserver/loan_refinancing/tests/test_managements/assets/R4-special-sample.csv')
        loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.filter(
            loan_id=self.loan.id
        ).order_by('-id').first()
        self.assertIsNotNone(loan_ref_req_campaign)
        self.assertEqual(loan_ref_req_campaign.extra_data['reason'],
                         'Invalid loan refinancing request status')
        # change the ongoing refinancing request of  Email Sent, Form Viewed,
        # Offer Generated to Expired
        loan_ref_req.status = "Email Sent"
        loan_ref_req.save()
        rs = management.call_command(
            'collection_offer_R4_for_special_cohort',
            file=settings.BASE_DIR +
                 '/juloserver/loan_refinancing/tests/test_managements/assets/R4-special-sample.csv')
        loan_ref_req_check = LoanRefinancingRequest.objects.get(id=loan_ref_req.id)
        self.assertEqual(loan_ref_req_check.expire_in_days, 0)
        mock_email().send_approved_email.assert_called_once()
        mock_sms().send_approved_sms.assert_called_once()
        mock_pn().send_approved_pn.assert_called_once()

        # check loan refinancing request created
        loan_ref_request = LoanRefinancingRequest.objects.filter(loan_id=self.loan.id).order_by(
            '-id').first()
        self.assertIsNotNone(loan_ref_request)
        self.assertEqual(loan_ref_request.product_type, "R4")
        self.assertEqual(loan_ref_request.expire_in_days,
                         (self.expired_date-timezone.now().date()).days)
        self.assertEqual(loan_ref_request.status, "Approved")

        # check loan refinancing offer created
        loan_ref_offer = LoanRefinancingOffer.objects.filter(
            loan_refinancing_request=loan_ref_request).order_by('-id').first()
        self.assertIsNotNone(loan_ref_offer)
        self.assertEqual(loan_ref_offer.product_type, "R4")
        payment = Payment.objects.filter(loan=self.loan).first()
        remaining_late_fee = payment.late_fee_amount*4
        remaining_interest = payment.installment_interest*4
        remaining_principal = payment.installment_principal*4
        total_unpaid = remaining_late_fee + remaining_interest + remaining_principal
        total_discount = remaining_late_fee + remaining_interest + remaining_principal*0.15

        self.assertEqual(loan_ref_offer.prerequisite_amount, total_unpaid-total_discount)
        self.assertEqual(loan_ref_offer.validity_in_days,
                         (self.expired_date - timezone.now().date()).days)

        # check waiver request create
        waiver_request = WaiverRequest.objects.filter(
            loan=self.loan).order_by('-id').first()
        self.assertIsNotNone(waiver_request)
        self.assertEqual(waiver_request.waiver_validity_date, self.expired_date)
        self.assertEqual(waiver_request.outstanding_amount, total_unpaid)

        # check waiver temp create
        waiver_temp = WaiverTemp.objects.filter(
            loan=self.loan).order_by('-id').first()
        self.assertIsNotNone(waiver_temp)
        self.assertEqual(waiver_temp.valid_until, self.expired_date)
        self.assertEqual(waiver_temp.need_to_pay, total_unpaid-total_discount)

    def test_loan_not_found(self):
        # loan not found
        Loan.objects.filter(id=3456).delete()
        rs = management.call_command(
            'collection_offer_R4_for_special_cohort',
            file=settings.BASE_DIR +
                 '/juloserver/loan_refinancing/tests/test_managements/assets/R4-special-sample.csv')
        loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.filter(
            loan_id=self.loan.id
        ).order_by('-id').first()
        self.assertIsNotNone(loan_ref_req_campaign)
        self.assertIsNotNone(loan_ref_req_campaign.extra_data.get('reason'))

    @patch(
        'juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort'
        '.CovidLoanRefinancingSMS')
    @patch(
        'juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort'
        '.CovidLoanRefinancingPN')
    @patch(
        'juloserver.loan_refinancing.management.commands.collection_offer_R4_for_special_cohort'
        '.CovidLoanRefinancingEmail')
    def test_error_send_comms(self, mock_send_email, mock_test_sms, mock_test_pn):
        self.loan.loan_status_id = 220
        self.loan.save()
        mock_send_email().send_approved_email.side_effect = Exception('test')
        rs = management.call_command(
            'collection_offer_R4_for_special_cohort',
            file=settings.BASE_DIR +
                 '/juloserver/loan_refinancing/tests/test_managements/assets/R4-special-sample.csv')
        loan_ref_req_campaign = LoanRefinancingRequestCampaign.objects.filter(
            loan_id=self.loan.id
        ).order_by('-id').first()
        self.assertIsNotNone(loan_ref_req_campaign)
        self.assertIsNotNone(loan_ref_req_campaign.extra_data.get('reason'))
