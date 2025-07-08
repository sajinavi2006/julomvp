from datetime import (
    date,
    datetime,
    timedelta,
)
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from factory import Iterator

from juloserver.account.constants import AccountChangeReason, AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountStatusHistoryFactory,
)
from juloserver.ana_api.tests.factories import PdApplicationFraudModelResultFactory
from juloserver.api_token.constants import (
    REFRESH_TOKEN_EXPIRY,
    REFRESH_TOKEN_MIN_APP_VERSION,
)
from juloserver.api_token.models import ExpiryToken
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.application_flow.factories import ApplicationRiskyCheckFactory
from juloserver.customer_module.tests.factories import (
    BankAccountCategoryFactory,
    BankAccountDestinationFactory,
)
from juloserver.fraud_security.constants import (
    FraudFlagSource,
    FraudFlagTrigger,
    FraudFlagType,
)
from juloserver.fraud_security.models import (
    FraudFlag,
    FraudVelocityModelGeohash,
    FraudSwiftLimitDrainerAccount,
    FraudTelcoMaidTemporaryBlock,
    FraudBlockAccount,
)
from juloserver.fraud_security.services import (
    ATODeviceChangeLoanChecker,
    ATODeviceChangeSetting,
    VelocityModelGeohashService,
    add_android_id_to_blacklisted_fraudster,
    add_geohash_to_fraud_hotspot,
    check_login_for_ato_device_change,
    fetch_geohash_applications,
    fetch_unchecked_geohashes,
    is_android_whitelisted,
    update_and_record_geohash_result_check,
    blacklisted_asn_check,
    block_swift_limit_drainer_account,
    block_telco_maid_location_account,
    update_fraud_block_account_by_agent,
)
from juloserver.fraud_security.tests.factories import (
    FraudBlacklistedASNFactory,
    FraudFlagFactory,
    FraudVelocityModelGeohashBucketFactory,
    FraudVelocityModelGeohashFactory,
    FraudVelocityModelResultsCheckFactory,
    SecurityWhitelistFactory,
    FraudBlockAccountFactory,
)
from juloserver.geohash.tests.factories import AddressGeolocationGeohashFactory
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.statuses import (
    JuloOneCodes,
    LoanStatusCodes,
)
from juloserver.julo.tests.factories import (
    AddressGeolocationFactory,
    ApplicationHistoryFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    DeviceFactory,
    DeviceIpHistoryFactory,
    FeatureSettingFactory,
    FruadHotspotFactory,
    LoanFactory,
    StatusLookupFactory,
    VPNDetectionFactory,
    WorkflowFactory,
)
from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.loan.constants import LoanStatusChangeReason
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.pin.models import LoginAttempt
from juloserver.pin.tests.factories import (
    BlacklistedFraudsterFactory,
    LoginAttemptFactory,
)


class TestCheckLoginForAtoDeviceChange(TestCase):
    def setUp(self):
        self.prev_attempt = LoginAttemptFactory(
            android_id='android-old',
            is_success=True,
            latitude=-5,
            longitude=105,
        )
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_ATO_DEVICE_CHANGE,
            is_active=True,
        )

    def test_setting_is_not_active(self):
        current_attempt = LoginAttemptFactory(
            customer=self.prev_attempt.customer,
            android_id='android-current',
            is_success=True,
            latitude=-6,
            longitude=106,
        )

        self.setting.is_active = False
        self.setting.save()
        ret_val = check_login_for_ato_device_change(current_attempt)
        self.assertIsNone(ret_val)

        self.setting.delete()
        ret_val = check_login_for_ato_device_change(current_attempt)
        self.assertIsNone(ret_val)

    def test_create_fraud_flag(self):
        current_attempt = LoginAttemptFactory(
            customer=self.prev_attempt.customer,
            android_id='android-current',
            is_success=True,
            latitude=-6,
            longitude=106,
        )
        ret_val = check_login_for_ato_device_change(current_attempt)

        self.assertIsInstance(ret_val, FraudFlag)
        self.assertEqual(FraudFlagTrigger.LOGIN_SUCCESS, ret_val.trigger)
        self.assertEqual(FraudFlagSource.ANDROID, ret_val.flag_source_type)
        self.assertEqual(FraudFlagType.ATO_DEVICE_CHANGE, ret_val.fraud_type)
        self.assertEqual('android-current', ret_val.flag_source_id)
        self.assertEqual(current_attempt.customer_id, ret_val.customer_id)

    def test_same_android_id(self):
        LoginAttemptFactory(
            customer=self.prev_attempt.customer,
            android_id='android-new',
            is_success=True,
            latitude=-6,
            longitude=106,
        )
        current_attempt = LoginAttemptFactory(
            customer=self.prev_attempt.customer,
            android_id='android-new',
            is_success=True,
            latitude=-5,
            longitude=105,
        )
        ret_val = check_login_for_ato_device_change(current_attempt)

        self.assertIsNone(ret_val)

    def test_less_than_distance(self):
        current_attempt = LoginAttemptFactory(
            customer=self.prev_attempt.customer,
            android_id='android-current',
            is_success=True,
            latitude=-5.001,
            longitude=105.001,
        )
        ret_val = check_login_for_ato_device_change(current_attempt)

        self.assertIsNone(ret_val)

    def test_already_whitelist(self):
        SecurityWhitelistFactory(
            customer=self.prev_attempt.customer,
            object_id='android-current',
            object_type=FraudFlagSource.ANDROID,
        )
        current_attempt = LoginAttemptFactory(
            customer=self.prev_attempt.customer,
            android_id='android-current',
            is_success=True,
            latitude=-6,
            longitude=106,
        )
        ret_val = check_login_for_ato_device_change(current_attempt)

        self.assertIsNone(ret_val)

    def test_skip_check_for_7_10_0_version(self):
        self.prev_attempt.update_safely(app_version='7.10.0')
        current_attempt = LoginAttemptFactory(
            customer=self.prev_attempt.customer,
            android_id='android-current',
            is_success=True,
            latitude=-6,
            longitude=106,
        )
        ret_val = check_login_for_ato_device_change(current_attempt)
        self.assertIsNone(ret_val)

        self.prev_attempt.update_safely(app_version=None)
        current_attempt.update_safely(app_version='7.10.0')
        ret_val = check_login_for_ato_device_change(current_attempt)
        self.assertIsNone(ret_val)

    def test_skip_check_for_7_10_1_version(self):
        self.prev_attempt.update_safely(app_version='7.10.1')
        current_attempt = LoginAttemptFactory(
            customer=self.prev_attempt.customer,
            android_id='android-current',
            is_success=True,
            latitude=-6,
            longitude=106,
        )
        ret_val = check_login_for_ato_device_change(current_attempt)
        self.assertIsNone(ret_val)

        self.prev_attempt.update_safely(app_version=None)
        current_attempt.update_safely(app_version='7.10.1')
        ret_val = check_login_for_ato_device_change(current_attempt)
        self.assertIsNone(ret_val)

    def test_for_newly_register_user(self):
        customer = self.prev_attempt.customer
        account = AccountFactory(
            customer=customer, status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        )
        application = ApplicationJ1Factory(customer=customer, account=account)
        address_geolocation = AddressGeolocationFactory(
            application=application, latitude=-10, longitude=4
        )
        device = DeviceFactory(customer=customer, android_id='android-oldest')
        self.assertEqual(1, LoginAttempt.objects.count())
        ret_val = check_login_for_ato_device_change(current_attempt=self.prev_attempt)

        self.assertIsInstance(ret_val, FraudFlag)
        self.assertEqual(FraudFlagTrigger.LOGIN_SUCCESS, ret_val.trigger)
        self.assertEqual(FraudFlagSource.ANDROID, ret_val.flag_source_type)
        self.assertEqual(FraudFlagType.ATO_DEVICE_CHANGE, ret_val.fraud_type)
        self.assertEqual('android-old', ret_val.flag_source_id)
        self.assertEqual(self.prev_attempt.customer_id, ret_val.customer_id)


