from __future__ import absolute_import
from builtins import str
from builtins import object
from ..exceptions import JuloException
from juloserver.julo.models import AAIBlacklistLog

from .http_client import OpenApiClient


class JuloAdvanceaiClient(object):
    """
    Julo Advanceai Client
    """

    def __init__(self, app_api_key, app_secret_key, base_url):
        self.app_api_key = app_api_key
        self.app_secret_key = app_secret_key
        self.base_url = base_url

    def id_check(self, ktp, fullname):
        '''checking application after passing blacklist in advance ai'''

        api_name = '/openapi/anti-fraud/v3/identity-check'
        application_data = {'idNumber': ktp, 'name': fullname.upper()}

        client = OpenApiClient(self.base_url, self.app_api_key, self.app_secret_key)

        response = client.request(api_name, application_data)
        if response.status_code != 200:
            raise JuloException("%s %s %s" % (response.status_code, str(response), ktp))

        json_response=response.json()
        return json_response['code']


    def blacklist_check(self, ktp, fullname, phone_number, application_id):
        '''Returns response from advance ai api blacklist check'''

        api_name='/openapi/anti-fraud/v5/blacklist-check'
        application_data = {'idNumber': ktp, 'name': fullname.upper()}

        '''phone number formatting'''
        phoneNumber = {
            "countryCode": "+62",
            "areaCode": "",
            "number": phone_number[1:]
        }
        application_data['phoneNumber'] = phoneNumber

        client=OpenApiClient(self.base_url, self.app_api_key, self.app_secret_key)
        response=client.request(api_name, application_data)

        AAIBlacklistLog.objects.create(
            application_id=application_id,
            response_status_code=response.status_code,
            request_string=application_data,
            response_string=response.json()
        )

        if response.status_code != 200:
            raise JuloException("%s %s %s" % (response.status_code, str(response), ktp))

        json_response=response.json()
        if json_response['code'] == 'SUCCESS':
            '''no error, return recommendation'''
            return json_response['data']['recommendation']

        else:
            '''error with request'''
            return json_response['code']
