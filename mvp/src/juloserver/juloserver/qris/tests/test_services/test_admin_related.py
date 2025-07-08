from mock import patch

from django.test import TestCase

from juloserver.julo.models import RedisWhiteListUploadHistory
from juloserver.julocore.constants import RedisWhiteList
from juloserver.julo.tests.factories import AuthUserFactory, CustomerFactory
from juloserver.qris.services.admin_related import upload_qris_customer_whitelist_csv


class TestUploadQrisWhitelistCSV(TestCase):
    def setUp(self):
        self.admin_user = AuthUserFactory()
        self.customer_1 = CustomerFactory()
        self.customer_2 = CustomerFactory()

        self.csv_content = f"customer_id\{self.customer_1.id}\{self.customer_2.id}"

    @patch("juloserver.qris.services.admin_related.retrieve_and_set_qris_redis_whitelist_csv.delay")
    @patch("juloserver.qris.services.admin_related.upload_file_as_bytes_to_oss")
    def test_upload_qris_customer_whitelist_csv_ok(self, mock_upload, mock_delay):

        file_bytes = self.csv_content.encode()
        upload_qris_customer_whitelist_csv(
            file_bytes=file_bytes,
            user_id=self.admin_user.id,
        )

        history = RedisWhiteListUploadHistory.objects.filter(
            whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
            status=RedisWhiteList.Status.UPLOAD_SUCCESS,
        ).last()

        self.assertIsNotNone(history)
        self.assertEqual(history.user, self.admin_user)

        mock_delay.assert_called_once()

    @patch("juloserver.qris.services.admin_related.retrieve_and_set_qris_redis_whitelist_csv.delay")
    @patch("juloserver.qris.services.admin_related.upload_file_as_bytes_to_oss")
    def test_upload_qris_customer_whitelist_csv_failed_upload(self, mock_upload, mock_delay):

        mock_upload.side_effect = Exception()

        file_bytes = self.csv_content.encode()
        upload_qris_customer_whitelist_csv(
            file_bytes=file_bytes,
        )

        history = RedisWhiteListUploadHistory.objects.filter(
            whitelist_name=RedisWhiteList.Name.QRIS_CUSTOMER_IDS_WHITELIST,
            status=RedisWhiteList.Status.UPLOAD_FAILED,
        ).last()

        self.assertIsNotNone(history)

        mock_delay.assert_not_called()