class TestATODeviceChangeLoanChecker(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        )
        self.application = ApplicationJ1Factory(
            customer=self.customer,
            account=self.account,
        )
        self.account_limit = AccountLimitFactory(
            account=self.account,
        )
        self.loan = LoanFactory(
            transaction_method_id=TransactionMethodCode.OTHER.code,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE),
            customer=self.customer,
            account=self.account,
        )
        self.user = self.customer.user
        self.auth_token = self.user.auth_expiry_token
        self.fraud_flag = FraudFlagFactory(
            fraud_type=FraudFlagType.ATO_DEVICE_CHANGE,
            flag_source_type=FraudFlagSource.ANDROID,
            flag_source_id='android-current',
            trigger=FraudFlagTrigger.LOGIN_SUCCESS,
            extra={'prev_android_id': 'android-old'},
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_ATO_DEVICE_CHANGE,
            is_active=True,
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.EXPIRY_TOKEN_SETTING,
            is_active=True,
            parameters={
                "expiry_token_hours": 720,
                REFRESH_TOKEN_EXPIRY: 8760.01,
                REFRESH_TOKEN_MIN_APP_VERSION: '8.13.0'
            },
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.LEGACY)
        WorkflowStatusPathFactory(status_previous=210, status_next=216, workflow=self.workflow)

    def test_is_fraud_true(self):
        checker = ATODeviceChangeLoanChecker(loan=self.loan, android_id='android-current')

        self.assertTrue(checker.is_fraud())
        self.assertTrue(checker._can_be_block)
        self.assertEqual(
            {
                'transaction_method_id': TransactionMethodCode.OTHER.code,
                'fraud_flag_id': self.fraud_flag.id,
                'current_android_id': 'android-current',
                'checked_android_id': 'android-old',
            },
            checker._check_data,
        )

    def test_is_fraud_tarik_dana(self):
        self.loan.update_safely(transaction_method_id=TransactionMethodCode.SELF.code)
        checker = ATODeviceChangeLoanChecker(loan=self.loan, android_id='android-current')

        self.assertFalse(checker.is_fraud())

    def test_is_fraud_not_suspicious(self):
        checker = ATODeviceChangeLoanChecker(loan=self.loan, android_id='android-old')

        self.assertFalse(checker.is_fraud())

    def test_is_fraud_whitelisted(self):
        SecurityWhitelistFactory(
            customer=self.customer,
            object_id='android-current',
            object_type=FraudFlagSource.ANDROID,
        )
        checker = ATODeviceChangeLoanChecker(loan=self.loan, android_id='android-current')

        self.assertFalse(checker.is_fraud())

    @mock.patch('juloserver.fraud_security.services.send_pn_fraud_ato_device_change.apply_async')
    def test_block_success(self, mock_send_pn_fraud_ato_device_change):
        self.auth_token.update_safely(is_active=True)
        checker = ATODeviceChangeLoanChecker(loan=self.loan, android_id='android-current')
        checker.is_fraud()
        ret_val = checker.block()

        old_token_key = self.auth_token.key
        self.loan.refresh_from_db()
        self.auth_token.refresh_from_db()
        expected_extra_data = {
            'transaction_method_id': TransactionMethodCode.OTHER.code,
            'fraud_flag_id': self.fraud_flag.id,
            'current_android_id': 'android-current',
            'checked_android_id': 'android-old',
        }
        expected_message = "Fraud ATO Device Change"
        self.assertIsInstance(ret_val, FraudFlag)
        self.assertEqual(FraudFlagType.ATO_DEVICE_CHANGE, ret_val.fraud_type)
        self.assertEqual(FraudFlagSource.LOAN, ret_val.flag_source_type)
        self.assertEqual(FraudFlagTrigger.LOAN_CREATION, ret_val.trigger)
        self.assertEqual(self.loan.id, ret_val.flag_source_id)
        self.assertEqual(expected_extra_data, ret_val.extra)
        self.assertEqual(self.customer.id, ret_val.customer_id)

        self.assertEqual(LoanStatusCodes.CANCELLED_BY_CUSTOMER, self.loan.loan_status_id)
        self.assertEqual(expected_message, self.loan.loanhistory_set.last().change_reason)

        self.assertEqual(JuloOneCodes.FRAUD_REPORTED, self.account.status_id)
        self.assertEqual(
            expected_message, self.account.accountstatushistory_set.last().change_reason
        )

        self.assertNotEqual(old_token_key, self.auth_token.key)
        expiry_token = ExpiryToken.objects.get(user=self.user)
        self.assertIsNotNone(expiry_token.refresh_key)

        force_run_on_commit_hook()
        mock_send_pn_fraud_ato_device_change.assert_called_once_with(
            [self.customer.id],
            countdown=20,
        )

    def test_block_without_is_fraud(self):
        checker = ATODeviceChangeLoanChecker(loan=self.loan, android_id='android-current')
        ret_val = checker.block()

        self.assertIsNone(ret_val)

    def test_ato_device_change_loan_checker_exclude_julover_email(self):
        customer = self.loan.customer
        customer.email = 'julo12345@julo.co.id'
        customer.save()
        self.loan.refresh_from_db()
        checker = ATODeviceChangeLoanChecker(loan=self.loan, android_id='android-current')
        ret_val = checker.is_fraud()

        self.assertFalse(ret_val)

    def test_is_fraud_true_none_customer_email(self):
        customer_copy = self.customer
        customer_copy.email = None
        loan_copy = self.loan
        loan_copy.customer = customer_copy

        checker = ATODeviceChangeLoanChecker(loan=loan_copy, android_id='android-current')

        self.assertTrue(checker.is_fraud())
        self.assertTrue(checker._can_be_block)
        self.assertEqual(
            {
                'transaction_method_id': TransactionMethodCode.OTHER.code,
                'fraud_flag_id': self.fraud_flag.id,
                'current_android_id': 'android-current',
                'checked_android_id': 'android-old',
            },
            checker._check_data,
        )

    def test_is_fraud_is_change_bank_account_destination_day_diff_under_config(self):
        bank_account_category = BankAccountCategoryFactory(
            category='self', display_label='Pribadi', parent_category_id=1
        )
        self.bank_account_1 = BankAccountDestinationFactory(
            cdate=timezone.localtime(timezone.now()).date(),
            bank_account_category=bank_account_category,
            customer=self.customer,
            account_number='12345',
            is_deleted=False,
        )
        checker = ATODeviceChangeLoanChecker(loan=self.loan, android_id='android-current')
        result = checker._is_change_bank_account_destination_day_diff_under_config()
        self.assertFalse(result)  # because only has 1 bank account destination

        self.bank_account_2 = BankAccountDestinationFactory(
            cdate=timezone.localtime(timezone.now()).date() - timedelta(days=17),
            bank_account_category=bank_account_category,
            customer=self.customer,
            account_number='123456',
            is_deleted=False,
        )
        self.bank_account_1.update_safely(
            cdate=timezone.localtime(timezone.now()).date() - timedelta(days=16)
        )
        self.bank_account_2.update_safely(
            cdate=timezone.localtime(timezone.now()).date() - timedelta(days=7)
        )
        result = checker._is_change_bank_account_destination_day_diff_under_config()
        self.assertFalse(result)  # the bank account destination is more than the threshold

        self.bank_account_3 = BankAccountDestinationFactory(
            cdate=timezone.localtime(timezone.now()).date(),
            bank_account_category=bank_account_category,
            customer=self.customer,
            account_number='12345',
            is_deleted=False,
        )
        self.bank_account_2.update_safely(
            cdate=timezone.localtime(timezone.now()).date() - timedelta(days=3)
        )
        result = checker._is_change_bank_account_destination_day_diff_under_config()
        self.assertTrue(result)


