from builtins import str
from builtins import object
import json
import logging
import requests

from juloserver.julo.exceptions import SimApiError

logger = logging.getLogger(__name__)


class JuloSimClient(object):
    """
        Client For Sims API request
    """
    def __init__(self, username, password, base_url):
        self.username = username
        self.password = password
        self.base_url = base_url

    def send_click2call_data(self, phone_number, name, agent_username, application_id):
        relative_url = '/api/1/julo/call'
        url = '{}{}'.format(self.base_url, relative_url)
        params = {
                 'username': self.username,
                 'password': self.password,
                 'applid': application_id,
                 'tlpn': phone_number,
                 'nama': name,
                 'userid': agent_username
                }

        try:
            response = requests.get(url, params=params, timeout=15)
        except Exception as e:
            raise SimApiError('{} - request params: {}'.format(str(e), json.dumps(params)))

        return response.json()
