from builtins import str
from datetime import timedelta

import mock
from django.contrib.auth.models import Group
from django.utils import timezone
from django.test.testcases import TestCase, override_settings
from rest_framework import status
import json

from rest_framework.exceptions import ValidationError

from juloserver.julo.services2 import encrypt
from juloserver.julo.services2 import payment_event
from juloserver.julo.services2.payment_event import PaymentEventServices
from juloserver.julo.tests.factories import (
    LoanFactory,
    PaymentMethodFactory,
    AuthUserFactory,
    CustomerFactory)
from juloserver.loan_refinancing.constants import WAIVER_B1_CURRENT_APPROVER_GROUP, ApprovalLayerConst, \
    WaiverApprovalDecisions, WAIVER_SPV_APPROVER_GROUP, WAIVER_COLL_HEAD_APPROVER_GROUP, WAIVER_OPS_TL_APPROVER_GROUP, \
    WAIVER_B2_APPROVER_GROUP, WAIVER_B3_APPROVER_GROUP, WAIVER_B4_APPROVER_GROUP, WAIVER_B5_APPROVER_GROUP
from juloserver.loan_refinancing.models import WaiverApproval
from juloserver.loan_refinancing.services.loan_related2 import get_data_for_approver_portal
from .factories import (
    LoanRefinancingRequestFactory,
    CovidRefinancingFeatureSettingFactory,
    LoanRefinancingOfferFactory,
    WaiverRecommendationFactory,
    CollectionOfferExtensionConfigurationFactory, WaiverRequestFactory, WaiverPaymentRequestFactory,
    WaiverApprovalFactory, WaiverPaymentApprovalFactory,
    LoanRefinancingScoreFactory)
from ..services.refinancing_product_related import generate_unique_uuid


DISABLED_CSRF_MIDDLEWARE = [
    'django_cookies_samesite.middleware.CookiesSameSite',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # 3rd party middleware classes
    'juloserver.julo.middleware.DeviceIpMiddleware',
    'cuser.middleware.CuserMiddleware',
    'juloserver.julocore.restapi.middleware.ApiLoggingMiddleware',
    'juloserver.standardized_api_response.api_middleware.StandardizedApiURLMiddleware',
    'juloserver.routing.middleware.CustomReplicationMiddleware',
]


