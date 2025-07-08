import datetime
import mock
from django.test.testcases import TestCase
from django.db.models import signals
from factory import Iterator
from faker import Faker
from rest_framework.test import APITestCase

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import StatusLookup, Application
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CreditScoreFactory,
    CustomerFactory,
    LoanFactory,
    PartnerFactory,
    ProductLineFactory,
    ReferralSystemFactory,
    StatusLookupFactory,
    WorkflowFactory,
    AuthUserFactory,
    FeatureSettingFactory,
    RefereeMappingFactory
)
from juloserver.moengage.constants import MoengageEventType
from juloserver.referral.services import (
    generate_customer_level_referral_code,
    show_referral_code,
    get_shareable_referral_image,
    get_referral_benefit,
    apply_referral_benefits,
    get_referrer_level_benefit,
    get_referrer_benefits,
    get_referee_benefits,
    generate_referral_code,
    get_referral_benefits_by_level,
    get_referee_information_by_referrer,
    get_current_referral_level,
    get_referees_code_used,
    get_referees_approved_count,
    get_total_referral_invited_and_total_referral_benefits_v2,
)
from juloserver.cfs.tests.factories import (
    CashbackBalanceFactory,
)
from juloserver.referral.constants import (
    FeatureNameConst,
    ReferralBenefitConst,
    ReferralLevelConst,
    ReferralPersonTypeConst,
    ReferralRedisConstant,
)
from juloserver.referral.signals import invalidate_cache_referee_count
from juloserver.referral.tests.factories import (
    ReferralBenefitFactory,
    ReferralLevelFactory,
    ReferralLevelBenefitFeatureSettingFactory,
    ReferralBenefitHistoryFactory,
    ReferralBenefitFeatureSettingFactory,
)
from unittest.mock import patch
from juloserver.loyalty.models import LoyaltyPoint


class TestServiceShowReferralCode(APITestCase):
    def setUp(self):
        signals.post_save.disconnect(invalidate_cache_referee_count, sender=Application)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.partner = PartnerFactory(name='julo')
        self.app = ApplicationFactory(partner=self.partner, product_line=self.product_line)
        self.credit_score = CreditScoreFactory(application_id=self.app.id, score='A')

    def test_show_referral_code(self):
        result = show_referral_code(self.app.customer)
        self.assertFalse(result)

        customer = self.app.customer
        customer.update_safely(self_referral_code='ABCD')
        self.app.refresh_from_db()
        result = show_referral_code(self.app.customer)
        self.assertFalse(result)

        ReferralSystemFactory()
        result = show_referral_code(self.app.customer)
        self.assertFalse(result)

        self.account = AccountFactory(customer=customer)
        self.app.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            account=self.account
        )
        result = show_referral_code(self.app.customer)
        self.assertTrue(result)


class TestServiceGenerateJ1ReferralCode(APITestCase):
    def setUp(self):
        signals.post_save.disconnect(invalidate_cache_referee_count, sender=Application)
        self.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.customer = CustomerFactory(fullname='test')
        self.app = ApplicationFactory(
            workflow=self.workflow, customer=self.customer, product_line=self.product_line
        )
        self.referral_system = ReferralSystemFactory()

    @mock.patch('juloserver.moengage.services.use_cases.update_moengage_referral_event')
    def test_generate_referral_code(self, mock_update_moengage_referral_event):
        status_lookup = StatusLookup.objects.get(status_code=190)
        account = AccountFactory(customer=self.app.customer)
        account.status_id = 420
        account.save()
        self.app.application_status = status_lookup
        self.app.account = account
        self.app.save()
        CreditScoreFactory(application_id=self.app.id, score='B+')
        generate_customer_level_referral_code(self.app)
        self.assertNotEqual(str(self.app.customer.self_referral_code), '')
        mock_update_moengage_referral_event.delay.assert_called_once_with(
            self.customer, MoengageEventType.BEx190_NOT_YET_REFER
        )


