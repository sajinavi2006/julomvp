import json
import datetime
from unittest import mock
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_405_METHOD_NOT_ALLOWED,
)

from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
    AuthUserFactory,
    ProductLineFactory,
)
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.account.tests.factories import AccountFactory
from juloserver.graduation.tests.factories import DowngradeCustomerHistoryFactory
from juloserver.graduation.constants import DowngradeInfoRedisConst
from juloserver.account.tests.factories import AccountLimitFactory
from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.graduation.tasks import run_downgrade_account


PACKAGE_NAME = 'juloserver.graduation.services'


class TestDowngradeInfoAlertAPI(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.account = AccountFactory(customer=self.customer)
        self.account_limit = AccountLimitFactory(account=self.account, set_limit=1_000_000)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.application_status_id = 190
        self.application.save()

        self.feature_setting = FeatureSettingFactory(
            feature_name="downgrade_info_alert",
            is_active=True,
            parameters={
                'downgrade_date_period': 60,
                'info_alert_title': 'Ada penyesuaian pada limitmu. Baca selengkapnya',
                'bottom_sheet_title': 'Terdapat Penyesuaian Pada Limitmu',
                'bottom_sheet_image_url': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717990791&Signature=cEYrPRtZQIFdCOsUlPd96CX3ljc%3D',
                'bottom_sheet_content': """
                    Limit totalmu disesuaikan menjadi {set_limit}.\
                        Penyesuaian ini terkait penurunan jumlah transaksi atau riwayat keterlambatan di JULO dan/atau aplikasi pinjaman lain.
                    Jika sedang ada pinjaman aktif di JULO, segera lunasi limit terpakai agar limit total setelah penyesuaian digunakan lagi, ya!
                """,
                'how_to_revert_limit_content': {
                    'title': "Tenang, limitmu bisa naik lagi, kok!",
                    'items': [
                        "Pastikan selalu bayar tagihan tepat waktu di JULO dan aplikasi pinjaman lain",
                        "Transaksi di JULO sesering mungkin"
                    ]
                },
                'additional_tip': "Lunasi tagihan aktifmu, limit tersediamu utuh lagi",
            }
        )
        self.url = '/api/graduation/v1/downgrade-info-alert'

    def get_customer_graduation(self):
        return {
            'id': 1000,
            'cdate': datetime.datetime(2024, 11, 21, 0, 0, 0),
            'udate': datetime.datetime(2024, 11, 21, 0, 0, 0),
            'customer_id': self.customer.id,
            'account_id': self.account.id,
            'partition_date': datetime.date(2024, 11, 21),
            'old_set_limit': 1_000_000,
            'new_set_limit': 500_000,
            'new_max_limit': 500_000,
            'is_graduate': False,
            'graduation_flow': 'FTC repeat',
        }

    def test_application_invalid(self):
        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)

        self.application.delete()
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_404_NOT_FOUND)

    def test_invalid_request(self):
        response = self.client.post(self.url)
        self.assertEquals(response.status_code, HTTP_405_METHOD_NOT_ALLOWED)

    def test_feature_setting_off(self):
        self.feature_setting.update_safely(is_active=False)
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEqual(
            response.data['data']['is_showed_downgrade_alert'], False
        )

    def test_not_downgrade_history(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['data']['is_showed_downgrade_alert'], False
        )

    @mock.patch('juloserver.graduation.services.get_redis_client')
    def test_get_set_redis_value_not_show_alert(self, mock_get_redis_client):
        fake_redis = MockRedisHelper()
        mock_get_redis_client.return_value = fake_redis
        expected_result = {
            'is_showed_downgrade_alert': False,
        }

        fake_redis.set(
            DowngradeInfoRedisConst.DOWNGRADE_INFO_ALERT.format(self.customer.id),
            json.dumps(expected_result),
        )

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEquals(response.json()['data'], expected_result)

    @mock.patch('django.utils.timezone.now')
    def test_have_downgrade_history(self, mock_now):
        mock_now.return_value = datetime.datetime(2024, 11, 21, 12, 59, 33, tzinfo=timezone.utc)
        downgrade_history = DowngradeCustomerHistoryFactory(account_id=self.account.id)
        expected_respone = {
            'is_showed_downgrade_alert': True,
            'last_downgrade_history_date': '21/11/2024 12:59:33 UTC',
            'info_alert_title': 'Ada penyesuaian pada limitmu. Baca selengkapnya',
            'bottom_sheet_title': 'Terdapat Penyesuaian Pada Limitmu',
            'bottom_sheet_image_url': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717990791&Signature=cEYrPRtZQIFdCOsUlPd96CX3ljc%3D',
            'bottom_sheet_content': """
                    Limit totalmu disesuaikan menjadi Rp 1.000.000.\
                        Penyesuaian ini terkait penurunan jumlah transaksi atau riwayat keterlambatan di JULO dan/atau aplikasi pinjaman lain.
                    Jika sedang ada pinjaman aktif di JULO, segera lunasi limit terpakai agar limit total setelah penyesuaian digunakan lagi, ya!
                """,
            'how_to_revert_limit_content': {
                'items': ['Pastikan selalu bayar tagihan tepat waktu di JULO dan aplikasi pinjaman lain', 'Transaksi di JULO sesering mungkin'],
                'title': 'Tenang, limitmu bisa naik lagi, kok!'
            },
            'additional_tip': "Lunasi tagihan aktifmu, limit tersediamu utuh lagi"
        }
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['data']['is_showed_downgrade_alert'], True
        )
        self.assertEqual(response.data['data'], expected_respone)

    @mock.patch('juloserver.graduation.services.get_redis_client')
    def test_get_set_redis_value_show_alert(self, mock_get_redis_client):
        fake_redis = MockRedisHelper()
        mock_get_redis_client.return_value = fake_redis
        expected_respone = {
            'is_showed_downgrade_alert': True,
            'info_alert_title': 'Ada penyesuaian pada limitmu. Baca selengkapnya',
            'bottom_sheet_title': 'Terdapat Penyesuaian Pada Limitmu',
            'bottom_sheet_image_url': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717990791&Signature=cEYrPRtZQIFdCOsUlPd96CX3ljc%3D',
            'bottom_sheet_content': """
                    Limit totalmu disesuaikan menjadi Rp 1.000.000.\
                        Penyesuaian ini terkait penurunan jumlah transaksi atau riwayat keterlambatan di JULO dan/atau aplikasi pinjaman lain.
                    Jika sedang ada pinjaman aktif di JULO, segera lunasi limit terpakai agar limit total setelah penyesuaian digunakan lagi, ya!
                """,
            'how_to_revert_limit_content': {
                'items': ['Pastikan selalu bayar tagihan tepat waktu di JULO dan aplikasi pinjaman lain', 'Transaksi di JULO sesering mungkin'],
                'title': 'Tenang, limitmu bisa naik lagi, kok!'
            }
        }

        fake_redis.set(
            DowngradeInfoRedisConst.DOWNGRADE_INFO_ALERT.format(self.customer.id),
            json.dumps(expected_respone),
        )

        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        self.assertEquals(response.json()['data'], expected_respone)

    @mock.patch('juloserver.graduation.services.execute_after_transaction_safely')
    @mock.patch('juloserver.graduation.services.get_redis_client')
    @mock.patch('django.utils.timezone.now')
    def test_invalidate_downgrade_info_alert_cache(
        self,
        mock_now,
        mock_get_redis_client,
        mock_execute_after_transaction_safely_graduation,
    ):
        """
        Context: Morning, we dont have downgrade history --> dont show alert
        For example, customer got downgrade at 5PM from cronjob
        6PM customer go to homepage app again --> invalidate cache, show alert
        """
        mock_now.return_value = datetime.datetime(2024, 11, 21, 13, 0, 35, tzinfo=timezone.utc)
        fake_redis = MockRedisHelper()
        mock_get_redis_client.return_value = fake_redis
        expected_result = {
            'is_showed_downgrade_alert': False,
        }

        fake_redis.set(
            DowngradeInfoRedisConst.DOWNGRADE_INFO_ALERT.format(self.customer.id),
            json.dumps(expected_result),
        )
        # Trigger downgrade
        customer_graduation = self.get_customer_graduation()
        run_downgrade_account(customer_graduation)
        expected_respone = {
            'is_showed_downgrade_alert': True,
            'last_downgrade_history_date': '21/11/2024 13:00:35 UTC',
            'info_alert_title': 'Ada penyesuaian pada limitmu. Baca selengkapnya',
            'bottom_sheet_title': 'Terdapat Penyesuaian Pada Limitmu',
            'bottom_sheet_image_url': 'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/company_proof_image.jpg?OSSAccessKeyId=LTAIH82qJI3QFWf5&Expires=1717990791&Signature=cEYrPRtZQIFdCOsUlPd96CX3ljc%3D',
            'bottom_sheet_content': """
                    Limit totalmu disesuaikan menjadi Rp 500.000.\
                        Penyesuaian ini terkait penurunan jumlah transaksi atau riwayat keterlambatan di JULO dan/atau aplikasi pinjaman lain.
                    Jika sedang ada pinjaman aktif di JULO, segera lunasi limit terpakai agar limit total setelah penyesuaian digunakan lagi, ya!
                """,
            'how_to_revert_limit_content': {
                'items': ['Pastikan selalu bayar tagihan tepat waktu di JULO dan aplikasi pinjaman lain', 'Transaksi di JULO sesering mungkin'],
                'title': 'Tenang, limitmu bisa naik lagi, kok!'
            }
        }
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, HTTP_200_OK)
        mock_execute_after_transaction_safely_graduation.assert_called()
