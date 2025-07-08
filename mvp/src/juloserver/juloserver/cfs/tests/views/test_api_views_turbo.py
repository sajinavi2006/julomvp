from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountPropertyFactory
from juloserver.julo.constants import (
    FeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.cfs.tests.factories import (
    CashbackBalanceFactory,
    CfsActionPointsAssignmentFactory,
    CfsActionPointsFactory,
    CfsTierFactory,
    EntryGraduationListFactory,
    PdClcsPrimeResultFactory,
    TotalActionPointsHistoryFactory,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    PaymentFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ApplicationUpgradeFactory,
)
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory

PACKAGE_NAME = 'juloserver.cfs.views.api_views'


class TestCfsTurbo(APITestCase):
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
        self.account_property = AccountPropertyFactory(account=self.account)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.workflow_turbo = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.product_line_turbo = ProductLineFactory(product_line_code=ProductLineCodes.TURBO)
        self.application_turbo = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow_turbo,
            product_line=self.product_line_turbo,
        )
        self.application_turbo.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application_turbo.save()
        self.application_j1 = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line_j1,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        )
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_turbo.id,
            application_id_first_approval=self.application_turbo.id,
            is_upgrade=1,
        )
        self.application_turbo.save()
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
        PdCreditModelResultFactory(application_id=self.application_turbo.id, pgood=0.8)
        CfsTierFactory(id=1, name='Starter', point=100, icon='123.pnj')
        CfsTierFactory(id=2, name='Advanced', point=300, icon='123.pnj')
        CfsTierFactory(id=3, name='Pro', point=600, icon='123.pnj')
        CfsTierFactory(id=4, name='Champion', point=1000, icon='123.pnj')

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


class TestCfsTierTurbo(APITestCase):
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
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.product_line_turbo = ProductLineFactory(product_line_code=ProductLineCodes.TURBO)
        self.application_turbo = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            product_line=self.product_line_turbo,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.application_j1 = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            product_line=self.product_line_j1,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        )
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_turbo.id,
            application_id_first_approval=self.application_turbo.id,
            is_upgrade=1,
        )
        CfsTierFactory(id=1, name='Starter', point=100)
        CfsTierFactory(id=2, name='Advanced', point=300)
        CfsTierFactory(id=3, name='Pro', point=600)
        CfsTierFactory(id=4, name='Champion', point=1000)

    def test_get_tiers(self):
        today = timezone.localtime(timezone.now()).date()
        PdCreditModelResultFactory(application_id=self.application_turbo.id, pgood=0.8)
        PdClcsPrimeResultFactory(
            customer_id=self.customer.id, partition_date=today, clcs_prime_score=0.5
        )
        response = self.client.get('/api/cfs/v1/get_tiers')
        assert response.status_code == 200


class TestCustomerJScoreTurbo(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.product_line_turbo = ProductLineFactory(product_line_code=ProductLineCodes.TURBO)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application_turbo = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            product_line=self.product_line_turbo,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.application_j1 = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            product_line=self.product_line_j1,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        )
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_turbo.id,
            application_id_first_approval=self.application_turbo.id,
            is_upgrade=1,
        )
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
        PdCreditModelResultFactory(application_id=self.application_turbo.id, pgood=0.8)
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


class TestPageAccessibilityTurbo(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.product_line_j1 = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.product_line_turbo = ProductLineFactory(product_line_code=ProductLineCodes.TURBO)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )
        self.application_turbo = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            product_line=self.product_line_turbo,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.application_j1 = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            product_line=self.product_line_j1,
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.FORM_PARTIAL)
        )
        self.application_upgrade = ApplicationUpgradeFactory(
            application_id=self.application_turbo.id,
            application_id_first_approval=self.application_turbo.id,
            is_upgrade=1,
        )

    def test_get_page_acessibility(self):
        EntryGraduationListFactory(customer_id=self.customer.id, account_id=self.account.id)
        response = self.client.get(f'/api/cfs/v1/get_page_accessibility')

        self.assertEqual(response.status_code, 200)