class TestATODeviceChangeSetting(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_ATO_DEVICE_CHANGE,
            is_active=True,
        )

    def test_is_active(self):
        setting = ATODeviceChangeSetting()
        self.assertTrue(setting.is_active)

    def test_other_default_value(self):
        setting = ATODeviceChangeSetting()
        self.assertEqual(50, setting.fraud_distance_in_km)
        self.assertEqual(5, setting.transaction_range_in_day)

    def test_fraud_distance_in_km(self):
        self.feature_setting.update_safely(parameters={"fraud_distance_in_km": 10})
        setting = ATODeviceChangeSetting()
        self.assertEqual(10, setting.fraud_distance_in_km)

    def test_transaction_range_in_day(self):
        self.feature_setting.update_safely(parameters={"transaction_range_in_day": 1})
        setting = ATODeviceChangeSetting()
        self.assertEqual(1, setting.transaction_range_in_day)


class TestAddAndroidIdToBlacklistedFraudster(TestCase):
    def test_new_data(self):
        ret_val = add_android_id_to_blacklisted_fraudster('testandroidid', 'test reason')

        self.assertEqual('testandroidid', ret_val.android_id)
        self.assertEqual('test reason', ret_val.blacklist_reason)
        self.assertIsNotNone(ret_val.id)

    def test_existing_data(self):
        blacklist_fraudster = BlacklistedFraudsterFactory(android_id='testandroidid')
        ret_val = add_android_id_to_blacklisted_fraudster('testandroidid', 'test reason')

        self.assertEqual(blacklist_fraudster.id, ret_val.id)


