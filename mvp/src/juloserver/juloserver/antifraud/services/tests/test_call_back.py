import mock
from django.test.testcases import TestCase

from juloserver.antifraud.constant.binary_checks import StatusEnum
from juloserver.antifraud.constant.call_back import CallBackType
from juloserver.antifraud.services.call_back import (
    hit_anti_fraud_call_back,
    overwrite_application_history_and_call_anti_fraud_call_back,
)
from juloserver.fraud_security.constants import FraudChangeReason
from juloserver.julo.tests.factories import ApplicationFactory, ApplicationHistoryFactory
from juloserver.julocore.tests import force_run_on_commit_hook


class TestPostAntiFraudCallBack(TestCase):
    @mock.patch("juloserver.antifraud.services.call_back.anti_fraud_http_client")
    def test_get_400_error(
        self,
        mock_anti_fraud_http_client: mock.Mock,
    ):
        mock_anti_fraud_http_client.post.return_value = mock.Mock(
            status_code=400,
            json=lambda: {"status": None},
        )

        result = hit_anti_fraud_call_back(
            call_back_type=CallBackType.MOVE_APPLICATION_STATUS, application_id=1, new_status="115"
        )
        self.assertFalse(result)

    @mock.patch("juloserver.antifraud.services.call_back.anti_fraud_http_client")
    def test_get_200_but_no_status(
        self,
        mock_anti_fraud_http_client: mock.Mock,
    ):
        mock_anti_fraud_http_client.post.return_value = mock.Mock(
            status_code=200,
            json=lambda: {},
        )

        result = hit_anti_fraud_call_back(
            call_back_type=CallBackType.MOVE_APPLICATION_STATUS, application_id=1, new_status="115"
        )
        self.assertFalse(result)

    @mock.patch("juloserver.antifraud.services.call_back.anti_fraud_http_client")
    def test_happy_path(
        self,
        mock_anti_fraud_http_client: mock.Mock,
    ):
        mock_anti_fraud_http_client.post.return_value = mock.Mock(
            status_code=200,
            json=lambda: {"success": True},
        )

        result = hit_anti_fraud_call_back(
            call_back_type=CallBackType.MOVE_APPLICATION_STATUS, application_id=1, new_status="115"
        )
        self.assertTrue(result)

    @mock.patch("juloserver.antifraud.services.call_back.anti_fraud_http_client")
    def test_sad_path(
        self,
        mock_anti_fraud_http_client: mock.Mock,
    ):
        mock_anti_fraud_http_client.post.return_value = mock.Mock(
            status_code=200,
            json=lambda: {"success": False},
        )

        result = hit_anti_fraud_call_back(
            call_back_type=CallBackType.MOVE_APPLICATION_STATUS, application_id=1, new_status="115"
        )
        self.assertFalse(result)

    @mock.patch("juloserver.antifraud.services.call_back.anti_fraud_http_client")
    def test_sad_path_has_error_message(
        self,
        mock_anti_fraud_http_client: mock.Mock,
    ):
        mock_anti_fraud_http_client.post.return_value = mock.Mock(
            status_code=200,
            json=lambda: {"success": False, "error": "error"},
        )

        result = hit_anti_fraud_call_back(
            call_back_type=CallBackType.MOVE_APPLICATION_STATUS, application_id=1, new_status="115"
        )
        self.assertFalse(result)


class TestOverwriteApplicationHistoryAndCallAntiFraudCallBackAPI(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.application_history = ApplicationHistoryFactory(
            application_id=self.application.id,
            status_new=115,
            status_old=105,
            change_reason=FraudChangeReason.ANTI_FRAUD_API_UNAVAILABLE,
        )

    @mock.patch("juloserver.fraud_security.tasks.insert_fraud_application_bucket.delay")
    def test_overwrite_application_history_and_call_anti_fraud_call_back(
        self, mock_insert_fraud_application_bucket
    ):
        expected_change_reason = (
            FraudChangeReason.ANTI_FRAUD_API_UNAVAILABLE
            + " -> "
            + StatusEnum.MOVE_APPLICATION_TO115.value
        )
        overwrite_application_history_and_call_anti_fraud_call_back(
            self.application.id, self.application_history
        )
        self.assertEqual(self.application_history.change_reason, expected_change_reason)
        force_run_on_commit_hook()
        mock_insert_fraud_application_bucket.assert_called_once_with(
            self.application.id, expected_change_reason
        )
