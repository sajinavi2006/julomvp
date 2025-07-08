import base64
import hashlib
import logging

from typing import Any, Union
from urllib.parse import urlparse

from rest_framework.authentication import BaseAuthentication

from juloserver.partnership.liveness_partnership.exceptions import APIForbiddenError
from juloserver.partnership.liveness_partnership.constants import LivenessHTTPGeneralErrorMessage
from juloserver.partnership.models import LivenessConfiguration
from juloserver.partnership.liveness_partnership.utils import decrypt_api_key

logger = logging.getLogger(__name__)


class PartnershipLivenessAuthentication(BaseAuthentication):
    def verify_token(self, authorization: str) -> Union[bool, str]:
        if not authorization:
            return False
        token = authorization.split(' ')
        if len(token) == 2 and token[0].lower() == 'token':
            return token[1]

        return False

    def authenticate(self, request) -> Any:
        token = self.verify_token(request.META.get('HTTP_AUTHORIZATION'))
        http_origin = request.META.get('HTTP_ORIGIN', 'FAILED_GET_HTTP_ORIGIN')
        if http_origin != 'FAILED_GET_HTTP_ORIGIN':
            # Remove the scheme (http or https)
            parsed_url = urlparse(http_origin)
            http_origin = parsed_url.netloc
        else:
            logger.info(
                {
                    "action": "failed_partnership_liveness_authentication",
                    "message": "failed get HTTP_ORIGIN",
                    "host": http_origin,
                }
            )
            raise APIForbiddenError(LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        if not token:
            raise APIForbiddenError(LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        try:
            # Decode the Base64 string
            decoded_token = base64.b64decode(token, validate=True).decode('utf-8')
            hash_client_id, api_key = decoded_token.split(':')
            # process decrypt API key
            cdate_client_id, hashed_cdate_client_id = decrypt_api_key(api_key)

            # get client_id from decrypted_data
            _, client_id = cdate_client_id.split(':')
        except Exception as e:
            logger.info(
                {
                    "action": "failed_partnership_liveness_authentication",
                    "message": str(e),
                    "http_origin": http_origin,
                }
            )
            raise APIForbiddenError(LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        liveness_configuration = LivenessConfiguration.objects.filter(
            client_id=client_id,
            is_active=True,
        ).last()
        if not liveness_configuration:
            raise APIForbiddenError(LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        # Verify the hash_client_id
        hash_client_id_from_decrypted_data = hashlib.sha1(
            str(liveness_configuration.client_id).encode()
        ).hexdigest()
        if hash_client_id_from_decrypted_data != hash_client_id:
            raise APIForbiddenError(LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        # Verify encrypted_data from API Key
        # this steps we compare encrypted_data (cdate:client_id) inside API key
        # we create hashing cdate:client_id from decrypted api key
        # compare hasing data is valid or not. if no valid we return 403
        liveness_configuration_cdate = int(liveness_configuration.cdate.timestamp())
        create_data_from_decrypted_api_key = "{}:{}".format(
            liveness_configuration_cdate, liveness_configuration.client_id
        )
        hashing_cdate_client_id = hashlib.sha256(
            create_data_from_decrypted_api_key.encode()
        ).digest()
        if hashed_cdate_client_id != hashing_cdate_client_id:
            raise APIForbiddenError(LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        # checking http_host and http_forwarded in whitelisted domain
        whitelisted_domain = liveness_configuration.whitelisted_domain
        if not whitelisted_domain:
            logger.info(
                {
                    "action": "failed_partnership_liveness_authentication",
                    "message": "whitelisted_domain is empty",
                    "host": http_origin,
                }
            )
            raise APIForbiddenError(LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS)
        if http_origin not in whitelisted_domain:
            logger.info(
                {
                    "action": "failed_partnership_liveness_authentication",
                    "message": "domain/ip not in whitelisted_domain",
                    "host": http_origin,
                }
            )
            raise APIForbiddenError(LivenessHTTPGeneralErrorMessage.FORBIDDEN_ACCESS)

        request.liveness_configuration = liveness_configuration
