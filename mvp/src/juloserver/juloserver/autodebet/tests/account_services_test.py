from django.test.testcases import TestCase
from django.utils import timezone
import mock

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountStatusHistoryFactory,
)
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    FeatureSettingFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    WorkflowFactory,
    ExperimentSettingFactory,
    StatusLookupFactory,
    LoanFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory

from juloserver.autodebet.constants import (
    FeatureNameConst,
    AutodebetDeductionSourceConst,
    AutodebetVendorConst,
    AutodebetStatuses,
    ExperimentConst,
)
from juloserver.autodebet.services.account_services import (
    get_existing_autodebet_account,
    is_account_eligible_for_fund_collection,
    is_autodebet_feature_active,
    is_autodebet_gopay_feature_active,
    construct_autodebet_bca_feature_status,
    update_deduction_fields_to_new_cycle_day,
    is_autodebet_feature_disable,
    is_idfy_enable,
    is_idfy_autodebet_valid,
    construct_deactivate_warning,
    get_autodebet_experiment_setting,
    is_experiment_group_autodebet,
    is_disabled_autodebet_activation,
)
from juloserver.autodebet.models import AutodebetAccount
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from juloserver.julo.constants import (
    WorkflowConst,
)
from juloserver.account.constants import (
    AccountConstant,
    AccountChangeReason,
)
from juloserver.julo.statuses import LoanStatusCodes


class TestDeactivationWarning(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.BCA_AUTODEBET_DEACTTIVATE_WARNING,
            parameters={
                "interval_days": 7,
                "title": "Gagal Nonaktifkan Autodebit BCA",
                "content": "Kamu baru saja nonaktifkan Autodebit BCA kurang dari {{interval_days}} hari yang lalu. Coba lagi mulai tanggal <b>{{date}}</b>, ya!",
            },
        )
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account,
            status=AutodebetStatuses.REGISTERED,
        )

    def test_activation_more_than_interval(self):
        self.autodebet_account.activation_ts = timezone.localtime(timezone.now()) - timedelta(
            days=7
        )
        self.autodebet_account.save()
        result = construct_deactivate_warning(self.autodebet_account, 'BCA')
        self.assertIsNone(result)

    def test_activation_less_than_or_equal_interval(self):
        self.autodebet_account.activation_ts = timezone.localtime(timezone.now()) - timedelta(
            days=6
        )
        self.autodebet_account.save()
        result = construct_deactivate_warning(self.autodebet_account, 'BCA')
        self.assertIsNotNone(result)
        self.assertEqual("Gagal Nonaktifkan Autodebit BCA", result["title"])


class TestAutodebetAccountServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_BCA
        )
        cls.whitelist_setting = FeatureSettingFactory()
        cls.account = AccountFactory()
        cls.application  = ApplicationFactory(account=cls.account)
        cls.gopay_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_GOPAY
        )
        cls.bri_feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_BRI
        )

    def setUp(self):
        self.autodebet_account = AutodebetAccountFactory(account=self.account)

    def test_get_existing_autodebet_account(self):
        self.assertIsNotNone(get_existing_autodebet_account(self.account))

    def test_is_autodebet_feature_active(self):
        self.assertTrue(is_autodebet_feature_active())
        self.feature_setting.feature_name = "feature_name"
        self.feature_setting.save()
        self.assertFalse(is_autodebet_feature_active())

    def test_construct_autodebet_bca_feature_status(self):
        feature_active, autodebet_active, _ = construct_autodebet_bca_feature_status(self.account)
        self.assertTrue(feature_active)
        self.assertFalse(autodebet_active)

        self.feature_setting.feature_name = "feature_name"
        self.feature_setting.save()
        feature_active, autodebet_active, _ = construct_autodebet_bca_feature_status(self.account)
        self.assertFalse(feature_active)
        self.assertFalse(autodebet_active)

        self.whitelist_setting.feature_name = FeatureNameConst.WHITELIST_AUTODEBET_BCA
        self.whitelist_setting.parameters = {"applications": [self.application.id]}
        self.whitelist_setting.save()
        feature_active, autodebet_active, _ = construct_autodebet_bca_feature_status(self.account)
        self.assertTrue(feature_active)
        self.assertFalse(autodebet_active)

    def test_is_account_eligible_for_fund_collection(self):
        account_payment = AccountPaymentFactory(account=self.autodebet_account.account)
        self.assertEqual(is_account_eligible_for_fund_collection(account_payment), True)
        self.autodebet_account.activation_ts = datetime.now() + timedelta(days=10)
        self.autodebet_account.save()
        self.assertEqual(is_account_eligible_for_fund_collection(account_payment), False)
        self.autodebet_account.activation_ts = datetime.now() + timedelta(days=11)
        self.autodebet_account.save()
        self.assertEqual(is_account_eligible_for_fund_collection(account_payment), True)

    def test_update_deduction_fields_to_new_cycle_day(self):
        account_payment = AccountPaymentFactory(account=self.autodebet_account.account)
        update_deduction_fields_to_new_cycle_day(account_payment)
        self.assertFalse(AutodebetAccount.objects.filter(
            deduction_cycle_day=self.autodebet_account.account.cycle_day,
            deduction_source=AutodebetDeductionSourceConst.ORIGINAL_CYCLE_DAY,
            is_payday_changed=True).exists())
        self.autodebet_account.is_use_autodebet = True
        self.autodebet_account.save()
        update_deduction_fields_to_new_cycle_day(account_payment)
        self.assertTrue(AutodebetAccount.objects.filter(
            deduction_cycle_day=self.autodebet_account.account.cycle_day,
            deduction_source=AutodebetDeductionSourceConst.ORIGINAL_CYCLE_DAY,
            is_payday_changed=True).exists())

    def test_is_autodebet_gopay_feature_active(self):
        self.assertTrue(is_autodebet_gopay_feature_active())
        self.gopay_feature_setting.feature_name = "feature_name"
        self.gopay_feature_setting.save()
        self.assertFalse(is_autodebet_gopay_feature_active())

    def test_is_autodebet_feature_disable(self):
        now = timezone.localtime(timezone.now()).replace(day=7, month=8, year=2023, hour=12, minute=30)
        today = datetime.strptime(datetime.strftime(now, '%d-%m-%y %H:%M'), '%d-%m-%y %H:%M')
        with mock.patch('django.utils.timezone.now') as mock_today:
            mock_today.return_value = today

            self.assertFalse(is_autodebet_feature_disable(AutodebetVendorConst.BCA))
            self.assertFalse(is_autodebet_feature_disable(AutodebetVendorConst.BRI))
            self.assertFalse(is_autodebet_feature_disable(AutodebetVendorConst.GOPAY))

            disable = {
                "disable_start_date_time": datetime.strftime(today - relativedelta(days=1), '%d-%m-%Y %H:%M'),
                "disable_end_date_time": datetime.strftime(today + relativedelta(days=1), '%d-%m-%Y %H:%M')
            }
            self.feature_setting.feature_name = FeatureNameConst.AUTODEBET_BCA
            self.feature_setting.parameters['disable'] = disable
            self.feature_setting.save()
            self.bri_feature_setting.parameters['disable'] = disable
            self.bri_feature_setting.save()
            self.gopay_feature_setting.parameters['disable'] = disable
            self.gopay_feature_setting.save()
            self.assertTrue(is_autodebet_feature_disable(AutodebetVendorConst.BCA))
            self.assertTrue(is_autodebet_feature_disable(AutodebetVendorConst.BRI))
            self.assertTrue(is_autodebet_feature_disable(AutodebetVendorConst.GOPAY))

            self.feature_setting.parameters['disable']["disable_start_date_time"] = '08-08-2023 12:30'
            self.feature_setting.save()
            self.assertFalse(is_autodebet_feature_disable(AutodebetVendorConst.BCA))

            self.gopay_feature_setting.parameters['disable']['disable_end_date_time'] = '05-08-2023 12:30'
            self.gopay_feature_setting.save()
            self.assertFalse(is_autodebet_feature_disable(AutodebetVendorConst.GOPAY))

            self.bri_feature_setting.parameters['disable']['disable_start_date_time'] = '08-08-2023 12:30'
            self.bri_feature_setting.parameters['disable']['disable_end_date_time'] = '05-08-2023 12:30'
            self.bri_feature_setting.save()
            self.assertFalse(is_autodebet_feature_disable(AutodebetVendorConst.BRI))


