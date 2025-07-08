from django.utils import timezone
from datetime import timedelta, datetime, date
from dateutil.relativedelta import relativedelta
from rest_framework.test import APITestCase
from juloserver.minisquad.services import (
    get_turned_on_autodebet_customer_exclude_for_dpd_plus,
    get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet,
    is_eligible_for_in_app_ptp,
    filter_intelix_blacklist_for_t0,
)
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    PTPFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
)
from juloserver.julo.models import FeatureNameConst
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.account.tests.factories import (
    AccountwithApplicationFactory,
    AccountFactory,
    ApplicationFactory
)
from juloserver.apiv2.tests.factories import PdCollectionModelResultFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.account_payment.models import AccountPayment
from juloserver.minisquad.tests.factories import intelixBlacklistFactory


class TestServiceMinisquad(APITestCase):
    def setUp(self):
        self.account = AccountwithApplicationFactory(id=1)
        self.autodebet_customer_turned_on = AutodebetAccountFactory(
            account = self.account,
            vendor = "BCA",
            is_use_autodebet = True,
            is_deleted_autodebet = False
        )
        self.today = timezone.localtime(timezone.now()).date()
        self.due_date = self.today + timedelta(days=5)
        self.account_payment = AccountPaymentFactory(
            id=11,
            account=self.account,
            due_date=self.due_date
        )
        self.collection_data = PdCollectionModelResultFactory(
            account_payment=self.account_payment,
            range_from_due_date=str(-5),
            cdate=self.today
        )
        self.collection_model_account_payments = PdCollectionModelResult.objects.filter(
            id=self.collection_data.id
        )
        self.account2 = AccountwithApplicationFactory(id=2)
        self.account_payment2 = AccountPaymentFactory(
            id=12,
            account=self.account2,
            due_date=self.due_date
        )
        self.oldest_account_payment = AccountPayment.objects.filter(
            id=self.account_payment2.id
        ).values_list('id', flat=True)
        self.parameters = {
            "dpd_minus": True,
            "dpd_zero": False,
            "dpd_plus": True
        }
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
            parameters=self.parameters,
            is_active=False
        )

    def test_get_turned_on_autodebet_customer_exclude_for_dpd_plus_feature_setting_off(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.assertEqual(
            [], get_turned_on_autodebet_customer_exclude_for_dpd_plus()
        )

    def test_get_turned_on_autodebet_customer_exclude_for_dpd_plus_feature_setting_on(self):
        self.feature_setting.is_active = True
        self.feature_setting.save()
        self.assertTrue(
            1 in get_turned_on_autodebet_customer_exclude_for_dpd_plus()
        )

    def test_get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet_feature_off(self):
        self.assertEqual(
            ([], self.oldest_account_payment, self.collection_model_account_payments), get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet(
                -5, self.oldest_account_payment, self.collection_model_account_payments
            )
        )

    def test_get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet_empty_data(self):
        self.feature_setting.is_active = True
        self.autodebet_customer_turned_on.is_use_autodebet = False
        self.feature_setting.save()
        self.autodebet_customer_turned_on.save()
        result = get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet(
            -5, self.oldest_account_payment, self.collection_model_account_payments)
        self.assertEqual(self.oldest_account_payment, result[1])
        self.assertEqual(self.collection_model_account_payments, result[2])

    def test_get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet(self):
        self.feature_setting.is_active = True
        self.autodebet_customer_turned_on.is_use_autodebet = True
        self.feature_setting.save()
        self.autodebet_customer_turned_on.save()
        result = get_not_sent_to_intelix_account_payments_dpd_minus_turned_on_autodebet(
            -5, self.oldest_account_payment, self.collection_model_account_payments)
        self.assertEqual([
            {
                'reason': 'excluded due to autodebet',
                'id': 11
            }
        ], result[0])
        self.assertTrue(12 in result[1])
        self.assertTrue(len(result[2]) is 0)

    def test_filter_intelix_blacklist_for_t0(self):
        self.intelix_blacklist = intelixBlacklistFactory(
            account=self.account2,
            expire_date=timezone.localtime(timezone.now()) + relativedelta(days=10)
        )
        account_payments = list(AccountPayment.objects.all())
        not_sent_account_payments = []
        account_payments, not_sent_account_payments = filter_intelix_blacklist_for_t0(
            account_payments, not_sent_account_payments)
        self.assertIsNotNone(not_sent_account_payments)


class TestIsEligibleForInAppPtp(APITestCase):
    def setUp(self):
        self.today = timezone.localtime(timezone.now())
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date = date.today() + timedelta(days=40))
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            customer=self.customer,
        )
        self.ptp = PTPFactory(
            account_payment=self.account_payment,
            account=self.account,
            ptp_date=datetime.today() + timedelta(days=10),
            ptp_status=None
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.IN_APP_PTP_SETTING,
            is_active=False
        )

    def test_on_going_ptp(self):
        eligible_for_app_ptp, already_have_ptp, ptp_date, in_app_ptp_order = is_eligible_for_in_app_ptp(
            self.account)
        self.assertEqual(eligible_for_app_ptp, False)
        self.assertEqual(already_have_ptp, None)
        self.assertEqual(ptp_date, None)
        self.assertEqual(in_app_ptp_order, None)
