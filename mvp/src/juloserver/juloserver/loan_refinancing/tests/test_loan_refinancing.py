import mock
from datetime import timedelta
import json
from django.db.models import Sum
from rest_framework import status
import mock
from django.utils import timezone
from django.test.testcases import TestCase, override_settings

from juloserver.julo.services2 import encrypt
from juloserver.julo.tests.factories import (
    LoanFactory,
    PaymentFactory,
    PaymentMethodFactory,
    AuthUserFactory,
    CustomerFactory)
from juloserver.account.tests.factories import AccountFactory
from .factories import (
    LoanRefinancingRequestFactory,
    CovidRefinancingFeatureSettingFactory,
    LoanRefinancingOfferFactory,
    WaiverRequestFactory,
    WaiverRecommendationFactory,
    CollectionOfferExtensionConfigurationFactory)
from ..constants import CovidRefinancingConst
from ..models import (CollectionOfferExtensionConfiguration,
                      LoanRefinancingMainReason,
                      LoanRefinancingOffer)
from ..management.commands import retroload_recommendation_order, bulk_create_waiver_recommendation
from ..services.comms_channels import send_loan_refinancing_request_offer_selected_notification
from ..services.loan_related import get_r2_payment_structure, get_r3_payment_structure
from ..services.offer_related import generated_default_offers
from ..services.refinancing_product_related import (generate_unique_uuid,
                                                    get_max_tenure_extension_r1,
                                                    proactive_offer_generation,
                                                    get_waiver_recommendation)
from ..services.notification_related import CovidLoanRefinancingEmail
from ..utils import generate_status_and_tips_loan_refinancing_status
from ..views import covid_approval
from juloserver.loan_refinancing.services.refinancing_product_related import (
            CovidLoanRefinancing,
        )
from juloserver.loan_refinancing.services.loan_related2 import get_not_allowed_products
from juloserver.loan_refinancing.models import LoanRefinancingRequest, WaiverRecommendation
from ...apiv2.models import LoanRefinancingScore


class TestLoanRefinancingWithoutSetUp(TestCase):
    def test_retroload_waiver_recommendation(self):
        bulk_create_waiver_recommendation.Command().handle()
        all_waiver_recommendation = WaiverRecommendation.objects.count()
        self.assertEqual(144, all_waiver_recommendation)

        bulk_create_waiver_recommendation.Command().handle()
        all_waiver_recommendation = WaiverRecommendation.objects.count()
        self.assertEqual(144, all_waiver_recommendation)


