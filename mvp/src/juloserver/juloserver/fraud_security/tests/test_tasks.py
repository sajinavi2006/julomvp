from datetime import (
    datetime,
)
from importlib import import_module
from unittest import mock
from unittest.mock import MagicMock

from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.utils import timezone
from factory import Iterator
from mock import patch

from juloserver.account.constants import AccountChangeReason
from juloserver.account.tests.factories import (
    AccountFactory,
)
from juloserver.ana_api.tests.factories import PdApplicationFraudModelResultFactory
from juloserver.antifraud.constant.call_back import CallBackType
from juloserver.application_flow.factories import ApplicationRiskyCheckFactory
from juloserver.followthemoney.factories import ApplicationHistoryFactory
from juloserver.fraud_security.constants import (
    FraudApplicationBucketType,
    FraudBucket,
    FraudChangeReason,
    FraudFlagType,
)
from juloserver.fraud_security.models import (
    FraudApplicationBucket,
    FraudFlag,
    FraudVelocityModelGeohash,
    FraudVelocityModelGeohashBucket,
    FraudVerificationResults,
    FraudSwiftLimitDrainerAccount,
    FraudTelcoMaidTemporaryBlock,
    BankNameVelocityThresholdHistory,
    FraudBlockAccount,
)
from juloserver.fraud_security.services import VelocityModelGeohashService
from juloserver.fraud_security.tasks import (
    add_geohash_to_velocity_model_geohash_bucket,
    check_high_risk_asn,
    flag_application_as_fraud_suspicious,
    insert_fraud_application_bucket,
    process_fraud_hotspot_geohash_velocity_model,
    process_mobile_user_action_log_checks,
    remove_application_from_fraud_application_bucket,
    scan_fraud_hotspot_geohash_velocity_model,
    store_verification_result_for_velocity_model_geohash,
    flag_blacklisted_android_id_for_j1_and_jturbo_task,
    flag_blacklisted_phone_for_j1_and_jturbo_task,
    swift_limit_drainer_account_daily_action,
    telco_maid_temporary_block_daily_action,
    save_bank_name_velocity_threshold_history,
    fraud_block_account_daily_action,
)
from juloserver.fraud_security.tests.factories import (
    FraudApplicationBucketFactory,
    FraudHighRiskAsnFactory,
    FraudVelocityModelGeohashBucketFactory,
    FraudVelocityModelGeohashFactory,
    FraudVelocityModelResultsCheckFactory,
    FraudVerificationResultsFactory,
    FraudSwiftLimitDrainerAccountFactory,
    FraudAppealTemporaryBlockFactory,
    FraudTelcoMaidTemporaryBlockFactory,
    FraudBlockAccountFactory,
)
from juloserver.geohash.tests.factories import AddressGeolocationGeohashFactory
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.models import StatusLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    DeviceFactory,
    DeviceIpHistoryFactory,
    FeatureSettingFactory,
    FruadHotspotFactory,
    StatusLookupFactory,
    VPNDetectionFactory,
    WorkflowFactory,
    ProductLineFactory,
)
from juloserver.julocore.tests import force_run_on_commit_hook
from juloserver.pin.models import BlacklistedFraudster


@mock.patch('juloserver.fraud_security.tasks.process_fraud_hotspot_geohash_velocity_model.delay')
@mock.patch.object(timezone, 'now')
class TestScanFraudHotspotGeohashVelocityModel(TestCase):
    def setUp(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_VELOCITY_MODEL_GEOHASH, is_active=True
        )

    def test_success_filter(self, mock_now, mock_process_velocity_model):
        now = timezone.localtime(datetime(2023, 1, 10, 10, 0, 0))

        # Prepare invalid data
        mock_now.return_value = now - relativedelta(days=1)
        AddressGeolocationGeohashFactory(
            geohash8='12345679',
            geohash9='123456799',
        )

        # Prepare valid data
        mock_now.return_value = now
        AddressGeolocationGeohashFactory.create_batch(
            3,
            geohash8=Iterator(['12345677', '12345678', '12345677']),
            geohash9=Iterator(['123456788', '123456789', '123456770']),
        )

        scan_fraud_hotspot_geohash_velocity_model()

        mock_process_velocity_model.assert_has_calls(
            [
                mock.call('12345677', check_time=now),
                mock.call('12345678', check_time=now),
                mock.call('123456770', check_time=now),
                mock.call('123456788', check_time=now),
                mock.call('123456789', check_time=now),
            ]
        )

    def test_process_pre_midnight_data(self, mock_now, mock_process_velocity_model):
        now = timezone.localtime(datetime(2023, 1, 10, 0, 0, 0))

        mock_now.return_value = timezone.localtime(datetime(2023, 1, 9, 23, 59, 59))
        AddressGeolocationGeohashFactory(
            geohash8='12345679',
            geohash9='123456799',
        )

        mock_now.return_value = now
        scan_fraud_hotspot_geohash_velocity_model()

        expected_check_time = timezone.localtime(datetime(2023, 1, 9, 23, 59, 59))
        mock_process_velocity_model.assert_has_calls(
            [
                mock.call('12345679', check_time=expected_check_time),
                mock.call('123456799', check_time=expected_check_time),
            ]
        )

    @mock.patch('juloserver.fraud_security.tasks.get_redis_client')
    def test_with_cache(self, mock_get_redis_client, mock_now, mock_process_velocity_model):
        now = timezone.localtime(datetime(2023, 1, 10, 10, 0, 0))

        # Prepare invalid data
        mock_now.return_value = now - relativedelta(days=1)
        AddressGeolocationGeohashFactory(
            geohash8='12345679',
            geohash9='123456799',
        )

        # Prepare valid data
        mock_now.return_value = now
        geohashes = AddressGeolocationGeohashFactory.create_batch(
            3,
            geohash8=Iterator(['12345677', '12345678', '12345677']),
            geohash9=Iterator(['123456788', '123456789', '123456770']),
        )

        mock_get_redis_client.return_value.get.return_value = geohashes[0].id

        scan_fraud_hotspot_geohash_velocity_model()

        mock_get_redis_client.return_value.get.assert_called_once()
        mock_get_redis_client.return_value.set.assert_called_once()
        mock_process_velocity_model.assert_has_calls(
            [
                mock.call('12345677', check_time=now),
                mock.call('12345678', check_time=now),
                mock.call('123456770', check_time=now),
                mock.call('123456789', check_time=now),
            ]
        )