class TestAddGeohashToFraudHotspot(TestCase):
    def test_new_data(self):
        ret_val = add_geohash_to_fraud_hotspot('testghsh')

        self.assertEqual('testghsh', ret_val.geohash)
        self.assertIsNotNone(ret_val.latitude)
        self.assertIsNotNone(ret_val.longitude)
        self.assertIsNotNone(ret_val.radius)

    def test_existing_data(self):
        fraud_hotspot = FruadHotspotFactory(geohash='testghsh')
        ret_val = add_geohash_to_fraud_hotspot('testghsh')

        self.assertEqual(fraud_hotspot.id, ret_val.id)


@mock.patch('juloserver.julo.workflows2.tasks.send_email_status_change_task.delay')
class TestVelocityModelGeohashServiceUpdateApplicationStatus(TestCase):
    @classmethod
    def setUpTestData(cls):
        j1_workflow = WorkflowFactory(name='JuloOneWorkflow')
        WorkflowStatusPathFactory.create_batch(
            2,
            status_previous=Iterator([100, 115]),
            status_next=133,
            is_active=True,
            workflow=j1_workflow,
        )

        # Recovery status path
        WorkflowStatusPathFactory(
            status_previous=115,
            status_next=124,
            is_active=True,
            workflow=j1_workflow,
        )

    def test_not_change_application_status(self, *args):
        for status in (190, 133):
            application = ApplicationJ1Factory(
                application_status=StatusLookupFactory(status_code=status),
            )

            old_status, new_status = VelocityModelGeohashService._update_application_status(
                application=application,
                is_fraud=True,
                change_reason='reason',
            )

            self.assertEqual(status, old_status)
            self.assertEqual(status, new_status)

    def test_change_application_status_if_fraud(self, *args):
        for status in (100, 115):
            application = ApplicationJ1Factory(
                application_status=StatusLookupFactory(status_code=status),
            )

            old_status, new_status = VelocityModelGeohashService._update_application_status(
                application=application,
                is_fraud=True,
                change_reason='reason',
            )

            application.refresh_from_db()
            self.assertEqual(133, application.status)
            self.assertEqual(status, old_status)
            self.assertEqual(133, new_status)

    def test_change_application_status_if_not_fraud(self, *args):
        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=115),
        )

        ApplicationHistoryFactory(application_id=application.id, status_old=105, status_new=124)
        ApplicationHistoryFactory(application_id=application.id, status_old=124, status_new=115)

        old_status, new_status = VelocityModelGeohashService._update_application_status(
            application=application,
            is_fraud=False,
            change_reason='reason',
        )

        application.refresh_from_db()
        self.assertEqual(124, application.status)
        self.assertEqual(115, old_status)
        self.assertEqual(124, new_status)

    def test_skip_change_application_status_if_not_fraud(self, *args):
        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=124),
        )

        ApplicationHistoryFactory(application_id=application.id, status_old=105, status_new=124)

        old_status, new_status = VelocityModelGeohashService._update_application_status(
            application=application,
            is_fraud=False,
            change_reason='reason',
        )

        application.refresh_from_db()
        self.assertEqual(124, application.status)
        self.assertEqual(124, old_status)
        self.assertEqual(124, new_status)

    def test_change_account_status_fraud(self, *args):
        for status in (410, 450):
            application = ApplicationJ1Factory(
                account=AccountFactory(status=StatusLookupFactory(status_code=status))
            )
            account = application.account

            old_status, new_status = VelocityModelGeohashService._update_account_status(
                account=account,
                is_fraud=True,
                change_reason='change account not fraud status',
            )

            account.refresh_from_db()
            history = account.accountstatushistory_set.last()
            self.assertEqual(440, account.status_id)
            self.assertEqual(status, old_status)
            self.assertEqual(440, new_status)
            self.assertEqual('change account not fraud status', history.change_reason)

    def test_change_account_status_not_fraud(self, *args):
        application = ApplicationJ1Factory(
            account=AccountFactory(status=StatusLookupFactory(status_code=450))
        )
        account = application.account

        AccountStatusHistoryFactory(account=account, status_old_id=420, status_new_id=450)

        old_status, new_status = VelocityModelGeohashService._update_account_status(
            account=account,
            is_fraud=False,
            change_reason='change account not fraud status',
        )

        account.refresh_from_db()
        history = account.accountstatushistory_set.last()
        self.assertEqual(420, account.status_id)
        self.assertEqual(450, old_status)
        self.assertEqual(420, new_status)
        self.assertEqual('change account not fraud status', history.change_reason)

    def test_skip_account_status_not_fraud(self, *args):
        application = ApplicationJ1Factory(
            account=AccountFactory(status=StatusLookupFactory(status_code=421))
        )
        account = application.account

        AccountStatusHistoryFactory(account=account, status_old_id=420, status_new_id=421)

        old_status, new_status = VelocityModelGeohashService._update_account_status(
            account=account,
            is_fraud=False,
            change_reason='change account not fraud status',
        )

        account.refresh_from_db()
        history = account.accountstatushistory_set.last()
        self.assertEqual(421, account.status_id)
        self.assertEqual(421, old_status)
        self.assertEqual(421, new_status)
        self.assertNotEqual('change account not fraud status', history.change_reason)

    def test_update_application_or_account_status_190(self, *args):
        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=190),
            account=AccountFactory(status=StatusLookupFactory(status_code=420)),
        )

        old_status, new_status = VelocityModelGeohashService.update_application_or_account_status(
            application=application,
            is_fraud=True,
            change_reason='geohash reason',
        )

        account = application.account
        account.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(440, account.status_id)
        self.assertEqual(190, application.status)
        self.assertEqual(420, old_status)
        self.assertEqual(440, new_status)

    def test_update_application_or_account_status_190_less(self, *args):
        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=115),
            account=AccountFactory(status=StatusLookupFactory(status_code=410)),
        )

        old_status, new_status = VelocityModelGeohashService.update_application_or_account_status(
            application=application,
            is_fraud=True,
            change_reason='geohash reason',
        )

        account = application.account
        account.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(410, account.status_id)
        self.assertEqual(133, application.status)
        self.assertEqual(115, old_status)
        self.assertEqual(133, new_status)


