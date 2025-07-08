import json
from unittest.mock import patch
from datetime import datetime, timedelta
from django.db.models import Sum

from django.conf import settings
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.test import APIClient, APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.apiv2.tests.factories import PdWebModelResultFactory
from juloserver.cfs.constants import TierId
from juloserver.cfs.tests.factories import CfsTierFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes, PaymentStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CreditScoreFactory,
    CustomerFactory,
    ImageFactory,
    LoanFactory,
    PartnerFactory,
    ProductLineFactory,
    ReferralSystemFactory,
    StatusLookupFactory,
    WorkflowFactory,
    RefereeMappingFactory,
    FeatureSettingFactory,
)
from juloserver.julo.utils import display_rupiah
from juloserver.promo.models import PromoHistory
from juloserver.promo.tests.factories import PromoHistoryFactory, PromoCodeFactory
from juloserver.referral.constants import (
    LATEST_REFERRAL_MAPPING_ID,
    ReferralCodeMessage,
    FeatureNameConst,
    ReferralRedisConstant
)
from juloserver.referral.tests.factories import (
    ReferralLevelBenefitFeatureSettingFactory,
    ReferralBenefitHistoryFactory,
)
from juloserver.referral.models import ReferralBenefitHistory
from juloserver.julo.tests.factories import ExperimentSettingFactory
from juloserver.application_flow.factories import (
    ApplicationTagFactory,
    ApplicationPathTagStatusFactory,
)
from juloserver.julo.constants import ExperimentConst
from juloserver.application_form.constants import OfflineBoothConst
from juloserver.application_flow.models import (
    ApplicationPathTagStatus,
    ApplicationPathTag,
)
from juloserver.referral.constants import ReferralPersonTypeConst, ReferralBenefitConst
from juloserver.referral.services import refresh_top_referral_cashbacks

PACKAGE_NAME = 'juloserver.referral.views'


