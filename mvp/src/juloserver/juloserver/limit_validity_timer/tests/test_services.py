from unittest.mock import patch
from rest_framework.test import APITestCase
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julo.tests.factories import (
   CustomerFactory
)
from juloserver.limit_validity_timer.constants import LimitValidityTimerConsts
from juloserver.limit_validity_timer.services import populate_limit_validity_campaign_on_redis, \
    delete_limit_validity_campaign_on_redis
from juloserver.limit_validity_timer.tests.factories import LimitValidityTimerCampaignFactory


class TestPopulateDataCampaignRedis(APITestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.fake_redis = MockRedisHelper()
        self.campaign = LimitValidityTimerCampaignFactory()
        self.redis_key = LimitValidityTimerConsts.LIMIT_VALIDITY_TIMER_REDIS_KEY.format(
            self.campaign.id
        )

    @patch('juloserver.limit_validity_timer.services.get_redis_client')
    def test_populate_limit_validity_campaign_on_redis(self, mock_redis):
        mock_redis.return_value = self.fake_redis
        populate_limit_validity_campaign_on_redis(
            {self.customer.id}, self.campaign.id, self.campaign.end_date
        )
        result = self.fake_redis.sismember(self.redis_key, self.customer.id)
        self.assertTrue(result)

        delete_limit_validity_campaign_on_redis(self.campaign.id)
        result = self.fake_redis.get(self.redis_key, self.customer.id)
        self.assertIsNone(result)