@mock.patch('juloserver.fraud_security.tasks.add_geohash_to_velocity_model_geohash_bucket.delay')
class TestProcessFraudHotspotGeohashVelocityModel(TestCase):
    def setUp(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_VELOCITY_MODEL_GEOHASH,
            is_active=True,
            parameters={'geohash8': {}, 'geohash9': {}},
        )

    @staticmethod
    def create_address_geohash(total, created_at, **data):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = created_at
            return AddressGeolocationGeohashFactory.create_batch(
                total,
                **data,
            )

    def test_risky_and_store_velocity_model(self, mock_add_geohash_task, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(1, now, geohash8=check_geohash)
        self.create_address_geohash(5, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(1, now - relativedelta(days=7), geohash8=check_geohash)
        self.create_address_geohash(2, now - relativedelta(days=13), geohash8=check_geohash)

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)

        self.assertEqual(
            9,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash, risky_date=now.date()
            ).count(),
        )

        mock_add_geohash_task.assert_called_once_with('12345678', mock.ANY)

    def test_store_x105_data(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(datetime(2023, 1, 10, 10, 0, 0))
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now
            # Prepare 6 day data.
            geohashes = self.create_address_geohash(
                6, now - relativedelta(days=6), geohash8=check_geohash
            )

            # Prepare 14 day data.
            self.create_address_geohash(3, now - relativedelta(days=13), geohash8=check_geohash)

        test_application = geohashes[0].address_geolocation.application
        with mock.patch.object(timezone, 'now') as mock_now:
            x105_date = now - relativedelta(days=6) + relativedelta(seconds=3000)
            mock_now.return_value = x105_date
            ApplicationHistoryFactory(
                application=test_application,
                status_new=ApplicationStatusCodes.FORM_PARTIAL,
                status_old=ApplicationStatusCodes.FORM_CREATED,
            )

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)

        velocity_model_geohash = FraudVelocityModelGeohash.objects.filter(
            geohash=check_geohash, risky_date=now.date(), application=test_application
        ).get()
        self.assertEqual(3000, velocity_model_geohash.x105_complete_duration)
        self.assertEqual('2023-01-04', str(velocity_model_geohash.x105_date))

    def test_process_21_days_data(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(1, now, geohash8=check_geohash)
        self.create_address_geohash(5, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(1, now - relativedelta(days=7), geohash8=check_geohash)
        self.create_address_geohash(2, now - relativedelta(days=13), geohash8=check_geohash)

        # prepare 21 day data
        self.create_address_geohash(2, now - relativedelta(days=20), geohash8=check_geohash)

        # prepare more than 21 day data
        geohashes = self.create_address_geohash(
            1, now - relativedelta(days=21), geohash8=check_geohash
        )

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)

        self.assertEqual(
            11,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash, risky_date=now.date()
            ).count(),
        )
        self.assertEqual(
            0,
            FraudVelocityModelGeohash.objects.filter(
                application_id=geohashes[0].address_geolocation.application_id
            ).count(),
        )

    def test_skip_existing_velocity_model(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        geohashes = self.create_address_geohash(
            6, now - relativedelta(days=6), geohash8=check_geohash
        )

        # Prepare 14 day data.
        self.create_address_geohash(3, now - relativedelta(days=13), geohash8=check_geohash)

        skip_data = geohashes[0]
        FraudVelocityModelGeohashFactory(
            application=skip_data.address_geolocation.application,
            geohash=check_geohash,
            risky_date=now - relativedelta(days=3),
        )

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)
        self.assertEqual(
            8,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash, risky_date=now.date()
            ).count(),
        )

    def test_skip_for_app_in_7d_check(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(5, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(1, now - relativedelta(days=14), geohash8=check_geohash)

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)
        self.assertEqual(
            0,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash,
            ).count(),
        )

    def test_skip_for_app_in_7d_rate_check(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(6, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(4, now - relativedelta(days=14), geohash8=check_geohash)

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)
        self.assertEqual(
            0,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash,
            ).count(),
        )

    def test_unsupported_geohash(self, *args):
        check_geohash = '12345'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(6, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(3, now - relativedelta(days=14), geohash8=check_geohash)

        with self.assertRaises(ValueError):
            process_fraud_hotspot_geohash_velocity_model(check_geohash, now)

        self.assertEqual(
            0,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash,
            ).count(),
        )

    def test_skip_risky_higher_geohash(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(6, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(3, now - relativedelta(days=14), geohash8=check_geohash)

        FraudVelocityModelGeohashFactory(
            geohash='1234567',
            risky_date=now.date(),
        )

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)
        self.assertEqual(
            0,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash,
            ).count(),
        )

    def test_no_duplicate_data(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(6, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(3, now - relativedelta(days=13), geohash8=check_geohash)

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)
        process_fraud_hotspot_geohash_velocity_model(check_geohash, now + relativedelta(days=2))

        self.assertEqual(
            9,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash, risky_date=now.date()
            ).count(),
        )

    def test_skip_verified_velocity_model(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(6, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(3, now - relativedelta(days=14), geohash8=check_geohash)

        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now - relativedelta(days=3)
            FraudVelocityModelGeohashBucketFactory(
                geohash=check_geohash,
                fraud_velocity_model_results_check=FraudVelocityModelResultsCheckFactory(),
            )

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)
        self.assertEqual(
            0,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash,
            ).count(),
        )

    def test_not_skip_verified_velocity_model(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(6, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(3, now - relativedelta(days=13), geohash8=check_geohash)

        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = now - relativedelta(days=4)
            FraudVelocityModelGeohashBucketFactory(
                geohash=check_geohash,
                fraud_velocity_model_results_check=FraudVelocityModelResultsCheckFactory(),
            )

            mock_now.return_value = now - relativedelta(days=3)
            FraudVelocityModelGeohashBucketFactory(
                geohash='diffgeo',
                fraud_velocity_model_results_check=FraudVelocityModelResultsCheckFactory(),
            )
            FraudVelocityModelGeohashBucketFactory(
                geohash=check_geohash,
                fraud_velocity_model_results_check=None,
            )

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)
        self.assertEqual(
            9,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash,
            ).count(),
        )

    def test_skip_for_fraud_hotspot(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 6 day data.
        self.create_address_geohash(6, now - relativedelta(days=6), geohash8=check_geohash)

        # Prepare 14 day data.
        self.create_address_geohash(3, now - relativedelta(days=14), geohash8=check_geohash)

        FruadHotspotFactory(geohash=check_geohash)

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)
        self.assertEqual(
            0,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash,
            ).count(),
        )

    def test_prevent_division_by_zero(self, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        self.create_address_geohash(6, now - relativedelta(days=6), geohash8=check_geohash)
        self.create_address_geohash(6, now - relativedelta(days=14), geohash8=check_geohash)
        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)

        self.assertEqual(
            0,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash, risky_date=now.date()
            ).count(),
        )


