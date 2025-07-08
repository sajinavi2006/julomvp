from builtins import object
import logging
import requests

from ..exceptions import JuloException


logger = logging.getLogger(__name__)


class PrimoApiError(JuloException):
    pass


class JuloPrimoClient(object):
    """Client SDK for interacting with Primo Dialler API"""

    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        logger.info(self.base_url)

    def upload_leads(self, leads):

        url = self.base_url + '/api/add_leads.php'
        url_params = {'user': self.username, 'pass': self.password}
        response = requests.post(url, params=url_params, json=leads)

        if response.status_code != requests.codes.ok:
            logger.error({
                'status_code': response.status_code,
                'text': response.text
            })
            raise PrimoApiError(
                "%s returned status_code=%s" % (url, response.status_code))

        results = response.json()
        for result in results:
            if not result['status']:
                logger.error({
                    'status': result['status'],
                    'message': result['message']
                })
                raise PrimoApiError(result['message'])

        return response.json()

    def delete_lead(self, lead_id):

        url = self.base_url + '/adminpanel/api.php'
        url_params = {
            'user': self.username,
            'pass': self.password,
            'source': 'test',
            'function': 'update_lead',
            'lead_id': lead_id,
            'delete_lead': 'Y'
        }
        response = requests.get(url, params=url_params)

        if response.status_code != requests.codes.ok:
            logger.error({
                'status_code': response.status_code,
                'text': response.text
            })
            raise PrimoApiError(
                "%s returned status_code=%s" % (url, response.status_code))

        if 'SUCCESS' not in response.text:
            logger.error({
                'action': 'delete_lead',
                'message': response.text
            })
            raise PrimoApiError(response.text)

    def delete_list(self, list_id):

        url = self.base_url + '/api/delete.php'
        url_params = {'user': self.username, 'pass': self.password}
        data = [{'list_id': list_id}]
        response = requests.post(url, params=url_params, json=data)

        if response.status_code != requests.codes.ok:
            logger.error({
                'status_code': response.status_code,
                'text': response.text
            })
            raise PrimoApiError(
                "%s returned status_code=%s" % (url, response.status_code))

        results = response.json()
        for result in results:
            if not result['status']:
                logger.error({
                    'status': result['status'],
                    'message': result['message']
                })
                raise PrimoApiError(result['message'])

        return response.json()

    ############################################################################

    def upload_primo_data(self, data):
        url = self.base_url + '/api/add_leads.php'
        url_params = {'user': self.username,
                      'pass': self.password}
        response = requests.post(url, params=url_params, json=data)
        if response.status_code != requests.codes.ok:
            logger.error({
                'status_code': response.status_code,
                'text': response.text
            })
            raise PrimoApiError(response.text)
        logger.info(response.json())
        return response

    def delete_primo_list_data(self, list_id):
        url = self.base_url + '/api/delete.php'
        url_params = {'user': self.username,
                      'pass': self.password}
        data = [{'list_id': list_id}]
        response = requests.post(url, params=url_params, json=data)
        return response

    def delete_primo_lead_data(self, lead_id):
        url = self.base_url + '/adminpanel/api.php'
        url_params = {'user': self.username,
                      'pass': self.password,
                      'source': 'test',
                      'function': 'update_lead',
                      'lead_id': lead_id,
                      'delete_lead': 'Y'}

        response = requests.get(url, params=url_params)
        return response


def get_primo_fake_lead():
    data = {
        'function': 'add_lead',
        'phone_number': '08159147752',
        'alt_phone': '08159147752',
        'email': 'hans@julofinance.com',
        'custom_fields': 'Y',
        'list_id': 1002,
        'comments': 'NoComments',
        'Due_Date': '26-08-2018',
        'Due_Amount': 'Rp 1,000,000',
        'Disbursement_Date': None,
        'genderiden': 'Pria',
        'Loan_Purpose_Desc': 'For starting a business',
        'Application_ID': '2000000000',
        'Fullname': "Hans Sebastian",
        'Loan_Purpose': "Business Capital",
        'Application_Status': 180,
        'CRM_Link': 'https://www.google.com',
        'Loan_Amount': 'Rp 4,000,000',
        'Loan_Duration': 6,
        'Company_Name': "Sketcher"
    }
    return data