class TestReferralHomeView(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.status_420 = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        cls.status_190 = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        cls.status_330 = StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user, id=123123123, self_referral_code='test')
        self.account = AccountFactory(customer=self.customer, status=self.status_420)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.partner = PartnerFactory(name='julo')
        CreditScoreFactory(application_id=self.application.id, score='B+')
        self.application.update_safely(application_status=self.status_190, partner=self.partner)
        self.referral_system = ReferralSystemFactory(
            extra_data={
                'content': {
                    'header': '11',
                    'body': 'cashback:{} referee:{}',
                    'footer': '33',
                    'message': 'referee:{} code:{}',
                    'terms': 'cashback:{}',
                }
            },
            extra_params={LATEST_REFERRAL_MAPPING_ID: 3},
            referral_bonus_limit=3,
        )
        self.first_loan = LoanFactory(
            account=self.account, application=self.application, customer=self.customer
        )
        self.first_payment = self.first_loan.payment_set.order_by('payment_number').first()
        self.first_payment.update_safely(payment_status=self.status_330)

        # CFS data
        self.cfs_tier = CfsTierFactory(id=TierId.STARTER, point=0, referral_bonus=2000)
        PdWebModelResultFactory(application_id=self.application.id)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SHAREABLE_REFERRAL_IMAGE,
            is_active=True,
            parameters={
                'text': {
                    'coordinates': {'x': 10, 'y': 20},
                    'size': 32,
                },
                'image': 'https://statics.julo.co.id/juloserver/staging/static/images/'
                'ecommerce/juloshop/julo_shop_banner.png',
            },
        )
        self.err_message = 'Mohon maaf, kode referral sedang dalam perbaikan'
        self.promo_code = "RenteePromo"
        self.promo_code_app = PromoCodeFactory(
            promo_code=self.promo_code,
            is_active=True,
            start_date=datetime(2023, 7, 20),
            end_date=datetime(2023, 8, 20),
        )

    def test_referral_code_empty(self):
        self.customer.update_safely(self_referral_code=None)
        response = self.client.get('/api/referral/v1/referral-home/')
        assert response.status_code == HTTP_400_BAD_REQUEST
        assert response.json()['errors'] == [self.err_message]

    def test_referral_system_not_found(self):
        self.referral_system.delete()
        response = self.client.get('/api/referral/v1/referral-home/')
        assert response.status_code == HTTP_400_BAD_REQUEST
        assert response.json()['errors'] == [self.err_message]

    def test_success(self):
        response = self.client.get('/api/referral/v1/referral-home/')
        json_data = response.json()

        self.assertEqual(200, response.status_code)
        resp_data = json_data.get('data')
        self.assertIsNotNone(resp_data, json_data)
        self.assertEqual('cashback:Rp 2.000 referee:Rp 20.000', resp_data.get('body'))
        self.assertEqual('cashback:Rp 2.000', resp_data.get('terms'))
        self.assertEqual('referee:Rp 20.000 code:test', resp_data.get('message'))

        # testcase julover
        self.referral_system.product_code.append(200)
        self.referral_system.save()
        julover_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        julover_workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        self.application.product_line = julover_product_line
        self.application.workflow = julover_workflow
        self.application.save()
        response = self.client.get('/api/referral/v1/referral-home/')
        json_data = response.json()

        self.assertEqual(200, response.status_code)
        resp_data = json_data.get('data')
        self.assertIsNotNone(resp_data, json_data)
        self.assertEqual('cashback:Rp 40.000 referee:Rp 20.000', resp_data.get('body'))
        self.assertEqual('cashback:Rp 40.000', resp_data.get('terms'))
        self.assertEqual('referee:Rp 20.000 code:test', resp_data.get('message'))

    def test_j1_partner_application(self):
        partner = PartnerFactory(name='julo')
        self.application.update_safely(partner=partner)

        response = self.client.get('/api/referral/v1/referral-home/')
        json_data = response.json()

        self.assertEqual(200, response.status_code)
        resp_data = json_data.get('data')
        self.assertIsNotNone(resp_data, json_data)
        self.assertIn('cashback:Rp 2.000 ', resp_data.get('body'), json_data)

    @patch('{}.get_cfs_referral_bonus_by_application'.format(PACKAGE_NAME))
    def test_not_cfs_eligible(self, mock_get_cfs_referral_bonus_by_application):
        mock_get_cfs_referral_bonus_by_application.return_value = None

        response = self.client.get('/api/referral/v1/referral-home/')
        json_data = response.json()

        self.assertEqual(200, response.status_code)
        resp_data = json_data.get('data')
        self.assertIsNotNone(resp_data, json_data)
        self.assertIn('cashback:Rp 40.000 ', resp_data.get('body'), json_data)

    def test_referral_code_check_limit(self):
        # the referral code valid
        response = self.client.get('/api/referral/v1/referral-check-limit/test/')
        assert response.status_code == 200

        response = self.client.get('/api/referral/v1/referral-check-limit/test')
        assert response.status_code == 200

        # the referral code invalid
        RefereeMappingFactory.create_batch(6, referrer=self.customer, referee=CustomerFactory())
        response = self.client.get('/api/referral/v1/referral-check-limit/test/')
        assert response.json()['errors'][0] == ReferralCodeMessage.ERROR.LIMIT

        # the referral code doesn't exist
        response = self.client.get('/api/referral/v1/referral-check-limit/test12/')
        assert response.json()['errors'][0] == ReferralCodeMessage.ERROR.WRONG

    def test_shareable_referral_image_feature_setting(self):
        self.feature_setting.parameters['text'] = ''
        self.feature_setting.save()
        response = self.client.get('/api/referral/v1/referral-home/')
        data = response.json()['data']
        self.assertEquals(data['shareable_referral_image'], None)

        self.feature_setting.update_safely(is_active=False)
        response = self.client.get('/api/referral/v1/referral-home/')
        data = response.json()['data']
        self.assertEquals(data['shareable_referral_image'], None)

    def test_shareable_referral_image_success(self):
        response = self.client.get('/api/referral/v1/referral-home/')
        data = response.json()['data']
        self.assertEquals(
            data['shareable_referral_image']['image_url'], self.feature_setting.parameters['image']
        )
        self.assertEquals(data['shareable_referral_image']['text_x_coordinate'], 10)
        self.assertEquals(data['shareable_referral_image']['text_y_coordinate'], 20)
        self.assertEquals(data['shareable_referral_image']['text_size'], 32)

    @patch('django.utils.timezone.now')
    def test_promo_code_for_application(self, mock_time_zone):
        mock_time_zone.return_value = datetime(2023, 8, 1, 0, 0, 0)
        # the referral code valid
        uri_api = '/api/referral/v1/referral-check-limit/{}/'.format(self.promo_code)
        response = self.client.get(uri_api)
        assert response.status_code == 200

        # the referral code invalid
        self.promo_code_app.is_active = False
        self.promo_code_app.save()
        response = self.client.get(uri_api)
        assert response.json()['errors'][0] == ReferralCodeMessage.ERROR.WRONG

        # other promo code
        code = " CEPATCAIR7 "
        self.promo_code_app.promo_code = "CEPATCAIR7"
        self.promo_code_app.is_active = True
        self.promo_code_app.save()
        response = self.client.get('/api/referral/v1/referral-check-limit/{}/'.format(code))
        assert response.status_code == 200

        # promo code is expired
        self.promo_code_app.start_date = datetime(2023, 8, 2)
        self.promo_code_app.save()
        response = self.client.get(
            '/api/referral/v1/referral-check-limit/{}/'.format(self.promo_code_app.promo_code)
        )
        assert response.json()['errors'][0] == ReferralCodeMessage.ERROR.WRONG

        # the referral code doesn't exist
        response = self.client.get('/api/referral/v1/referral-check-limit/test12/')
        assert response.json()['errors'][0] == ReferralCodeMessage.ERROR.WRONG

        # not found
        response = self.client.get('/api/referral/v1/referral-check-limit//')
        assert response.status_code == 404

    def test_promo_code_for_active_booth(self):
        self.promo_code = 'JULO123'

        # init data
        self.setting = ExperimentSettingFactory(
            code=ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE,
            start_date=datetime.now() - timedelta(minutes=10),
            end_date=datetime.now() + timedelta(days=50),
            is_active=True,
            criteria={'referral_code': [self.promo_code, 'JULO#1']},
            is_permanent=False,
        )
        self.path_tag = ApplicationTagFactory(
            application_tag=OfflineBoothConst.TAG_NAME, is_active=True
        )
        self.path_tag_status = ApplicationPathTagStatusFactory(
            application_tag=OfflineBoothConst.TAG_NAME, status=1
        )

        # the referral code valid
        uri_api = '/api/referral/v1/referral-check-limit/{}/'.format(self.promo_code)
        response = self.client.get(uri_api)
        path_tag = ApplicationPathTagStatus.objects.filter(
            application_tag=OfflineBoothConst.TAG_NAME, status=OfflineBoothConst.SUCCESS_VALUE
        ).last()
        application_path = ApplicationPathTag.objects.filter(
            application_id=self.application.id, application_path_tag_status=path_tag
        ).exists()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(application_path)

        self.setting.update_safely(is_active=False)
        response = self.client.get(uri_api)
        self.assertEqual(response.status_code, 400)


