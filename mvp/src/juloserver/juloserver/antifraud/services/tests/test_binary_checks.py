import unittest

import mock
from django.test import TestCase

from juloserver.antifraud.constant.binary_checks import StatusEnum as ABCStatus
from juloserver.antifraud.services.binary_checks import (
    get_anti_fraud_binary_check_status,
    get_application_old_status_code,
)
from juloserver.fraud_security.constants import FraudChangeReason
from juloserver.julo.tests.factories import ApplicationFactory, ApplicationHistoryFactory


class TestGetAntiFraudBinaryCheckStatus(unittest.TestCase):
    @mock.patch("juloserver.antifraud.services.binary_checks.FeatureSetting.objects.filter")
    @mock.patch("juloserver.antifraud.services.binary_checks.anti_fraud_http_client")
    def test_happy_path(
        self,
        mock_anti_fraud_http_client: mock.Mock,
        mock_feature_setting_filter: mock.Mock,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        for status in ABCStatus:
            mock_anti_fraud_http_client.get.return_value = mock.Mock(
                status_code=200,
                json=lambda: {"data": {"status": status.value}},
            )

            result = get_anti_fraud_binary_check_status(status=69, application_id=1)
            self.assertEqual(result, status)

    @mock.patch("juloserver.antifraud.services.binary_checks.FeatureSetting.objects.filter")
    @mock.patch("juloserver.antifraud.services.binary_checks.anti_fraud_http_client")
    def test_error(
        self,
        mock_anti_fraud_http_client: mock.Mock,
        mock_feature_setting_filter: mock.Mock,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_anti_fraud_http_client.get.side_effect = Exception("error")

        result = get_anti_fraud_binary_check_status(status=69, application_id=1)
        self.assertEqual(result, ABCStatus.ERROR)

    @mock.patch("juloserver.antifraud.services.binary_checks.FeatureSetting.objects.filter")
    @mock.patch("juloserver.antifraud.services.binary_checks.anti_fraud_http_client")
    def test_no_response(
        self,
        mock_anti_fraud_http_client: mock.Mock,
        mock_feature_setting_filter: mock.Mock,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_anti_fraud_http_client.get.return_value = None

        result = get_anti_fraud_binary_check_status(status=69, application_id=1)
        self.assertEqual(result, ABCStatus.ERROR)

    @mock.patch("juloserver.antifraud.services.binary_checks.FeatureSetting.objects.filter")
    @mock.patch("juloserver.antifraud.services.binary_checks.anti_fraud_http_client")
    def test_no_status(
        self,
        mock_anti_fraud_http_client: mock.Mock,
        mock_feature_setting_filter: mock.Mock,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_anti_fraud_http_client.get.return_value = mock.Mock(
            status_code=200,
            json=lambda: {"data": {}},
        )

        result = get_anti_fraud_binary_check_status(status=69, application_id=1)
        self.assertEqual(result, ABCStatus.ERROR)

    @mock.patch("juloserver.antifraud.services.binary_checks.FeatureSetting.objects.filter")
    def test_no_feature_setting(
        self,
        mock_feature_setting_filter: mock.Mock,
    ):
        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = None

        mock_feature_setting_filter.return_value = mock_feature_settings

        result = get_anti_fraud_binary_check_status(status=69, application_id=1)
        self.assertEqual(result, ABCStatus.DO_NOTHING)

    @mock.patch("juloserver.antifraud.services.binary_checks.FeatureSetting.objects.filter")
    @mock.patch("juloserver.antifraud.services.binary_checks.anti_fraud_http_client")
    def test_invalid_response_none(
        self,
        mock_anti_fraud_http_client: mock.Mock,
        mock_feature_setting_filter: mock.Mock,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_anti_fraud_http_client.get.return_value = mock.Mock(
            status_code=200,
            json=lambda: None,
        )

        result = get_anti_fraud_binary_check_status(status=69, application_id=1)
        self.assertEqual(result, ABCStatus.ERROR)

    @mock.patch("juloserver.antifraud.services.binary_checks.FeatureSetting.objects.filter")
    @mock.patch("juloserver.antifraud.services.binary_checks.anti_fraud_http_client")
    def test_invalid_response_no_data(
        self,
        mock_anti_fraud_http_client: mock.Mock,
        mock_feature_setting_filter: mock.Mock,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_anti_fraud_http_client.get.return_value = mock.Mock(
            status_code=200,
            json=lambda: {},
        )

        result = get_anti_fraud_binary_check_status(status=69, application_id=1)
        self.assertEqual(result, ABCStatus.ERROR)

    @mock.patch("juloserver.antifraud.services.binary_checks.FeatureSetting.objects.filter")
    @mock.patch("juloserver.antifraud.services.binary_checks.anti_fraud_http_client")
    def test_invalid_response_no_status(
        self,
        mock_anti_fraud_http_client: mock.Mock,
        mock_feature_setting_filter: mock.Mock,
    ):
        mock_feature_setting = mock.Mock()

        mock_feature_settings = mock.Mock()
        mock_feature_settings.last.return_value = mock_feature_setting

        mock_feature_setting_filter.return_value = mock_feature_settings

        mock_anti_fraud_http_client.get.return_value = mock.Mock(
            status_code=200,
            json=lambda: {"data": {}},
        )

        result = get_anti_fraud_binary_check_status(status=69, application_id=1)
        self.assertEqual(result, ABCStatus.ERROR)


class TestGetApplicationOldStatusCode(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=115,
            status_old=105,
            change_reason=FraudChangeReason.ANTI_FRAUD_API_UNAVAILABLE,
        )

    def test_get_application_old_status_code(self):
        application_history, application_status, is_need_callback = get_application_old_status_code(
            self.application.id, 115
        )
        self.assertEqual(application_status, 105)
        self.assertTrue(is_need_callback)
        self.assertIsNotNone(application_history)

        application_history, application_status, is_need_callback = get_application_old_status_code(
            self.application.id, 105
        )
        self.assertEqual(application_status, 105)
        self.assertFalse(is_need_callback)
        self.assertIsNone(application_history)

        self.application_history2 = ApplicationHistoryFactory(
            application_id=self.application.id, status_new=105, status_old=100, change_reason="test"
        )

        application_history, application_status, is_need_callback = get_application_old_status_code(
            self.application.id, 105
        )
        self.assertEqual(application_status, 105)
        self.assertFalse(is_need_callback)
        self.assertIsNone(application_history)
