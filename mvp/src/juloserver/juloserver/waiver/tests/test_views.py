import json
from builtins import str
from django.test.testcases import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from django.utils import timezone
from datetime import datetime, timedelta

from django.contrib.auth.models import Group
from juloserver.julo.models import FeatureSetting

from juloserver.account.tests.factories import AccountFactory, AccountTransactionFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory,
    WaiverRequestFactory,
    WaiverApprovalFactory,
    WaiverPaymentApprovalFactory,
    LoanRefinancingOfferFactory,
    WaiverRecommendationFactory
)
from .factories import WaiverAccountPaymentApprovalFactory, WaiverAccountPaymentRequestFactory
from juloserver.julo.tests.factories import (
    AccountingCutOffDateFactory,
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    ProductLineFactory,
    PaybackTransactionFactory,
    PaymentFactory,
    StatusLookupFactory,
    LoanFactory,
    FeatureSettingFactory,
)

from juloserver.loan_refinancing.constants import (
    CovidRefinancingConst,
    WAIVER_SPV_APPROVER_GROUP,
    WAIVER_B2_APPROVER_GROUP,
)
from juloserver.julo.constants import FeatureNameConst


class TestViewWaiver(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.account = AccountFactory()
        self.account_payment = AccountPaymentFactory(account=self.account)
        AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(
            customer=self.account.customer,
            loan_status=StatusLookupFactory(status_code=220),
        )
        self.payment = PaymentFactory(
            account_payment=self.account_payment,
            payment_status=StatusLookupFactory(status_code=310),
            loan=self.loan,
        )

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        product_line = ProductLineFactory(product_line_code=1,product_line_type="J1")
        ApplicationFactory(account=self.account, product_line=product_line)
        FeatureSettingFactory(
            feature_name=FeatureNameConst.REFINANCING_MAX_CAP_RULE_TRIGGER,
            parameters={'R1': True, 'R2': True, 'R3': True, 'R4': True, 'Stacked': False},
            is_active=True,
            description="Trigger setting for refinancing max cap rule",
            category='loan refinancing',
        )

    def test_collection_offer_j1(self):
        self.client.force_login(self.user)
        response = self.client.get(
            '/waiver/collection-offer-j1/',
            data=dict(account_id=self.account.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.groups.add(Group.objects.create(name=WAIVER_SPV_APPROVER_GROUP))
        response = self.client.get(
            '/waiver/collection-offer-j1/',
            data=dict(
                account_id=self.account.id,
                portal_type="approver_portal",
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_get_j1_exisiting_offers(self):
        response = self.client.get('/waiver/ajax_get_j1_exisiting_offers/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.post('/waiver/ajax_get_j1_exisiting_offers/')
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "non authorized user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.force_login(self.user)
        response = self.client.post(
            '/waiver/ajax_get_j1_exisiting_offers/',
            data=dict(account_id=self.account.id)
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        assert "existing_offers" in content["response"]
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_generate_j1_waiver_refinancing_offer(self):
        response = self.client.get('/waiver/ajax_generate_j1_waiver_refinancing_offer/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.post('/waiver/ajax_generate_j1_waiver_refinancing_offer/')
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "non authorized user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.force_login(self.user)
        response = self.client.post('/waiver/ajax_generate_j1_waiver_refinancing_offer/')
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "Feature setting status tidak aktif")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.COVID_REFINANCING,
            is_active=True,
            parameters={"email_expire_in_days": 0}
        )
        data = dict(
            account_id=self.account.id,
            is_auto_populated=True,
            selected_product="R6",
        )
        loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account, loan=None,
            status=CovidRefinancingConst.STATUSES.offer_selected,
            prerequisite_amount=0,
            expire_in_days=0,
        )
        LoanRefinancingOfferFactory(
            loan_refinancing_request=loan_refinancing_request,
            product_type=CovidRefinancingConst.PRODUCTS.r6,
            is_accepted=True,
            is_latest=True,
        )
        waiver_request = WaiverRequestFactory(
            account=self.account,
            is_approved=None,
            is_automated=False,
            waiver_validity_date=timezone.localtime(timezone.now()).date(),
            loan_refinancing_request=loan_refinancing_request,
            first_waived_account_payment=self.account_payment,
            last_waived_account_payment=self.account_payment,
            requested_late_fee_waiver_percentage="100%",
            requested_interest_waiver_percentage="100%",
            requested_principal_waiver_percentage="100%",
        )
        WaiverAccountPaymentRequestFactory(
            waiver_request=waiver_request, account_payment=self.account_payment,
            total_remaining_amount=1,
        )
        WaiverAccountPaymentApprovalFactory(
            waiver_approval=WaiverApprovalFactory(waiver_request=waiver_request),
            account_payment=self.account_payment, total_remaining_amount=1,
        )
        response = self.client.post('/waiver/ajax_generate_j1_waiver_refinancing_offer/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "offers berhasil di autopopulate")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data["is_auto_populated"] = False
        response = self.client.post('/waiver/ajax_generate_j1_waiver_refinancing_offer/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "offers berhasil di generate")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        loan_refinancing_request.refresh_from_db()
        loan_refinancing_request.status = CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email
        loan_refinancing_request.save()
        response = self.client.post('/waiver/ajax_generate_j1_waiver_refinancing_offer/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "offers berhasil di generate")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_generate_j1_waiver_refinancing_offer_proposed_offer(self):
        self.client.force_login(self.user)
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.COVID_REFINANCING,
            is_active=True,
            parameters={"email_expire_in_days": 0}
        )
        data = dict(
            account_id=self.account.id,
            is_auto_populated=False,
            selected_product="R4",
        )
        loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account, loan=None,
            status=CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email,
            prerequisite_amount=0,
            expire_in_days=0,
        )
        LoanRefinancingOfferFactory(
            loan_refinancing_request=loan_refinancing_request,
            product_type=CovidRefinancingConst.PRODUCTS.r4,
            is_latest=False,
            recommendation_order=2,
        )
        LoanRefinancingOfferFactory(
            loan_refinancing_request=loan_refinancing_request,
            product_type=CovidRefinancingConst.PRODUCTS.r4,
            is_latest=False,
            recommendation_order=1,
        )
        waiver_request = WaiverRequestFactory(
            account=self.account,
            is_approved=None,
            is_automated=False,
            waiver_validity_date=timezone.localtime(timezone.now()).date(),
            loan_refinancing_request=loan_refinancing_request,
            first_waived_account_payment=self.account_payment,
            last_waived_account_payment=self.account_payment,
            requested_late_fee_waiver_percentage="100%",
            requested_interest_waiver_percentage="100%",
            requested_principal_waiver_percentage="100%",
        )
        WaiverAccountPaymentRequestFactory(
            waiver_request=waiver_request, account_payment=self.account_payment,
            total_remaining_amount=1,
        )
        WaiverAccountPaymentApprovalFactory(
            waiver_approval=WaiverApprovalFactory(waiver_request=waiver_request),
            account_payment=self.account_payment, total_remaining_amount=1,
        )
        response = self.client.post('/waiver/ajax_generate_j1_waiver_refinancing_offer/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "offers berhasil di generate")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_j1_waiver_recommendation(self):
        response = self.client.get('/waiver/ajax_j1_waiver_recommendation/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        self.client.force_login(self.user)
        current_date = datetime.now()
        previous_date = current_date - timedelta(days=1)
        account_payment = AccountPaymentFactory(account=self.account, due_date=previous_date.date())

        data = {
            "account_id": self.account.id,
            "selected_offer_recommendation": "R6",
            "is_covid_risky": True,
            "bucket": "1",
            "account_payment_ids": [account_payment.id],
        }

        response = self.client.post(
            '/waiver/ajax_j1_waiver_recommendation/',
            data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "waiver recommendation tidak ditemukan")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        WaiverRecommendationFactory(bucket_name="1", program_name="R6", total_installments=1)
        data["is_covid_risky"] = False
        response = self.client.post(
            '/waiver/ajax_j1_waiver_recommendation/',
            data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "berhasil mendapatkan waiver recommendation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        WaiverRecommendationFactory(bucket_name="1", program_name="R4")
        data["selected_offer_recommendation"] = "R4"
        response = self.client.post(
            '/waiver/ajax_j1_waiver_recommendation/',
            data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "berhasil mendapatkan waiver recommendation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account, loan=None,
            status=CovidRefinancingConst.STATUSES.offer_selected,
            prerequisite_amount=0,
            expire_in_days=0,
        )
        waiver_request = WaiverRequestFactory(
            account=self.account,
            is_approved=None,
            is_automated=False,
            waiver_validity_date=timezone.localtime(timezone.now()).date(),
            loan_refinancing_request=loan_refinancing_request,
            first_waived_account_payment=self.account_payment,
            last_waived_account_payment=self.account_payment,
            requested_late_fee_waiver_percentage="100%",
            requested_interest_waiver_percentage="100%",
            requested_principal_waiver_percentage="100%",
        )
        response = self.client.post(
            '/waiver/ajax_j1_waiver_recommendation/',
            data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "berhasil mendapatkan waiver recommendation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        loan_refinancing_request.status = CovidRefinancingConst.STATUSES.approved
        loan_refinancing_request.save()
        response = self.client.post(
            '/waiver/ajax_j1_waiver_recommendation/',
            data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "berhasil mendapatkan waiver recommendation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_j1_covid_refinancing_submit_waiver_request(self):
        response = self.client.get('/waiver/ajax_j1_covid_refinancing_submit_waiver_request/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.post('/waiver/ajax_j1_covid_refinancing_submit_waiver_request/')
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "non authorized user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.client.force_login(self.user)
        waiver_reco = WaiverRecommendationFactory(bucket_name="1", program_name="R4")
        selected_account_payments_waived = {
            "waiver": [
                {
                    'account_payment_id': self.account_payment.id,
                    'late_fee': 0,
                    'interest': 0,
                    'principal': 0,
                    'total_waiver': 0,
                }
            ],
            "outstanding": [
                {
                    'account_payment_id': self.account_payment.id,
                    'late_fee': 0,
                    'interest': 0,
                    'principal': 0,
                    'need_to_pay': 0,
                }
            ],
            "remaining": [
                {
                    'account_payment_id': self.account_payment.id,
                    'late_fee': 0,
                    'interest': 0,
                    'principal': 0,
                    'remaining_installment': 0,
                }
            ],
        }

        data = dict(
            bucket_name="1",
            selected_program_name="R4",
            is_covid_risky="yes",
            outstanding_amount=0,
            unpaid_principal=0,
            unpaid_interest=0,
            unpaid_late_fee=0,
            waiver_validity_date=timezone.localtime(timezone.now()).date(),
            ptp_amount=0,
            calculated_unpaid_waiver_percentage=1.0,
            recommended_unpaid_waiver_percentage=1.0,
            waived_account_payment_count=1,
            partner_product="normal",
            is_automated=False,
            waiver_recommendation_id=waiver_reco.id,
            requested_late_fee_waiver_percentage=100,
            requested_interest_waiver_percentage=100,
            requested_principal_waiver_percentage=100,
            requested_late_fee_waiver_amount=0,
            requested_interest_waiver_amount=0,
            requested_principal_waiver_amount=0,
            requested_waiver_amount=0,
            remaining_amount_for_waived_payment=0,
            agent_notes="note",
            first_waived_account_payment=self.account_payment.id,
            last_waived_account_payment=self.account_payment.id,
            comms_channels="Email,SMS,PN",
            is_customer_confirmed=False,
            outstanding_late_fee_amount=0,
            outstanding_interest_amount=0,
            outstanding_principal_amount=0,
            selected_account_payments_waived=json.dumps(selected_account_payments_waived),
            unrounded_requested_interest_waiver_percentage=1.0,
            unrounded_requested_late_fee_waiver_percentage=1.0,
            unrounded_requested_principal_waiver_percentage=1.0,
            is_multiple_ptp_payment=False,
            number_of_multiple_ptp_payment=0,
            agent_group='Desk Collector',
        )
        response = self.client.post(
            '/waiver/ajax_j1_covid_refinancing_submit_waiver_request/', data=data)
        content = response.json()
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"].replace("u'", "'"), u"{'account_id': ['This field is required.']}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data["account_id"] = self.account.id
        response = self.client.post(
            '/waiver/ajax_j1_covid_refinancing_submit_waiver_request/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "Feature setting status tidak aktif")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account, loan=None,
            status=CovidRefinancingConst.STATUSES.offer_selected,
            product_type="R6",
            expire_in_days=1,
            form_submitted_ts=timezone.localtime(timezone.now()),
        )
        response = self.client.post(
            '/waiver/ajax_j1_covid_refinancing_submit_waiver_request/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")

        payback_transaction = PaybackTransactionFactory(
            customer=self.account.customer, payment=self.payment, loan=self.loan,
        )
        AccountTransactionFactory(
            account=self.account,
            transaction_type="payment",
            transaction_amount=1000,
            transaction_date=timezone.localtime(timezone.now()),
            payback_transaction=payback_transaction,
        )
        response = self.client.post(
            '/waiver/ajax_j1_covid_refinancing_submit_waiver_request/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")

        loan_refinancing_request.status = CovidRefinancingConst.STATUSES.activated
        loan_refinancing_request.save()
        response = self.client.post(
            '/waiver/ajax_j1_covid_refinancing_submit_waiver_request/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")

        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.COVID_REFINANCING,
            is_active=True
        )
        loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_generated
        loan_refinancing_request.save()
        loan_refinancing_offer = LoanRefinancingOfferFactory(
            loan_refinancing_request=loan_refinancing_request,
            product_type=CovidRefinancingConst.PRODUCTS.r4,
            latefee_discount_percentage="0%",
            interest_discount_percentage="0%",
            principal_discount_percentage="0%",
            generated_by=None,
            is_latest=True,
            is_proactive_offer=False,
        )
        response = self.client.post(
            '/waiver/ajax_j1_covid_refinancing_submit_waiver_request/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "Loan Refinancing Request berhasil diubah")

        loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_generated
        loan_refinancing_request.save()
        loan_refinancing_offer.is_proactive_offer = True
        loan_refinancing_offer.save()
        data['is_automated'] = False
        data['is_customer_confirmed'] = True
        response = self.client.post(
            '/waiver/ajax_j1_covid_refinancing_submit_waiver_request/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")

        loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_generated
        loan_refinancing_request.save()
        loan_refinancing_offer.is_proactive_offer = True
        loan_refinancing_offer.save()
        data['is_automated'] = True
        data['is_customer_confirmed'] = True
        response = self.client.post(
            '/waiver/ajax_j1_covid_refinancing_submit_waiver_request/', data=data)
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")

    def test_submit_j1_waiver_approval(self):
        response = self.client.get('/waiver/submit_j1_waiver_approval/')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client.post('/waiver/submit_j1_waiver_approval/')
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "non authorized user")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_login(self.user)
        response = self.client.post('/waiver/submit_j1_waiver_approval/')
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "User anda tidak termasuk dalam role Waiver Approver")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_j1_waiver_approval_with_group(self):
        self.user.groups.add(Group.objects.create(name=WAIVER_B2_APPROVER_GROUP))
        self.client.force_login(self.user)
        loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account, loan=None,
            status=CovidRefinancingConst.STATUSES.offer_selected,
            product_type="R6",
            expire_in_days=1,
            form_submitted_ts=timezone.localtime(timezone.now()),
        )

        waiver_request = WaiverRequestFactory(
            account=self.account,
            bucket_name="2",
            is_approved=None,
            is_automated=False,
            waiver_validity_date=timezone.localtime(timezone.now()).date(),
            loan_refinancing_request=loan_refinancing_request,
            first_waived_account_payment=self.account_payment,
            last_waived_account_payment=self.account_payment,
            requested_late_fee_waiver_percentage="100%",
            requested_interest_waiver_percentage="100%",
            requested_principal_waiver_percentage="100%",
            is_need_approval_tl=True
        )

        waiver_account_payment_approvals = [
            {
                "outstanding_late_fee_amount": "0",
                "outstanding_interest_amount": "0",
                "outstanding_principal_amount": "0",
                "total_outstanding_amount": "0",
                "approved_late_fee_waiver_amount": "0",
                "approved_interest_waiver_amount": "0",
                "approved_principal_waiver_amount": "0",
                "total_approved_waiver_amount": "0",
                "remaining_late_fee_amount": "0",
                "remaining_interest_amount": "0",
                "remaining_principal_amount": "0",
                "total_remaining_amount": "0",
                "account_payment_id": self.account_payment.id,
            }
        ]

        data = {
            "account_id": self.account.id,
            "waiver_request_id": waiver_request.id,
            "paid_ptp_amount": 0,
            "decision": "yes",
            "approved_program": "R6",
            "approved_late_fee_waiver_percentage": "100",
            "approved_interest_waiver_percentage": "100",
            "approved_principal_waiver_percentage": "100",
            "approved_waiver_amount": "0",
            "approved_remaining_amount": "0",
            "approved_waiver_validity_date": str(timezone.localtime(timezone.now()).date()),
            "notes": "lunas",
            "waiver_account_payment_approvals": waiver_account_payment_approvals,
            "waiver_request": {},
            "waiver_account_payment_requests": [],
            "unrounded_approved_late_fee_waiver_percentage": "100",
            "unrounded_approved_interest_waiver_percentage": "100",
            "unrounded_approved_principal_waiver_percentage": "100",
            "ptp_amount": 0,
            "approved_reason_type": "R4"
        }
        response = self.client.post(
            '/waiver/submit_j1_waiver_approval/', data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "success")
        self.assertEqual(content["message"], "Berhasil memproses approval")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        waiver_request.is_approved = True
        waiver_request.save()
        response = self.client.post(
            '/waiver/submit_j1_waiver_approval/', data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "Gagal memproses approval harap cek kembali")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data['waiver_request_id'] = None
        waiver_request.is_approved = False
        waiver_request.save()
        response = self.client.post(
            '/waiver/submit_j1_waiver_approval/', data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "Gagal memproses approval harap cek kembali")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        waiver_reco = WaiverRecommendationFactory(bucket_name="1", program_name="R4")
        data['waiver_account_payment_requests'] = [
            {
                "outstanding_late_fee_amount": "0",
                "outstanding_interest_amount": "0",
                "outstanding_principal_amount": "0",
                "total_outstanding_amount": "0",
                "requested_late_fee_waiver_amount": "0",
                "requested_interest_waiver_amount": "0",
                "requested_principal_waiver_amount": "0",
                "total_requested_waiver_amount": "0",
                "remaining_late_fee_amount": "0",
                "remaining_interest_amount": "0",
                "remaining_principal_amount": "0",
                "total_remaining_amount": "0",
                "account_payment_id": self.account_payment.id,
                "is_paid_off_after_ptp": True,
            }
        ]
        data['waiver_request'] = dict(
            account_id=self.account.id,
            bucket_name="1",
            selected_program_name="R4",
            is_covid_risky="yes",
            outstanding_amount=0,
            unpaid_principal=0,
            unpaid_interest=0,
            unpaid_late_fee=0,
            waiver_validity_date=str(timezone.localtime(timezone.now()).date()),
            ptp_amount=0,
            calculated_unpaid_waiver_percentage=1.0,
            recommended_unpaid_waiver_percentage=1.0,
            waived_account_payment_count=1,
            partner_product="normal",
            is_automated=False,
            waiver_recommendation_id=waiver_reco.id,
            requested_late_fee_waiver_percentage=100,
            requested_interest_waiver_percentage=100,
            requested_principal_waiver_percentage=100,
            requested_late_fee_waiver_amount=0,
            requested_interest_waiver_amount=0,
            requested_principal_waiver_amount=0,
            requested_waiver_amount=0,
            remaining_amount_for_waived_payment=0,
            agent_notes="note",
            first_waived_account_payment=self.account_payment.id,
            last_waived_account_payment=self.account_payment.id,
            unrounded_requested_interest_waiver_percentage=1.0,
            unrounded_requested_late_fee_waiver_percentage=1.0,
            unrounded_requested_principal_waiver_percentage=1.0,
        )
        data['waiver_request_id'] = None
        waiver_request.is_approved = True
        waiver_request.save()
        response = self.client.post(
            '/waiver/submit_j1_waiver_approval/', data=json.dumps(data),
            content_type='application/json'
        )
        content = json.loads(response.content)
        self.assertEqual(content["status"], "failed")
        self.assertEqual(content["message"], "Gagal memproses approval harap cek kembali")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