class TestServiceGenerateJuloverReferralCode(APITestCase):
    def setUp(self):
        self.workflow = WorkflowFactory(name='Testing')
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.customer = CustomerFactory(fullname='test')
        self.partner = PartnerFactory(name='julovers')
        self.app = ApplicationFactory(
            workflow=self.workflow,
            customer=self.customer,
            product_line=self.product_line,
            partner=self.partner,
        )
        self.referral_system = ReferralSystemFactory()
        self.referral_system.product_code.append(200)
        self.referral_system.partners.append('julovers')
        self.referral_system.save()

    @mock.patch('juloserver.moengage.services.use_cases.update_moengage_referral_event')
    def test_generate_referral_code(self, mock_update_moengage_referral_event):
        status_lookup = StatusLookup.objects.get(status_code=190)
        account = AccountFactory(customer=self.app.customer)
        account.status_id = 420
        account.save()
        self.app.application_status = status_lookup
        self.app.account = account
        self.app.save()
        CreditScoreFactory(application_id=self.app.id, score='B+')
        generate_customer_level_referral_code(self.app)

        mock_update_moengage_referral_event.delay.assert_called_once_with(
            self.customer, MoengageEventType.BEx190_NOT_YET_REFER_JULOVER
        )
        self.assertNotEqual(str(self.app.customer.self_referral_code), '')


class TestServiceGenerateJuloTurboReferralCode(APITestCase):
    def setUp(self):
        # jturbo
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_status=StatusLookup.objects.get(status_code=190),
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER),
        )
        _ = LoanFactory(customer=self.customer,
                        account=self.account,
                        application=self.application,
                        loan_amount=54000,
                        loan_status=StatusLookupFactory(status_code=StatusLookup.CURRENT_CODE))
        self.referral_system = ReferralSystemFactory()

    @mock.patch('juloserver.moengage.services.use_cases.update_moengage_referral_event')
    def test_generate_referral_code_jturbo(self, mock_update_moengage_referral_event):
        CreditScoreFactory(application_id=self.application.id, score='B+')
        generate_customer_level_referral_code(self.application)
        self.assertNotEqual(str(self.application.customer.self_referral_code), '')
        mock_update_moengage_referral_event.delay.assert_called_once_with(
            self.customer, MoengageEventType.BEx190_NOT_YET_REFER
        )


class TestServiceGenerateCustomerLevelReferralCode(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(id=1999999999, self_referral_code=None, fullname='likiooo')
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1)
        )
        self.referral_system = ReferralSystemFactory(product_code=[1])

    def test_generate_success(self):
        fake = Faker()
        # generate 100 times
        for number in range(100):
            full_name = fake.name()
            self.customer.update_safely(fullname=full_name, self_referral_code=None)
            generate_customer_level_referral_code(self.application)
            self.customer.refresh_from_db()
            self_referral_code = self.customer.self_referral_code
            self.assertNotIn('I', self_referral_code)
            self.assertNotIn('L', self_referral_code)
            self.assertNotIn('O', self_referral_code)
            self.assertNotIn('0', self_referral_code)
            self.assertNotIn('1', self_referral_code)

    def test_application_not_found(self):
        with self.assertRaises(JuloException):
            generate_customer_level_referral_code(None)

        self.assertIsNone(self.customer.self_referral_code)

    def test_referral_code_already_exists(self):
        referral_code = generate_referral_code(self.customer)
        self.customer.update_safely(self_referral_code=referral_code)
        generate_customer_level_referral_code(self.application)
        self.assertEquals(self.customer.self_referral_code, referral_code)

    def test_referral_system_off(self):
        self.referral_system.update_safely(is_active=False)
        generate_customer_level_referral_code(self.application)
        self.assertIsNone(self.customer.self_referral_code)

    def test_invalid_product_line(self):
        self.referral_system.update_safely(product_code=[200])
        generate_customer_level_referral_code(self.application)
        self.assertIsNone(self.customer.self_referral_code)

    def test_invalid_partner(self):
        self.referral_system.update_safely(partners=['doge'])
        generate_customer_level_referral_code(self.application)
        self.assertIsNone(self.customer.self_referral_code)