@mock.patch('juloserver.fraud_security.tasks.add_geohash_to_velocity_model_geohash_bucket.delay')
class TestProcessFraudHotspotGeohashVelocityModelSetting(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_VELOCITY_MODEL_GEOHASH,
            is_active=True,
            parameters={
                'geohash8': {
                    'check_period_day': 2,
                    'check_period_compare_day': 4,
                    'threshold_total_app_in_period': 2,
                    'threshold_rate_app_in_period': 2,
                    'flag_period_day': 3,
                },
                'geohash9': {
                    'check_period_day': 3,
                    'check_period_compare_day': 6,
                    'threshold_total_app_in_period': 3,
                    'threshold_rate_app_in_period': 3,
                    'flag_period_day': 6,
                },
            },
        )

    @staticmethod
    def create_address_geohash(total, created_at, **data):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = created_at
            return AddressGeolocationGeohashFactory.create_batch(
                total,
                **data,
            )

    def test_risky_and_store_velocity_model_geohash8(self, mock_add_geohash_task, *args):
        check_geohash = '12345678'
        now = timezone.localtime(timezone.now())
        # Prepare 2 day data.
        self.create_address_geohash(1, now, geohash8=check_geohash)
        self.create_address_geohash(3, now - relativedelta(days=1), geohash8=check_geohash)

        # Prepare 4 day data.
        self.create_address_geohash(1, now - relativedelta(days=2), geohash8=check_geohash)
        self.create_address_geohash(1, now - relativedelta(days=3), geohash8=check_geohash)

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)

        self.assertEqual(
            5,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash, risky_date=now.date()
            ).count(),
        )

        mock_add_geohash_task.assert_called_once_with('12345678', mock.ANY)

    def test_risky_and_store_velocity_model_geohash9(self, mock_add_geohash_task, *args):
        check_geohash = '123456789'
        now = timezone.localtime(timezone.now())
        # Prepare 3 day data.
        self.create_address_geohash(1, now, geohash9=check_geohash)
        self.create_address_geohash(5, now - relativedelta(days=2), geohash9=check_geohash)

        # Prepare 6 day data.
        self.create_address_geohash(1, now - relativedelta(days=3), geohash9=check_geohash)
        self.create_address_geohash(1, now - relativedelta(days=5), geohash9=check_geohash)

        process_fraud_hotspot_geohash_velocity_model(check_geohash, now)

        self.assertEqual(
            8,
            FraudVelocityModelGeohash.objects.filter(
                geohash=check_geohash, risky_date=now.date()
            ).count(),
        )

        mock_add_geohash_task.assert_called_once_with('123456789', mock.ANY)


@mock.patch('juloserver.fraud_security.tasks.flag_application_as_fraud_suspicious.delay')
class TestAddGeohashToVelocityModelGeohashBucket(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_VELOCITY_MODEL_GEOHASH,
            is_active=True,
            parameters={
                'is_enable_fraud_verification': True,
            },
        )

    def test_setting_parameter_is_disabled(self, mock_flag_application_task):
        self.setting.parameters['is_enable_fraud_verification'] = False
        self.setting.save()

        applications = ApplicationJ1Factory.create_batch(3)
        application_ids = [application.id for application in applications]

        add_geohash_to_velocity_model_geohash_bucket('12345678', application_ids)

        geohash_bucket = FraudVelocityModelGeohashBucket.objects.filter(geohash='12345678').first()
        self.assertIsNone(geohash_bucket)
        mock_flag_application_task.assert_not_called()

    def test_setting_is_disabled(self, mock_flag_application_task):
        self.setting.parameters['is_enable_fraud_verification'] = True
        self.setting.is_active = False
        self.setting.save()

        applications = ApplicationJ1Factory.create_batch(3)
        application_ids = [application.id for application in applications]

        add_geohash_to_velocity_model_geohash_bucket('12345678', application_ids)

        geohash_bucket = FraudVelocityModelGeohashBucket.objects.filter(geohash='12345678').first()
        self.assertIsNone(geohash_bucket)
        mock_flag_application_task.assert_not_called()

    def test_flag_applications(self, mock_flag_application_task):
        applications = ApplicationJ1Factory.create_batch(3)
        application_ids = [application.id for application in applications]
        FraudVerificationResultsFactory(application=applications[2])

        add_geohash_to_velocity_model_geohash_bucket('12345678', application_ids)

        geohash_bucket = FraudVelocityModelGeohashBucket.objects.filter(geohash='12345678').first()
        self.assertIsNotNone(geohash_bucket)

        expected_change_reason = 'Suspicious fraud hotspot velocity model (12345678)'
        mock_flag_application_task.assert_has_calls(
            [
                mock.call(application_ids[0], expected_change_reason),
                mock.call(application_ids[1], expected_change_reason),
            ],
            any_order=True,
        )

    def test_not_create_existing_geohash_bucket(self, *args):
        FraudVelocityModelGeohashBucketFactory(geohash='12345678')

        applications = ApplicationJ1Factory.create_batch(3)
        application_ids = [application.id for application in applications]

        add_geohash_to_velocity_model_geohash_bucket('12345678', application_ids)

        total_bucket = FraudVelocityModelGeohashBucket.objects.filter(geohash='12345678').count()
        self.assertEqual(1, total_bucket)


