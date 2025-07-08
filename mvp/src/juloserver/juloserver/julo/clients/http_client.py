from builtins import bytes
from builtins import str
from builtins import object
import base64
import hashlib
import hmac
import json
import os
import requests
import time
import sys
from datetime import datetime
from random import randint

from juloserver.julocore.python2.utils import py2round

PY2 = sys.version_info[0] == 2


def _b(s):
    return s if PY2 else bytes(s, 'utf-8')


class OpenApiFileData(object):
    name = None
    data = None

    def __init__(self, name, data):
        self.name = name
        self.data = data


class OpenApiClient(object):
    """ADVANCE.AI's open api client."""

    api_host = None
    access_key = None
    secret_key = None
    time_out = 20

    request_url = None
    request_headers = None
    request_post_body = None

    def __init__(self, api_host=None, access_key=None, secret_key=None):
        self.api_host = api_host
        self.access_key = access_key
        self.secret_key = secret_key

    def _hmac_base64(self, sign_str=''):

        secret = sign_str.encode()
        message = self.secret_key.encode()
        signature = base64.b64encode(hmac.new(message, secret, digestmod=hashlib.sha256).digest())
        return signature.decode()

    def _is_scalar(self, value):
        types = (type(None), str, int, float, bool, str) if PY2 else (type(None), str, int, float, bool)
        return isinstance(value, types)

    def set_timeout(self, timeout):
        self.time_out = timeout

    def _prepare(self, api_name, param_dict, file_dict):
        if not api_name.startswith('/'):
            api_name = '/' + api_name

        self.request_url = self.api_host[:-1] if self.api_host.endswith('/') else self.api_host
        self.request_url += api_name

        if not file_dict:
            content_type = 'application/json'
            self.request_post_body = json.dumps(param_dict)
        else:
            self.request_post_body = _b('')
            rand_int = 10000000 + randint(0, 10000000 - 1)
            boundary = '----AD1238MJL7' + str(int(py2round(time.time() * 1000))) + 'I' + str(rand_int)
            content_type = 'multipart/form-data; boundary={}'.format(boundary)

            if param_dict:
                for k, v in list(param_dict.items()):
                    if not self._is_scalar(v):
                        raise RuntimeError("only scalar key/value params support when uploading files")
                    self.request_post_body += _b("--{}\r\n".format(boundary))
                    self.request_post_body += _b('Content-Disposition: form-data; name="{}"\r\n'.format(k))
                    self.request_post_body += _b("\r\n{}\r\n".format(v))

            for k, f in list(file_dict.items()):

                if isinstance(f, OpenApiFileData):
                    base_name = f.name
                    file_content = f.data
                else:
                    fn = f
                    if not os.path.exists(fn):
                        raise RuntimeError("{} not exists".format(fn))

                    base_name = os.path.basename(fn)
                    with open(fn, 'rb') as fd:
                        file_content = fd.read()

                file_type = base_name.split('.')[1]
                if file_type == 'jpg':
                    file_type = 'jpeg'
                if file_type != 'jpeg' and file_type != 'png':
                    raise RuntimeError("{} file type not support, only support jpeg/jpg/png.".format(file_type))
                mime_type = 'image/' + file_type

                self.request_post_body += _b("--{}\r\n".format(boundary))
                self.request_post_body += _b('Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.format(k, base_name))
                self.request_post_body += _b("Content-Type: {}\r\n".format(mime_type))
                self.request_post_body += b"\r\n" + file_content + b"\r\n"

            self.request_post_body += _b("--{}--".format(boundary))

        now = datetime.utcnow()
        gmt_now = now.strftime("%a, %d %b %Y %H:%M:%S") + ' GMT'

        separator = '$'
        sign_str = 'POST' + separator
        sign_str += api_name + separator
        sign_str += gmt_now + separator
        authorization = '{}:{}'.format(self.access_key, self._hmac_base64(sign_str=sign_str))

        self.request_headers = {
            'Content-Type': content_type,
            'Date': gmt_now,
            'Authorization': authorization
        }

    def request(self, api_name, param_array=None, file_array=None):
        self._prepare(api_name, param_array, file_array)

        resp = requests.request(
            url=self.request_url,
            method='POST',
            headers=self.request_headers,
            data=self.request_post_body,
            timeout=self.time_out
        )
        return resp