class TestVelocityModelGeohashService(TestCase):
    def test_add_application_to_velocity_model_geohash(self):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = timezone.localtime(datetime(2023, 1, 20, 8, 0, 0))
            AddressGeolocationGeohashFactory(geohash8='12345678')

        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = timezone.localtime(datetime(2023, 1, 22, 8, 0, 0))
            valid_geolocation = AddressGeolocationGeohashFactory(geohash8='12345678')

            # Invalid because already in velocity model geohash table.
            invalid_geolocation = AddressGeolocationGeohashFactory(geohash8='12345678')
            FraudVelocityModelGeohashFactory(
                geohash='12345678',
                application=invalid_geolocation.address_geolocation.application,
            )

        ret_val = VelocityModelGeohashService.add_application_to_velocity_model_geohash(
            geohash_str='12345678',
            risky_date=date(2023, 1, 30),
            filter_date=date(2023, 1, 21),
        )

        velocity_model_geohash = FraudVelocityModelGeohash.objects.last()
        self.assertEquals(2, len(ret_val))
        self.assertEquals(2, FraudVelocityModelGeohash.objects.count())
        self.assertEquals('2023-01-30', str(velocity_model_geohash.risky_date))
        self.assertEquals('12345678', velocity_model_geohash.geohash)
        self.assertEquals(
            valid_geolocation.address_geolocation.application_id,
            velocity_model_geohash.application_id,
        )

    def test_add_application_to_velocity_model_geohash_unsupported_geohash(self):
        with self.assertRaises(ValueError):
            VelocityModelGeohashService.add_application_to_velocity_model_geohash(
                geohash_str='1234567890',
                risky_date=date(2023, 1, 30),
                filter_date=date(2023, 1, 21),
            )

    @mock.patch.object(VelocityModelGeohashService, 'add_application_to_velocity_model_geohash')
    @mock.patch('juloserver.fraud_security.services.add_geohash_to_fraud_hotspot')
    @mock.patch(
        'juloserver.fraud_security.tasks.store_verification_result_for_velocity_model_geohash.delay'
    )
    def test_verify_fraud_velocity_geohash_bucket_as_fraud(
        self,
        mock_store_result,
        mock_add_fraud_hotspot,
        mock_add_application_to_velocity_model_geohash,
    ):
        bucket = FraudVelocityModelGeohashBucketFactory(geohash='12345678')
        result_check = FraudVelocityModelResultsCheckFactory(is_fraud=True)
        user = AuthUserFactory()

        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 1, 20, 8, 0, 0)
            VelocityModelGeohashService.verify_fraud_velocity_geohash_bucket(
                velocity_geohash_bucket=bucket,
                model_result_check=result_check,
                auth_user=user,
            )

        bucket.refresh_from_db()
        self.assertEqual(result_check.id, bucket.fraud_velocity_model_results_check_id)
        self.assertEqual(user.id, bucket.agent_user_id)

        mock_add_fraud_hotspot.assert_called_once_with('12345678')
        mock_add_application_to_velocity_model_geohash.assert_called_once_with(
            geohash_str='12345678',
            risky_date=date(2023, 1, 20),
            filter_date=date(2023, 1, 19),
        )
        mock_store_result.assert_called_once_with(bucket.id)

    @mock.patch.object(VelocityModelGeohashService, 'add_application_to_velocity_model_geohash')
    @mock.patch('juloserver.fraud_security.services.add_geohash_to_fraud_hotspot')
    @mock.patch(
        'juloserver.fraud_security.tasks.store_verification_result_for_velocity_model_geohash.delay'
    )
    def test_verify_fraud_velocity_geohash_bucket_as_not_fraud(
        self,
        mock_store_result,
        mock_add_fraud_hotspot,
        mock_add_application_to_velocity_model_geohash,
    ):
        bucket = FraudVelocityModelGeohashBucketFactory(geohash='12345678')
        result_check = FraudVelocityModelResultsCheckFactory(is_fraud=False)
        user = AuthUserFactory()

        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 1, 20, 8, 0, 0)
            VelocityModelGeohashService.verify_fraud_velocity_geohash_bucket(
                velocity_geohash_bucket=bucket,
                model_result_check=result_check,
                auth_user=user,
            )

        bucket.refresh_from_db()
        self.assertEqual(result_check.id, bucket.fraud_velocity_model_results_check_id)
        self.assertEqual(user.id, bucket.agent_user_id)

        mock_add_fraud_hotspot.assert_not_called()
        mock_add_application_to_velocity_model_geohash.assert_not_called()
        mock_store_result.assert_called_once_with(bucket.id)

    @mock.patch.object(VelocityModelGeohashService, 'add_application_to_velocity_model_geohash')
    @mock.patch('juloserver.fraud_security.services.add_geohash_to_fraud_hotspot')
    @mock.patch(
        'juloserver.fraud_security.tasks.store_verification_result_for_velocity_model_geohash.delay'
    )
    def test_verify_fraud_velocity_geohash_bucket_has_been_verified(
        self,
        mock_store_result,
        mock_add_fraud_hotspot,
        mock_add_application_to_velocity_model_geohash,
    ):
        result_check = FraudVelocityModelResultsCheckFactory(is_fraud=False)
        bucket = FraudVelocityModelGeohashBucketFactory(
            geohash='12345678',
            fraud_velocity_model_results_check=result_check,
        )
        user = AuthUserFactory()

        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 1, 20, 8, 0, 0)
            VelocityModelGeohashService.verify_fraud_velocity_geohash_bucket(
                velocity_geohash_bucket=bucket,
                model_result_check=result_check,
                auth_user=user,
            )

        bucket.refresh_from_db()
        self.assertNotEqual(user.id, bucket.agent_user_id)

        mock_add_fraud_hotspot.assert_not_called()
        mock_add_application_to_velocity_model_geohash.assert_not_called()
        mock_store_result.assert_not_called()