class TestFlagApplicationAsFraudSuspicious(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_VELOCITY_MODEL_GEOHASH,
            is_active=True,
            parameters={
                'is_enable_fraud_verification': True,
            },
        )

    @classmethod
    def setUpTestData(cls):
        retroload = import_module(
            name='.167781583868__fraud_security__add_workflow_status_path_for_fraud_suspicious',
            package='juloserver.retroloads',
        )
        retroload.add_application_workflow_status_path()
        retroload.add_new_account_status()

    def test_setting_parameter_is_disabled(self):
        self.setting.parameters['is_enable_fraud_verification'] = False
        self.setting.save()

        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ),
        )

        flag_application_as_fraud_suspicious(application.id, 'test change reason')

        application.refresh_from_db()
        self.assertEqual(ApplicationStatusCodes.DOCUMENTS_SUBMITTED, application.status)

    def test_setting_is_disabled(self):
        self.setting.is_active = False
        self.setting.save()

        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ),
        )

        flag_application_as_fraud_suspicious(application.id, 'test change reason')

        application.refresh_from_db()
        self.assertEqual(ApplicationStatusCodes.DOCUMENTS_SUBMITTED, application.status)

    def test_application_status_is_valid(self):
        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(
                status_code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ),
        )

        flag_application_as_fraud_suspicious(application.id, 'test change reason')

        application.refresh_from_db()
        last_history = application.applicationhistory_set.last()
        self.assertEqual(
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            application.status,
        )

        self.assertEqual(ApplicationStatusCodes.DOCUMENTS_SUBMITTED, last_history.status_old)
        self.assertEqual('test change reason', last_history.change_reason)
        self.assertEqual(
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            last_history.status_new,
        )

    def test_skip_application_status_is_not_valid(self):
        invalid_statuses = (
            ApplicationStatusCodes.FORM_CREATED,
            ApplicationStatusCodes.FORM_PARTIAL,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
            ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        )

        for status in invalid_statuses:
            application = ApplicationJ1Factory(
                application_status=StatusLookupFactory(status_code=status),
            )

            flag_application_as_fraud_suspicious(application.id, 'test change reason')

            application.refresh_from_db()
            self.assertEqual(status, application.status, msg=f"testing {status}")

    def test_application_status_x190(self):
        account = AccountFactory(
            status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE),
        )
        application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=ApplicationStatusCodes.LOC_APPROVED),
            account=account,
            customer=account.customer,
        )

        flag_application_as_fraud_suspicious(application.id, 'test change reason')

        application.refresh_from_db()
        self.assertEqual(ApplicationStatusCodes.LOC_APPROVED, application.status)

        account.refresh_from_db()
        last_history = account.accountstatushistory_set.last()
        self.assertEqual(JuloOneCodes.FRAUD_SUSPICIOUS, account.status_id)

        self.assertEqual(JuloOneCodes.ACTIVE, last_history.status_old_id)
        self.assertEqual(JuloOneCodes.FRAUD_SUSPICIOUS, last_history.status_new_id)
        self.assertEqual('test change reason', last_history.change_reason)

    def test_skip_application_status_x190_invalid_status(self):
        invalid_statuses = (
            JuloOneCodes.DEACTIVATED,
            JuloOneCodes.TERMINATED,
            JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD,
            JuloOneCodes.FRAUD_SUSPICIOUS,
        )

        for status in invalid_statuses:
            account = AccountFactory(
                status=StatusLookupFactory(status_code=status),
            )
            application = ApplicationJ1Factory(
                application_status=StatusLookupFactory(
                    status_code=ApplicationStatusCodes.LOC_APPROVED
                ),
                account=account,
                customer=account.customer,
            )

            flag_application_as_fraud_suspicious(application.id, 'test change reason')
            account.refresh_from_db()
            self.assertEqual(status, account.status_id)


