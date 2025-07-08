from unittest import mock
from django.test import TestCase

from juloserver.fraud_score.constants import (
    SeonConstant,
)
from juloserver.fraud_score.tasks import (
    fetch_monnai_application_submit_result,
    fetch_seon_application_submit_result,
    fetch_seon_fraud_api_result,
    handle_post_user_submit_application,
)
from juloserver.fraud_score.tests.factories import SeonFingerprintFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    FeatureSettingFactory,
)


class TestHandlePostUserSubmitApplication(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory(
            email='test+handle@example.com',
            mobile_phone_1='081234567890',
        )
        self.customer = self.application.customer
        FeatureSettingFactory(feature_name=FeatureNameConst.SEON_FRAUD_SCORE, is_active=True)

    @mock.patch('juloserver.fraud_score.tasks.seon_services.store_seon_fingerprint')
    def test_handle_post_user_submit_application(self, mock_store_seon_fingerprint):
        handle_post_user_submit_application(
            customer_id=self.customer.id,
            application_id=self.application.id,
            ip_address='127.0.0.1',
            request_data={
                'seon_sdk_fingerprint': 'test seon fingerprint',
            },
        )

        mock_store_seon_fingerprint.assert_called_once_with({
            'customer_id': self.customer.id,
            'trigger': 'application_submit',
            'ip_address': '127.0.0.1',
            'sdk_fingerprint_hash': 'test seon fingerprint',
            'target_type': 'application',
            'target_id': self.application.id,
        })

    @mock.patch('juloserver.fraud_score.tasks.seon_services.store_seon_fingerprint')
    def test_handle_post_user_submit_application_no_fingerprint(self, mock_store_seon_fingerprint):
        handle_post_user_submit_application(
            customer_id=self.customer.id,
            application_id=self.application.id,
            ip_address='127.0.0.1',
            request_data={},
        )

        mock_store_seon_fingerprint.assert_called_once_with({
            'customer_id': self.customer.id,
            'trigger': 'application_submit',
            'ip_address': '127.0.0.1',
            'sdk_fingerprint_hash': None,
            'target_type': 'application',
            'target_id': self.application.id,
        })


@mock.patch('juloserver.fraud_score.tasks.fetch_seon_fraud_api_result.delay')
class TestFetchSeonApplicationSubmitResult(TestCase):
    def setUp(self):
        self.application = ApplicationJ1Factory()
        FeatureSettingFactory(feature_name=FeatureNameConst.SEON_FRAUD_SCORE, is_active=True)

    def test_fingerprint_not_found(self, mock_fetch_seon_fraud_api_result):
        SeonFingerprintFactory(
            target_type='application',
            target_id=self.application.id,
        )
        fetch_seon_application_submit_result(self.application.id)
        mock_fetch_seon_fraud_api_result.assert_not_called()

    def test_fingerprint_found(self, mock_fetch_seon_fraud_api_result):
        seon_fingerprint = SeonFingerprintFactory(
            trigger=SeonConstant.Trigger.APPLICATION_SUBMIT,
            target_type='application',
            target_id=self.application.id,
        )

        fetch_seon_application_submit_result(self.application.id)
        mock_fetch_seon_fraud_api_result.assert_called_once_with(seon_fingerprint.id)


class TestFetchSeonFraudApiResult(TestCase):
    def setUp(self):
        self.seon_fingerprint = SeonFingerprintFactory()
        self.mock_seon_repository = mock.MagicMock()
        FeatureSettingFactory(feature_name=FeatureNameConst.SEON_FRAUD_SCORE, is_active=True)

    @mock.patch('juloserver.fraud_score.tasks.seon_services.get_seon_repository')
    def test_fetch_seon_fraud_api_result(self, mock_get_seon_repository):
        mock_get_seon_repository.return_value = self.mock_seon_repository
        fetch_seon_fraud_api_result(self.seon_fingerprint.id)
        self.mock_seon_repository.fetch_fraud_api_result.assert_called_once_with(
            self.seon_fingerprint,
        )


@mock.patch('juloserver.fraud_score.tasks.monnai_services')
class TestFetchMonnaiApplicationSubmitResult(TestCase):
    def setUp(self):
        self.mock_monnai_repo = mock.MagicMock()
        self.application = ApplicationJ1Factory()
        self.packages = ['ADDRESS_VERIFICATION', 'DEVICE_DETAILS']
        self.application_tsp_name = "INDOSAT_OOREDO"

        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.MONNAI_FRAUD_SCORE,
            is_active=True,
            parameters={
                'test_group': ['00-50'],
                'control_group': ['51-99']
            }
        )

    @mock.patch('juloserver.fraud_score.tasks.check_application_experiment_monnai_eligibility',
                return_value=True)
    @mock.patch('juloserver.fraud_score.tasks.get_telco_code_and_tsp_name',
                return_value=['0855', 'INDOSAT_OOREDO'])
    def test_fetch_monnai_application_submit(
            self, mock_get_telco_code_and_tsp, mock_monnai_eligibility, mock_monnai_services
    ):
        mock_monnai_services.get_monnai_repository.return_value = self.mock_monnai_repo
        fetch_monnai_application_submit_result(self.application.id)

        (
            self.mock_monnai_repo.fetch_insight_for_address_verification_and_device_detail.assert_called_once_with(
                self.application,
                self.packages,
                self.application_tsp_name,
                self.application.mobile_phone_1,
            )
        )

    def test_setting_is_disabled(self, mock_monnai_services):
        self.feature_setting.update_safely(is_active=False)
        mock_monnai_services.get_monnai_repository.return_value = self.mock_monnai_repo
        fetch_monnai_application_submit_result(self.application.id)
