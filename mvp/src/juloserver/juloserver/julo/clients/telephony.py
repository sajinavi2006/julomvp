from builtins import str
from builtins import object
import logging

import requests

from ..exceptions import JuloException


logger = logging.getLogger(__name__)


class QuirosApiError(JuloException):
    pass


class QuirosApiValidationError(JuloException):
    pass


class QuirosApiCodes(object):
    SUCCESS = "0000"
    RESOURCE_NOT_FOUND = "1200"


# Debugging code, commented out
# import httplib
# def patch_send():
#     old_send = httplib.HTTPConnection.send
#
#     def new_send(self, data):
#         print "_" * 80
#         print data
#         return old_send(self, data) #return is not necessary, but never hurts, in case the library is changed
#     httplib.HTTPConnection.send = new_send
# patch_send()


class QuirosClient(object):
    """
    Makes API calls to Quiros Outbound API and Voice Broadcast API

    Note about API:
    * all timestamps returned by the API is in WIB
    * all responses that return a list of results are never paginated
    * intermediary status for a call is either Pending or Calling

    Note about Client:
    * it can be used directly by passing in a token or the token can be set
      after calling the login method
    """

    def __init__(self, base_url, token=None):
        self.base_url = base_url
        self.token = token

    @staticmethod
    def _check_response_and_get_result(response, identifier):
        """
        The identifier can be anything that can be used to tie the exception
        to some specific data
        """
        if response.status_code != requests.codes.ok:
            raise QuirosApiError(
                "Request to %s returns %s for %s" % (
                    response.url, response.status_code, identifier))

        response_dict = response.json()
        if response_dict['code'] != QuirosApiCodes.SUCCESS:
            raise QuirosApiError(
                "Request to %s returns API code %s for %s because %s" % (
                    response.url, response_dict['code'], identifier,
                    response_dict['description']))

        data = response_dict.get('result')
        if data is None:
            data = response_dict.get('results')
        if data is None:
            raise QuirosApiError(
                "Response from %s for %s has no result" % (response.url, identifier))
        return data

    def get_headers_with_auth(self):
        """Helps setting the token in headers"""
        if self.token is None:
            raise QuirosApiValidationError("Token not provided")
        return {
            'Authorization': "Bearer %s" % self.token
        }

    def login(self, username, password):
        """If token not set, call this method first"""
        url_endpoint = '/authApi/login'
        url_params = {
            'username': username,
            'password': password
        }

        response = requests.get(self.base_url + url_endpoint, params=url_params)
        result = self._check_response_and_get_result(response, username)

        token = result['token']
        self.token = token

        logger.info({
            'status': 'token_received',
            'url_endpoint': url_endpoint,
            'username': username
        })
        return token


class AutodialClient(QuirosClient):
    """All actions are for the current user, the agent. Including the reports"""

    def call(self, customer_info, phone_number):

        url_endpoint = '/callApi/call'
        headers = self.get_headers_with_auth()
        headers['Content-Type'] = "application/json"
        data = {
            'customer': customer_info,
            'phone': phone_number
        }

        response = requests.post(self.base_url + url_endpoint, json=data, headers=headers)
        result = self._check_response_and_get_result(response, phone_number)
        call_id = result['id']

        logger.info({
            'status': 'call_made',
            'url_endpoint': url_endpoint,
            'call_id': call_id,
            'phone_number': phone_number
        })
        return call_id

    def hangup(self, call_id):

        url_endpoint = '/callApi/hangup'
        headers = self.get_headers_with_auth()
        headers['Content-Type'] = "application/json"
        data = {
            'id': call_id
        }

        response = requests.post(self.base_url + url_endpoint, json=data, headers=headers)
        self._check_response_and_get_result(response, call_id)

    def get_report_by_call_id(self, call_id):

        url_endpoint = '/reportApi/get'
        headers = self.get_headers_with_auth()
        url_params = {
            'id': call_id
        }

        response = requests.get(self.base_url + url_endpoint, params=url_params, headers=headers)
        result = self._check_response_and_get_result(response, call_id)

        logger.info({
            'status': 'report_received',
            'url_endpoint': url_endpoint,
            'call_id': call_id
        })
        return result

    def get_report_by_call_id_if_exists(self, call_id):
        """
        When the call is still ongoing, there is no report yet so return None
        """
        try:
            return self.get_report_by_call_id(call_id)
        except QuirosApiError as qae:
            if QuirosApiCodes.RESOURCE_NOT_FOUND in str(qae):
                return None
            raise qae