@mock.patch.object(VelocityModelGeohashService, 'update_application_or_account_status')
class TestStoreVerificationResultForVelocityModelGeohash(TestCase):
    def test_bucket_is_not_verified(self, mock_update_application_or_account_status):
        bucket = FraudVelocityModelGeohashBucketFactory()

        with self.assertRaises(Exception) as context:
            store_verification_result_for_velocity_model_geohash(bucket.id)

        self.assertEqual(
            'Fraud Velocity Model Geohash Bucket is not verified',
            str(context.exception),
        )
        mock_update_application_or_account_status.assert_not_called()

    def test_change_application_status_as_fraud(self, mock_update_application_or_account_status):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 1, 20)
            bucket = FraudVelocityModelGeohashBucketFactory(
                geohash='12345678',
                fraud_velocity_model_results_check=FraudVelocityModelResultsCheckFactory(
                    is_fraud=True,
                ),
            )

        # checked application
        checked_model_geohashes = FraudVelocityModelGeohashFactory.create_batch(
            3,
            geohash='12345678',
            risky_date=Iterator(['2023-01-19', '2023-01-20', '2023-01-21']),
        )

        # Skipped application
        skipped_model_geohash = FraudVelocityModelGeohashFactory(
            geohash='12345678', risky_date='2023-01-18'
        )
        FraudVerificationResultsFactory(
            application=skipped_model_geohash.application,
            bucket=FraudBucket.VELOCITY_MODEL_GEOHASH,
        )

        mock_update_application_or_account_status.return_value = (420, 440)

        store_verification_result_for_velocity_model_geohash(bucket.id)

        expected_change_reason = (
            'Flag as fraud hotspot velocity model '
            '(geohash:12345678) (result_id:{})'.format(bucket.fraud_velocity_model_results_check_id)
        )
        mock_update_application_or_account_status.assert_has_calls(
            [
                mock.call(
                    application=checked_model_geohashes[0].application,
                    is_fraud=True,
                    change_reason=expected_change_reason,
                ),
                mock.call(
                    application=checked_model_geohashes[1].application,
                    is_fraud=True,
                    change_reason=expected_change_reason,
                ),
                mock.call(
                    application=checked_model_geohashes[2].application,
                    is_fraud=True,
                    change_reason=expected_change_reason,
                ),
            ],
            any_order=True,
        )

        application_ids = [
            model_geohash.application_id for model_geohash in checked_model_geohashes
        ]
        self.assertEqual(
            3,
            FraudVerificationResults.objects.filter(application_id__in=application_ids).count(),
        )
        self.assertEqual(
            1,
            FraudVerificationResults.objects.filter(
                application_id=skipped_model_geohash.application_id,
            ).count(),
        )

        # Call the second time
        mock_update_application_or_account_status.reset_mock()
        mock_update_application_or_account_status.return_value = (420, 440)
        store_verification_result_for_velocity_model_geohash(bucket.id)

        mock_update_application_or_account_status.assert_not_called()
        self.assertEqual(
            3,
            FraudVerificationResults.objects.filter(application_id__in=application_ids).count(),
        )

    def test_verification_result_data(self, mock_update_application_or_account_status):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 1, 20)
            agent_user = AuthUserFactory()
            bucket = FraudVelocityModelGeohashBucketFactory(
                geohash='12345678',
                fraud_velocity_model_results_check=FraudVelocityModelResultsCheckFactory(
                    is_fraud=True,
                ),
                agent_user=agent_user,
            )

        # checked application
        checked_model_geohash = FraudVelocityModelGeohashFactory(
            geohash='12345678',
            risky_date='2023-01-20',
        )

        mock_update_application_or_account_status.return_value = (420, 440)

        store_verification_result_for_velocity_model_geohash(bucket.id)

        expected_change_reason = (
            'Flag as fraud hotspot velocity model '
            '(geohash:12345678) (result_id:{})'.format(bucket.fraud_velocity_model_results_check_id)
        )

        result = FraudVerificationResults.objects.last()
        self.assertEqual('12345678', result.geohash),
        self.assertEqual(
            bucket.fraud_velocity_model_results_check_id,
            result.fraud_velocity_model_results_check_id,
        )
        self.assertEqual('Velocity Model Geohash', result.bucket)
        self.assertEqual(agent_user.id, result.agent_user_id)
        self.assertEqual(expected_change_reason, result.reason)
        self.assertIsNotNone(result.latitude)
        self.assertIsNotNone(result.longitude)
        self.assertIsNotNone(result.radius)
        self.assertEqual(checked_model_geohash.application_id, result.application_id)
        self.assertEqual(420, result.previous_status_code)
        self.assertEqual(440, result.next_status_code)

    @mock.patch('juloserver.fraud_security.tasks.add_android_id_to_blacklisted_fraudster')
    def test_blacklist_android_id(
        self,
        mock_add_android_id_to_blacklisted_fraudster,
        mock_update_application_or_account_status,
    ):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2023, 1, 20)
            bucket = FraudVelocityModelGeohashBucketFactory(
                geohash='12345678',
                fraud_velocity_model_results_check=FraudVelocityModelResultsCheckFactory(
                    is_fraud=True,
                ),
            )

        # checked application
        checked_model_geohash = FraudVelocityModelGeohashFactory(
            geohash='12345678',
            risky_date='2023-01-20',
        )
        DeviceFactory(
            customer=checked_model_geohash.application.customer,
            android_id='testandroid',
        )

        mock_update_application_or_account_status.return_value = (420, 440)
        store_verification_result_for_velocity_model_geohash(bucket.id)

        expected_change_reason = (
            'Flag as fraud hotspot velocity model '
            '(geohash:12345678) (result_id:{})'.format(bucket.fraud_velocity_model_results_check_id)
        )
        result = FraudVerificationResults.objects.last()
        self.assertEqual('testandroid', result.android_id)
        mock_add_android_id_to_blacklisted_fraudster.assert_called_once_with(
            'testandroid',
            expected_change_reason,
        )


class TestRemoveApplicationFromFraudApplicationBucket(TestCase):
    def test_remove_application_from_bucket(self):
        buckets = FraudApplicationBucketFactory.create_batch(2, is_active=True)

        ret_val = remove_application_from_fraud_application_bucket(buckets[0].application_id)
        self.assertEqual(1, ret_val)
        self.assertEqual(1, FraudApplicationBucket.objects.filter(is_active=True).count())
        self.assertTrue(
            FraudApplicationBucket.objects.filter(
                is_active=False,
                application_id=buckets[0].application_id,
            ).exists()
        )


class TestInsertFraudApplicationBucket(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=115),
        )
        self.application_history = ApplicationHistoryFactory(
            application=self.application,
            change_reason=FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )

    @patch('juloserver.fraud_security.tasks.hit_anti_fraud_call_back_async')
    def test_insert(self, mock_anti_fraud_call_back):

        insert_fraud_application_bucket(
            self.application.id,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )
        force_run_on_commit_hook()
        bucket = FraudApplicationBucket.objects.filter(
            application_id=self.application.id,
            type=FraudApplicationBucketType.SELFIE_IN_GEOHASH,
            is_active=True,
        ).get()
        mock_anti_fraud_call_back.delay.assert_not_called()
        self.assertIsNotNone(bucket)

        bucket.update_safely(is_active=False)
        insert_fraud_application_bucket(
            self.application.id,
            FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        )
        force_run_on_commit_hook()
        bucket.refresh_from_db()
        mock_anti_fraud_call_back.delay.assert_not_called()
        self.assertTrue(bucket.is_active)

    @patch('juloserver.fraud_security.tasks.hit_anti_fraud_call_back_async')
    def test_callback(self, mock_anti_fraud_call_back):
        self.application2 = ApplicationJ1Factory(
            application_status=StatusLookupFactory(status_code=115),
        )
        self.application_history2 = ApplicationHistoryFactory(
            application=self.application2,
            change_reason=FraudChangeReason.BANK_NAME_VELOCITY_NO_FRAUD,
        )
        status_115 = str(ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS)

        insert_fraud_application_bucket(
            self.application2.id,
            FraudChangeReason.BANK_NAME_VELOCITY_NO_FRAUD,
        )
        force_run_on_commit_hook()
        mock_anti_fraud_call_back.delay.assert_called_with(
            CallBackType.MOVE_APPLICATION_STATUS,
            self.application2.id,
            status_115,
        )


