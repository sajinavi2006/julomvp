import mock
import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from django.contrib.auth.models import Group

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
)
from juloserver.julo.models import Document
from juloserver.disbursement.constants import DailyDisbursementLimitWhitelistConst

SUB_FOLDER = "juloserver.disbursement.views.crm_views"


class TestChannelingCRMViews(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory(username="prod_only")
        self.user.groups.add(Group.objects.create(name='product_manager'))
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)

    def test_get_daily_disbursement_limit_upload_view(self):
        res = self.client.get('/disbursement/daily_disbursement_limit')
        self.assertEqual(res.status_code, 200)

    def test_post_daily_disbursement_limit_upload_view(self):
        res = self.client.post(
            '/disbursement/daily_disbursement_limit',
            {
                'file_field': '',
                'url_field': '',
            },
        )
        self.assertEqual(res.status_code, 200)

    @mock.patch('django.utils.timezone.now')
    @mock.patch(f'{SUB_FOLDER}.process_daily_disbursement_limit_whitelist_task')
    def test_post_daily_disbursement_limit_upload_view_url_field(
        self, mock_process_task, mock_now
    ):
        mock_now.return_value = datetime.datetime(2025, 4, 15, 12, 23, 0)

        res = self.client.post(
            '/disbursement/daily_disbursement_limit',
            {
                'file_field': '',
                'url_field': 'https://docs.google.com/spreadsheets',
            },
        )
        self.assertEqual(res.status_code, 200)

        mock_process_task.delay.assert_called_once_with(
            user_id=self.user.id,
            document_id=None,
            form_data=mock.ANY
        )

    @mock.patch('django.utils.timezone.now')
    @mock.patch(f'{SUB_FOLDER}.process_daily_disbursement_limit_whitelist_task')
    def test_post_daily_disbursement_limit_upload_view_file_field(
        self, mock_process_task, mock_now
    ):
        mock_now.return_value = datetime.datetime(2025, 4, 15, 12, 23, 0)
        csv_bytes = b'customer_id,source\n1000000001,test\n1000000002,test\n'
        file = SimpleUploadedFile(
            "daily_disbursement_whitelist.csv",
            csv_bytes,
            content_type='text/csv'
        )

        res = self.client.post(
            '/disbursement/daily_disbursement_limit',
            {
                'file_field': file,
                'url_field': '',
            },
        )
        self.assertEqual(res.status_code, 200)

        document = (
            Document.objects
            .filter(
                document_source=self.user.id,
                document_type=DailyDisbursementLimitWhitelistConst.DOCUMENT_TYPE)
            .last()
        )
        self.assertEqual(
            document.filename,
            '{username}_{timestamp}_{upload_file_name}'.format(
                username='prod_only',
                timestamp='202504151223',
                upload_file_name='daily_disbursement_whitelist.csv'
            )
        )

        mock_process_task.delay.assert_called_once_with(
            user_id=self.user.id,
            document_id=document.id,
            form_data=mock.ANY
        )
