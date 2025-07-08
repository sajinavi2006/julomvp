import json
import requests
from datetime import timedelta

from django.conf import settings
from juloserver.julo.exceptions import JuloException
from juloserver.minisquad.clients.airudder_pds import AIRudderPDSClient
from juloserver.julo.services2 import get_redis_client
from juloserver.sales_ops_pds.constants import RedisKey


class GeneralAIRudderPDSClient(AIRudderPDSClient):
    """
        Inherited from AIRudderPDSClient to have separated Redis key for storing credentials
    """
    def __init__(self, api_key: str, api_secret_key: str, base_url: str, redis_key: str):
        self.redis_key = redis_key
        super(GeneralAIRudderPDSClient, self).__init__(api_key, api_secret_key, base_url)

    def _AIRudderPDSClient__get_token_from_redis(self):
        redisClient = get_redis_client()
        token = redisClient.get(self.redis_key)
        return token

    def refresh_token(self):
        redisClient = get_redis_client()
        auth_api = self.base_url + self.PDS_URL_PATH + '/auth'

        app_info = {
            'APPKey': self.api_key,
            'APPSecret': self.api_secret_key
        }

        response = requests.post(auth_api, data=app_info)
        parsed_response = json.loads(response.text)
        self.logger.info({
            'action': 'refresh_token',
            'message': 'raw response from airudder',
            'data': parsed_response
        })
        if response.status_code == requests.codes.unauthorized:
            raise JuloException('Failed to Get Token from AIRudder PDS - Unauthorized')

        converted_response = json.loads(response.text)
        if converted_response.get('code', 1) != 0:
            raise JuloException(
                'Failed to Get Token from AIRudder PDS - {}'.format(response.text)
            )

        body_response = converted_response .get('body')
        token = body_response.get('token')
        redisClient.set(self.redis_key, token, timedelta(hours=23))
        self.token = token
        return token


def get_sales_ops_airudder_pds_client():
    return GeneralAIRudderPDSClient(
        api_key=settings.SALES_OPS_AIRUDDER_PDS_APP_KEY,
        api_secret_key=settings.SALES_OPS_AIRUDDER_PDS_APP_SECRET,
        base_url=settings.SALES_OPS_AIRUDDER_PDS_BASE_URL,
        redis_key=RedisKey.SALES_OPS_AIRUDDER_PDS_BEARER_TOKEN_KEY
    )