class TestGetCorrectApplication(APITestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.application_1 = ApplicationFactory(
            customer=self.customer,
            product_line_code=10,
        )
        self.application_1.update_safely(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED
            )
        )
        self.application_2 = ApplicationFactory(customer=self.customer, product_line_code=10)
        self.application_2.update_safely(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED)
        )
        self.referral_system = ReferralSystemFactory()

    def test_get_correct_application(self):
        correct_application = self.customer.application_set.regular_not_deletes().last()
        self.assertEqual(correct_application.status, 190)


class TestReferralShareableImage(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SHAREABLE_REFERRAL_IMAGE,
            is_active=True,
            parameters={
                'text': {
                    'coordinates': {'x': 0, 'y': 0},
                    'size': 0,
                },
                'image': 'https://statics.julo.co.id/juloserver/staging/static/images/'
                'ecommerce/juloshop/julo_shop_banner.png',
            },
        )

    def test_none_feature_setting(self):
        self.feature_setting.update_safely(is_active=False)
        text, image = get_shareable_referral_image()
        self.assertIsNone(text)
        self.assertIsNone(image)

        self.feature_setting.delete()
        text, image = get_shareable_referral_image()
        self.assertIsNone(text)
        self.assertIsNone(image)

    def test_get_referral_image_success(self):
        text, image = get_shareable_referral_image()
        parameters = self.feature_setting.parameters
        expected_text = parameters['text']
        expected_image = parameters['image']
        self.assertEquals(text, expected_text)
        self.assertEquals(image, expected_image)