@mock.patch('juloserver.fraud_security.tasks.logger')
class TestCheckHighRiskAsn(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.application_risky_check = ApplicationRiskyCheckFactory(
            application=self.application,
            is_vpn_detected=True,
        )
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.HIGH_RISK_ASN_TOWER_CHECK,
            parameters={
                'mycroft_threshold_min': 0.4,
                'mycroft_threshold_max': 0.7,
            },
            is_active=True,
        )
        self.mycroft_score = PdApplicationFraudModelResultFactory(
            application_id=self.application.id,
            customer_id=self.customer.id,
            model_version='Mycroft v2.0.0',
            pgood=0.6,
        )
        self.device_ip_history = DeviceIpHistoryFactory(customer=self.customer)
        self.vpn_detection = VPNDetectionFactory(
            ip_address=self.device_ip_history.ip_address,
            extra_data={'org': 'AS001 PT Dummy Indonesia'},
        )
        self.fraud_high_risk_asn = FraudHighRiskAsnFactory()

    def test_check_application_has_high_risk_asn(self, mock_logger):
        high_risk_asn_result = check_high_risk_asn(self.application.id)
        self.application_risky_check.refresh_from_db()

        mock_logger.info.assert_called_once_with(
            {
                'action': 'check_high_risk_asn',
                'application_id': self.application.id,
                'customer_id': self.customer.id,
                'pd_application_fraud_model_result_id': self.mycroft_score.id,
                'message': 'Application flagged as high risk ASN.',
            }
        )
        self.assertTrue(high_risk_asn_result)
        self.assertTrue(self.application_risky_check.is_high_risk_asn_mycroft)

    def test_check_application_has_no_application_risky_check(self, mock_logger):
        self.application_risky_check.delete()
        high_risk_asn_result = check_high_risk_asn(self.application.id)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'check_high_risk_asn',
                'application_id': self.application.id,
                'message': 'ApplicationRiskyCheck not found for this application_id.',
            }
        )
        self.assertIsNone(high_risk_asn_result)

    def test_check_application_has_no_vpn_detected(self, mock_logger):
        self.application_risky_check.update_safely(is_vpn_detected=False)
        high_risk_asn_result = check_high_risk_asn(self.application.id)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'check_high_risk_asn',
                'application_id': self.application.id,
                'application_risky_check_id': self.application_risky_check.id,
                'message': 'Application does not have VPN detected.',
            }
        )
        self.assertFalse(high_risk_asn_result)

    def test_check_application_has_no_mycroft_score_result(self, mock_logger):
        self.mycroft_score.delete()
        high_risk_asn_result = check_high_risk_asn(self.application.id)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'check_high_risk_asn',
                'application_id': self.application.id,
                'message': 'Application has no mycroft result found.',
            }
        )
        self.assertFalse(high_risk_asn_result)

    def test_check_application_fail_mycroft_threshold(self, mock_logger):
        self.mycroft_score.update_safely(pgood=0.9)
        high_risk_asn_result = check_high_risk_asn(self.application.id)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'check_high_risk_asn',
                'application_id': self.application.id,
                'message': 'Application\'s mycroft score not within threshold.',
            }
        )
        self.assertFalse(high_risk_asn_result)

    def test_check_application_has_no_device_ip_history(self, mock_logger):
        self.device_ip_history.delete()
        high_risk_asn_result = check_high_risk_asn(self.application.id)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'check_high_risk_asn',
                'application_id': self.application.id,
                'customer_id': self.customer.id,
                'pd_application_fraud_model_result_id': self.mycroft_score.id,
                'message': 'Customer\'s device has no IP history.',
            }
        )
        self.assertIsNone(high_risk_asn_result)

    def test_check_application_for_high_risk_asn(self, mock_logger):
        high_risk_asn_result = check_high_risk_asn(self.application.id)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'check_high_risk_asn',
                'application_id': self.application.id,
                'customer_id': self.customer.id,
                'pd_application_fraud_model_result_id': self.mycroft_score.id,
                'message': 'Application flagged as high risk ASN.',
            }
        )
        self.assertTrue(high_risk_asn_result)

    def test_check_with_feature_setting_off(self, mock_logger):
        self.feature_setting.update_safely(is_active=False)
        high_risk_asn_result = check_high_risk_asn(self.application.id)

        mock_logger.info.assert_called_once_with(
            {
                'action': 'check_high_risk_asn',
                'message': 'Skip check as FeatureSetting for high_risk_asn_tower_check is off.',
            }
        )
        self.assertIsNone(high_risk_asn_result)


