import time
import base64
import json
import requests

from datetime import datetime
from django.conf import settings
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP

from rest_framework.status import HTTP_200_OK

from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.tokopedia.exceptions import TokoScoreException
from juloserver.tokopedia.constants import TokoScoreConst


logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


def get_request_tokoscore():
    return TokoScoreClient(
        settings.TOKOSCORE_PUBLIC_KEY,
        settings.TOKOSCORE_PRIVATE_KEY,
        settings.TOKOSCORE_BASE_URL,
        settings.TOKOSCORE_CLIENT_ID,
        settings.TOKOSCORE_CLIENT_SECRET,
    )


class TokoScoreClient(object):

    # Endpoint Lists
    token_endpoint = '{}/oauth/token?grant_type=client_credentials'.format(
        settings.TOKOSCORE_BASE_URL,
    )
    get_score_endpoint = '{}/api/v1/partner/score'.format(
        settings.TOKOSCORE_BASE_URL,
    )

    def __init__(self, public_key, private_key, base_url, client_id, client_secret):

        # Setup credentials
        self.public_key = public_key
        self.private_key = private_key
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url
        self.headers = {'Content-Type': 'application/json'}
        self.encoding = 'utf-8'

    def build_auth_token(self):

        basic_auth = '{0}:{1}'.format(self.client_id, self.client_secret)
        encoded_token = base64.b64encode(basic_auth.encode('utf-8')).decode(self.encoding)

        logger.info({'message': 'Execute Build Auth token', 'encoded_token': encoded_token})

        return encoded_token

    def get_token(self):
        """
        To getting access token
        """

        headers = {
            'Authorization': 'Basic {}'.format(self.build_auth_token()),
            **self.headers,
        }
        response = requests.post(self.token_endpoint, headers=headers)
        if response.status_code != HTTP_200_OK:
            logger.info({'message': '[Tokoscore] failed to get token', 'response': response.json()})
            return

        response_data = response.json()
        access_token = response_data.get('access_token', None)
        token_type = response_data.get('token_type', None)

        return access_token, token_type

    @sentry.capture_exceptions
    def get_request_score(self, mobile_phone_number, email):

        access_token, token_type = self.get_token()
        if not access_token or not token_type:
            logger.error(
                {
                    'message': 'failed to get access token or token type',
                }
            )
            return

        if not mobile_phone_number or not email:
            logger.error(
                {
                    'message': 'Invalid request mobile phone or email is empty',
                    'mobile_phone_number': mobile_phone_number,
                    'email': email,
                }
            )
            return

        payload = {
            'message_id': self.build_message_id(),
            'score_id': TokoScoreConst.SCORE_ID,
            'personal_information': self.build_personal_information(
                mobile_phone_number=mobile_phone_number,
                email=email,
            ),
        }

        try:
            headers = {
                'Authorization': token_type + ' ' + access_token,
                **self.headers,
                'Unix-time': str(int(time.time())),
            }
            response = requests.post(self.get_score_endpoint, json=payload, headers=headers)
            logger.info(
                {
                    'message': 'Response from Tokoscore',
                    'status_code': response.status_code if response else None,
                    'mobile_phone_number': mobile_phone_number,
                    'email': email,
                    'headers': str(headers),
                    'payload': str(payload),
                }
            )
            return response

        except Exception as error:
            logger.error(
                {
                    'message': 'Error when create request tokoscore',
                    'error': str(error),
                    'mobile_phone_number': mobile_phone_number,
                    'email': email,
                }
            )
            raise TokoScoreException(str(error))

    @staticmethod
    def determine_for_is_active_user(no_pg_dg):
        """
        PD -> is active
        NO PD -> is not active

        Return True is for Active users
        """
        if no_pg_dg:
            return False

        return True

    @sentry.capture_exceptions
    def do_encrypt(self, payload):

        message = json.dumps(payload)
        # load public key
        try:
            key = RSA.import_key(self.public_key)
            cipher = PKCS1_OAEP.new(key, hashAlgo=SHA256)

            # encode to base64
            encoded_text = cipher.encrypt(message.encode(self.encoding))
            cipher_text = base64.b64encode(encoded_text).decode(self.encoding)

            return cipher_text

        except Exception as error:
            logger.error(
                {
                    'message': 'Error when encrypt process: ' + str(error),
                }
            )
            raise TokoScoreException(str(error))

    @sentry.capture_exceptions
    def do_decrypt(self, encoded_chiper_text):

        # load private key
        try:
            key = RSA.import_key(self.private_key)
            cipher_rsa = PKCS1_OAEP.new(key, hashAlgo=SHA256)

            # decode from base64
            cipher_text = base64.b64decode(encoded_chiper_text)
            plain_payload = cipher_rsa.decrypt(cipher_text).decode(self.encoding)

            return plain_payload
        except Exception as error:
            logger.error(
                {
                    'message': 'Error when decrypt process: ' + str(error),
                }
            )
            raise TokoScoreException(str(error))

    @staticmethod
    def build_message_id():

        date = datetime.today().strftime('%Y%m%d')
        unix_time = str(time.time()).replace('.', '')
        message_id = '{0}.{1}'.format(date, unix_time)

        return message_id

    def build_personal_information(self, mobile_phone_number, email):
        from juloserver.tokopedia.services.common_service import (
            reformat_phone_number,
        )

        payload = {
            TokoScoreConst.KEY_PAYLOAD_PHONE_NUMBER: reformat_phone_number(mobile_phone_number),
            TokoScoreConst.KEY_PAYLOAD_EMAIL: email,
        }

        encrypted_data = self.do_encrypt(payload)

        logger.info(
            {
                'message': 'success to build personal information',
                'encrypted_data': encrypted_data,
                'email': email,
            }
        )

        return encrypted_data