class TestGeohashCRMServices(TestCase):
    def test_fetch_unchecked_geohashes(self):
        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=190),
            account=AccountFactory(status=StatusLookupFactory(status_code=420)),
        )
        bucket = FraudVelocityModelGeohashBucketFactory(geohash='12345678')
        data = fetch_unchecked_geohashes()
        self.assertEqual(data.count(), 1)

        result_check = FraudVelocityModelResultsCheckFactory(is_fraud=False)
        bucket.fraud_velocity_model_results_check = result_check
        bucket.save()

        data = fetch_unchecked_geohashes()
        self.assertEqual(data.count(), 0)

        bucket.fraud_velocity_model_results_check = None
        bucket.save()
        data = fetch_unchecked_geohashes()
        self.assertEqual(data.count(), 1)

    def test_fetch_unchecked_geohashes_search(self):
        geohashes = ['bucket_1', 'bucket_2', 'bucket_3']
        for hash in geohashes:
            customer = CustomerFactory(fullname=hash + ' testing', email=hash + '@julofinance.com')
            device = DeviceFactory(customer=customer, android_id=hash + '_id')
            application = ApplicationJ1Factory(
                customer=customer,
                application_status=StatusLookupFactory(status_code=190),
                account=AccountFactory(status=StatusLookupFactory(status_code=420)),
            )
            application.email = hash + '@julofinance.com'
            application.fullname = hash + ' testing'
            application.save()

            bucket = FraudVelocityModelGeohashBucketFactory(geohash=hash)
            geohash = FraudVelocityModelGeohashFactory(geohash=hash, application=application)

        # Test count of geohashes without search
        data = fetch_unchecked_geohashes()
        self.assertEqual(data.count(), 3)

        # Test count of geohashes with application_id as search param
        data = fetch_unchecked_geohashes(search_q=str(application.id))
        self.assertEqual(data.count(), 1)

        # Test count of geohashes with geohash as search param
        data = fetch_unchecked_geohashes(search_q='bucket_2')
        self.assertEqual(data.count(), 1)
        self.assertEqual(data.last().geohash, 'bucket_2')

        # Test count of geohashes with email as search param
        data = fetch_unchecked_geohashes(search_q='bucket_1@julofinance.com')
        self.assertEqual(data.count(), 1)

        # Test count of geohashes with adnroid_id as search param
        data = fetch_unchecked_geohashes(search_q=hash + '_id')
        self.assertEqual(data.count(), 1)

    def test_fetch_geohash_applications(self):
        hash = 'abcd'
        bucket = FraudVelocityModelGeohashBucketFactory(geohash=hash)
        for n in range(0, 3):
            customer = CustomerFactory(
                fullname=hash + ' testing_{}'.format(str(n)),
                email=hash + str(n) + '@julofinance.com',
            )
            device = DeviceFactory(customer=customer, android_id=hash + '_{}'.format(str(n)))
            application = ApplicationJ1Factory(
                customer=customer,
                application_status=StatusLookupFactory(status_code=190),
                account=AccountFactory(status=StatusLookupFactory(status_code=420)),
            )
            application.email = hash + str(n) + '@julofinance.com'
            application.fullname = hash + ' testing_{}'.format(str(n))
            application.save()
            FraudVelocityModelGeohashFactory(geohash=hash, application=application)
        data = fetch_geohash_applications(bucket_id=bucket.id)
        self.assertEqual(data.count(), 3)

    def test_fetch_geohash_applications_search(self):
        hash = 'abcd'
        bucket = FraudVelocityModelGeohashBucketFactory(geohash=hash)
        for n in range(0, 3):
            customer = CustomerFactory(
                fullname=hash + ' testing_{}'.format(str(n)),
                email=hash + str(n) + '@julofinance.com',
            )
            device = DeviceFactory(customer=customer, android_id=hash + '_{}'.format(str(n)))
            application = ApplicationJ1Factory(
                customer=customer,
                application_status=StatusLookupFactory(status_code=190),
                account=AccountFactory(status=StatusLookupFactory(status_code=420)),
            )
            application.email = hash + str(n) + '@julofinance.com'
            application.fullname = hash + ' testing_{}'.format(str(n))
            application.save()
            FraudVelocityModelGeohashFactory(geohash=hash, application=application)
        data = fetch_geohash_applications(bucket_id=bucket.id)
        self.assertEqual(data.count(), 3)

        # Test count of applications with application_id as search param
        data = fetch_geohash_applications(bucket_id=bucket.id, search_q=str(application.id))
        self.assertEqual(data.count(), 1)

        # Test count of applications with email as search param
        data = fetch_geohash_applications(
            bucket_id=bucket.id, search_q=hash + str(n) + '@julofinance.com'
        )
        self.assertEqual(data.count(), 1)

        # Test count of applications with fullname as search param
        data = fetch_geohash_applications(
            bucket_id=bucket.id, search_q=hash + ' testing_{}'.format(str(n))
        )
        self.assertEqual(data.count(), 1)

        # Test count of applications with android_id as search param
        data = fetch_geohash_applications(bucket_id=bucket.id, search_q=hash + '_{}'.format(str(n)))
        self.assertEqual(data.count(), 1)

    def test_update_and_record_geohash_result_check(self):
        hash = "abcd"
        customer = CustomerFactory(fullname="test user", email=hash + '@julofinance.com')
        ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=190),
            account=AccountFactory(status=StatusLookupFactory(status_code=420)),
        )
        bucket = FraudVelocityModelGeohashBucketFactory(geohash='12345678')
        data = {"bucket_id": bucket.id, "is_fraud": False}
        results_check = update_and_record_geohash_result_check(
            validated_data=data, agent_user=customer.user
        )
        self.assertEqual(results_check.is_fraud, False)


