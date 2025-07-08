from functools import wraps
import json
from typing import Optional
import logging
import urllib.parse as urlparse
from urllib.parse import urlencode

from juloserver.standardized_api_response.utils import not_found_response
from juloserver.julo.utils import generate_hex_sha256
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


def is_customer_exists(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')

        customer = user.customer
        if not customer:
            return not_found_response("customer tidak ditemukan")
        account = customer.account
        if not account:
            return not_found_response("customer tidak ditemukan")

        return function(view, request, *args, **kwargs)

    return wrapper


def generate_string_to_sign_asymmetric(
    timestamp: str, data: dict, method: str, relative_url: str
) -> str:
    body = json.dumps(data, separators=(',', ':'))
    encrypted_data = generate_hex_sha256(body)
    string_to_sign = '%s:%s:%s:%s' % (method.upper(), relative_url, encrypted_data, timestamp)

    return string_to_sign


def add_params_to_url(url: str, params: dict) -> Optional[str]:
    try:
        url_parts = list(urlparse.urlparse(url))
        query = dict(urlparse.parse_qsl(url_parts[4]))
        query.update(params)
        url_parts[4] = urlencode(query)
        return urlparse.urlunparse(url_parts)
    except Exception as e:
        julo_sentry_client.captureException()
        logger.error(
            {
                'action': 'juloserver.dana_linking.utils.add_params_to_url',
                'message': "error add params to url",
                'error': str(e),
                'url': url,
                'params': params,
            }
        )
