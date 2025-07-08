from builtins import str
from builtins import object

import logging

from juloserver.disbursement.exceptions import XfersApiError
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
    RedisCacheValue,
)
from juloserver.julo.utils import generate_sha1_hex
from juloserver.disbursement.utils import get_session_request_xfers
import time as time1

logger = logging.getLogger(__name__)

ss_requests = get_session_request_xfers()


class XfersClient(object):
    """
        Client For Xfers API request
    """

    def __init__(self, app_api_key, app_secret_key, julo_user_token, base_url, callback_url):
        self.app_api_key = app_api_key
        self.app_secret_key = app_secret_key
        self.julo_user_token = julo_user_token
        self.base_url = base_url
        self.callback_url = callback_url

    def get_user_token(self, mobile_phone, is_use_cache_data_if_exist=False):
        try:
            valid_mobile_phone = format_e164_indo_phone_number(mobile_phone)
        except Exception as e:
            raise XfersApiError(str(e))

        redis_cache_value = None
        if is_use_cache_data_if_exist:
            redis_cache_value = RedisCacheValue(
                cache_key='xfers_user_api_token:{}'.format(valid_mobile_phone),
                feature_setting_name=FeatureNameConst.CACHE_XFERS_USER_API_TOKEN,
            )

            user_api_token = redis_cache_value.get_if_exists()
            if user_api_token:
                return {
                    'user_api_token': user_api_token,
                }

        relative_url = '/authorize/private_wallet'
        url = '{}{}'.format(self.base_url, relative_url)
        headers = {
            'X-XFERS-APP-API-KEY': self.app_api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        signature = generate_sha1_hex('{}{}'.format(valid_mobile_phone, self.app_secret_key))
        json = {
            'phone_no': valid_mobile_phone,
            'signature': signature
        }
        logger.info({
            'action': 'XfersClient.get_user_token',
            'json': json
        })

        response = ss_requests.post(url, headers=headers, json=json)
        if response.status_code != 200:
            raise XfersApiError('Failed to get token {}'.format(response.reason))

        respond_data = response.json()

        if is_use_cache_data_if_exist:
            redis_cache_value.cache(
                value=respond_data['user_api_token'],
                is_expire_time_get_from_fs=True,
                parameter_key_to_get_days='expire_time_in_days',
            )

        return respond_data

    def get_julo_account_info(self, counter=1):
        relative_url = '/user/'
        url = '{}{}'.format(self.base_url, relative_url)
        headers = {
            'X-XFERS-USER-API-KEY': self.julo_user_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        response = ss_requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.info({
                'counter': counter,
                'message': 'Failed get balance info %s' % (response.reason)
            })
            if counter > 5:
                raise XfersApiError('Failed get balance info %s' % (response.reason))
            else:
                time1.sleep(pow(2, counter))
                return self.get_julo_account_info(counter + 1)
        return response.json()

    def add_bank_account(self, user_token, bank_account, bank_code, name_in_bank=None):
        relative_url = '/user/bank_account'
        url = '{}{}'.format(self.base_url, relative_url)
        headers = {
            'X-XFERS-USER-API-KEY': user_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        json = {
            'account_no': bank_account,
            'bank': bank_code,
            "account_holder_name": name_in_bank
        }

        try:
            response = ss_requests.post(url, headers=headers, json=json)
        except Exception as e:
            logger.warning({
                "message": "Connection timeout",
                "error": str(e),
                "payload": json
            })
            raise XfersApiError('Connection timeout: {message}'.format(
                message=str(e),
            ), http_code=800)  # custom error

        if response.status_code != 200:
            try:
                message = response.json()
            except ValueError:  # to catch simplejson.JSONDecodeError
                message = response.content

            raise XfersApiError('Failed to add bank account; reponse: {status}; {message}'.format(
                status=response.status_code,
                message=message,
            ), http_code=response.status_code)

        return response.json()

    def submit_withdraw(self, bank_id, amount, idempotency_id, user_token):
        relative_url = '/user/bank_account/{}/withdraw'.format(bank_id)
        url = '{}{}'.format(self.base_url, relative_url)
        headers = {
            'X-XFERS-USER-API-KEY': self.julo_user_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        json = {
            "amount": amount,
            "idempotency_id": idempotency_id,
            "user_api_token": user_token,
            "notify_url": self.callback_url
        }
        logger.info({
            'action': 'XfersClient.submit_withdraw',
            'json': json
        })
        response = ss_requests.post(url, headers=headers, json=json)
        if response.status_code != 200:
            logger.error({
                'action': 'XfersClient.submit_withdraw.error',
                'json': json,
                'response_http_status_code': response.status_code,
                'response_content': response.content.decode(),
            })
            raise XfersApiError('Failed withdrawal, {}'.format(response.reason),
                                http_code=response.status_code)

        return response.json()

    def get_withdraw_status(self, reference_id):
        relative_url = '/user/bank_account/withdrawal_requests/{}'.format(str(reference_id))
        url = '{}{}'.format(self.base_url, relative_url)
        headers = {
            'X-XFERS-USER-API-KEY': self.julo_user_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        response = ss_requests.get(url, headers=headers)
        if response.status_code != 200:
            raise XfersApiError('Failed get withdraw status %s' % (response.reason))
        return response.json()

    def submit_charge_jtp(self, amount, order_id, client_token):
        """charge money from jtp account"""
        relative_url = '/charges'
        url = '{}{}'.format(self.base_url, relative_url)
        headers = {
            'X-XFERS-USER-API-KEY': client_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        json = {
            "amount": amount,
            "order_id": order_id,
            "user_api_token": self.julo_user_token,
            "notify_url": self.callback_url,
        }
        response = ss_requests.post(url, headers=headers, json=json)
        if response.status_code != 200:
            logger.error({
                'action': 'XfersClient.submit_charge_jtp.error',
                'json': json,
                'response_http_status_code': response.status_code,
                'response_content': response.content.decode(),
            })
            raise XfersApiError('Failed charge money, {}'.format(response.reason),
                                http_code=response.status_code)
        return response.json()