class TestIsAndroidWhitelisted(TestCase):
    def setUp(self):
        SecurityWhitelistFactory(object_id='android-id', object_type=FraudFlagSource.ANDROID)

    def test_is_true(self):
        ret_val = is_android_whitelisted('android-id')
        self.assertTrue(ret_val)

    def test_is_false(self):
        ret_val = is_android_whitelisted('not-found-android-id')
        self.assertFalse(ret_val)


class TestFraudBlacklistedASN(TestCase):
    def setUp(self):
        self.j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=124),
        )
        self.application_risky_check = ApplicationRiskyCheckFactory(application=self.application)
        self.device_ip_history = DeviceIpHistoryFactory(customer=self.application.customer)
        self.vpn_detection = VPNDetectionFactory(
            ip_address='127.0.0.1', is_vpn_detected=True, extra_data={'org': 'testing_org'}
        )
        self.blocked_asn = FraudBlacklistedASNFactory(asn_data='testing_org')
        WorkflowStatusPathFactory(
            status_previous=124,
            status_next=133,
            workflow=self.j1_workflow,
            is_active=True,
        )
        self.feature_blocked_asn = FeatureSettingFactory(
            feature_name=FeatureNameConst.BLACKLISTED_ASN
        )

    def test_blacklisted_asn_check_feature_off(self):
        self.feature_blocked_asn.is_active = False
        self.feature_blocked_asn.save()
        self.feature_blocked_asn.refresh_from_db()
        result = blacklisted_asn_check(self.application)
        self.assertEqual(False, result)

    def test_blacklisted_asn_check_no_device_ip_history(self):
        self.device_ip_history.delete()
        result = blacklisted_asn_check(self.application)
        self.assertEqual(False, result)

    def test_blacklisted_asn_check_no_vpn_detection(self):
        self.vpn_detection.delete()
        result = blacklisted_asn_check(self.application)
        self.assertEqual(False, result)

    def test_blacklisted_asn_check_no_blocked_asn_row(self):
        self.blocked_asn.delete()
        result = blacklisted_asn_check(self.application)
        self.assertEqual(False, result)

    def test_blacklisted_asn_check_is_vpn_detected_false(self):
        self.vpn_detection.is_vpn_detected = False
        self.vpn_detection.save()
        result = blacklisted_asn_check(self.application)
        self.assertEqual(False, result)

    @mock.patch('juloserver.julo.workflows.send_email_status_change_task')
    def test_blacklisted_asn_check_no_app_risky_check(self, mock_send_email_status_change_task):
        self.application_risky_check.delete()
        result = blacklisted_asn_check(self.application)
        self.assertEqual(True, result)
        self.application.refresh_from_db()

    @mock.patch('juloserver.julo.workflows.send_email_status_change_task')
    def test_blacklisted_asn_check(self, mock_send_email_status_change_task):
        result = blacklisted_asn_check(self.application)
        self.assertEqual(True, result)
        self.application.refresh_from_db()


