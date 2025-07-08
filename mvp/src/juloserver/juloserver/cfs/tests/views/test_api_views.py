import datetime

from factory import Iterator
from mock import patch
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory, AccountLimitFactory, AccountPropertyFactory
)
from juloserver.cfs.models import CfsActionAssignment
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.cfs.tests.factories import (
    CashbackBalanceFactory,
    CfsActionAssignmentFactory,
    CfsActionFactory,
    CfsActionPointsAssignmentFactory,
    CfsActionPointsFactory,
    CfsTierFactory,
    EntryGraduationListFactory,
    ImageFactory,
    PdClcsPrimeResultFactory,
    TotalActionPointsHistoryFactory,
    CfsAssignmentVerificationFactory,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    MobileFeatureSettingFactory,
    PaymentFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ApplicationJ1Factory,
)
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.cfs.constants import (
    CfsProgressStatus,
    VerifyStatus,
)
from juloserver.otp.constants import OTPType
from juloserver.julo.models import OtpRequest
import re
from juloserver.cfs.authentication import (
    EasyIncomeTokenAuth
)

PACKAGE_NAME = 'juloserver.cfs.views.api_views'


class TestCfs(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.cashback_balance = CashbackBalanceFactory(customer=self.customer)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'faqs': {
                    'header': 'header',
                    'topics': [{
                        'question': 'question test 1',
                        'answer': 'answer test 1'
                    }]
                },
                "graduation_rules": [
                    {
                        "max_late_payment": 0,
                        "max_account_limit": 300000,
                        "max_grace_payment": 1,
                        "min_account_limit": 100000,
                        "new_account_limit": 500000,
                        "min_percentage_limit_usage": 300,
                        "min_percentage_paid_amount": 100
                    },
                    {
                        "max_late_payment": 0,
                        "max_account_limit": 500000,
                        "max_grace_payment": 1,
                        "min_account_limit": 500000,
                        "new_account_limit": 1000000,
                        "min_percentage_limit_usage": 200,
                        "min_percentage_paid_amount": 100
                    }
                ]
            }
        )
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        CfsTierFactory(id=1, name='Starter', point=100, icon='123.pnj')
        CfsTierFactory(id=2, name='Advanced', point=300, icon='123.pnj')
        CfsTierFactory(id=3, name='Pro', point=600, icon='123.pnj')
        CfsTierFactory(id=4, name='Champion', point=1000, icon='123.pnj')
        FeatureSettingFactory(
            feature_name='otp_switch',
            parameters={
                'message': 'Harap masukkan kode OTP yang telah kami kirim lewat SMS atau Email ke '
                'nomor atau email Anda yang terdaftar.',
            },
            is_active=False,
        )

    def test_get_faqs(self):
        response = self.client.get('/api/cfs/v1/get_faqs')
        assert response.status_code == 200

    def test_application_not_found(self):
        response = self.client.get('/api/cfs/v1/get_status/{}'.format(None))
        assert response.status_code == 404

    @patch('juloserver.boost.services.get_boost_mobile_feature_settings')
    def test_get_mission(self, mock_boost_mobile_setting):
        self.account.status_id = AccountConstant.STATUS_CODE.suspended
        self.account.save()
        response = self.client.get('/api/cfs/v1/get_missions/{}'.format(self.application.id))
        assert response.status_code == 417

        mock_boost_mobile_setting.return_value.parameters = {
            "bank": {
                'is_active': True,
            },
            "bpjs": {
                'is_active': True,
            }
        }
        self.account.status_id = AccountConstant.STATUS_CODE.active
        self.account.save()
        response = self.client.get('/api/cfs/v1/get_missions/{}'.format(self.application.id))
        assert response.status_code == 200

    def test_get_status(self):
        self.account_property = AccountPropertyFactory(account=self.account, is_entry_level=True)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.account.status_id = AccountConstant.STATUS_CODE.active
        self.account.save()
        response = self.client.get('/api/cfs/v1/get_status/{}'.format(self.application.id))
        assert response.status_code == 200

    def test_claim_rewards(self):
        data = {
            'action_assignment_id': 5,
        }
        response = self.client.post(
            '/api/cfs/v1/claim_rewards/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 404
        assert response.json()['errors'] == ['Assignment not found']

        self.action = CfsActionFactory(
            id=11,
            is_active=True,
            action_code='verify_office_phone_number',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        self.cfs_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.action,
            repeat_action_no=1,
            cashback_amount=5000,
            progress_status=CfsProgressStatus.PENDING
        )
        data = {
            'action_assignment_id': self.cfs_action_assignment.id,
        }
        response = self.client.post(
            '/api/cfs/v1/claim_rewards/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 400
        assert response.json()['errors'] == ['Invalid assignment status']

        self.cfs_action_assignment.progress_status = CfsProgressStatus.UNCLAIMED
        self.cfs_action_assignment.extra_data = {
            'cashback_amount': 5000,
            'default_expiry': 90,
            'multiplier': 1.5
        }
        self.cfs_action_assignment.save()
        data = {
            'action_assignment_id': self.cfs_action_assignment.id,
        }
        response = self.client.post(
            '/api/cfs/v1/claim_rewards/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 200

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_do_mission_upload_document(self, mock_send_cfs_ga_event):
        self.image = ImageFactory(image_source=self.application.id)
        data = {
            'image_id': self.image.id,
            'document_type': 1,
        }
        response = self.client.post(
            '/api/cfs/v1/do_mission/upload_document/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 400
        assert response.json()['errors'] == ['Invalid Image']

        self.image.image_type = 'paystub'
        self.image.save()
        response = self.client.post(
            '/api/cfs/v1/do_mission/upload_document/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 404
        assert response.json()['errors'] == ['Action not found']

        self.action = CfsActionFactory(
            id=5,
            is_active=True,
            action_code='upload_salary_slip',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/111.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=2000,
            repeat_occurrence_cashback_amount=500
        )
        response = self.client.post(
            '/api/cfs/v1/do_mission/upload_document/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 200

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    @patch('juloserver.cfs.services.core_services.check_distance_more_than_1_km')
    def test_do_mission_verify_address(self, mock_check_distance_more_than_1_km,
                                       mock_send_cfs_ga_event):
        mock_check_distance_more_than_1_km.return_value = False, {
            "device_lat": "-6.2243538",
            "device_long": "106.843988",
            "application_address_lat": "-6.2243538",
            "application_address_long": "106.843988",
            "distance_in_km": 8.6,
            "decision": False,
        }

        data = {
            'latitude': '0.1',
            'longitude': '0.2'
        }

        response = self.client.post(
            '/api/cfs/v1/do_mission/verify_address/{}'.format(self.application.id),
            data=data,
            format='json'
        )

        assert response.status_code == 404
        assert response.json()['errors'] == ['Action not found']

        self.action = CfsActionFactory(
            id=12,
            is_active=True,
            action_code='verify_address',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/222.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=500,
            repeat_occurrence_cashback_amount=100
        )

        mock_check_distance_more_than_1_km.return_value = False, {
            "device_lat": "-6.2243538",
            "device_long": "106.843988",
            "application_address_lat": "-6.2243538",
            "application_address_long": "106.843988",
            "distance_in_km": 8.6,
            "decision": False,
        }

        data = {
            'latitude': '0.1',
            'longitude': '0.2'
        }

        response = self.client.post(
            '/api/cfs/v1/do_mission/verify_address/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 400
        action_assignment_failed = CfsActionAssignment.objects.filter(
            customer=self.customer, action_id=12
        ).last()
        self.assertEqual(action_assignment_failed.progress_status, CfsProgressStatus.FAILED)

        mock_check_distance_more_than_1_km.return_value = True, {
            "device_lat": "-6.2243538",
            "device_long": "106.843988",
            "application_address_lat": "-6.2243538",
            "application_address_long": "106.843988",
            "distance_in_km": 8.6,
            "decision": True,
        }

        data = {
            'latitude': '0.1',
            'longitude': '0.2'
        }
        response = self.client.post(
            '/api/cfs/v1/do_mission/verify_address/{}'.format(self.application.id),
            data=data,
            format='json'
        )

        assert response.status_code == 200

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_do_mission_connect_bpjs(self, mock_send_cfs_ga_event):
        data = {
            'bank_name': 'bri',
        }
        response = self.client.post(
            '/api/cfs/v1/do_mission/connect_bpjs/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 404
        assert response.json()['errors'] == ['Action not found']

        self.action = CfsActionFactory(
            id=3,
            is_active=True,
            action_code='connect_bpjs',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        response = self.client.post(
            '/api/cfs/v1/do_mission/connect_bpjs/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 200

        response = self.client.post(
            '/api/cfs/v1/do_mission/connect_bpjs/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 400
        self.assertEqual(response.data['errors'], ['Invalid status change'])

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_do_mission_add_related_phone(self, mock_send_cfs_ga_event):
        data = {
            'phone_related_type': 2,
            'company_name': 'Julo',
            "phone_number": "0123456789",
        }
        self.action = CfsActionFactory(
            id=11,
            is_active=True,
            action_code='verify_office_phone_number',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        response = self.client.post(
            '/api/cfs/v1/do_mission/add_related_phone/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 200

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_do_mission_share_social_media(self, mock_send_cfs_ga_event):
        self.action = CfsActionFactory(
            id=13,
            is_active=True,
            action_code='share_to_social_media',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        data = {
            'app_name': 'instagram',
        }
        response = self.client.post(
            '/api/cfs/v1/do_mission/share_social_media/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 200

    @patch('juloserver.cfs.services.core_services.send_cfs_ga_event')
    def test_do_mission_verify_phone_1(self, mock_send_cfs_ga_event):
        self.client = APIClient()
        self.client_wo_auth = APIClient()
        self.user = AuthUserFactory()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.application.save()
        PdCreditModelResultFactory(id=122, application_id=self.application.id, pgood=0.8)
        self.token = self.user.auth_expiry_token.key
        self.otp_action_setting = FeatureSettingFactory(
            feature_name='otp_action_type',
            parameters={
                'login': 'short_lived',
                'verify_phone_number': 'short_lived'
            }
        )
        self.action = CfsActionFactory(
            id=7,
            is_active=True,
            action_code='verify_phone_number_1',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        data = {
            "otp_service_type": "sms",
            "action_type": "verify_phone_number",
            "phone_number": "081218926858",
        }
        self.mfs = MobileFeatureSettingFactory(
            feature_name='otp_setting',
            parameters={
                'mobile_phone_1': {
                    'otp_max_request': 2,
                    'otp_resend_time_sms': 180,
                    'otp_resend_time_miscall': 180,
                    "otp_resend_time_experiment": 60,
                    'otp_max_validate': 3,
                },
                'wait_time_seconds': 400
            }
        )
        result = self.client.post('/api/otp/v2/request', data=data)
        self.assertEqual(result.json()['data']['is_feature_active'], True)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token)
        otp_request = OtpRequest.objects.filter(
            customer=self.customer,
            otp_service_type__in=[OTPType.SMS]
        ).latest('id')
        result = self.client.post(
            '/api/otp/v1/validate',
            data={
                'otp_token': otp_request.otp_token,
                'action_type': 'verify_phone_number'
            }
        )
        session_token = result.json()['data']['session_token']
        self.assertEqual(result.status_code, 200)

        data = {
            'session_token': session_token
        }
        response = self.client.post(
            '/api/cfs/v1/do_mission/verify_phone_number_1/{}'.format(self.application.id),
            data=data,
            format='json'
        )
        assert response.status_code == 200

    def test_cfs_notification_action(self):
        data = {}
        response = self.client.post(
            '/api/cfs/v1/validate/notification',
            data=data,
            format='json'
        )
        assert response.status_code == 400

        data['action'] = "asdf"
        response = self.client.post(
            '/api/cfs/v1/validate/notification',
            data=data,
            format='json'
        )
        assert response.status_code == 400

        data['action'] = "cfs"
        response = self.client.post(
            '/api/cfs/v1/validate/notification',
            data=data,
            format='json'
        )
        assert response.status_code == 200

    def test_get_cfs_status_not_eligible(self):
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.application.product_line = product_line
        self.application.save()

        response = self.client.get(f'/api/cfs/v1/get_status/{self.application.id}')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['errors'][0], 'Not eligible for CFS')


class TestCfsTier(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        CfsTierFactory(id=1, name='Starter', point=100)
        CfsTierFactory(id=2, name='Advanced', point=300)
        CfsTierFactory(id=3, name='Pro', point=600)
        CfsTierFactory(id=4, name='Champion', point=1000)

    def test_get_tiers(self):
        today = timezone.localtime(timezone.now()).date()
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id, partition_date=today, clcs_prime_score=0.5
        )
        response = self.client.get('/api/cfs/v1/get_tiers')
        assert response.status_code == 200


class TestCustomerJScore(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        CfsTierFactory(id=1, name='Starter', point=100)
        CfsTierFactory(id=2, name='Advanced', point=300)
        CfsTierFactory(id=3, name='Pro', point=600)
        CfsTierFactory(id=4, name='Champion', point=1000)
        self.cfs_action_points = CfsActionPointsFactory(
            id=1, description='transact', multiplier=0.001, floor=5, ceiling=25, default_expiry=180
        )
        self.status = StatusLookupFactory()
        self.status.status_code = 220
        self.status.save()
        self.loan = LoanFactory(customer=self.customer, loan_status=self.status)
        self.payment = PaymentFactory(loan=self.loan)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
            parameters={
                'jscore_messages': [
                    {
                        'max_value': 100000,
                        'min_value': 0,
                        'message': 'Selemat! Jscore kamu bertambah. Yuk, pertahankan dan '
                                   'tingkatkan lagi skor kredit kamu!',
                    },
                    {
                        'max_value': -1,
                        'min_value': -100,
                        'message': 'Yuk, tetap bayar tepat waktu untuk pertahankan Jscore kamu',
                    },
                    {
                        'max_value': -101,
                        'min_value': -300,
                        'message': 'Wah Jscore kamu berpotensi menurun. Tingkatkan transaksi dan '
                                   'bayar tepat waktu agar Jscore stabil',
                    },
                    {
                        'max_value': -301,
                        'min_value': -100000,
                        'message': 'Duh! Jscore kamu menurun, nih. Perbaiki score dengan '
                                   'bertransaksi dan jangan telat bayar tagihan.',
                    },
                ]
            }
        )

    def test_get_customer_j_score_histories(self):
        today = timezone.localtime(timezone.now()).date()
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        ps_clcs_prime_result = PdClcsPrimeResultFactory(
            customer_id=self.customer.id, partition_date=today, clcs_prime_score=0.5
        )
        self.cfs_action_point_assignment = CfsActionPointsAssignmentFactory(
            customer_id=self.customer.id,
            loan_id=self.loan.id,
            payment_id=self.payment.id,
            cfs_action_points_id=self.cfs_action_points.id
        )
        action_points_history = TotalActionPointsHistoryFactory(
            customer_id=self.customer.id,
            cfs_action_point_assignment_id=self.cfs_action_point_assignment.id,
            partition_date=timezone.localtime(timezone.now()).date(),
            new_point=10,
            change_reason='action_points'
        )
        response = self.client.get('/api/cfs/v1/get_customer_j_score_histories')
        assert response.status_code == 200
        j_score_histories = response.json()['data']['j_score_histories']
        self.assertEqual(
            j_score_histories[0]['message'],
            'Selemat! Jscore kamu bertambah. Yuk, pertahankan dan tingkatkan lagi skor kredit kamu!'
        )

        ps_clcs_prime_result.clcs_prime_score = 0.01
        ps_clcs_prime_result.save()

        action_points_history.update_safely(new_point=-99)
        response = self.client.get('/api/cfs/v1/get_customer_j_score_histories')
        j_score_histories = response.json()['data']['j_score_histories']
        self.assertEqual(
            j_score_histories[0]['message'],
            'Yuk, tetap bayar tepat waktu untuk pertahankan Jscore kamu'
        )

        action_points_history.update_safely(new_point=-250)
        response = self.client.get('/api/cfs/v1/get_customer_j_score_histories')
        j_score_histories = response.json()['data']['j_score_histories']
        self.assertEqual(
            j_score_histories[0]['message'],
            'Wah Jscore kamu berpotensi menurun. Tingkatkan transaksi dan bayar tepat waktu '
            'agar Jscore stabil'
        )

        action_points_history.update_safely(new_point=-1500)
        response = self.client.get('/api/cfs/v1/get_customer_j_score_histories')
        j_score_histories = response.json()['data']['j_score_histories']
        self.assertEqual(
            j_score_histories[0]['message'],
            'Duh! Jscore kamu menurun, nih. Perbaiki score dengan bertransaksi dan jangan telat '
            'bayar tagihan.'
        )


class TestPageAccessibility(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

    def test_get_page_acessibility(self):
        EntryGraduationListFactory(customer_id=self.customer.id, account_id=self.account.id)
        response = self.client.get(f'/api/cfs/v1/get_page_accessibility')

        self.assertEqual(response.status_code, 200)


class TestCfsAssignmentActionConnectBank(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationJ1Factory(customer=self.customer)
        PdCreditModelResultFactory(application_id=self.application.id, pgood=0.8)
        self.cfs_action = CfsActionFactory(
            id=2,
            is_active=True,
            action_code='connect_bank',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/333.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=5000,
            repeat_occurrence_cashback_amount=1000
        )
        CfsTierFactory(id=1, name='Starter', point=100, icon='123.pnj')
        CfsTierFactory(id=2, name='Advanced', point=300, icon='123.pnj')
        CfsTierFactory(id=3, name='Pro', point=600, icon='123.pnj')
        CfsTierFactory(id=4, name='Champion', point=1000, icon='123.pnj')

    def test_post(self):
        url = f'/api/cfs/v1/do_mission/connect_bank/{self.application.id}'
        response = self.client.post(url)

        self.assertEqual(200, response.status_code)
        self.assertEqual('Berhasil', response.data['data']['message'])


class TestCustomerJScoreHistoryDetails(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.cfs_action_points = CfsActionPointsFactory(id=99999)

        cfs_action_point_assignments_batch = CfsActionPointsAssignmentFactory.create_batch(
            11, customer_id=self.customer.id, cfs_action_points_id=self.cfs_action_points.id
        )
        cfs_action_point_assignments_ids = list(map(
            lambda assignment: assignment.id, cfs_action_point_assignments_batch
        ))

        TotalActionPointsHistoryFactory.create_batch(
            11, customer_id=self.customer.id,
            cfs_action_point_assignment_id=Iterator(cfs_action_point_assignments_ids),
            partition_date=Iterator([
                datetime.datetime(2021, 11, 2).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 3, 7).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 3, 11).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 3, 30).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 7, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 7, 12).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 7, 15).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 7, 20).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 9, 5).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 9, 10).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 9, 20).strftime('%Y-%m-%d')
            ]),
            old_point=Iterator([0, 5, 10, 20, 90, 100, 250, 200, 400, 300, 200]),
            new_point=Iterator([5, 10, 20, 90, 100, 250, 200, 400, 300, 200, 100]),
            change_reason=Iterator([
                'action_points', 'action_expired', 'action_points', 'action_expired',
                'action_expired', 'action_expired', 'action_expired', 'action_expired',
                'action_points', 'action_expired', 'action_expired'
            ])
        )

        PdClcsPrimeResultFactory.create_batch(
            15, customer_id=self.customer.id,
            partition_date=Iterator([
                datetime.datetime(2021, 11, 2).strftime('%Y-%m-%d'),
                datetime.datetime(2021, 12, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 1, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 2, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 3, 11).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 3, 30).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 4, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 5, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 6, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 7, 12).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 7, 15).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 7, 20).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 8, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 9, 10).strftime('%Y-%m-%d'),
                datetime.datetime(2022, 9, 20).strftime('%Y-%m-%d')
            ]),
            clcs_prime_score=Iterator([
                0.7, 0.5, 0.6, 0.8, 0.5, 0.6, 0.7, 0.85, 0.8, 0.8, 0.9, 0.85, 0.7, 0.9, 0.987
            ])
        )

        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.J_SCORE_HISTORY_CONFIG,
            parameters={
                "j_score_history_details": {
                    "action_points": [
                        {
                            "max_value": 999999,
                            "title": "test1",
                            "message": "test1",
                            "min_value": 1
                        },
                        {
                            "max_value": 0,
                            "title": "test2",
                            "message": "test2",
                            "min_value": 0
                        },
                        {
                            "max_value": -1,
                            "title": "test3",
                            "message": "test3",
                            "min_value": -999999
                        }
                    ],
                    "action_expired": [
                        {
                            "max_value": 999999,
                            "title": "test4",
                            "message": "test4",
                            "min_value": 1
                        },
                        {
                            "max_value": 0,
                            "title": "test5",
                            "message": "test5",
                            "min_value": 0
                        },
                        {
                            "max_value": -1,
                            "title": "test6",
                            "message": "test6",
                            "min_value": -999999
                        }
                    ]
                }
            })

    def test_get_month_history_success(self):
        url = '/api/cfs/v1/get_customer_j_score_history_details?month=7&year=2022'
        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":{'
                                      '"action_points":{},'
                                      '"action_expired":{'
                                      '"title":"test4","score":335.0,"message":"test4"'
                                      '}}}')

        url = '/api/cfs/v1/get_customer_j_score_history_details?month=9&year=2022'
        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":'
                                      '{"action_points":{'
                                      '"title":"test3","score":-28.5,"message":"test3"'
                                      '},'
                                      '"action_expired":{'
                                      '"title":"test6","score":-128.5,"message":"test6"'
                                      '}}}')

        url = '/api/cfs/v1/get_customer_j_score_history_details?month=3&year=2022'
        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":'
                                      '{"action_points":{'
                                      '"title":"test3","score":-40.0,"message":"test3"'
                                      '},'
                                      '"action_expired":{'
                                      '"title":"test4","score":25.0,"message":"test4"'
                                      '}}}')

    def test_get_month_history_empty(self):
        url = '/api/cfs/v1/get_customer_j_score_history_details?month=6&year=2022'
        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":'
                                      '{"action_points":{},'
                                      '"action_expired":{}}}')

        url = '/api/cfs/v1/get_customer_j_score_history_details?month=12&year=2021'
        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":'
                                      '{"action_points":{},'
                                      '"action_expired":{}}}')

        url = '/api/cfs/v1/get_customer_j_score_history_details?month=4&year=2022'
        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":'
                                      '{"action_points":{},'
                                      '"action_expired":{}}}')

    def test_get_first_month_history(self):
        url = '/api/cfs/v1/get_customer_j_score_history_details?month=11&year=2021'
        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":'
                                      '{"action_points":{},'
                                      '"action_expired":{}}}')

    def test_get_invalid_month_history(self):
        url = '/api/cfs/v1/get_customer_j_score_history_details?month=-11&year=1999'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

        url = '/api/cfs/v1/get_customer_j_score_history_details?month=wormy1&year=potato'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

        url = '/api/cfs/v1/get_customer_j_score_history_details?month=-11&year=cat'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

        url = '/api/cfs/v1/get_customer_j_score_history_details?month=&year='
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    def test_multiple_clcs_prime_score_before_user_make_loan(self):
        PdClcsPrimeResultFactory.create_batch(
            5, customer_id=self.customer.id,
            partition_date=Iterator([
                datetime.datetime(2021, 6, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2021, 7, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2021, 8, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2021, 9, 1).strftime('%Y-%m-%d'),
                datetime.datetime(2021, 10, 11).strftime('%Y-%m-%d')
            ]),
            clcs_prime_score=Iterator([
                0.9, 0.8, 0.7, 0.6, 0.5
            ])
        )

        url = '/api/cfs/v1/get_customer_j_score_history_details?month=11&year=2021'
        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":'
                                      '{"action_points":{'
                                      '"title":"test1","score":105.0,"message":"test1"'
                                      '},'
                                      '"action_expired":{}}}')

    def test_is_active_false(self):
        """
        Purpose: test if the response is empty if the feature is turned off (is_active = False)
            Expected result: {}
        """
        url = '/api/cfs/v1/get_customer_j_score_history_details?month=6&year=2022'
        self.feature_setting.is_active = False
        self.feature_setting.save()

        response = self.client.get(url)
        self.assertContains(response, '{"j_score_history_details":{}}')


