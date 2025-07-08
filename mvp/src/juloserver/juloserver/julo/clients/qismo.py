from builtins import range
from builtins import object
import logging
import requests
from .constants import QismoConst
from ..exceptions import JuloException


logger = logging.getLogger(__name__)


class QismoAPIError(JuloException):
    pass


class QismoAPIValidationError(JuloException):
    pass


class JuloQismoClient(object):
    """Client for Qismo API"""
    def __init__(self, base_url, token=None):
        self.base_url = base_url
        self.token = token

    def post_request(self, url, data=None, json=None, **kwargs):
        """Wrapper for requests.post, matching its parameters"""
        try:
            r = requests.post(url, data=data, json=json, **kwargs)
            if not (r.status_code == 200):
                raise QismoAPIError(r.text)
            response = r.json()
        except Exception as e:
            raise QismoAPIError(e)

        return response['data']

    def get_request(self, url):
        """Wrapper for request.get, matching its parameter"""
        try:
            headers = self.get_headers_with_auth()
            r = requests.get(url, headers=headers)
            if not (r.status_code == 200):
                raise QismoAPIError(r.text)
            response = r.json()
        except Exception as e:
            raise QismoAPIError(e)

        return response['data']

    def get_headers_with_auth(self):
        """Helps setting the token in headers"""
        if self.token is None:
            raise QismoAPIValidationError("Token not provided")
        return {
            'Authorization': self.token
        }

    def sign_in(self, username, password):
        url_endpoint = QismoConst.SIGNIN_PATH
        data = {
            "email": username,
            "password": password,
        }
        logger.debug(data)
        result = self.post_request(self.base_url + url_endpoint, data=data)
        token = result['user']['authentication_token']
        self.token = token

        logger.info({
            'status': 'token_received',
            'url_endpoint': url_endpoint,
            'username': username
        })

        return token

    def get_agent_list(self):
        url_endpoint = QismoConst.AGENT_LIST_PATH

        result = self.get_request(self.base_url + url_endpoint)
        agent_list = result['agents']['data']
        first_page = result['agents']['from']
        last_page = result['agents']['last_page']
        page_count = first_page - last_page

        if page_count > 0:
            for page in range(first_page + 1, last_page + 1):
                next_result = self.get_request(
                    self.base_url + url_endpoint + '?page=%s' % (page))
                agent_list += next_result['agents']['data']

        return agent_list

    def assign_agent_to_room(self, agent_id, room_id):
        url_endpoint = QismoConst.ASSIGN_AGGENT_PATH
        headers = self.get_headers_with_auth()

        data = {
            'room_id': room_id,
            'agent_id': agent_id,
        }

        logger.debug({
            'action': 'qismo request assign_agent_to_room',
            'url_endpoint': url_endpoint,
            'data': data
        })

        result = self.post_request(
            self.base_url + url_endpoint, data=data, headers=headers)

        return result
