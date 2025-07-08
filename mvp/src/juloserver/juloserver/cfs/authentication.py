from typing import Dict, Any
import json
import base64
import hmac
import hashlib
from juloserver.api_token.authentication import WebToken
from juloserver.api_token.exceptions import (
    UnsupportedAlgoException,
    InvalidWebTokenException,
    ExpiredWebTokenException
)
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from datetime import timedelta, datetime
from juloserver.cfs.constants import EasyIncomeConstant
from juloserver.julo.models import FeatureSetting
from rest_framework.authentication import TokenAuthentication
import time
from juloserver.julo.models import Customer


class EasyIncomeWebToken(WebToken):
    """
    Custom Web Token implementation class.
    Consist of 3 parts [If needed we can expand]
        - header
        - payload
        - signature
    """
    type = "EWT"

    def __init__(self) -> None:
        now_timestamp = time.time()
        self.localtime_offset = datetime.fromtimestamp(
            now_timestamp
        ) - datetime.utcfromtimestamp(now_timestamp)

    def encode(self,
               payload: Dict[str, Any],
               secret_key: str,
               algorithm_name: str
        ) -> str:
        """
        Encode with the given payload using the specified algorithm.
        Parameters:
        - payload (Dict[str, Any]): A dictionary containing the data to be included in the EWT.
        - secret_key (str): The secret key used for signing the EWT.
        - algorithm_name (str): The algorithm used for signing, specified as a string.
        Returns:
        - str: The encoded EWT.
        Raises:
        - UnsupportedAlgoException: If algorithm name not supported
        Example:
        ```
        encoder = EasyIncomeWebToken()
        payload = {"user_id": 123, "username": "john_doe"}
        secret_key = "your_secret_key"
        algorithm_name = "HS256"
        token = encoder.encode(payload, secret_key, algorithm_name)
        ```
        """
        if not self.is_supported_algorithm(algorithm_name):
            raise UnsupportedAlgoException("Algorithm is not supported")
        # Header 
        header = {"alg": algorithm_name.upper(), "typ": self.type}
        encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=")

        # handle if there is exp
        if 'exp' in payload:
            payload['exp'] = payload['exp'].timestamp()

        # Payload
        encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")

        # Signature
        signature_input = encoded_header + b"." + encoded_payload
        signature = base64.urlsafe_b64encode(
            hmac.new(secret_key.encode(),
            signature_input,
            hashlib.sha256).digest()
        ).rstrip(b"=")

        # Combine the parts
        token = encoded_header + b"." + encoded_payload + b"." + signature

        return token.decode("utf-8")

    def decode(self,
               token: str,
               secret_key: str,
               algorithm_name: str
        ) -> Dict[str, Any]:
        """
        Decode a web token and verify its signature.
        Parameters:
        - token (str): The web token to decode.
        - secret_key (str): The secret key used to sign the token.
        - algorithm_name (str): The name of the algorithm used for signing.
        Returns:
        - Dict[str, Any]: The payload of the decoded token.
        Raises:
        - InvalidWebTokenException: If the token format is invalid.
        - UnsupportedAlgoException: If the signature is invalid.
        - ExpiredWebTokenException: If the token has expired.
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidWebTokenException("Invalid {} format".format(self.type))
        current_datetime = timezone.localtime(timezone.now())
        encoded_header, encoded_payload, signature = parts

        # Verify the signature
        signature_input = (encoded_header + "." + encoded_payload).encode()
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(secret_key.encode(),
                     signature_input,
                     self.get_algorithm_by_name(algorithm_name)
            ).digest()
        ).rstrip(b"=")

        if str(signature) != str(expected_signature.decode('utf-8')):
            raise InvalidWebTokenException(
                "Invalid signature: {}: {}".format(str(signature), str(expected_signature))
            )

        decoded_bytes = base64.urlsafe_b64decode(
            encoded_payload + b"=".decode("utf-8") * (4 - len(encoded_payload) % 4)
        )
        decoded_str = decoded_bytes.decode('utf-8')
        payload = json.loads(decoded_str)

        # check if exp is there or not
        # if found then validate expiration
        if 'exp' in payload:
            exp_datetime = datetime.utcfromtimestamp(payload['exp'])
            if current_datetime >= timezone.localtime(self.localtime_offset + exp_datetime):
                raise ExpiredWebTokenException("Token is expired")
        return payload

    @staticmethod
    def generate_token_from_user(user: User) -> str:
        current_time = timezone.localtime(timezone.now())
        feature_setting = FeatureSetting.objects.filter(
            feature_name=EasyIncomeConstant.FEATURE_SETTING_KEY,
            is_active=True
        ).last()
        expire_after = settings.DEFAULT_TOKEN_EXPIRE_AFTER_HOURS
        if feature_setting:
            expire_after = feature_setting.parameters.get(
                EasyIncomeConstant.TOKEN_AFTER_HOURS_KEY_IN_FEATURE_SETTING,
                settings.DEFAULT_TOKEN_EXPIRE_AFTER_HOURS
            )

        expire_after = int(expire_after)

        exp = current_time + timedelta(hours=expire_after)
        customer = user.customer
        payload = {
            'customer_id': customer.id,
            'exp': exp

        }
        token = _global_easy_income_web_token_obj.encode(
            payload,
            settings.EASY_INCOME_AUTH_SECRET_KEY,
            "HS256"
        )
        return token


_global_easy_income_web_token_obj = EasyIncomeWebToken()


class EasyIncomeTokenAuth(TokenAuthentication):
    model = EasyIncomeWebToken

    def authenticate(self, request):
        token = request.META.get('HTTP_AUTHORIZATION', "")
        token = token.replace("Bearer ", "")
        if not token:
            raise exceptions.AuthenticationFailed('No token provided.')

        return self.authenticate_credentials(token)

    def authenticate_credentials(self, token):
        try:
            payload = _global_easy_income_web_token_obj.decode(
                token,
                settings.EASY_INCOME_AUTH_SECRET_KEY,
                'HS256'
            )
        except (
            UnsupportedAlgoException,
            InvalidWebTokenException
        ):
            raise exceptions.AuthenticationFailed("Authentication failed.")
        except ExpiredWebTokenException:
            raise exceptions.AuthenticationFailed("Token expired")

        user = None
        # get user from payload
        if 'customer_id' in payload:
            customer_id = payload['customer_id']
            customer = Customer.objects.filter(id=customer_id, is_active=True).first()
            if customer:
                user = customer.user

        return user, token