class TestEasyIncome(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.upload_salary_slip_action = CfsActionFactory(
            id=5,
            is_active=True,
            action_code='upload_salary_slip',
            default_expiry=90,
            icon="https://julostatics.oss-ap-southeast-5.aliyuncs.com/cfs/111.png",
            app_link="deeplink",
            first_occurrence_cashback_amount=2000,
            repeat_occurrence_cashback_amount=500
        )
        self.upload_bank_statement_action = CfsActionFactory(
            id=6,
            is_active=True,
            action_code='upload_bank_statement',
            default_expiry=90,
            icon=(
                "https://julostatics.oss-ap-southeast"
                "-5.aliyuncs.com/cfs/upload_utilities_document.png"
            ),
            app_link="deeplink",
            first_occurrence_cashback_amount=50000,
            repeat_occurrence_cashback_amount=50000
        )
        self.upload_credit_card = CfsActionFactory(
            id=16,
            is_active=True,
            action_code='upload_credit_card',
            default_expiry=180,
            icon=(
                "https://julostatics.oss-ap-southeast"
                "-5.aliyuncs.com/cfs/upload_credit_Card.png"
            ),
            app_link="deeplink",
            first_occurrence_cashback_amount=0,
            repeat_occurrence_cashback_amount=0
        )

    def test_mission_web_url(self):
        # both
        web_url_regex = (
            'upload_bank_statement=true&upload_bank_statement_status=start'
            '&upload_salary_slip=true&upload_salary_slip_status=start'
            '&upload_credit_card=true&upload_credit_card_status=start&'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        self.assertIsNotNone(re.search(web_url_regex, web_url))

        # upload_bank_statement
        web_url_regex = (
            r'upload_bank_statement\/\?'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url?action=upload_bank_statement'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        self.assertIsNotNone(re.search(web_url_regex, web_url))

        # upload_salary_slip
        web_url_regex = (
            r'upload_salary_slip\/\?'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url?action=upload_salary_slip'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        self.assertIsNotNone(re.search(web_url_regex, web_url))

    def test_mission_web_url_pending_status(self):
        upload_salary_slip_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_salary_slip_action,
            repeat_action_no=1,
            cashback_amount=5000,
            progress_status=CfsProgressStatus.PENDING
        )
        upload_bank_statement_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_bank_statement_action,
            repeat_action_no=1,
            cashback_amount=10000,
            progress_status=CfsProgressStatus.PENDING
        )
        CfsAssignmentVerificationFactory(
            account=self.account,
            cfs_action_assignment=upload_salary_slip_action_assignment
        )
        CfsAssignmentVerificationFactory(
            account=self.account,
            cfs_action_assignment=upload_bank_statement_action_assignment
        )

        web_url_regex = (
            'upload_bank_statement=true&upload_bank_statement_status=in_progress'
            '&upload_salary_slip=true&upload_salary_slip_status=in_progress'
            '&upload_credit_card=true&upload_credit_card_status=start&'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        self.assertIsNotNone(re.search(web_url_regex, web_url))


    def test_mission_web_url_approve_reject_status(self):
        upload_salary_slip_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_salary_slip_action,
            repeat_action_no=1,
            cashback_amount=5000,
            progress_status=CfsProgressStatus.START
        )
        upload_bank_statement_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_bank_statement_action,
            repeat_action_no=1,
            cashback_amount=10000,
            progress_status=CfsProgressStatus.UNCLAIMED,
            expiry_date=timezone.localtime(timezone.now() + datetime.timedelta(days=90))
        )
        CfsAssignmentVerificationFactory(
            account=self.account,
            cfs_action_assignment=upload_salary_slip_action_assignment,
            verify_status=VerifyStatus.REFUSE
        )
        CfsAssignmentVerificationFactory(
            account=self.account,
            cfs_action_assignment=upload_bank_statement_action_assignment,
            verify_status=VerifyStatus.APPROVE
        )
        CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_credit_card,
            repeat_action_no=1,
            cashback_amount=5000,
            progress_status=CfsProgressStatus.START
        )

        web_url_regex = (
            'upload_bank_statement=false&upload_bank_statement_status=approved'
            '&upload_salary_slip=true&upload_salary_slip_status=rejected'
            '&upload_credit_card=true&upload_credit_card_status=start&'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        self.assertIsNotNone(re.search(web_url_regex, web_url))


    @patch('django.utils.timezone.now')
    def test_mission_web_url_reset_approve_status(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 9, 16, 12, 23, 34)
        upload_bank_statement_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_bank_statement_action,
            repeat_action_no=1,
            cashback_amount=10000,
            progress_status=CfsProgressStatus.CLAIMED,
            expiry_date=datetime.datetime(2024, 9, 20, 12, 23, 34)
        )
        CfsAssignmentVerificationFactory(
            account=self.account,
            cfs_action_assignment=upload_bank_statement_action_assignment,
            verify_status=VerifyStatus.APPROVE
        )
        CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_credit_card,
            repeat_action_no=1,
            cashback_amount=10000,
            progress_status=CfsProgressStatus.START,
        )

        web_url_regex = (
            'upload_bank_statement=false&upload_bank_statement_status=approved'
            '&upload_salary_slip=true&upload_salary_slip_status=start'
            '&upload_credit_card=true&upload_credit_card_status=start&'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        self.assertIsNotNone(re.search(web_url_regex, web_url))

        upload_bank_statement_action_assignment.update_safely(
            progress_status=CfsProgressStatus.CLAIMED,
            expiry_date=datetime.datetime(2024, 9, 10, 12, 23, 34)
        )
        web_url_regex = (
            'upload_bank_statement=true&upload_bank_statement_status=start'
            '&upload_salary_slip=true&upload_salary_slip_status=start'
            '&upload_credit_card=true&upload_credit_card_status=start&'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        self.assertIsNotNone(re.search(web_url_regex, web_url))


    @patch('django.utils.timezone.now')
    def test_mission_web_url_reset_other_status(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 9, 16, 12, 23, 34)
        upload_bank_statement_action_assignment = CfsActionAssignmentFactory(
            customer=self.customer,
            action=self.upload_bank_statement_action,
            repeat_action_no=1,
            cashback_amount=10000,
            progress_status=CfsProgressStatus.PENDING
        )
        upload_bank_statement_verification = CfsAssignmentVerificationFactory(
            cdate=datetime.datetime(2024, 7, 16, 12, 23, 34),
            account=self.account,
            cfs_action_assignment=upload_bank_statement_action_assignment
        )

        web_url_regex = (
            'upload_bank_statement=true&upload_bank_statement_status=in_progress'
            '&upload_salary_slip=true&upload_salary_slip_status=start'
            '&upload_credit_card=true&upload_credit_card_status=start&'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        self.assertIsNotNone(re.search(web_url_regex, web_url))

        upload_bank_statement_verification.update_safely(
            cdate=datetime.datetime(2024, 5, 16, 12, 23, 34)
        )
        web_url_regex = (
            'upload_bank_statement=true&upload_bank_statement_status=start'
            '&upload_salary_slip=true&upload_salary_slip_status=start'
            '&upload_credit_card=true&upload_credit_card_status=start&'
            r'token=[\w-]*\.[\w-]*\.[\w-]*'
        )
        url = '/api/cfs/v1/mission_web_url'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        print(web_url)
        self.assertIsNotNone(re.search(web_url_regex, web_url))


    def test_easy_income_auth_token(self):
        token_regex = r'token=[\w-]*\.[\w-]*\.[\w-]*'
        url = '/api/cfs/v1/mission_web_url'
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        web_url = response_data['data']["url"]
        # retrieve token
        match = re.search(token_regex, web_url)
        self.assertIsNotNone(match)
        token = match[0].replace("token=", "")

        # validate token
        auth_obj = EasyIncomeTokenAuth()
        user, token = auth_obj.authenticate_credentials(token)

        self.assertEqual(self.user.id, user.id)