class TestPromoInfoView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_customer_not_found(self):
        response = self.client.get('/api/referral/v1/promo/9999999/')
        assert response.status_code == 200
        self.assertTemplateUsed(response, '404-promo.html')

    def test_campaign_not_found(self):
        response = self.client.get('/api/referral/v1/promo/{}/'.format(self.customer.id))
        assert response.status_code == 200
        self.assertTemplateUsed(response, '404-promo.html')

    def test_promo_history_existed(self):
        account_payment = AccountPaymentFactory()
        # account payment is not paid
        account_payment.status_id = 330
        account_payment.save()
        promo_history = PromoHistoryFactory(
            customer=self.customer,
            account=account_payment.account,
            promo_type='promo-cash-june22.html',
        )
        response = self.client.get('/api/referral/v1/promo/%s/' % self.customer.id)
        assert response.status_code == 200
        self.assertTemplateUsed(response, '404-promo.html')

        # account paymnet not due
        account_payment.status_id = 310
        account_payment.save()
        response = self.client.get('/api/referral/v1/promo/%s/' % self.customer.id)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'promo-cash-june22.html')

    def test_promo_history_not_existed(self):
        # not account
        response = self.client.get('/api/referral/v1/promo/%s/' % self.customer.id)
        assert response.status_code == 200
        self.assertTemplateUsed(response, '404-promo.html')

        account_payment = AccountPaymentFactory()
        # account payment is not paid
        account_payment.status_id = 330
        account_payment.save()
        account_payment.account.customer = self.customer
        account_payment.account.save()
        response = self.client.get('/api/referral/v1/promo/%s/' % self.customer.id)
        assert response.status_code == 200
        self.assertTemplateUsed(response, '404-promo.html')

        # account paymnet not due
        account_payment.status_id = 310
        account_payment.save()
        response = self.client.get('/api/referral/v1/promo/%s/' % self.customer.id)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'promo-cash-june22.html')
        self.assertIsNotNone(PromoHistory.objects.get_or_none(account=account_payment.account))