class TestReferralBenefitLevel(TestCase):
    def setUp(self):
        self.referrer = CustomerFactory()
        self.referee = CustomerFactory()
        self.referrer_cashback = CashbackBalanceFactory(customer=self.referrer)
        self.referee_cashback = CashbackBalanceFactory(customer=self.referee)
        self.referral_benefit = ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=50000,
            referee_benefit=20000, min_disburse_amount=400000, is_active=True
        )
        self.referral_level = ReferralLevelFactory(
            benefit_type=ReferralLevelConst.CASHBACK, min_referees=5, referrer_level_benefit=50000,
            is_active=True
        )
        self.referee_mapping = RefereeMappingFactory.create_batch(5, referrer=self.referrer)
        self.loan = LoanFactory(customer=self.referee, loan_amount=500000)
        self.referee_mapping = RefereeMappingFactory(referrer=self.referrer, referee=self.referee)
        self.feature_setting = ReferralBenefitFeatureSettingFactory()

    @patch('juloserver.moengage.services.use_cases.trigger_moengage_after_freeze_unfreeze_cashback.delay')
    def test_get_and_apply_referral_benefit_success(self, mock_trigger_moengage):
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referee_benefits = get_referee_benefits(referral_benefit)
        apply_referral_benefits(
            self.referee, referee_benefits, ReferralPersonTypeConst.REFEREE, self.referee_mapping
        )
        self.referee_cashback.refresh_from_db()
        self.assertEquals(self.referee_cashback.cashback_balance, 20000)
        mock_trigger_moengage.assert_called_with([{
            'customer_id': self.referee.id,
            'referral_type': ReferralPersonTypeConst.REFEREE,
            'cashback_earned': 20000
        }], is_freeze=True)

        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        self.referrer_cashback.refresh_from_db()
        self.assertEquals(self.referrer_cashback.cashback_balance, 100000)
        mock_trigger_moengage.assert_called_with([{
            'customer_id': self.referrer.id,
            'referral_type': ReferralPersonTypeConst.REFERRER,
            'cashback_earned': 100000
        }], is_freeze=True)

    def test_multiple_referral_benefits(self):
        ReferralBenefitFactory.create_batch(
            2, benefit_type=ReferralBenefitConst.CASHBACK,
            referrer_benefit=Iterator([100000, 150000]),
            referee_benefit=Iterator([70000, 120000]),
            min_disburse_amount=Iterator([450000, 500000]), is_active=True
        )
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referee_benefits = get_referee_benefits(referral_benefit)
        apply_referral_benefits(
            self.referee, referee_benefits, ReferralPersonTypeConst.REFEREE, self.referee_mapping
        )
        self.referee_cashback.refresh_from_db()
        self.assertEquals(self.referee_cashback.cashback_balance, 120000)

        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        self.referrer_cashback.refresh_from_db()
        self.assertEquals(self.referrer_cashback.cashback_balance, 200000)

    def test_multiple_benefit_types(self):
        self.referral_level.update_safely(
            benefit_type=ReferralLevelConst.POINTS, referrer_level_benefit=200
        )
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)

        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        expected_referrer_benefits = {
            ReferralBenefitConst.CASHBACK: 50000,
        }
        self.assertEquals(referrer_benefits, expected_referrer_benefits)

        referee_benefits = get_referee_benefits(referral_benefit)
        expected_referee_benefits = {ReferralBenefitConst.CASHBACK: 20000}
        self.assertEquals(referee_benefits, expected_referee_benefits)

    def test_deactivate_referral_benefit_level(self):
        # referral benefit: off
        # referral level: on
        self.referral_benefit.update_safely(is_active=False)
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        self.assertIsNone(referral_benefit)

        # referral benefit: on
        # referral level: off
        self.referral_benefit.update_safely(is_active=True)
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)

        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        self.referrer_cashback.refresh_from_db()
        self.assertEquals(self.referrer_cashback.cashback_balance, 100000)

        referee_benefits = get_referee_benefits(referral_benefit)
        apply_referral_benefits(
            self.referee, referee_benefits, ReferralPersonTypeConst.REFEREE, self.referee_mapping
        )
        self.referee_cashback.refresh_from_db()
        self.assertEquals(self.referee_cashback.cashback_balance, 20000)

    def test_referral_level_percentage(self):
        self.referral_level.update_safely(
            benefit_type=ReferralLevelConst.PERCENTAGE, referrer_level_benefit=50
        )
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        self.referrer_cashback.refresh_from_db()
        self.assertEquals(self.referrer_cashback.cashback_balance, 75000)

        self.referral_benefit.update_safely(
            benefit_type=ReferralBenefitConst.POINTS, referrer_benefit=1
        )
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        expected_referrer_benefits = {ReferralBenefitConst.POINTS: 2}
        self.assertEquals(referrer_benefits, expected_referrer_benefits)

        self.referral_level.update_safely(
            benefit_type=ReferralLevelConst.PERCENTAGE, referrer_level_benefit=30
        )
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        expected_referrer_benefits = {ReferralBenefitConst.POINTS: 1}
        self.assertEquals(referrer_benefits, expected_referrer_benefits)

    @patch('django.utils.timezone.now')
    def test_old_referee_mapping_records(self, mock_now):
        mock_now.return_value = datetime.datetime(2020, 1, 1, 0, 0,0)
        RefereeMappingFactory.create_batch(3, referrer=self.referrer)
        mock_now.return_value = datetime.datetime(2023, 8, 1, 0, 0,0)

        # referrer does not receive referral level since he has only referred 6 customers
        self.referral_level.update_safely(min_referees=7)
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referee_benefits = get_referee_benefits(referral_benefit)
        apply_referral_benefits(
            self.referee, referee_benefits, ReferralPersonTypeConst.REFEREE, self.referee_mapping
        )
        self.referee_cashback.refresh_from_db()
        self.assertEquals(self.referee_cashback.cashback_balance, 20000)

        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        self.referrer_cashback.refresh_from_db()
        self.assertEquals(self.referrer_cashback.cashback_balance, 50000)

        # referrer receives referral level since he has referred 7 customers
        RefereeMappingFactory(referrer=self.referrer)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        self.referrer_cashback.refresh_from_db()
        self.assertEquals(self.referrer_cashback.cashback_balance, 150000)

        # update referral level min referee
        # referrer receives referral level since he has only referred 10 customers
        self.referral_level.update_safely(min_referees=10)
        self.feature_setting.update_safely(parameters={
            'count_start_date': '2019-01-01'
        })
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        self.referrer_cashback.refresh_from_db()
        self.assertEquals(self.referrer_cashback.cashback_balance, 250000)