@mock.patch('juloserver.fraud_security.services.process_change_account_status', return_value=None)
@mock.patch(
    'juloserver.fraud_security.services.update_loan_status_and_loan_history', return_value=None
)
class TestBlockSwiftLimitDrainerAccount(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.loan = LoanFactory(account=self.account)

    def test_successful_execution(self, mock_update_loan, mock_process_change_account_status):
        block_swift_limit_drainer_account(self.account, self.loan.id)
        mock_update_loan.assert_called_once_with(
            self.loan.id,
            new_status_code=215,
            change_reason='System - Blocked Swift Limit Drainer',
        )
        mock_process_change_account_status.assert_called_once_with(
            self.account, 440, 'System - Blocked Swift Limit Drainer'
        )
        fraud_in_table = FraudBlockAccount.objects.filter(account=self.account).last()
        self.assertIsNotNone(fraud_in_table)


@mock.patch('juloserver.fraud_security.services.process_change_account_status', return_value=None)
@mock.patch(
    'juloserver.fraud_security.services.update_loan_status_and_loan_history', return_value=None
)
class TestBlockTelcoMaidLocationAccount(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.loan = LoanFactory(account=self.account)

    def test_successful_execution(self, mock_update_loan, mock_process_change_account_status):
        block_telco_maid_location_account(self.account, self.loan.id)
        mock_update_loan.assert_called_once_with(
            self.loan.id,
            new_status_code=215,
            change_reason=LoanStatusChangeReason.TELCO_MAID_LOCATION,
        )
        mock_process_change_account_status.assert_called_once_with(
            self.account, 440, AccountChangeReason.TELCO_MAID_LOCATION
        )
        telco_maid_block_account = FraudTelcoMaidTemporaryBlock.objects.get_or_none(
            account=self.account
        )
        self.assertIsNotNone(telco_maid_block_account)


@mock.patch('juloserver.fraud_security.services.process_application_status_change')
@mock.patch('juloserver.fraud_security.services.process_change_account_status', return_value=None)
class TestFraudBlockAccountByAgent(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=121),
            account=AccountFactory(status=StatusLookupFactory(status_code=420)),
        )
        self.fraud_block_account = FraudBlockAccountFactory(
            feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER,
            account=self.account,
            is_block=False,
            is_need_action=True,
        )
        self.pd_credit_model_score = PdCreditModelResultFactory(
            application_id=self.application.id, has_fdc=True
        )
        self.pd_application_fraud_model_result = PdApplicationFraudModelResultFactory(
            application_id=self.application.id, pgood=0.9
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER,
            parameters={'jail_days': 0, 'mycroft_j1': 0.85},
            is_active=True,
        )

    def test_blocked_by_swift_limit(
        self, mock_process_change_account_status, mock_process_application_status_change
    ):
        update_fraud_block_account_by_agent(
            self.fraud_block_account,
            self.application,
            True,
            True,
        )
        self.assertTrue(self.fraud_block_account.is_appeal)
        self.assertTrue(self.fraud_block_account.is_confirmed_fraud)
        self.assertTrue(self.fraud_block_account.is_block)
        self.assertTrue(self.fraud_block_account.is_verified_by_agent)
        mock_process_change_account_status.assert_called_once_with(
            account=self.account,
            new_status_code=AccountConstant.STATUS_CODE.__dict__.get('terminated', None),
            change_reason=AccountChangeReason.PERMANENT_BLOCK_SWIFT_LIMIT_DRAINER,
        )
        mock_process_application_status_change.assert_called_once()

    def test_blocked_by_swift_limit_2(
        self, mock_process_change_account_status, mock_process_application_status_change
    ):
        self.pd_credit_model_score.has_fdc = False
        self.pd_credit_model_score.save()
        update_fraud_block_account_by_agent(
            self.fraud_block_account,
            self.application,
            True,
            False,
        )
        self.assertTrue(self.fraud_block_account.is_appeal)
        self.assertFalse(self.fraud_block_account.is_confirmed_fraud)
        self.assertTrue(self.fraud_block_account.is_block)
        self.assertTrue(self.fraud_block_account.is_verified_by_agent)
        mock_process_change_account_status.assert_called_once_with(
            account=self.account,
            new_status_code=AccountConstant.STATUS_CODE.__dict__.get('terminated', None),
            change_reason=AccountChangeReason.PERMANENT_BLOCK_SWIFT_LIMIT_DRAINER,
        )
        mock_process_application_status_change.assert_called_once()

    def test_blocked_by_swift_limit_3(
        self, mock_process_change_account_status, mock_process_application_status_change
    ):
        self.pd_credit_model_score.has_fdc = False
        self.pd_credit_model_score.save()
        self.pd_application_fraud_model_result.pgood = 0.1
        self.pd_application_fraud_model_result.save()

        update_fraud_block_account_by_agent(
            self.fraud_block_account,
            self.application,
            True,
            False,
        )
        self.assertTrue(self.fraud_block_account.is_appeal)
        self.assertFalse(self.fraud_block_account.is_confirmed_fraud)
        self.assertTrue(self.fraud_block_account.is_block)
        self.assertTrue(self.fraud_block_account.is_verified_by_agent)
        mock_process_change_account_status.assert_called_once_with(
            account=self.account,
            new_status_code=AccountConstant.STATUS_CODE.__dict__.get('terminated', None),
            change_reason=AccountChangeReason.PERMANENT_BLOCK_SWIFT_LIMIT_DRAINER,
        )
        mock_process_application_status_change.assert_called_once()

    def test_block_false_by_swift_limit(
        self, mock_process_change_account_status, mock_process_application_status_change
    ):
        update_fraud_block_account_by_agent(
            self.fraud_block_account,
            self.application,
            True,
            False,
        )
        self.assertTrue(self.fraud_block_account.is_appeal)
        self.assertFalse(self.fraud_block_account.is_confirmed_fraud)
        self.assertFalse(self.fraud_block_account.is_block)
        self.assertTrue(self.fraud_block_account.is_verified_by_agent)
        mock_process_change_account_status.assert_called_once_with(
            account=self.account,
            new_status_code=AccountConstant.STATUS_CODE.__dict__.get('active', None),
            change_reason=AccountChangeReason.SWIFT_LIMIT_DRAINER_RETURN,
        )
        mock_process_application_status_change.assert_not_called()

    def test_block_false_by_swift_limit_2(
        self, mock_process_change_account_status, mock_process_application_status_change
    ):
        update_fraud_block_account_by_agent(
            self.fraud_block_account,
            self.application,
            False,
            False,
        )
        self.assertFalse(self.fraud_block_account.is_appeal)
        self.assertFalse(self.fraud_block_account.is_block)
        self.assertTrue(self.fraud_block_account.is_verified_by_agent)
        self.assertFalse(self.fraud_block_account.is_confirmed_fraud)
        mock_process_change_account_status.assert_called_once_with(
            account=self.account,
            new_status_code=AccountConstant.STATUS_CODE.__dict__.get('active', None),
            change_reason=AccountChangeReason.SWIFT_LIMIT_DRAINER_RETURN,
        )
        mock_process_application_status_change.assert_not_called()