class MobileUserActionLogFraudFlag(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.log_data_list = [
            {
                "id": 1,
                "log_ts": "2018-01-01 00:00:00",
                "customer_id": self.customer.id,
                "activity": "Dummy",
                "fragment": "fragment",
                "event": "event",
                "view": "view",
            },
            {
                "id": 2,
                "log_ts": "2018-01-01 00:00:00",
                "customer_id": self.customer.id,
                "activity": "ChangePhoneActivity",
                "fragment": "fragment",
                "event": "event",
                "view": "view",
            },
            {
                "id": 3,
                "log_ts": "2018-01-01 00:00:00",
                "customer_id": self.customer.id,
                "activity": "Dummy",
                "fragment": "fragment",
                "event": "event",
                "view": "view",
            },
        ]

    def test_process_mobile_user_action_log_checks(self):
        process_mobile_user_action_log_checks(self.log_data_list)
        self.assertEqual(
            FraudFlag.objects.filter(
                customer=self.customer, fraud_type=FraudFlagType.CHANGE_PHONE_ACTIVITY
            ).exists(),
            True,
        )


class TestBlacklistedFraudsterAccountStatusMoveTox440(TestCase):
    def setUp(self):
        self.customer1 = CustomerFactory()
        self.customer2 = CustomerFactory()
        self.account1 = AccountFactory(
            customer=self.customer1, status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        )
        self.account2 = AccountFactory(
            customer=self.customer2, status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        )
        self.fraud_reported_status = StatusLookupFactory(status_code=JuloOneCodes.FRAUD_REPORTED)
        self.application1 = ApplicationFactory(
            customer=self.customer1, account=self.account1, mobile_phone_1='08456234596'
        )
        self.application2 = ApplicationFactory(
            customer=self.customer2, account=self.account2, mobile_phone_1='08456234596'
        )
        self.c1device1 = DeviceFactory(customer=self.customer1, android_id='dummy1')
        self.c1device2 = DeviceFactory(customer=self.customer1, android_id='12345')

        self.c2device1 = DeviceFactory(customer=self.customer2, android_id='12345')
        self.c2device2 = DeviceFactory(customer=self.customer2, android_id='dummy2')

    def test_flag_blacklisted_android_id_for_j1_and_jturbo_task_flagged_c1(self):
        blacklisted_fraudster, _ = BlacklistedFraudster.objects.get_or_create(android_id='12345')
        flag_blacklisted_android_id_for_j1_and_jturbo_task(blacklisted_fraudster.id)
        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertEqual(self.account1.status.status_code, JuloOneCodes.FRAUD_REPORTED)
        self.assertEqual(self.account2.status.status_code, JuloOneCodes.ACTIVE)

    def test_flag_blacklisted_android_id_for_j1_and_jturbo_task_flagged_c2(self):
        blacklisted_fraudster, _ = BlacklistedFraudster.objects.get_or_create(android_id='dummy2')
        flag_blacklisted_android_id_for_j1_and_jturbo_task(blacklisted_fraudster.id)
        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertEqual(self.account2.status.status_code, JuloOneCodes.FRAUD_REPORTED)
        self.assertEqual(self.account1.status.status_code, JuloOneCodes.ACTIVE)

    def test_flag_blacklisted_application_phone_for_j1_and_jturbo_task_flagged(self):
        blacklisted_fraudster, _ = BlacklistedFraudster.objects.get_or_create(
            phone_number='08456234596'
        )
        flag_blacklisted_phone_for_j1_and_jturbo_task(blacklisted_fraudster.id)
        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertEqual(self.account1.status.status_code, JuloOneCodes.FRAUD_REPORTED)
        self.assertEqual(self.account2.status.status_code, JuloOneCodes.FRAUD_REPORTED)

    def test_flag_blacklisted_customer_phone_for_j1_and_jturbo_task_flagged(self):
        self.application1.mobile_phone_1 = '54321'  # setting dummy
        self.application2.mobile_phone_1 = '54321'  # setting dummy
        self.customer1.phone = '08456234596'
        self.customer1.save()
        blacklisted_fraudster, _ = BlacklistedFraudster.objects.get_or_create(
            phone_number='08456234596'
        )
        flag_blacklisted_phone_for_j1_and_jturbo_task(blacklisted_fraudster.id)
        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertEqual(self.account1.status.status_code, JuloOneCodes.FRAUD_REPORTED)

    def test_flag_blacklisted_android_id_for_j1_and_jturbo_task_unflagged(self):
        blacklisted_fraudster, _ = BlacklistedFraudster.objects.get_or_create(android_id='234567')
        flag_blacklisted_android_id_for_j1_and_jturbo_task(blacklisted_fraudster.id)
        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertEqual(self.account1.status.status_code, JuloOneCodes.ACTIVE)
        self.assertEqual(self.account2.status.status_code, JuloOneCodes.ACTIVE)

    def test_flag_blacklisted_application_phone_for_j1_and_jturbo_task_unflagged(self):
        blacklisted_fraudster, _ = BlacklistedFraudster.objects.get_or_create(phone_number='234567')
        flag_blacklisted_phone_for_j1_and_jturbo_task(blacklisted_fraudster.id)
        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertEqual(self.account1.status.status_code, JuloOneCodes.ACTIVE)
        self.assertEqual(self.account2.status.status_code, JuloOneCodes.ACTIVE)


@mock.patch('juloserver.fraud_security.tasks.process_change_account_status', return_value=None)
class TestUnblockSwiftLimitDrainerAccountDaily(TestCase):
    def setUp(self):
        self.status_lookup_420 = StatusLookup.objects.get_or_none(status_code=420)
        self.status_lookup_440 = StatusLookupFactory(status_code=440)
        self.feature_setting = FeatureSettingFactory(
            feature_name='swift_limit_drainer',
            parameters={'jail_days': 0},
        )
        self.account = AccountFactory()

    def test_feature_setting_inactive_return_early(self, mock_process_change_account_status):
        self.feature_setting.update_safely(is_active=False)

        swift_limit_drainer_account_daily_action()
        mock_process_change_account_status.assert_not_called()

    def test_fraud_swift_limit_drainer_account_model_within_jail_date_expect_process(
        self, mock_process_change_account_status
    ):
        FraudSwiftLimitDrainerAccountFactory(account=self.account)

        swift_limit_drainer_account_daily_action()
        mock_process_change_account_status.assert_called_once_with(
            self.account, 420, 'Returned blocked Swift Limit Drainer'
        )
        swift_drainer_account = FraudSwiftLimitDrainerAccount.objects.get_or_none(
            account=self.account
        )
        self.assertIsNone(swift_drainer_account)

    def test_fraud_swift_limit_drainer_account_model_outside_jail_date_expect_no_process(
        self, mock_process_change_account_status
    ):
        self.feature_setting.parameters['jail_days'] = 1
        self.feature_setting.save()
        FraudSwiftLimitDrainerAccountFactory(account=self.account)

        swift_limit_drainer_account_daily_action()
        mock_process_change_account_status.assert_not_called()
        swift_drainer_account = FraudSwiftLimitDrainerAccount.objects.get_or_none(
            account=self.account
        )
        self.assertIsNotNone(swift_drainer_account)

    def test_fraud_swift_limit_drainer_account_with_appeal_account(
        self, mock_process_change_account_status
    ):
        # arrange
        self.feature_setting_2 = FeatureSettingFactory(
            feature_name=FeatureNameConst.FRAUD_APPEAL_TEMPORARY_BLOCK,
        )
        FraudSwiftLimitDrainerAccountFactory(account=self.account)
        FraudAppealTemporaryBlockFactory(account_id=self.account.id)

        # act
        swift_limit_drainer_account_daily_action()

        # assert
        mock_process_change_account_status.assert_called_once_with(
            self.account, 432, 'Permanent Block Swift Limit Drainer'
        )
        swift_drainer_account = FraudSwiftLimitDrainerAccount.objects.get_or_none(
            account=self.account
        )
        self.assertIsNone(swift_drainer_account)


@mock.patch('juloserver.fraud_security.tasks.process_change_account_status', return_value=None)
class TestCheckTelcoMaidFeature(TestCase):
    def setUp(self):
        self.status_lookup_420 = StatusLookup.objects.get_or_none(status_code=420)
        self.status_lookup_440 = StatusLookupFactory(status_code=440)
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.TELCO_MAID_LOCATION_FEATURE,
            parameters={'jail_days': 0},
        )
        self.account = AccountFactory()

    def test_feature_setting_inactive_return_early(self, mock_process_change_account_status):
        self.feature_setting.update_safely(is_active=False)

        telco_maid_temporary_block_daily_action()
        mock_process_change_account_status.assert_not_called()

    def test_fraud_telco_maid_block_account_model_within_jail_date_expect_process(
        self, mock_process_change_account_status
    ):
        FraudTelcoMaidTemporaryBlockFactory(account=self.account)

        telco_maid_temporary_block_daily_action()
        mock_process_change_account_status.assert_called_once_with(
            self.account, 420, AccountChangeReason.TELCO_MAID_LOCATION_RETURN
        )
        telco_maid_block_account = FraudTelcoMaidTemporaryBlock.objects.get_or_none(
            account=self.account
        )
        self.assertIsNone(telco_maid_block_account)

    def test_fraud_telco_maid_account_model_outside_jail_date_expect_no_process(
        self, mock_process_change_account_status
    ):
        self.feature_setting.parameters['jail_days'] = 1
        self.feature_setting.save()
        FraudTelcoMaidTemporaryBlockFactory(account=self.account)

        telco_maid_temporary_block_daily_action()
        mock_process_change_account_status.assert_not_called()
        telco_maid_block_account = FraudTelcoMaidTemporaryBlock.objects.get_or_none(
            account=self.account
        )
        self.assertIsNotNone(telco_maid_block_account)


