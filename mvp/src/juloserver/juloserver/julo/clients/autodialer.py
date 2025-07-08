from builtins import object
import logging
import requests


logger = logging.getLogger(__name__)


class JuloAutodialerClient(object):
    """Client for CRM Click2call (autodialer)"""
    def __init__(self, api_key_click2call, api_key_robodial, base_url, base_url_robodial):
        self.api_key_click2call = api_key_click2call
        self.api_key_robodial = api_key_robodial
        self.base_url = base_url
        self.base_url_robodial = base_url_robodial

    def click_to_call(self, direct_number, user_extension):
        url = self.base_url + '/click2call/julo/'
        url_params = {'key': self.api_key_click2call, 'dn': direct_number, 'extension': user_extension}
        response = requests.get(url, params=url_params)
        return response.content

    def robodial(self, direct_number, skiptrace_id, payment_number, due_number, due_date,
                 product_id, retry_times=3, retry_cooldown=10800, wait_time=120):
        url = self.base_url_robodial + '/voiceblast/julo/'
        direct_number_formatted = direct_number.replace('+62','0')
        url_params = {'key': self.api_key_robodial,
                      'dn': direct_number_formatted,
                      'skiptraceid': skiptrace_id,
                      'number': payment_number,
                      'amount': due_number,
                      'duedate': due_date,
                      'productid': product_id,
                      'retry': retry_times,
                      'retrytime': retry_cooldown,
                      'waittime': wait_time}
        response = requests.get(url, params=url_params)
        return response