class TestReferralHomeV2View(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.status_420 = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        cls.status_190 = StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        cls.status_330 = StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)

    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user, id=123123123, self_referral_code='referral_code_test')
        self.account = AccountFactory(customer=self.customer, status=self.status_420)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.partner = PartnerFactory(name='julo')
        CreditScoreFactory(application_id=self.application.id, score='B+')
        self.application.update_safely(application_status=self.status_190, partner=self.partner)
        self.referral_system = ReferralSystemFactory(
            extra_data={
                'content': {
                    'header': '11',
                    'body': 'cashback:{} referee:{}',
                    'image': 'https://statics.julo.co.id/juloserver/staging/static/images/',
                    'footer': '33',
                    'message': 'referee:{} code:{}',
                    'terms': 'cashback:{}',
                }
            },
            extra_params={LATEST_REFERRAL_MAPPING_ID: 3},
            referral_bonus_limit=3,
            # caskback_amount=50000,
            referee_cashback_amount=300000
        )
        ImageFactory(
            image_source=self.referral_system.id,
            image_type="referral_promo",
            url='image/test'
        )
        self.first_loan = LoanFactory(
            account=self.account, application=self.application, customer=self.customer
        )
        self.first_payment = self.first_loan.payment_set.order_by('payment_number').first()
        self.first_payment.update_safely(payment_status=self.status_330)

        # CFS data
        self.cfs_tier = CfsTierFactory(id=TierId.STARTER, point=0, referral_bonus=24000)
        PdWebModelResultFactory(application_id=self.application.id)

        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.feature_setting = ReferralLevelBenefitFeatureSettingFactory()
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SHAREABLE_REFERRAL_IMAGE,
            is_active=True,
            parameters={
                'text': {
                    'coordinates': {'x': 10, 'y': 20},
                    'size': 32,
                },
                'image': 'https://statics.julo.co.id/banner.png',
            },
        )
        self.err_message = 'Mohon maaf, kode referral sedang dalam perbaikan'
        self.promo_code = "RenteePromo"
        self.promo_code_app = PromoCodeFactory(
            promo_code=self.promo_code,
            is_active=True,
            start_date=datetime(2023, 7, 20),
            end_date=datetime(2023, 8, 20),
        )

        self.url = '/api/referral/v2/referral-home/'
        self.fake_redis = MockRedisHelper()

        self.lt_190_key = ReferralRedisConstant.REFEREE_CODE_USED_COUNT.format(
            self.customer.id
        )
        self.gte_190_key = ReferralRedisConstant.REFEREE_ALREADY_APPROVED_COUNT.format(
            self.customer.id
        )
        self.counting_referees_disbursement_key = \
            ReferralRedisConstant.COUNTING_REFEREES_DISBURSEMENT_KEY.format(self.customer.id)
        self.total_referees_bonus_amount_key = \
            ReferralRedisConstant.TOTAL_REFERRAL_BONUS_AMOUNT_KEY.format(self.customer.id)

    @patch('juloserver.referral.services.get_redis_client')
    def test_get_success(self, mock_redis_client):
        mock_redis_client.return_value = self.fake_redis
        self.fake_redis.set(self.lt_190_key, 2)
        self.fake_redis.set(self.gte_190_key, 3)
        self.fake_redis.set(self.counting_referees_disbursement_key, 4)
        self.fake_redis.set(self.total_referees_bonus_amount_key, 200000)

        resp = self.client.get(self.url)
        json_data = resp.json()
        resp_data = json_data.get('data')

        self.assertEqual(resp_data.get('header'), '11')
        self.assertEqual(resp_data.get('image'), settings.JULOFILES_BUCKET_URL + 'image/test')
        self.assertEqual(resp_data.get('referral_code'), 'referral_code_test')
        self.assertEqual(resp_data.get('message'),
                         'referee:{} code:{}'.format(display_rupiah(300000), 'referral_code_test'))
        self.assertEqual(resp_data.get('terms'), 'cashback:{}'.format(display_rupiah(24000)))
        self.assertEqual(int(resp_data.get('referee_registered')), 2)
        self.assertEqual(int(resp_data.get('referee_approved')), 3)
        self.assertEqual(int(resp_data.get('referee_disbursed')), 4)
        self.assertEqual(int(resp_data.get('total_cashback')), 200000)
        self.assertEqual(resp_data.get('shareable_referral_image')['text_x_coordinate'], 10)
        self.assertEqual(resp_data.get('shareable_referral_image')['text_y_coordinate'], 20)
        self.assertEqual(resp_data.get('shareable_referral_image')['text_size'], 32)
        self.assertEqual(
            resp_data.get('shareable_referral_image')['image_url'],
            'https://statics.julo.co.id/banner.png'
        )

    @patch('juloserver.referral.services.get_redis_client')
    def test_additional_data_exists(self, mock_redis_client):
        mock_redis_client.return_value = self.fake_redis
        self.fake_redis.set(self.lt_190_key, 2)
        self.fake_redis.set(self.gte_190_key, 3)
        self.fake_redis.set(self.counting_referees_disbursement_key, 4)
        self.fake_redis.set(self.total_referees_bonus_amount_key, 200000)

        info_content = 'info_content abc123'
        resp = self.client.get(self.url)
        json_data = resp.json()
        resp_data = json_data.get('data')

        self.assertIsNone(resp_data.get('additional_info'))

        fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.ADDITIONAL_INFO,
            is_active=True,
            category='referral',
            parameters={
                'info_content': info_content
            },
        )
        fs.save()

        resp = self.client.get(self.url)
        json_data = resp.json()
        resp_data = json_data.get('data')
        self.assertEqual(resp_data.get('additional_info'), info_content)