class TestSaveBankNameVelocityThresholdHistory(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.ABC_BANK_NAME_VELOCITY,
            parameters={'threshold': 0.2},
        )

    @patch('juloserver.fraud_security.tasks.datetime')
    def test_save_bank_name_velocity_threshold_history(self, mock_datetime):
        mock_datetime.combine = MagicMock(return_value=datetime(2024, 10, 20, 12, 0, 0))

        current_date = datetime(2024, 10, 20, 0, 0, 0)
        target_time = datetime.strptime("12:00:00", "%H:%M:%S").time()
        target_datetime = datetime.combine(current_date, target_time)

        save_bank_name_velocity_threshold_history()
        result = BankNameVelocityThresholdHistory.objects.filter(
            threshold_date=target_datetime, threshold=0.2
        ).exists()
        self.assertTrue(result)


@mock.patch(
    'juloserver.fraud_security.services.process_application_status_change', return_value=None
)
@mock.patch('juloserver.fraud_security.services.process_change_account_status', return_value=None)
class TestFraudBlockAccountDailyAction(TestCase):
    def setUp(self):
        self.status_lookup_420 = StatusLookup.objects.get_or_none(status_code=420)
        self.status_lookup_440 = StatusLookupFactory(status_code=440)
        self.feature_setting = FeatureSettingFactory(
            feature_name='fraud_block_account',
            parameters={'jail_days': 0, 'jail_days_jturbo': 0, 'jail_days_j1': 0},
            is_active=True,
        )
        self.account = AccountFactory()
        self.application = ApplicationFactory(
            account=self.account,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )

    def test_fraud_swift_limit_drainer_account_model_within_jail_date_expect_process(
        self, mock_process_change_account_status, mock_process_application_status_change
    ):
        FraudBlockAccountFactory(
            feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER,
            account=self.account,
            is_block=False,
            is_need_action=True,
        )

        fraud_block_account_daily_action()
        mock_process_change_account_status.assert_called_once_with(
            self.account, 420, 'Returned blocked Swift Limit Drainer'
        )
        mock_process_application_status_change.assert_not_called()
        fraud_block_account = FraudBlockAccount.objects.get(account=self.account)
        self.assertFalse(fraud_block_account.is_need_action)

    def test_fraud_swift_limit_drainer_account_model_is_block_true(
        self, mock_process_change_account_status, mock_process_application_status_change
    ):
        FraudBlockAccountFactory(
            feature_name=FeatureNameConst.SWIFT_LIMIT_DRAINER,
            account=self.account,
            is_block=True,
            is_need_action=True,
        )

        fraud_block_account_daily_action()
        mock_process_change_account_status.assert_called_once_with(
            self.account, 432, 'Permanent Block Swift Limit Drainer'
        )
        mock_process_application_status_change.called_once()
        fraud_block_account = FraudBlockAccount.objects.get(account=self.account)
        self.assertFalse(fraud_block_account.is_need_action)

    def test_unknown_block_account_feature(
        self, mock_process_change_account_status, mock_process_application_status_change
    ):
        FraudBlockAccountFactory(
            feature_name='test',
            account=self.account,
            is_block=True,
            is_need_action=True,
        )

        fraud_block_account_daily_action()
        mock_process_change_account_status.not_called()
        mock_process_application_status_change.not_called()
        fraud_block_account = FraudBlockAccount.objects.get(account=self.account)
        self.assertTrue(fraud_block_account.is_need_action)