class TestReferralBenefitLevelForLoyaltyPointSystem(TestCase):
    def setUp(self):
        self.referrer = CustomerFactory()
        self.referee = CustomerFactory()
        self.referrer_cashback = CashbackBalanceFactory(customer=self.referrer)
        self.referee_cashback = CashbackBalanceFactory(customer=self.referee)
        self.referral_benefit = ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.POINTS, referrer_benefit=50000,
            referee_benefit=20000, min_disburse_amount=400000, is_active=True
        )
        self.referral_level = ReferralLevelFactory(
            benefit_type=ReferralLevelConst.POINTS, min_referees=5, referrer_level_benefit=50000,
            is_active=True
        )
        self.referee_mapping = RefereeMappingFactory.create_batch(5, referrer=self.referrer)
        self.loan = LoanFactory(customer=self.referee, loan_amount=500000)
        self.referee_mapping = RefereeMappingFactory(referrer=self.referrer, referee=self.referee)
        self.feature_setting = ReferralBenefitFeatureSettingFactory()

    def test_get_and_apply_referral_benefit_for_loyalty_points(self):
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referee_benefits = get_referee_benefits(referral_benefit)
        apply_referral_benefits(
            self.referee, referee_benefits, ReferralPersonTypeConst.REFEREE, self.referee_mapping
        )
        # Check referee loyalty point
        self.referee_loyalty_point = LoyaltyPoint.objects.get(customer_id=self.referee.id)
        self.assertEquals(self.referee_loyalty_point.total_point, 20000)

        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        # Check referrer loyalty point
        self.referrer_loyalty_point = LoyaltyPoint.objects.get(customer_id=self.referrer.id)
        self.assertEquals(self.referrer_loyalty_point.total_point, 100000)

    def test_get_and_apply_referral_benefit_for_loyalty_points_with_percentage_referral_level(self):
        self.referral_level.update_safely(
            benefit_type=ReferralLevelConst.PERCENTAGE, referrer_level_benefit=50
        )
        referral_benefit = get_referral_benefit(self.loan.loan_amount)
        referral_level = get_referrer_level_benefit(self.referrer, self.feature_setting, referral_benefit)
        referrer_benefits = get_referrer_benefits(referral_benefit, referral_level)
        apply_referral_benefits(
            self.referrer, referrer_benefits, ReferralPersonTypeConst.REFERRER, self.referee_mapping
        )
        # Check referrer loyalty point
        self.referrer_loyalty_point = LoyaltyPoint.objects.get(customer_id=self.referrer.id)
        self.assertEquals(self.referrer_loyalty_point.total_point, 75000)