@override_settings(MIDDLEWARE=DISABLED_CSRF_MIDDLEWARE)
@override_settings(SUSPEND_SIGNALS=True)
class TestWaiverEnhancement(TestCase):
    @classmethod
    def setUpTestData(cls):
        encrypter = encrypt()
        cls.uuid = generate_unique_uuid()
        cls.today = timezone.localtime(timezone.now())
        cls.encrypted_uuid = encrypter.encode_string(cls.uuid)
        cls.loan = LoanFactory()
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
        cls.payment_method = PaymentMethodFactory(loan=cls.loan, customer=cls.loan.customer)
        cls.waiver_recommendation = WaiverRecommendationFactory()

    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)

        self.waiver_recommendation = WaiverRecommendationFactory(
            bucket_name="Current",
            program_name="R4",
            is_covid_risky=True,
            partner_product="normal",
            late_fee_waiver_percentage=20,
            interest_waiver_percentage=20,
            principal_waiver_percentage=20,
        )
        self.waiver_request = WaiverRequestFactory(
            loan=self.loan,
            waiver_recommendation=self.waiver_recommendation,
            waiver_validity_date=(timezone.now() + timedelta(days=3)).date(),
            bucket_name="Current",
        )
        for payment in self.loan.payment_set.all():
            WaiverPaymentRequestFactory(
                waiver_request=self.waiver_request, payment=payment
            )

        self.loan_refinancing_request.new_income = 5000000
        self.loan_refinancing_request.new_expense = 1000000
        self.loan_refinancing_request.save()

        self.loan.refresh_from_db()
        self.loan_refinancing_request.refresh_from_db()
        self.loan_refinancing_offer.refresh_from_db()

    def test_get_data_for_approver_portal_exist(self):
        data = {
            'ongoing_loan_data': [],
            'loan_id': '',
            'show': False,
            'ability_score': '',
            'willingness_score': '',
            'is_covid_risky': '',
            'max_extension': '',
            'bucket': '',
            'loan_refinancing_request_count': 0,
            'reasons': [],
            'loan_id_list': [],
            'is_approver': True,
        }
        loan_id = self.loan.id
        returned_data = get_data_for_approver_portal(data, loan_id)
        self.assertTrue(returned_data['show'])

    def test_get_data_for_approver_portal_case_2(self):
        data = {
            'ongoing_loan_data': [],
            'loan_id': '',
            'show': False,
            'ability_score': '',
            'willingness_score': '',
            'is_covid_risky': '',
            'max_extension': '',
            'bucket': '',
            'loan_refinancing_request_count': 0,
            'reasons': [],
            'loan_id_list': [],
            'is_approver': True,
        }
        another_loan = LoanFactory()
        loan_id = another_loan.id

        payment = another_loan.payment_set.first()
        payment.paid_amount = 1
        payment.due_amount = payment.due_amount - 1
        payment.save()

        loan_refinancing_score = LoanRefinancingScoreFactory()
        loan_refinancing_score.loan = another_loan
        loan_refinancing_score.application_id = another_loan.application.id
        loan_refinancing_score.save()

        returned_data = get_data_for_approver_portal(data, loan_id)
        self.assertTrue(returned_data['show'])

    def test_submit_approval_no_privilege(self):
        url = '/api/loan_refinancing/v1/submit_waiver_approval/'
        response = self.client.post(url, {})
        self.assertEqual(response.json()['message'], 'User anda tidak termasuk dalam role Waiver Approver')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['status'], 'failed')

    def test_submit_approval_normal_case(self):
        group = Group.objects.create(name=WAIVER_B1_CURRENT_APPROVER_GROUP)
        self.user.groups.add(group)

        data = {
            "loan_id": None,
            "approved_program": "R6",
            "paid_ptp_amount": 6000000,
            "decision": "approved",
            "approved_interest_waiver_percentage": 70,
            "approved_late_fee_waiver_percentage": 60,
            "approved_remaining_amount": 1500000,
            "waiver_request_id": self.waiver_request.id,
            "waiver_payment_approvals": [{
                "approved_late_fee_waiver_amount": 80000,
                "approved_interest_waiver_amount": 70000,
                "approved_principal_waiver_amount": 45646,
                "remaining_principal_amount": 335960,
                "remaining_interest_amount": 357956,
                "remaining_late_fee_amount": 4487686,
                "total_approved_waiver_amount": 4540676,
                "total_remaining_amount": 536547,
                "payment_id": self.loan.payment_set.last().id,
                "outstanding_principal_amount": 8372652,
                "total_outstanding_amount": 904850934,
                "outstanding_late_fee_amount": 34546,
                "outstanding_interest_amount": 2354765
            }],
            "approved_waiver_amount": 3000000,
            "approved_waiver_validity_date": "2020-08-10",
            "approved_principal_waiver_percentage": 80
        }

        url = '/api/loan_refinancing/v1/submit_waiver_approval/'
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.json()['detail'], '')
        self.assertEqual(response.json()['message'], 'Berhasil memproses approval')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'success')

    def test_submit_approval_paid_case_2(self):
        group = Group.objects.create(name=WAIVER_B1_CURRENT_APPROVER_GROUP)
        self.user.groups.add(group)

        data = {
            "loan_id": self.loan.id,
            "approved_program": "R6",
            "paid_ptp_amount": 6000000,
            "decision": "approved",
            "approved_interest_waiver_percentage": 70,
            "approved_late_fee_waiver_percentage": 60,
            "approved_remaining_amount": 1500000,
            "waiver_request_id": None,
            "waiver_payment_approvals": [{
                "approved_late_fee_waiver_amount": 80000,
                "approved_interest_waiver_amount": 70000,
                "approved_principal_waiver_amount": 45646,
                "remaining_principal_amount": 335960,
                "remaining_interest_amount": 357956,
                "remaining_late_fee_amount": 4487686,
                "total_approved_waiver_amount": 4540676,
                "total_remaining_amount": 536547,
                "payment_id": self.loan.payment_set.last().id,
                "outstanding_principal_amount": 8372652,
                "total_outstanding_amount": 904850934,
                "outstanding_late_fee_amount": 34546,
                "outstanding_interest_amount": 2354765
            }],
            "approved_waiver_amount": 3000000,
            "approved_waiver_validity_date": "2020-08-10",
            "approved_principal_waiver_percentage": 80,
            "waiver_request": {
                "loan_id": self.loan.id,
                "outstanding_principal_amount": 645747,
                "new_expense": 3457346,
                "requested_late_fee_waiver_percentage": 100,
                "requested_principal_waiver_percentage": 100,
                "waiver_recommendation_id": 4,
                "is_automated": False,
                "outstanding_interest_amount": 400000,
                "unpaid_interest": 5000000,
                "waived_payment_count": 6000,
                "unpaid_late_fee": 8686868,
                "calculated_unpaid_waiver_percentage": 70,
                "outstanding_amount": 6868686,
                "requested_interest_waiver_percentage": 60,
                "new_income": 5000000,
                "bucket_name": "1",
                "requested_late_fee_waiver_amount": 857575,
                "first_waived_payment": self.loan.payment_set.last().id,
                "is_covid_risky": True,
                "ptp_amount": 700000,
                "selected_program_name": "R6",
                "requested_principal_waiver_amount": 50000,
                "outstanding_late_fee_amount": 67000,
                "waiver_validity_date": "2020-08-14",
                "reason": "bla bla bla",
                "partner_product": "normal",
                "last_waived_payment": self.loan.payment_set.last().id,
                "unpaid_principal": 758686,
                "recommended_unpaid_waiver_percentage": 80,
                "agent_notes": "uyriueyrewgtirgf",
                "requested_interest_waiver_amount": 80000,
                "remaining_amount_for_waived_payment": 900000,
                "requested_waiver_amount": 600000
            },
            "waiver_payment_requests":[{
                "payment_id": self.loan.payment_set.last().id,
                "outstanding_principal_amount": 37564,
                "outstanding_interest_amount": 485736,
                "total_requested_waiver_amount": 57367,
                "total_remaining_amount": 457386,
                "requested_principal_waiver_amount": 2357486,
                "total_outstanding_amount": 285764,
                "outstanding_late_fee_amount": 84756,
                "remaining_interest_amount": 4875486,
                "requested_late_fee_waiver_amount": 2574657,
                "is_paid_off_after_ptp": True,
                "remaining_late_fee_amount": 285798457,
                "remaining_principal_amount": 24657645,
                "requested_interest_waiver_amount": 3285296547
            }]
        }

        url = '/api/loan_refinancing/v1/submit_waiver_approval/'
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.json()['detail'], '')
        self.assertEqual(response.json()['message'], 'Berhasil memproses approval')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'success')

    def test_submit_approval_paid_case_2_yes_risky(self):
        group = Group.objects.create(name=WAIVER_B1_CURRENT_APPROVER_GROUP)
        self.user.groups.add(group)

        data = {
            "loan_id": self.loan.id,
            "approved_program": "R6",
            "paid_ptp_amount": 6000000,
            "decision": "approved",
            "approved_interest_waiver_percentage": 70,
            "approved_late_fee_waiver_percentage": 60,
            "approved_remaining_amount": 1500000,
            "waiver_request_id": None,
            "waiver_payment_approvals": [{
                "approved_late_fee_waiver_amount": 80000,
                "approved_interest_waiver_amount": 70000,
                "approved_principal_waiver_amount": 45646,
                "remaining_principal_amount": 335960,
                "remaining_interest_amount": 357956,
                "remaining_late_fee_amount": 4487686,
                "total_approved_waiver_amount": 4540676,
                "total_remaining_amount": 536547,
                "payment_id": self.loan.payment_set.last().id,
                "outstanding_principal_amount": 8372652,
                "total_outstanding_amount": 904850934,
                "outstanding_late_fee_amount": 34546,
                "outstanding_interest_amount": 2354765
            }],
            "approved_waiver_amount": 3000000,
            "approved_waiver_validity_date": "2020-08-10",
            "approved_principal_waiver_percentage": 80,
            "waiver_request": {
                "loan_id": self.loan.id,
                "outstanding_principal_amount": 645747,
                "new_expense": 3457346,
                "requested_late_fee_waiver_percentage": 100,
                "requested_principal_waiver_percentage": 100,
                "waiver_recommendation_id": 4,
                "is_automated": False,
                "outstanding_interest_amount": 400000,
                "unpaid_interest": 5000000,
                "waived_payment_count": 6000,
                "unpaid_late_fee": 8686868,
                "calculated_unpaid_waiver_percentage": 70,
                "outstanding_amount": 6868686,
                "requested_interest_waiver_percentage": 60,
                "new_income": 5000000,
                "bucket_name": "1",
                "requested_late_fee_waiver_amount": 857575,
                "first_waived_payment": self.loan.payment_set.last().id,
                "is_covid_risky": 'yes',
                "ptp_amount": 700000,
                "selected_program_name": "R6",
                "requested_principal_waiver_amount": 50000,
                "outstanding_late_fee_amount": 67000,
                "waiver_validity_date": "2020-08-14",
                "reason": "bla bla bla",
                "partner_product": "normal",
                "last_waived_payment": self.loan.payment_set.last().id,
                "unpaid_principal": 758686,
                "recommended_unpaid_waiver_percentage": 80,
                "agent_notes": "uyriueyrewgtirgf",
                "requested_interest_waiver_amount": 80000,
                "remaining_amount_for_waived_payment": 900000,
                "requested_waiver_amount": 600000
            },
            "waiver_payment_requests":[{
                "payment_id": self.loan.payment_set.last().id,
                "outstanding_principal_amount": 37564,
                "outstanding_interest_amount": 485736,
                "total_requested_waiver_amount": 57367,
                "total_remaining_amount": 457386,
                "requested_principal_waiver_amount": 2357486,
                "total_outstanding_amount": 285764,
                "outstanding_late_fee_amount": 84756,
                "remaining_interest_amount": 4875486,
                "requested_late_fee_waiver_amount": 2574657,
                "is_paid_off_after_ptp": True,
                "remaining_late_fee_amount": 285798457,
                "remaining_principal_amount": 24657645,
                "requested_interest_waiver_amount": 3285296547
            }]
        }

        url = '/api/loan_refinancing/v1/submit_waiver_approval/'
        response = self.client.post(url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.json()['detail'], '')
        self.assertEqual(response.json()['message'], 'Berhasil memproses approval')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'success')

    def test_waiver_do_payment(self):
        tobe_waived_loan = LoanFactory()
        approved_waiver_amount = 300000
        outstanding_amount = 1300000
        waived_payment = tobe_waived_loan.payment_set.last()

        data = {
            "loan_id": tobe_waived_loan.id,
            "approved_program": "R6",
            "paid_ptp_amount": 0,
            "decision": "approved",
            "approved_interest_waiver_percentage": 70,
            "approved_late_fee_waiver_percentage": 60,
            "approved_remaining_amount": 1500000,
            "waiver_request_id": None,
            "waiver_payment_approvals": [{
                "approved_late_fee_waiver_amount": 80000,
                "approved_interest_waiver_amount": 70000,
                "approved_principal_waiver_amount": 45646,
                "remaining_principal_amount": 335960,
                "remaining_interest_amount": 357956,
                "remaining_late_fee_amount": 4487686,
                "total_approved_waiver_amount": 4540676,
                "total_remaining_amount": 536547,
                "payment_id": waived_payment.id,
                "outstanding_principal_amount": 8372652,
                "total_outstanding_amount": 904850934,
                "outstanding_late_fee_amount": 34546,
                "outstanding_interest_amount": 2354765
            }],
            "approved_waiver_amount": approved_waiver_amount,
            "approved_waiver_validity_date": "2020-08-10",
            "approved_principal_waiver_percentage": 80,
            "waiver_request": {
                "loan_id": tobe_waived_loan.id,
                "outstanding_principal_amount": 645747,
                "new_expense": 3457346,
                "requested_late_fee_waiver_percentage": 100,
                "requested_principal_waiver_percentage": 100,
                "waiver_recommendation_id": 4,
                "is_automated": False,
                "outstanding_interest_amount": 400000,
                "unpaid_interest": 5000000,
                "waived_payment_count": 6000,
                "unpaid_late_fee": 8686868,
                "calculated_unpaid_waiver_percentage": 70,
                "outstanding_amount": outstanding_amount,
                "requested_interest_waiver_percentage": 60,
                "new_income": 5000000,
                "bucket_name": "1",
                "requested_late_fee_waiver_amount": 857575,
                "first_waived_payment": waived_payment.id,
                "is_covid_risky": True,
                "ptp_amount": 700000,
                "selected_program_name": "R6",
                "requested_principal_waiver_amount": 50000,
                "outstanding_late_fee_amount": 67000,
                "waiver_validity_date": "2020-08-14",
                "reason": "bla bla bla",
                "partner_product": "normal",
                "last_waived_payment": waived_payment.id,
                "unpaid_principal": 758686,
                "recommended_unpaid_waiver_percentage": 80,
                "agent_notes": "uyriueyrewgtirgf",
                "requested_interest_waiver_amount": 80000,
                "remaining_amount_for_waived_payment": 900000,
                "requested_waiver_amount": 600000
            },
            "waiver_payment_requests": [{
                "payment_id": waived_payment.id,
                "outstanding_principal_amount": 37564,
                "outstanding_interest_amount": 485736,
                "total_requested_waiver_amount": 57367,
                "total_remaining_amount": 457386,
                "requested_principal_waiver_amount": 2357486,
                "total_outstanding_amount": 285764,
                "outstanding_late_fee_amount": 84756,
                "remaining_interest_amount": 4875486,
                "requested_late_fee_waiver_amount": 2574657,
                "is_paid_off_after_ptp": True,
                "remaining_late_fee_amount": 285798457,
                "remaining_principal_amount": 24657645,
                "requested_interest_waiver_amount": 3285296547
            }]
        }

        url = '/api/loan_refinancing/v1/submit_waiver_approval/'
        self.client.post(url, json.dumps(data), content_type="application/json")

        payment_event_service = PaymentEventServices()
        data = {
            'paid_date': timezone.now().strftime("%d-%m-%Y"),
            'notes': 'test do payment for waiver',
            'payment_method_id': self.payment_method.id,
            'payment_receipt': 'dummy164365145643',
            'use_credits': 'false',
            'partial_payment': str(outstanding_amount - approved_waiver_amount),

        }

        returned_res = payment_event_service.process_event_type_payment(
            waived_payment, data, with_waiver=True)
        self.assertIsNotNone(returned_res)

    def test_get_next_approval_layer(self):
        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.TL)
        next_layer = self.waiver_request.get_next_approval_layer()
        self.assertEqual(next_layer, ApprovalLayerConst.SPV)

        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.SPV)
        next_layer = self.waiver_request.get_next_approval_layer()
        self.assertEqual(next_layer, ApprovalLayerConst.COLLS_HEAD)

        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.COLLS_HEAD)
        next_layer = self.waiver_request.get_next_approval_layer()
        self.assertEqual(next_layer, ApprovalLayerConst.OPS_HEAD)

        self.waiver_request.update_safely(approval_layer_state='Wrong status')

        with self.assertRaises(Exception) as context:
            self.waiver_request.get_next_approval_layer()

        self.assertEqual(ValidationError, type(context.exception))

    def test_is_last_approval_layer(self):
        data = {
            "approved_program": "R6",
            "paid_ptp_amount": 6000000,
            "decision": WaiverApprovalDecisions.APPROVED,
            "approved_interest_waiver_percentage": 70,
            "approved_late_fee_waiver_percentage": 60,
            "approved_remaining_amount": 1500000,
            "waiver_request": self.waiver_request,
            "approved_waiver_amount": 3000000,
            "approved_waiver_validity_date": "2020-08-10",
            "approved_principal_waiver_percentage": 80
        }

        waiver_approval = WaiverApproval(**data)

        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.SPV)
        result = self.waiver_request.is_last_approval_layer(waiver_approval)
        self.assertTrue(result)

        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.COLLS_HEAD)
        result = self.waiver_request.is_last_approval_layer(waiver_approval)
        self.assertTrue(result)

        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.OPS_HEAD)
        result = self.waiver_request.is_last_approval_layer(waiver_approval)
        self.assertTrue(result)

        waiver_approval.decision = WaiverApprovalDecisions.REJECTED
        result = self.waiver_request.is_last_approval_layer(waiver_approval)
        self.assertFalse(result)

    def test_update_approval_layer_state(self):
        self.waiver_request.update_safely(bucket_name='2')

        user_groups = [WAIVER_B2_APPROVER_GROUP]
        next_layer = self.waiver_request.get_next_approval_layer()
        result = self.waiver_request.update_approval_layer_state(user_groups)
        self.assertEqual(result, next_layer)

        user_groups = [WAIVER_B3_APPROVER_GROUP]
        self.waiver_request.update_safely(bucket_name='3')
        next_layer = self.waiver_request.get_next_approval_layer()
        result = self.waiver_request.update_approval_layer_state(user_groups)
        self.assertEqual(result, next_layer)

        user_groups = [WAIVER_B4_APPROVER_GROUP]
        self.waiver_request.update_safely(bucket_name='4')
        next_layer = self.waiver_request.get_next_approval_layer()
        result = self.waiver_request.update_approval_layer_state(user_groups)
        self.assertEqual(result, next_layer)

        user_groups = [WAIVER_B5_APPROVER_GROUP]
        self.waiver_request.update_safely(bucket_name='5')
        next_layer = self.waiver_request.get_next_approval_layer()
        result = self.waiver_request.update_approval_layer_state(user_groups)
        self.assertEqual(result, next_layer)

        user_groups = []
        with self.assertRaises(Exception) as context:
            self.waiver_request.update_approval_layer_state(user_groups)

        self.assertEqual(ValidationError, type(context.exception))

    def test_update_approval_layer_state_last(self):
        waiver_approval = WaiverApprovalFactory(
            waiver_request=self.waiver_request, approver_type=ApprovalLayerConst.TL)
        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.TL)

        user_groups = [WAIVER_SPV_APPROVER_GROUP]
        next_layer = self.waiver_request.get_next_approval_layer()
        result = self.waiver_request.update_approval_layer_state(user_groups)
        self.assertEqual(result, next_layer)

        user_groups = [WAIVER_COLL_HEAD_APPROVER_GROUP]
        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.SPV)
        waiver_approval.update_safely(approver_type=ApprovalLayerConst.SPV)
        next_layer = self.waiver_request.get_next_approval_layer()
        result = self.waiver_request.update_approval_layer_state(user_groups)
        self.assertEqual(result, next_layer)

        user_groups = [WAIVER_OPS_TL_APPROVER_GROUP]
        self.waiver_request.update_safely(approval_layer_state=ApprovalLayerConst.COLLS_HEAD)
        waiver_approval.update_safely(approver_type=ApprovalLayerConst.COLLS_HEAD)
        next_layer = self.waiver_request.get_next_approval_layer()
        result = self.waiver_request.update_approval_layer_state(user_groups)
        self.assertEqual(result, next_layer)

    def test_waiver_portal_agent(self):
        url = '/api/loan_refinancing/v1/covid_refinancing_web_portal/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        group = Group.objects.create(name=WAIVER_B1_CURRENT_APPROVER_GROUP)
        self.user.groups.add(group)
        url = '/api/loan_refinancing/v1/covid_refinancing_web_portal/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