class TestIsIdfyEnable(TestCase):
    @mock.patch('juloserver.autodebet.services.account_services.FeatureSetting')
    def test_is_idfy_enable_when_feature_setting_does_not_exist(self, mock_feature_setting):
        mock_feature_setting.objects.filter().last.return_value = None
        result = is_idfy_enable(123)
        self.assertTrue(result)

    @mock.patch('juloserver.autodebet.services.account_services.FeatureSetting')
    def test_is_idfy_enable_when_account_id_is_in_parameters(self, mock_feature_setting):
        mock_feature_setting.objects.filter().last.return_value = mock.Mock(
            parameters={"account_id": [123]}
        )
        result = is_idfy_enable(123)
        self.assertTrue(result)

    @mock.patch('juloserver.autodebet.services.account_services.FeatureSetting')
    def test_is_idfy_enable_when_account_id_is_not_in_parameters(self, mock_feature_setting):
        mock_feature_setting.objects.filter().last.return_value = mock.Mock(
            parameters={"account_id": [456]}
        )
        result = is_idfy_enable(123)
        self.assertFalse(result)


class TestAutodebetIDFyValid(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
        )

        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_BCA,
            is_active=True,
            parameters={
                "disable": {
                    "disable_end_date_time": "25-09-2023 10:01",
                    "disable_start_date_time": "20-05-2023 09:00",
                },
                "minimum_amount": 10000,
            },
        )

    def test_autodebet_idfy_valid(self):
        is_valid = is_idfy_autodebet_valid(self.account)
        self.assertTrue(is_valid)

        self.autodebet_account = AutodebetAccountFactory(
            account=self.account,
            status=AutodebetStatuses.REGISTERED,
        )
        is_valid = is_idfy_autodebet_valid(self.account)
        self.assertFalse(is_valid)


class TestAutodebetExperimentSetting(TestCase):
    def setUp(self):
        self.account_odd = AccountFactory(id=1)
        self.account_even = AccountFactory(id=2)
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.SMS_REMINDER_AUTODEBET_EXPERIMENT_CODE,
            name=ExperimentConst.SMS_REMINDER_AUTODEBET_EXPERIMENT_NAME,
            is_active=True,
            is_permanent=False,
            start_date=timezone.localtime(timezone.now()),
            end_date=timezone.localtime(timezone.now()) + timedelta(days=1),
            criteria={
                'account_id_tail': {
                    'experiment': [1, 3, 5, 7, 9],
                    'control': [0, 2, 4, 6, 8],
                },
            },
        )

    def test_get_autodebet_experiment_setting_valid(self):
        autodebet_experiment = get_autodebet_experiment_setting()
        self.assertIsNotNone(autodebet_experiment)
        self.assertEqual(
            autodebet_experiment.code, ExperimentConst.SMS_REMINDER_AUTODEBET_EXPERIMENT_CODE
        )

    def test_get_autodebet_experiment_setting_not_valid(self):
        # start and end date not valid
        self.experiment_setting.start_date = timezone.localtime(timezone.now()) - timedelta(days=1)
        self.experiment_setting.end_date = timezone.localtime(timezone.now()) - timedelta(days=1)
        self.experiment_setting.save()
        autodebet_experiment = get_autodebet_experiment_setting()
        self.assertIsNone(autodebet_experiment)

    def test_get_autodebet_experiment_setting_not_active(self):
        # is active not
        self.experiment_setting.is_active = False
        self.experiment_setting.save()
        autodebet_experiment = get_autodebet_experiment_setting()
        self.assertIsNone(autodebet_experiment)

    def test_is_experiment_group_autodebet(self):
        result_odd = is_experiment_group_autodebet(self.account_odd)
        result_even = is_experiment_group_autodebet(self.account_even)

        self.assertTrue(result_odd)
        self.assertFalse(result_even)


class TestDisableAutodebetActivation(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.status = StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.deactivated,
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            account=self.account,
        )
        self.account_status_history = AccountStatusHistoryFactory(
            account=self.account,
            change_reason=AccountChangeReason.EXCEED_DPD_THRESHOLD,
            status_old_id=420,
            status_new_id=432,
        )
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_90DPD),
        )

    def test_is_disabled_autodebet_activation(self):
        is_disabled = is_disabled_autodebet_activation(self.account)

        self.assertTrue(is_disabled)