@override_settings(SUSPEND_SIGNALS=True)
class TestLoanRefinancing(TestCase):
    @classmethod
    def setUpTestData(cls):
        encrypter = encrypt()
        cls.uuid = generate_unique_uuid()
        cls.today = timezone.localtime(timezone.now())
        cls.encrypted_uuid = encrypter.encode_string(cls.uuid)
        cls.account = AccountFactory()
        cls.loan = LoanFactory(account=cls.account)
        CovidRefinancingFeatureSettingFactory()
        cls.user = cls.loan.customer.user
        application = cls.loan.application
        application.product_line_id = 10
        application.save()
        cls.application = application
        cls.loan_refinancing_request = LoanRefinancingRequestFactory(
            loan=cls.loan, request_date=cls.today.date(), uuid=cls.uuid)
        cls.loan_refinancing_offer = LoanRefinancingOfferFactory()
        cls.loan_refinancing_request.save()
        PaymentMethodFactory(loan=cls.loan, customer=cls.application.customer)
        cls.waiver_recommendation = WaiverRecommendationFactory()

    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.extension_configuration = CollectionOfferExtensionConfigurationFactory()

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
        CollectionOfferExtensionConfigurationFactory(
            product_type='R1',
            remaining_payment=5,
            max_extension=4,
            date_start=timezone.localtime(timezone.now()).date(),
            date_end=timezone.localtime(timezone.now()).date(),
        )
        WaiverRecommendationFactory(
            bucket_name="Current",
            program_name="R4",
            is_covid_risky=True,
            partner_product="normal",
            late_fee_waiver_percentage=20,
            interest_waiver_percentage=20,
            principal_waiver_percentage=20,
        )
        self.loan_refinancing_request.new_income = 5000000
        self.loan_refinancing_request.new_expense = 1000000
        self.loan_refinancing_request.save()

        self.loan.refresh_from_db()
        self.loan_refinancing_request.refresh_from_db()
        self.loan_refinancing_offer.refresh_from_db()

    def test_retroload_recommendation_order(self):
        retroload_recommendation_order.Command().handle()
        self.loan_refinancing_request.refresh_from_db()
        self.assertEqual(0, self.loan_refinancing_request.loanrefinancingoffer_set.count())

    def test_approval_offer_generated(self):
        proposed_offer = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
        self.loan_refinancing_request.status = proposed_offer
        self.loan_refinancing_request.form_submitted_ts = timezone.localtime(timezone.now())
        self.loan_refinancing_request.save()

        url = '/api/loan_refinancing/v1/covid_approval/{}/'.format(self.encrypted_uuid)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R1'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.recommendation_order = 1
        self.loan_refinancing_offer.prerequisite_amount = '500000'
        self.loan_refinancing_offer.save()

        new_offer = LoanRefinancingOfferFactory()
        new_offer.loan_refinancing_request = self.loan_refinancing_request
        new_offer.product_type = 'R1'
        new_offer.is_latest = True
        new_offer.recommendation_order = 2
        new_offer.prerequisite_amount = '1000000'
        new_offer.loan_duration = 1
        new_offer.save()

        payment = PaymentFactory(loan=self.loan_refinancing_request.loan)
        payment.due_date = timezone.localtime(timezone.now()) - timedelta(days=10)
        payment.payment_number = 1
        payment.save()

        url = '/api/loan_refinancing/v1/covid_approval/{}/'.format(self.encrypted_uuid)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        new_offer.recommendation_order = None
        new_offer.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.loan_refinancing_offer.recommendation_order = None
        self.loan_refinancing_offer.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.loan_refinancing_offer.product_type = 'R1'
        self.loan_refinancing_offer.recommendation_order = 1
        self.loan_refinancing_offer.save()

        new_offer.recommendation_order = 2
        new_offer.save()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_approval_email_sent(self):
        proposed_email = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
        proposed_submit = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit
        self.loan_refinancing_request.status = proposed_email
        self.loan_refinancing_request.save()

        url = '/api/loan_refinancing/v1/covid_approval/{}/'.format(self.encrypted_uuid)
        response = self.client.get(url)
        self.loan_refinancing_request.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.loan_refinancing_request.status, 'Email Sent')

    @mock.patch('juloserver.loan_refinancing.services.comms_channels.send_sms_covid_refinancing_approved')
    @mock.patch('juloserver.loan_refinancing.services.comms_channels.send_email_covid_refinancing_approved')
    def test_ajax_submit_waiver_request(self, mock_send_email, mock_sms):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_generated
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R5'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.save()

        payment = PaymentFactory(loan=self.loan_refinancing_request.loan)
        payment.due_date = timezone.localtime(timezone.now()) - timedelta(days=10)
        payment.payment_number = 1
        payment.save()

        url = '/api/loan_refinancing/v1/ajax_covid_refinancing_submit_waiver_request/'
        data = dict(
            loan_id=self.loan_refinancing_request.loan.id,
            is_covid_risky=True,
            selected_program_name='R5',
            waiver_validity_date=self.today.date() + timedelta(days=2),
            bucket_name='Bucket 2',
            reason='Bekerja gaji minim',
            ptp_amount=1000000,
            outstanding_amount=1200000,
            unpaid_principal=500000,
            unpaid_interest=500000,
            unpaid_late_fee=200000,
            unpaid_payment_count=1,
            last_unpaid_payment_number=1,
            late_fee_waiver_percentage=100,
            late_fee_waiver_amount=200000,
            interest_fee_waiver_percentage=0,
            interest_fee_waiver_amount=0,
            principal_waiver_percentage=0,
            principal_waiver_amount=0,
            recommended_unpaid_waiver_percentage=100,
            calculated_unpaid_waiver_percentage=200000,
            is_automated=True,
            new_income=1000000,
            new_expense=800000,
            comms_channels="Email,SMS",
            is_customer_confirmed=False,
            partner_product="normal",
            waiver_recommendation_id=self.waiver_recommendation.id,
            requested_late_fee_waiver_percentage="10",
            requested_interest_waiver_percentage="10",
            requested_principal_waiver_percentage="10",
            requested_late_fee_waiver_amount=200000,
            requested_interest_waiver_amount=200000,
            requested_principal_waiver_amount=200000,
            agent_notes="dummy data",
            first_waived_payment=payment.id,
            last_waived_payment=payment.id,
            outstanding_late_fee_amount=300000,
            outstanding_interest_amount=300000,
            outstanding_principal_amount=300000,
            selected_payments_waived=json.dumps({
                "outstanding": [
                    {
                        "due_date": "9 Oktober 2017",
                        "principal": 1125000,
                        "interest": 0,
                        "late_fee": 0,
                        "need_to_pay": 1125000,
                        "payment_number": payment.payment_number,
                        "payment_id": payment.id
                    },
                ],
                "waiver": [
                    {
                        "due_date": "9 Oktober 2017",
                        "principal": 125000,
                        "interest": 200000,
                        "late_fee": 217500,
                        "total_waiver": 542500,
                        "payment_number": payment.payment_number,
                        "payment_id": payment.id
                    },
                ],
                "remaining": [
                    {
                        "payment_id": payment.id,
                        "payment_number": payment.payment_number,
                        "principal": 0,
                        "interest": 0,
                        "late_fee": 0,
                        "remaining_installment": 0,
                        "paid_off_status": "Y"
                    },
                ]
            }),
            waived_payment_count=1,
            remaining_amount_for_waived_payment=900000,
            requested_waiver_amount=600000,
            is_multiple_ptp_payment=False,
            number_of_multiple_ptp_payment=0,
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data['is_customer_confirmed'] = True
        data['selected_program_name'] = 'R5'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data['selected_program_name'] = 'R4'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.loan_refinancing_request.uuid = None
        self.loan_refinancing_request.save()
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.loan_refinancing.views.send_pn_covid_refinancing_offer_selected')
    @mock.patch('juloserver.loan_refinancing.views.send_sms_covid_refinancing_offer_selected')
    @mock.patch('juloserver.loan_refinancing.views.send_email_refinancing_offer_selected')
    def test_ajax_submit_refinancing_request(
        self,
        mock_send_email_refinancing_offer_selected,
        mock_send_sms_covid_refinancing_offer_selected,
        mock_send_pn_covid_refinancing_offer_selected):
        self.loan.loan_status_id = 220
        self.loan.save()

        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_generated
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R1'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.save()

        payment1 = PaymentFactory(loan=self.loan)
        payment1.due_date = timezone.localtime(timezone.now()) - timedelta(days=10)
        payment1.payment_number = 1
        payment1.payment_status_id = 310
        payment1.save()

        payment2 = PaymentFactory(loan=self.loan)
        payment2.due_date = timezone.localtime(timezone.now()) - timedelta(days=5)
        payment2.payment_number = 2
        payment2.payment_status_id = 310
        payment2.save()

        url = '/api/loan_refinancing/v1/ajax_covid_refinancing_submit_refinancing_request/'
        data = dict(
            loan_id=self.loan.id,
            selected_product='R1',
            tenure_extension=1,
            new_employment_status='Bekerja gaji minim',
            new_income=3000000,
            new_expense=800000,
            comms_channels="Email,SMS",
            is_customer_confirmed=False,
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data['is_customer_confirmed'] = True
        data['selected_product'] = 'R1'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data['selected_product'] = 'R2'
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.loan_refinancing_request.uuid = None
        self.loan_refinancing_request.save()
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_construct_email_params(self):
        CovidLoanRefinancingEmail(self.loan_refinancing_request)\
            ._construct_email_params(None, is_need_va=True)

    def test_approve_covid(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.product_type = 'R5'
        self.loan_refinancing_request.save()
        self.waiver_request = WaiverRequestFactory()
        self.waiver_request.loan = self.loan_refinancing_request.loan
        self.waiver_request.cdate = timezone.now() - timedelta(days=1)
        self.waiver_request.save()
        response = covid_approval(None, self.encrypted_uuid)
        self.assertIsNotNone(response)

    def test_activate_loan_refinancing_for_r1(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.product_type = 'R1'
        self.loan_refinancing_request.save()
        payment = self.loan.payment_set.last()
        refinancing_class = CovidLoanRefinancing(
            payment, self.loan_refinancing_request)
        refinancing_class.activate()
        self.loan_refinancing_request.refresh_from_db()
        self.assertEqual(self.loan_refinancing_request.status, CovidRefinancingConst.STATUSES.activated)

    @mock.patch(
        'juloserver.loan_refinancing.services.refinancing_product_related.get_sum_of_principal_paid_and_late_fee_amount')
    def test_activate_loan_refinancing_for_r2(self, mocked_func):
        mocked_func.return_value = {
            'paid_interest__sum': 0, 'installment_interest__sum': 500000,
            'late_fee_amount__sum': 275000, 'paid_principal__sum': 0,
            'installment_principal__sum': 14500000}

        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.product_type = 'R2'
        self.loan_refinancing_request.save()
        payment = self.loan.payment_set.last()
        refinancing_class = CovidLoanRefinancing(
            payment, self.loan_refinancing_request)
        refinancing_class.activate()
        self.loan_refinancing_request.refresh_from_db()
        self.assertEqual(self.loan_refinancing_request.status, CovidRefinancingConst.STATUSES.activated)

    @mock.patch(
        'juloserver.loan_refinancing.services.refinancing_product_related.get_sum_of_principal_paid_and_late_fee_amount')
    def test_activate_loan_refinancing_for_r3(self, mocked_func):
        mocked_func.return_value = {
            'paid_interest__sum': 0, 'installment_interest__sum': 500000,
            'late_fee_amount__sum': 275000, 'paid_principal__sum': 0,
            'installment_principal__sum': 14500000}

        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.product_type = 'R3'
        self.loan_refinancing_request.save()
        payment = self.loan.payment_set.last()
        refinancing_class = CovidLoanRefinancing(
            payment, self.loan_refinancing_request)
        refinancing_class.activate()
        self.loan_refinancing_request.refresh_from_db()
        self.assertEqual(self.loan_refinancing_request.status, CovidRefinancingConst.STATUSES.activated)

    def test_get_not_allowed_products_for_r1(self):
        from juloserver.loan_refinancing.services.loan_related2 import get_not_allowed_products
        from juloserver.loan_refinancing.models import LoanRefinancingRequest

        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.product_type = 'R1'
        self.loan_refinancing_request.save()
        loan_refinancing_request_qs = LoanRefinancingRequest.objects.filter(loan_id=self.loan)
        not_allowed_products = get_not_allowed_products(loan_refinancing_request_qs)
        self.assertIn(not_allowed_products, ['R1'])

    def test_get_not_allowed_products_for_r1(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.activated
        self.loan_refinancing_request.product_type = 'R1'
        self.loan_refinancing_request.save()
        loan_refinancing_request_qs = LoanRefinancingRequest.objects.filter(loan_id=self.loan)
        not_allowed_products = get_not_allowed_products(loan_refinancing_request_qs)
        self.assertIn('R1', not_allowed_products)

    @mock.patch('juloserver.loan_refinancing.services.loan_related2.MultipleRefinancingLimitConst.R2_R3', 1)
    def test_get_not_allowed_products_for_r2_r3(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.activated
        self.loan_refinancing_request.product_type = 'R2'
        self.loan_refinancing_request.save()
        loan_refinancing_request_qs = LoanRefinancingRequest.objects.filter(loan_id=self.loan)
        not_allowed_products = get_not_allowed_products(loan_refinancing_request_qs)
        self.assertIn('R2', not_allowed_products)
        self.assertIn('R3', not_allowed_products)

    def test_ajax_check_refinancing_request_status_offer_selected(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.product_type = 'R5'
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R5'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.offer_accepted_ts = timezone.now()
        self.loan_refinancing_offer.is_accepted = True
        self.loan_refinancing_offer.save()

        url = '/api/loan_refinancing/v1/ajax_check_refinancing_request_status'
        data = dict(
            loan_id=self.loan_refinancing_request.loan.id
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_check_refinancing_request_status_available(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R5'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.offer_accepted_ts = timezone.now()
        self.loan_refinancing_offer.is_accepted = True
        self.loan_refinancing_offer.save()

        url = '/api/loan_refinancing/v1/ajax_check_refinancing_request_status'
        data = dict(
            loan_id=self.loan_refinancing_request.loan.id
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_check_refinancing_request_status_offer_generated(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_generated
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R5'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.offer_accepted_ts = timezone.now()
        self.loan_refinancing_offer.is_accepted = True
        self.loan_refinancing_offer.save()

        url = '/api/loan_refinancing/v1/ajax_check_refinancing_request_status'
        data = dict(
            loan_id=self.loan_refinancing_request.loan.id
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_generate_reactive_refinancing_offer(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_generated
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R5'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.save()

        url = '/api/loan_refinancing/v1/ajax_generate_reactive_refinancing_offer/'
        data = dict(
            loan_id=self.loan_refinancing_request.loan.id,
            new_income=2000000,
            new_expense=1000000,
            new_employment_status='Dirumahkan gaji minim',
            recommendation_offer_products=['R1', 'R2'],
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_max_tenure_extension_r1(self):
        max_tenure = get_max_tenure_extension_r1(self.loan_refinancing_request)
        self.assertEqual(4, max_tenure)

    def test_get_max_tenure_extension_r1_not_found(self):
        CollectionOfferExtensionConfiguration.objects.filter(
            remaining_payment=4
        ).delete()
        max_tenure = get_max_tenure_extension_r1(self.loan_refinancing_request)
        self.assertIsNone(max_tenure)

    def test_ajax_get_exisiting_offers(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.activated
        self.loan_refinancing_request.offer_activated_ts = timezone.now()
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R5'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.offer_accepted_ts = timezone.now()
        self.loan_refinancing_offer.is_accepted = True
        self.loan_refinancing_offer.save()

        url = '/api/loan_refinancing/v1/ajax_get_exisiting_offers'
        data = dict(
            loan_id=self.loan_refinancing_request.loan.id
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_autopopulate_refinancing_offer(self):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R5'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.is_accepted = True
        self.loan_refinancing_offer.save()

        url = '/api/loan_refinancing/v1/ajax_generate_reactive_refinancing_offer/'
        data = dict(
            loan_id=self.loan_refinancing_request.loan.id,
            new_income=2000000,
            new_expense=1000000,
            new_employment_status='Dirumahkan gaji minim',
            recommendation_offer_products=['R1', 'R2'],
            is_auto_populated=True
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.loan_refinancing.services.comms_channels.send_email_covid_refinancing_opt')
    def test_send_offer_selected_notification(self, mock_send_email_covid_refinancing_opt):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.product_type = 'R1'
        self.loan_refinancing_request.comms_channel_1 = 'Email'
        self.loan_refinancing_request.save()
        send_loan_refinancing_request_offer_selected_notification(self.loan_refinancing_request)

    def test_generate_status_and_tips_loan_refinancing(self):
        data = generate_status_and_tips_loan_refinancing_status(loan_refinancing_req=None, data={})
        self.assertEqual(data['current_loan_refinancing_status'], '-')
        self.assertEqual(data['offer_selected_label'], '-')
        self.assertEqual(data['tips'], CovidRefinancingConst.STATUSES_TIPS_LABEL['-'])
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.product_type = 'R1'
        self.loan_refinancing_request.save()
        data = generate_status_and_tips_loan_refinancing_status(
            loan_refinancing_req=self.loan_refinancing_request, data={}
        )
        self.assertEqual(
            data['current_loan_refinancing_status'],
            CovidRefinancingConst.STATUSES.offer_selected
        )
        self.assertEqual(
            data['offer_selected_label'],
            CovidRefinancingConst.SELECTED_OFFER_LABELS[
                self.loan_refinancing_request.product_type
            ]
        )
        self.assertEqual(data['tips'], CovidRefinancingConst.STATUSES_TIPS_LABEL['Offer Selected'])
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.activated
        self.loan_refinancing_request.save()
        data = generate_status_and_tips_loan_refinancing_status(
            loan_refinancing_req=self.loan_refinancing_request, data={}
        )
        self.assertEqual(
            data['current_loan_refinancing_status'], "-"
        )

    @mock.patch('juloserver.loan_refinancing.services.comms_channels.send_email_covid_refinancing_approved')
    @mock.patch('juloserver.loan_refinancing.services.comms_channels.send_sms_covid_refinancing_approved')
    @mock.patch('juloserver.loan_refinancing.services.comms_channels.send_pn_covid_refinancing_approved')
    @mock.patch('juloserver.loan_refinancing.services.comms_channels.send_email_covid_refinancing_opt')
    def test_ajax_retrigger_comms(
        self,
        mock_send_email_covid_refinancing_opt,
        mock_send_pn_covid_refinancing_approved,
        mock_send_sms_covid_refinancing_approved,
        mock_send_email_covid_refinancing_approved):
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.save()

        self.loan_refinancing_offer.loan_refinancing_request = self.loan_refinancing_request
        self.loan_refinancing_offer.product_type = 'R1'
        self.loan_refinancing_offer.is_latest = True
        self.loan_refinancing_offer.save()

        url = '/api/loan_refinancing/v1/ajax_retrigger_comms/'
        data = dict(
            loan_id=self.loan_refinancing_request.loan.id,
            comms_channel_1='Email',
            comms_channel_2='',
            comms_channel_3='',
        )
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], True)
        data['comms_channel_2'] = 'PN'
        today = timezone.localtime(timezone.now()).date()
        self.loan_refinancing_request.last_retrigger_comms = today
        self.loan_refinancing_request.save()
        response2 = self.client.post(url, data)
        self.assertEqual(response2.json()['status'], "failed")
        self.assertEqual(response2.json()['message'], "hanya bisa retrigger 1x satu hari")

        self.loan_refinancing_request.last_retrigger_comms = None
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.approved
        self.loan_refinancing_request.save()
        response3 = self.client.post(url, data)
        self.assertEqual(response3.status_code, status.HTTP_200_OK)
        self.assertEqual(response3.json()['status'], True)

        self.loan_refinancing_request.last_retrigger_comms = None
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_generated
        self.loan_refinancing_request.save()
        response4 = self.client.post(url, data)
        self.assertEqual(response4.status_code, status.HTTP_200_OK)
        self.assertEqual(response4.json()['status'], "failed")
        response5 = self.client.get(url)
        self.assertEqual(response5.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        loan_without_refinancing = LoanFactory()
        data['loan_id'] = loan_without_refinancing.id
        response6 = self.client.post(url, data)
        self.assertEqual(response6.json()['status'], "failed")
        self.client.logout()
        response7 = self.client.post(url, data)
        self.assertEqual(response7.json()['status'], "failed")

    def test_get_payment_structure(self):
        self.loan_refinancing_offer.loan_duration = 1
        self.loan_refinancing_offer.save()
        new_payment_structure_r2 = get_r2_payment_structure(
            self.loan_refinancing_request,
            loan_duration_extension=self.loan_refinancing_offer.loan_duration)
        assert len(new_payment_structure_r2) > len(self.loan.payment_set.all())

        new_payment_structure_r3 = get_r3_payment_structure(
            self.loan_refinancing_request,
            loan_duration_extension=self.loan_refinancing_offer.loan_duration
        )['payments']
        assert len(new_payment_structure_r3) > len(self.loan.payment_set.all())

    def test_get_proactive_offer_generation(self):
        loan_refinancing_score = LoanRefinancingScore.objects.create(
            application_id=self.application.id,
            loan=self.loan,
            rem_installment=0,
            ability_score=1,
            willingness_score=2.7,
            is_covid_risky=False,
            bucket='current',
            oldest_payment_num=0
        )
        recomended_product_1 = proactive_offer_generation(self.loan_refinancing_request)
        assert recomended_product_1 == 'R1,R2,R3'
        # quadran LL
        self.loan_refinancing_request.new_income = 3000000
        self.loan_refinancing_request.new_expense = 2000000
        self.loan_refinancing_request.save()
        loan_refinancing_score.willingness_score = 1
        loan_refinancing_score.save()
        recomended_product_2 = proactive_offer_generation(self.loan_refinancing_request)
        assert recomended_product_2 == 'R1,R2,R3'
        # quadran HH
        loan_refinancing_score.willingness_score = 5
        loan_refinancing_score.ability_score = 5
        loan_refinancing_score.save()
        recomended_product_3 = proactive_offer_generation(self.loan_refinancing_request)
        assert recomended_product_3 == 'R5,R1,R3'
        # quadran HL
        loan_refinancing_score.willingness_score = 1
        loan_refinancing_score.save()
        recomended_product_4 = proactive_offer_generation(self.loan_refinancing_request)
        assert recomended_product_4 == 'R5,R6'
        loan_refinancing_score.delete()
        recomended_product_5 = proactive_offer_generation(self.loan_refinancing_request)
        assert recomended_product_5 is False

    def test_approval_offer_proactive_alignment_r1_r2_r3(self):
        proposed_offer = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
        self.loan.loan_status_id = 220
        self.loan.save()
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = proposed_offer
        self.loan_refinancing_request.form_submitted_ts = timezone.localtime(timezone.now())
        self.loan_refinancing_request.uuid = self.uuid
        self.loan_refinancing_request.save()
        payment = PaymentFactory(loan=self.loan)
        payment.payment_number = 0
        payment.payment_status_id = 310
        payment.save()
        generated_default_offers(self.loan_refinancing_request, 'R1,R2,R3', is_proactive_offer=True)
        url = '/api/loan_refinancing/v1/covid_approval/{}/'.format(self.encrypted_uuid)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, 'covid_refinancing/covid_proactive_offer.html')

    def test_approval_offer_proactive_alignment_r5_r6(self):
        proposed_offer = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
        self.loan.loan_status_id = 220
        self.loan.save()
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = proposed_offer
        self.loan_refinancing_request.form_submitted_ts = timezone.localtime(timezone.now())
        self.loan_refinancing_request.uuid = self.uuid
        self.loan_refinancing_request.save()
        LoanRefinancingScore.objects.create(
            application_id=self.application.id,
            loan=self.loan,
            rem_installment=0,
            ability_score=1,
            willingness_score=2.2,
            is_covid_risky='no',
            bucket='current',
            oldest_payment_num=0
        )

        payment = PaymentFactory(loan=self.loan)
        payment.payment_number = 0
        payment.payment_status_id = 310
        payment.save()
        generated_default_offers(self.loan_refinancing_request, 'R5,R6', is_proactive_offer=True)
        url = '/api/loan_refinancing/v1/covid_approval/{}/'.format(self.encrypted_uuid)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, 'covid_refinancing/covid_proactive_offer.html')

    def test_approval_offer_proactive_alignment_r3(self):
        proposed_offer = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
        self.loan.loan_status_id = 220
        self.loan.save()
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = proposed_offer
        self.loan_refinancing_request.form_submitted_ts = timezone.localtime(timezone.now())
        self.loan_refinancing_request.uuid = self.uuid
        self.loan_refinancing_request.save()
        payment = PaymentFactory(loan=self.loan)
        payment.payment_number = 0
        payment.payment_status_id = 310
        payment.save()
        generated_default_offers(self.loan_refinancing_request, 'R1,R3', is_proactive_offer=True)
        url = '/api/loan_refinancing/v1/covid_approval/{}/'.format(self.encrypted_uuid)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, 'covid_refinancing/covid_proactive_offer.html')

    def test_refinancing_form_submit(self):
        self.loan.loan_status_id = 220
        self.loan.save()

        payment = PaymentFactory(loan=self.loan)
        payment.payment_number = 0
        payment.payment_status_id = 310
        payment.save()
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
        self.loan_refinancing_request.form_submitted_ts = timezone.localtime(timezone.now())
        self.loan_refinancing_request.uuid = self.uuid
        self.loan_refinancing_request.save()
        main_reason = LoanRefinancingMainReason.objects.create(
            is_active=True,
            reason='dirumahkan gajih minim'
        )
        url = '/api/loan_refinancing/v1/refinancing_form_submit/{}/'.format(self.encrypted_uuid)
        data_for_send = {
            'main_reason': main_reason.id,
            'new_income': 2000000,
            'new_expense': 1800000,
            'mobile_phone_1': '081213123411',
            'mobile_phone_2': '081213123412',
        }
        response = self.client.post(url, data_for_send)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, 'covid_refinancing_proactive.html')

    def test_automate_refinancing_offer(self):
        main_reason = LoanRefinancingMainReason.objects.create(
            is_active=True,
            reason='dirumahkan gajih minim'
        )
        proposed_offer = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer
        self.loan.loan_status_id = 220
        self.loan.save()
        payment = PaymentFactory(loan=self.loan)
        payment.payment_number = 0
        payment.payment_status_id = 310
        payment.save()
        self.loan_refinancing_request.loan = self.loan
        self.loan_refinancing_request.status = proposed_offer
        self.loan_refinancing_request.form_submitted_ts = timezone.localtime(timezone.now())
        self.loan_refinancing_request.uuid = self.uuid
        self.loan_refinancing_request.loan_refinancing_main_reason = main_reason
        self.loan_refinancing_request.save()
        LoanRefinancingScore.objects.create(
            application_id=self.application.id,
            loan=self.loan,
            rem_installment=0,
            ability_score=1,
            willingness_score=2.2,
            is_covid_risky="no",
            bucket='current',
            oldest_payment_num=0
        )
        generated_default_offers(self.loan_refinancing_request, 'R5,R6', is_proactive_offer=True)
        loan_refinancing_offer = LoanRefinancingOffer.objects.filter(
            loan_refinancing_request=self.loan_refinancing_request,
            product_type='R5'
        ).last()
        url = '/api/loan_refinancing/v1/automate_refinancing_offer/{}/'.format(self.encrypted_uuid)
        data_for_send = {
            'product_type': 'R5',
            'product_id_1': loan_refinancing_offer.id,
            'product_id_2': 0
        }
        response = self.client.post(url, data_for_send)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

    def test_get_waiver_recommendatioin(self):
        waiver_recommendation = get_waiver_recommendation(self.loan.id, 'R4', True, 'Current')
        self.assertIsNotNone(waiver_recommendation)