class TestGetCountRefereeApplicationStatus(TestCase):
    def setUp(self):
        signals.post_save.disconnect(invalidate_cache_referee_count, sender=Application)
        ReferralSystemFactory()
        ReferralBenefitFeatureSettingFactory()
        self.referrer = CustomerFactory(self_referral_code='NGUYKOOVO')
        self.referee = CustomerFactory()
        self.application = ApplicationFactory(
            customer=self.referee,
            referral_code='NGUYKOOVO',
            application_status=StatusLookupFactory(status_code=124),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.fake_redis = MockRedisHelper()
        self.lt_190_key = ReferralRedisConstant.REFEREE_CODE_USED_COUNT.format(
            self.referrer.id
        )
        self.gte_190_key = ReferralRedisConstant.REFEREE_ALREADY_APPROVED_COUNT.format(
            self.referrer.id
        )
        self.counting_referees_disbursement_key = \
            ReferralRedisConstant.COUNTING_REFEREES_DISBURSEMENT_KEY.format(self.referrer.id)
        self.total_referees_bonus_amount_key = \
            ReferralRedisConstant.TOTAL_REFERRAL_BONUS_AMOUNT_KEY.format(self.referrer.id)

    @mock.patch('juloserver.referral.services.get_redis_client')
    def test_get_set_redis_value_case_1(self, mock_get_client):
        # case referee with referee application status < 190
        mock_get_client.return_value = self.fake_redis
        code_used_count, approved_count, disbursement_count, total_bonus_amount = (
            get_referee_information_by_referrer(
                self.referrer)
        )
        self.assertEquals(code_used_count, 1)
        self.assertEquals(approved_count, 0)
        self.assertEquals(disbursement_count, 0)
        self.assertEquals(total_bonus_amount, 0)

        self.assertEquals(self.fake_redis.get(self.lt_190_key), '1')
        self.assertEquals(self.fake_redis.get(self.gte_190_key), '0')
        self.assertEquals(self.fake_redis.get(self.counting_referees_disbursement_key), '0')
        self.assertEquals(self.fake_redis.get(self.total_referees_bonus_amount_key), '0')

        self.fake_redis.delete_key(
            ReferralRedisConstant.REFEREE_CODE_USED_COUNT.format(self.referrer.id)
        )
        self.fake_redis.delete_key(
            ReferralRedisConstant.REFEREE_ALREADY_APPROVED_COUNT.format(self.referrer.id)
        )
        self.fake_redis.delete_key(self.counting_referees_disbursement_key)
        self.fake_redis.delete_key(self.total_referees_bonus_amount_key)

        self.assertEquals(self.fake_redis.get(self.lt_190_key), None)
        self.assertEquals(self.fake_redis.get(self.gte_190_key), None)
        self.assertEquals(self.fake_redis.get(self.counting_referees_disbursement_key), None)
        self.assertEquals(self.fake_redis.get(self.total_referees_bonus_amount_key), None)

    @mock.patch('juloserver.referral.services.get_redis_client')
    def test_get_set_redis_value_case_2(self, mock_get_client):
        # case referee with referee application status = 190
        self.application.update_safely(application_status_id=190)
        mock_get_client.return_value = self.fake_redis

        code_used_count, approved_count, disbursement_count, total_bonus_amount = (
            get_referee_information_by_referrer(
                self.referrer)
        )
        self.assertEquals(code_used_count, 1)
        self.assertEquals(approved_count, 1)
        self.assertEquals(disbursement_count, 0)
        self.assertEquals(total_bonus_amount, 0)

        self.assertEquals(self.fake_redis.get(self.lt_190_key), '1')
        self.assertEquals(self.fake_redis.get(self.gte_190_key), '1')
        self.assertEquals(self.fake_redis.get(self.counting_referees_disbursement_key), '0')
        self.assertEquals(self.fake_redis.get(self.total_referees_bonus_amount_key), '0')

        self.fake_redis.delete_key(
            ReferralRedisConstant.REFEREE_CODE_USED_COUNT.format(self.referrer.id)
        )
        self.fake_redis.delete_key(
            ReferralRedisConstant.REFEREE_ALREADY_APPROVED_COUNT.format(self.referrer.id)
        )
        self.fake_redis.delete_key(self.counting_referees_disbursement_key)
        self.fake_redis.delete_key(self.total_referees_bonus_amount_key)

        self.assertEquals(self.fake_redis.get(self.lt_190_key), None)
        self.assertEquals(self.fake_redis.get(self.gte_190_key), None)
        self.assertEquals(self.fake_redis.get(self.counting_referees_disbursement_key), None)
        self.assertEquals(self.fake_redis.get(self.total_referees_bonus_amount_key), None)

    @mock.patch('juloserver.referral.services.get_redis_client')
    def test_get_set_redis_value_case_3(self, mock_get_client):
        # case succeed in referral mapping
        self.application.update_safely(application_status_id=190)
        ReferralBenefitHistoryFactory(
            customer=self.referrer,
            referral_person_type=ReferralPersonTypeConst.REFERRER,
            benefit_unit=ReferralBenefitConst.CASHBACK,
            amount=100000
        )
        mock_get_client.return_value = self.fake_redis
        code_used_count, approved_count, disbursement_count, total_bonus_amount = (
            get_referee_information_by_referrer(
                self.referrer)
        )
        self.assertEquals(code_used_count, 1)
        self.assertEquals(approved_count, 1)
        self.assertEquals(disbursement_count, 1)
        self.assertEquals(total_bonus_amount, 100000)

        self.assertEquals(self.fake_redis.get(self.lt_190_key), '1')
        self.assertEquals(self.fake_redis.get(self.gte_190_key), '1')
        self.assertEquals(self.fake_redis.get(self.counting_referees_disbursement_key), '1')
        self.assertEquals(self.fake_redis.get(self.total_referees_bonus_amount_key), '100000')

        self.fake_redis.delete_key(
            ReferralRedisConstant.REFEREE_CODE_USED_COUNT.format(self.referrer.id)
        )
        self.fake_redis.delete_key(
            ReferralRedisConstant.REFEREE_ALREADY_APPROVED_COUNT.format(self.referrer.id)
        )
        self.fake_redis.delete_key(self.counting_referees_disbursement_key)
        self.fake_redis.delete_key(self.total_referees_bonus_amount_key)

        self.assertEquals(self.fake_redis.get(self.lt_190_key), None)
        self.assertEquals(self.fake_redis.get(self.gte_190_key), None)
        self.assertEquals(self.fake_redis.get(self.counting_referees_disbursement_key), None)
        self.assertEquals(self.fake_redis.get(self.total_referees_bonus_amount_key), None)

    def test_get_referees_code_used_with_cut_off_date(self):
        self.application.update_safely(cdate='2020-01-01')
        referee_customers = get_referees_code_used(self.referrer)
        self.assertEqual(len(referee_customers), 0)

        self.application.update_safely(cdate='2023-08-10')
        referee_customers = get_referees_code_used(self.referrer)
        self.assertEqual(len(referee_customers), 1)

    def test_get_referees_approved_count_with_cut_off_date(self):
        self.application.update_safely(cdate='2020-01-01', application_status_id=190)
        result_count = get_referees_approved_count([self.referee.id])
        self.assertEqual(result_count, 0)

        self.application.update_safely(cdate='2023-08-10')
        result_count = get_referees_approved_count([self.referee.id])
        self.assertEqual(result_count, 1)

    def test_get_total_referral_invited_and_total_referral_benefits(self):
        self.benefit_histories = ReferralBenefitHistoryFactory(
            customer=self.referrer,
            referral_person_type=ReferralPersonTypeConst.REFERRER,
            amount=10000,
            benefit_unit=ReferralBenefitConst.CASHBACK
        )
        total_referral_invited, total_referral_benefits = (
            get_total_referral_invited_and_total_referral_benefits_v2(self.referrer)
        )
        self.assertEqual(total_referral_invited, 1)
        self.assertEqual(total_referral_benefits, 10000)


class TestSignalsApplicationStatus(TestCase):
    def setUp(self):
        signals.post_save.connect(invalidate_cache_referee_count, sender=Application)
        ReferralSystemFactory()
        ReferralBenefitFeatureSettingFactory()
        self.referrer = CustomerFactory(self_referral_code='NGUYKOOVO')
        self.referee = CustomerFactory()
        self.fake_redis = MockRedisHelper()
        self.lt_190_key = ReferralRedisConstant.REFEREE_CODE_USED_COUNT.format(
            self.referrer.id
        )
        self.gte_190_key = ReferralRedisConstant.REFEREE_ALREADY_APPROVED_COUNT.format(
            self.referrer.id
        )

    @mock.patch('juloserver.referral.signals.get_redis_client')
    @mock.patch('juloserver.referral.services.get_referee_information_by_referrer')
    def test_signals_case_1(self, mock_count_function, mock_get_client):
        # referral not change
        # application status < 190
        ApplicationFactory(
            customer=self.referee,
            application_status=StatusLookupFactory(status_code=124),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        mock_get_client.return_value = self.fake_redis
        mock_count_function.assert_not_called()

    @mock.patch('juloserver.referral.signals.get_redis_client')
    @mock.patch('juloserver.referral.signals.get_referee_information_by_referrer')
    def test_signals_case_2(self, mock_count_function, mock_get_client):
        # referral changes
        # application status < 190
        mock_count_function.return_value = 1, 0, 0, 0
        mock_get_client.return_value = self.fake_redis
        application = ApplicationFactory(
            customer=self.referee,
            application_status=StatusLookupFactory(status_code=124),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.update_safely(referral_code='NGUYKOOVO')
        mock_count_function.assert_called()

    @mock.patch('juloserver.referral.signals.get_redis_client')
    @mock.patch('juloserver.referral.signals.get_referee_information_by_referrer')
    def test_signals_case_3(self, mock_count_function, mock_get_client):
        # referral not changes
        # application status to 190
        mock_count_function.return_value = 1, 0, 0, 0
        mock_get_client.return_value = self.fake_redis
        application = ApplicationFactory(
            customer=self.referee,
            referral_code='NGUYKOOVO',
            application_status=StatusLookupFactory(status_code=110),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        application.update_safely(application_status_id=190)
        mock_count_function.assert_called()


class TestGetReferralBenefitLevel(TestCase):
    def setUp(self):
        self.referral_benefit = ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=75000,
            referee_benefit=20000, min_disburse_amount=500000, is_active=True
        )
        self.referral_benefit = ReferralBenefitFactory(
            benefit_type=ReferralBenefitConst.CASHBACK, referrer_benefit=150000,
            referee_benefit=40000, min_disburse_amount=1000000, is_active=True
        )
        self.referral_level = ReferralLevelFactory(
            benefit_type=ReferralLevelConst.PERCENTAGE, min_referees=20,
            referrer_level_benefit=30,
            is_active=True,
            level='Super',
        )
        self.feature_setting = ReferralLevelBenefitFeatureSettingFactory()

    def test_get_referral_benefit_level(self):
        expected_response = [
            {
                "level": "Basic",
                "color": "#404040",
                "icon": "http://drive.google.com/uc?id=1UnPJ5mnbnMoNlfeoe-4ZgAGqfsHVijvh",
                "benefit": [
                    {
                        "name": "Ajak teman",
                        "value": "Mulai dari 1 teman"
                    },
                    {
                        "name": "Kesempatan menangin hadiah utama",
                        "value": "false"
                    },
                    {
                        "name": "Min. transaksi Rp 500.000",
                        "value": "Cashback Rp 75.000"
                    },
                    {
                        "name": "Temanmu Min. transaksi Rp 500.000",
                        "value": "Temanmu dapat cashback Rp 20.000"
                    },
                    {
                        "name": "Min. transaksi Rp 1.000.000",
                        "value": "Cashback Rp 150.000"
                    },
                    {
                        "name": "Temanmu Min. transaksi Rp 1.000.000",
                        "value": "Temanmu dapat cashback Rp 40.000"
                    }
                ]
              },
            {
                "level": "Super",
                "color": "#F09537",
                "icon": "http://drive.google.com/uc?id=1X5YWWO2eBd3-KC2xhO4aBoxRTMEudso4",
                "benefit": [
                    {
                        "name": "Ajak teman",
                        "value": "20 teman atau lebih"
                    },
                    {
                        "name": "Kesempatan menangin hadiah utama",
                        "value": "true"
                    },
                    {
                        "name": "Min. transaksi Rp 500.000",
                        "value": "Cashback Rp 75.000 +30%"
                    },
                    {
                        "name": "Temanmu Min. transaksi Rp 500.000",
                        "value": "Temanmu dapat cashback Rp 20.000"
                    },
                    {
                        "name": "Min. transaksi Rp 1.000.000",
                        "value": "Cashback Rp 150.000 +30%"
                    },
                    {
                        "name": "Temanmu Min. transaksi Rp 1.000.000",
                        "value": "Temanmu dapat cashback Rp 40.000"
                    }
                ]
            }
        ]
        response = get_referral_benefits_by_level()
        self.assertEqual(response, expected_response)


class TestGetCurrentReferralLevel(TestCase):
    def setUp(self):
        self.referrer = CustomerFactory()
        self.fake_redis = MockRedisHelper()
        ReferralLevelFactory(level='Super', min_referees=2)
        ReferralBenefitFeatureSettingFactory()

    @mock.patch('juloserver.referral.services.get_redis_client')
    def test_get_current_referral_level(self, mock_get_client):
        mock_get_client.return_value = self.fake_redis
        self.count_referees = self.fake_redis.set(
            ReferralRedisConstant.COUNTING_REFEREES_DISBURSEMENT_KEY.format(self.referrer.id),
            1
        )
        result = get_current_referral_level(self.referrer)
        self.assertEqual(result, 'Basic')

        self.count_referees = self.fake_redis.set(
            ReferralRedisConstant.COUNTING_REFEREES_DISBURSEMENT_KEY.format(self.referrer.id),
            3
        )
        result = get_current_referral_level(self.referrer)
        self.assertEqual(result, 'Super')