class TestTopReferralCashbacksView(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user, fullname="Albert")
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        # Create some referral benefit history entries
        self.referral_benefit_history = ReferralBenefitHistoryFactory(
            customer=self.customer,
            referral_person_type=ReferralPersonTypeConst.REFERRER,
            benefit_unit=ReferralBenefitConst.CASHBACK,
            amount=100000
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.TOP_REFERRAL_CASHBACKS,
            is_active=True,
            parameters={
                'message': '{customer_name} just got {amount} thousands cashback from referral!',
                'top_referral_cashbacks_limit': 20,
            },
        )

    @patch('juloserver.referral.services.get_top_referral_cashbacks')
    @patch('juloserver.referral.services.get_redis_client')
    def test_get_top_cashbacks_success(self, mock_redis_client, mock_cache):
        mock_redis_client.return_value.get.return_value = json.dumps(
            ['A***** just got Rp 100.000 thousands cashback from referral!']
        )
        mock_cache.return_value =  ['A***** just got Rp 100.000 thousands cashback from referral!']

        response = self.client.get('/api/referral/v2/top-referral-cashbacks/')
        self.assertEqual(response.status_code, 200)

        data = response.json()['data']['top_cashbacks']
        self.assertEqual(data, ['A***** just got Rp 100.000 thousands cashback from referral!'])

    @patch('juloserver.referral.tasks.refresh_top_referral_cashbacks')
    def test_refresh_cache_task(self, mock_refresh):
        from juloserver.referral.tasks import refresh_top_referral_cashbacks_cache
        
        refresh_top_referral_cashbacks_cache()
        mock_refresh.assert_called_once()