class RobocallClient(QuirosClient):
    """
    There is no concept of agent, so a single username for the robocall service.
    """

    def create_bucket(self, label, voice="standard"):

        url_endpoint = '/bucketApi/createBucket'
        headers = self.get_headers_with_auth()
        headers['Content-Type'] = "application/json"
        data = {
            'label': label,
            'voice': voice
        }

        response = requests.post(self.base_url + url_endpoint, json=data, headers=headers)
        result = self._check_response_and_get_result(response, label)
        bucket_id = result['id']

        logger.info({
            'status': 'bucket_created',
            'url_endpoint': url_endpoint,
            'label': label
        })
        return bucket_id

    def delete_buckets(self, bucket_ids):

        url_endpoint = '/bucketApi/deleteBuckets'
        headers = self.get_headers_with_auth()
        headers['Content-Type'] = "application/json"

        response = requests.post(
            self.base_url + url_endpoint, json=bucket_ids, headers=headers)
        self._check_response_and_get_result(response, bucket_ids)

        logger.info({
            'status': 'buckets_deleted',
            'bucket_ids': bucket_ids
        })

    def get_buckets(self):

        url_endpoint = '/bucketApi/getBuckets'
        headers = self.get_headers_with_auth()
        headers['Content-Type'] = "application/json"

        response = requests.get(self.base_url + url_endpoint, headers=headers)
        results = self._check_response_and_get_result(response, None)

        logger.info({
            'status': 'buckets_returned',
            'url_endpoint': url_endpoint,
            'bucket_count': len(results)
        })
        return results

    def get_customer_list_from_bucket(self, bucket_id):

        url_endpoint = '/bucketApi/getCustomersByBucketId'
        headers = self.get_headers_with_auth()
        headers['Content-Type'] = "application/json"
        url_params = {
            'id': bucket_id
        }

        response = requests.get(
            self.base_url + url_endpoint, params=url_params, headers=headers)
        results = self._check_response_and_get_result(response, bucket_id)

        logger.info({
            'status': 'customer_list_returned',
            'url_endpoint': url_endpoint,
            'bucket_id': bucket_id,
            'count': len(results)
        })
        return results

    def add_customers_to_bucket(self, bucket_id, customer_dict_list):

        url_endpoint = '/bucketApi/addMultipleCustomers'
        headers = self.get_headers_with_auth()
        headers['Content-Type'] = "application/json"
        url_params = {
            'id': bucket_id
        }

        response = requests.post(
            self.base_url + url_endpoint, params=url_params, json=customer_dict_list,
            headers=headers)
        result = self._check_response_and_get_result(response, bucket_id)
        customer_count = result['entries']

        logger.info({
            'status': 'customers_added_to_bucket',
            'bucket_id': bucket_id,
            'customer_count': customer_count
        })
        return customer_count

    def create_campaign(
            self, name, tts, bucket_id, start_call=None, end_call=None,
            start=None, speech_option='tts', tts_speed=None):
        """This method only supports text-to-speech (TTS) for now"""

        url_endpoint = '/campaignApi/uploadNewCampaign'
        headers = self.get_headers_with_auth()
        headers['Content-Type'] = "application/json"
        data = {
            'name': name,
            'tts': tts,
            'bucketId': bucket_id,
        }
        if start_call is not None:
            data['startCall'] = start_call
        if end_call is not None:
            data['endCall'] = end_call
        if start is not None:
            data['start'] = start
        if speech_option is not None:
            data['speechOption'] = speech_option
        if tts_speed is not None:
            data['ttsSpeed'] = tts_speed

        response = requests.post(self.base_url + url_endpoint, data=data, headers=headers)
        result = self._check_response_and_get_result(response, name)
        campaign_id = result['id']

        logger.info({
            'status': 'campaign_created',
            'name': name,
            'tts': tts,
            'bucket_id': bucket_id,
        })
        return campaign_id

    def update_campaign(self):

        url_endpoint = '/campaignApi/uploadUpdateCampaign'

    def get_campaigns(self):

        url_endpoint = '/campaignApi/getCampaigns'
        headers = self.get_headers_with_auth()

        response = requests.get(self.base_url + url_endpoint, headers=headers)
        results = self._check_response_and_get_result(response, None)

        logger.info({
            'status': 'buckets_returned',
            'url_endpoint': url_endpoint,
            'bucket_count': len(results)
        })
        return results

    def get_campaign_statuses(self):

        url_endpoint = '/uploadApi/getUploadsByIds'
        # headers = self.get_headers_with_auth()
        # url_params = {
        #     'id': bucket_id
        # }
        #
        # response = requests.get(self.base_url + url_endpoint, headers=headers)
        # results = self._check_response_and_get_result(response, None)
        #
        # logger.info({
        #     'status': 'buckets_returned',
        #     'url_endpoint': url_endpoint,
        #     'bucket_count': len(results)
        # })
        # return results

    def get_campaign(self, campaign_id):

        url_endpoint = '/campaignApi/getCampaign'
        headers = self.get_headers_with_auth()
        url_params = {
            'uploadId': campaign_id
        }

        response = requests.get(
            self.base_url + url_endpoint, headers=headers, params=url_params)
        result = self._check_response_and_get_result(response, None)

        logger.info({
            'status': 'buckets_returned',
            'url_endpoint': url_endpoint,
        })
        return result

    def delete_campaigns(self):

        url_endpoint = '/campaignApi/deleteCampaigns'
        

    def get_reports_by_campaign(self, campaign_id):

        url_endpoint = '/reportApi/getReportsByDate'
