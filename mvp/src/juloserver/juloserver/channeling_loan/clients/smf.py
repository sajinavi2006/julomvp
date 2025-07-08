import hashlib
import hmac
import base64
import datetime
import json
import logging
import requests

from builtins import object
from urllib.parse import urlparse, parse_qs
from rest_framework import status

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.channeling_loan.constants.smf_constants import SMFChannelingConst
from juloserver.channeling_loan.constants.constants import ChannelingConst
from juloserver.channeling_loan.models import ChannelingLoanAPILog

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class SMFChannelingAPIClient(object):
    def __init__(self, gtw_access_key, gtw_api_key, hmac_secret_key, base_url, url_prefix):
        self.GTW_ACCESS_KEY = gtw_access_key
        self.GTW_API_KEY = gtw_api_key
        self.HMAC_SECRET_KEY = hmac_secret_key.encode()
        self.excluded_headers = {"Content-Length"}
        self.base_url = "%s%s" % (base_url, url_prefix)
        self.logging_data = {
            'head': 'channeling_loan.clients.smf.SMFChannelingAPIClient',
            'base_url': self.base_url,
        }
        self.product_data = {
            "product": "J01",
            "idcompany": "JUL",
        }

    def _add_hmac_auth(self, method, url, headers, body=''):
        signing_time = datetime.datetime.utcnow().isoformat() + "Z"
        parsed_url = urlparse(url)

        sb = []
        sb.append(method.upper())
        sb.append(parsed_url.path)
        sb.append(self._get_query_params_sort_by_keys(parsed_url.query))
        sb.append(self.GTW_ACCESS_KEY)
        sb.append(signing_time)

        signed_headers = []
        sorted_headers = sorted(
            (k, v) for k, v in headers.items() if k not in self.excluded_headers
        )

        for key, values in sorted_headers:
            joined_values = ",".join(values) if isinstance(values, list) else values
            sb.append(f"{key}:{joined_values}")
            signed_headers.append(key)

        signing_string = "\n".join(sb) + "\n"
        signature = self._generate_hmac_signature(signing_string)
        body_digest = self._generate_hmac_signature(body if body is not None else '')

        logger.info({
            **self.logging_data,
            'signing_string': signing_string,
            'signed_headers': signed_headers,
            'body_digest': body_digest,
        })

        headers.update({
            "X-HMAC-SIGNATURE": signature,
            "X-HMAC-ALGORITHM": "hmac-sha256",
            "Date": signing_time,
            "X-HMAC-DIGEST": body_digest,
            "X-HMAC-ACCESS-KEY": self.GTW_ACCESS_KEY,
            "X-HMAC-SIGNED-HEADERS": ";".join(signed_headers),
            "apikey": self.GTW_API_KEY,
        })

        return headers

    def _generate_hmac_signature(self, data):
        hasher = hmac.new(self.HMAC_SECRET_KEY, data.encode(), hashlib.sha256)
        return base64.b64encode(hasher.digest()).decode()

    def _get_query_params_sort_by_keys(self, query):
        if not query:
            return ""

        query_params = parse_qs(query)
        sorted_query = "&".join(
            f"{key}={value}" for key in sorted(query_params) for value in query_params[key]
        )
        return sorted_query

    def _send_request(self, request_path, request_type, data, loan):
        url = "%s%s" % (self.base_url, request_path)
        headers = {"Content-Type": "application/json"}
        data.update(self.product_data)
        body = json.dumps(data)
        signed_headers = self._add_hmac_auth(request_type, url, headers, body)
        error = None
        try:
            response = requests.request(request_type, url, headers=signed_headers, data=body)
            status_code = response.status_code
            response.raise_for_status()
            response = response.json()
        except Exception as error:
            sentry_client.captureException()
            response = {"error": error}
            logger.info({
                **self.logging_data,
                'body_string': body,
                'error': error,
            })

        logger.info({
            **self.logging_data,
            'data': data,
            'response': response,
        })

        ChannelingLoanAPILog.objects.create(
            channeling_type=ChannelingConst.SMF,
            application=None,
            loan=loan,
            request_type=request_type,
            http_status_code=status_code,
            request=data,
            response=response,
            error_message=error,
        )

        return status_code, response

    def _reconstruct_response_format(self, response):
        logger.info({
            **self.logging_data,
            'response': response,
        })

        error = response.get('error', {})
        if error:
            return SMFChannelingConst.NOT_OK_STATUS, error

        return (
            response.get('status', SMFChannelingConst.NOT_OK_STATUS),
            response['data'].get('result', {}) if response.get('data') else {}
        )

    def disburse(self, data, loan):
        _, response = self._send_request('disburse', 'POST', data, loan)
        return self._reconstruct_response_format(response)

    def check_transaction(self, data, loan):
        status_code, response = self._send_request('checkTransaction', 'POST', data, loan)
        if status_code == status.HTTP_204_NO_CONTENT:
            return SMFChannelingConst.NOT_OK_STATUS, {"error": "Disbursement not found"}

        return self._reconstruct_response_format(response)
