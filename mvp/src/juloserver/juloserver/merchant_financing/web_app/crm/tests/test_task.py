import mock

from django.test.testcases import TestCase

from mock import patch
from juloserver.julo.tests.factories import (
    PartnerFactory
)
from juloserver.merchant_financing.web_app.crm.tasks import process_mf_web_app_register_file_task
from juloserver.julovers.tests.factories import (
    UploadAsyncStateFactory
)
from juloserver.julo.constants import (
    UploadAsyncStateStatus,
)
from juloserver.merchant_financing.web_app.constants import MFWebAppUploadAsyncStateType
from juloserver.julo.models import UploadAsyncState
from juloserver.merchant_financing.web_app.crm.services import (
    process_mf_web_app_register_result
)


class TestMFWebAppRegisterCSVUploadProcess(TestCase):
    def setUp(self) -> None:
        self.partner = PartnerFactory(
            is_active=True,
            name="Axiata Web"
        )
        self.upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=MFWebAppUploadAsyncStateType.MERCHANT_FINANCING_WEB_APP_REGISTER,
            service = 'oss',
            file="test.csv",
        )

    @patch('juloserver.merchant_financing.web_app.crm.tasks.logger')
    def test_process_merchant_financing_register_with_no_upload_async_state(self, mock_logger) -> None:
        process_mf_web_app_register_file_task(13453, self.partner.id)
        mock_logger.info.assert_called_once_with(
            {
                "action": "MF_web_app_process_register_task_failed",
                "message": "File not found",
                "upload_async_state_id": 13453,
            }
        )

    @mock.patch('juloserver.merchant_financing.web_app.crm.services.process_mf_web_app_register_result')
    def test_process_merchant_financing_register_fail(
            self, mock_disburse_mf_upload
    ) -> None:
        mock_disburse_mf_upload.return_value = False
        process_mf_web_app_register_file_task(self.upload_async_state.id, self.partner.name)
        self.assertEqual(1, UploadAsyncState.objects.filter(
            id=self.upload_async_state.id,
            task_status=UploadAsyncStateStatus.PARTIAL_COMPLETED).count())

    @mock.patch('juloserver.merchant_financing.web_app.crm.services.process_mf_web_app_register_result')
    def test_process_merchant_financing_register_success(
            self, mock_disburse_mf_upload
    ) -> None:
        mock_disburse_mf_upload.return_value = True
        process_mf_web_app_register_file_task(self.upload_async_state.id, self.partner.name)
        self.assertEqual(1, UploadAsyncState.objects.filter(
            id=self.upload_async_state.id,
            task_status=UploadAsyncStateStatus.COMPLETED).count())
