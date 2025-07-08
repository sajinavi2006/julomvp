import csv
import io
import os
import tempfile
from unittest.mock import patch

from django.core.files import File
from django.test import TestCase
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.limit_validity_timer.constants import LimitValidityTimerConsts
from juloserver.limit_validity_timer.tasks import trigger_upload_limit_validity_timer_campaign
from juloserver.limit_validity_timer.tests.factories import LimitValidityTimerCampaignFactory


class TestUploadLimitValidityTimerCampaign(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.customer2 = CustomerFactory()
        self.customer3 = CustomerFactory()
        self.fake_redis = MockRedisHelper()
        self.campaign = LimitValidityTimerCampaignFactory()
        self.redis_key = LimitValidityTimerConsts.LIMIT_VALIDITY_TIMER_REDIS_KEY.format(
            self.campaign.id
        )

    @patch('juloserver.limit_validity_timer.tasks.read_csv_file_by_csv_reader')
    @patch('juloserver.limit_validity_timer.services.get_redis_client')
    def test_trigger_upload_limit_validity_timer_campaign(self, mock_redis, mock_read_csv_file):
        mock_redis.return_value = self.fake_redis
        data = [
            [str(self.customer.id)],
            [str(self.customer2.id)],
            [str(self.customer3.id)],
        ]
        file_name = 'limit_validity_timer_campaign.csv'
        file_path = os.path.abspath(file_name)
        with open(file_path, mode='w', newline='') as file:
            csv_writer = csv.writer(file, delimiter=',')
            csv_writer.writerows(data)

        with open(file_path, mode='r') as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=',')
            mock_read_csv_file.return_value = csv_reader
            trigger_upload_limit_validity_timer_campaign(self.campaign.id)
            self.assertTrue(self.fake_redis.sismember(self.redis_key, self.customer.id))
            self.assertTrue(self.fake_redis.sismember(self.redis_key, self.customer2.id))
            self.assertTrue(self.fake_redis.sismember(self.redis_key, self.customer3.id))
        os.remove(file_path)
