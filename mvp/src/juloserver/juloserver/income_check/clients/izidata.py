import datetime
import hashlib
import hmac
import sys

import requests

from juloserver.income_check.constants import IziDataConstant

requests.packages.urllib3.disable_warnings()

if sys.version_info.major == 2:
    from urllib import quote, urlencode

    from urlparse import urlparse
else:
    from urllib.parse import quote, urlencode, urlparse


class IziDataClient(object):
    def __init__(self, access_key, secret_key, base_url):
        self._access_key = access_key
        self._secret_key = secret_key
        self.base_url = base_url
        self.__client = requests
        self.__connect_timeout = IziDataConstant.CONNECT_TIMEOUT
        self.__socket_timeout = IziDataConstant.SOCKET_TIMEOUT
        self._proxies = {}

    def request(self, relative_url, data):
        params = {}
        headers = {}

        url = '{}{}'.format(self.base_url, relative_url)

        headers = self._get_auth_headers('POST', url, params, headers)
        response = self.__client.post(
            url,
            data=data,
            params=params,
            headers=headers,
            verify=False,
            timeout=(
                self.__connect_timeout,
                self.__socket_timeout,
            ),
            proxies=self._proxies,
        )

        return {'headers': headers, 'response': response, 'url': url}

    def _get_auth_headers(self, method, url, params=None, headers=None):
        headers = headers or {}
        params = params or {}

        url_result = urlparse(url)
        for kv in url_result.query.strip().split('&'):
            if kv:
                k, v = kv.split('=')
                params[k] = v

        # UTC timestamp
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

        headers['credit-date'] = timestamp
        version, expire = IziDataConstant.VERSIONS, IziDataConstant.EXPIRE

        # 1 Generate Signing key
        val = "credit-v%s/%s/%s/%s" % (version, self._access_key, timestamp, expire)
        signing_key = hmac.new(
            self._secret_key.encode('utf-8'), val.encode('utf-8'), hashlib.sha256
        ).hexdigest()

        # 2 Generate CanonicalRequest
        # 2.1 Genrate CanonicalURI
        canonical_uri = quote(url_result.path)
        # 2.2 Generate CanonicalURI: not used here
        # 2.3 Generate CanonicalHeaders: only include host here
        canonical_headers = []
        for header, val in headers.items():
            canonical_headers.append(
                '%s:%s' % (quote(header.strip(), '').lower(), quote(val.strip(), ''))
            )
        canonical_headers = '\n'.join(sorted(canonical_headers))

        # 2.4 Generate CanonicalRequest
        canonical_request = '%s\n%s\n%s\n%s' % (
            method.upper(),
            canonical_uri,
            '&'.join(sorted(urlencode(params).split('&'))),
            canonical_headers,
        )
        # 3 Generate Final Signature
        signature = hmac.new(
            signing_key.encode('utf-8'), canonical_request.encode('utf-8'), hashlib.sha256
        ).hexdigest()

        headers['authorization'] = 'credit-v%s/%s/%s/%s/%s/%s' % (
            version,
            self._access_key,
            timestamp,
            expire,
            ';'.join(headers.keys()).lower(),
            signature,
        )

        return headers
