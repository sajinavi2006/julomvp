import logging
from builtins import object

import requests
from rest_framework.renderers import JSONRenderer

from juloserver.personal_data_verification.models import (
    DukcapilAsliriBalance,
    DukcapilResponse,
)
from juloserver.personal_data_verification.serializers import (
    DukcapilApplicationSerializer,
)

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = logging.getLogger(__name__)


class DukcapilClient(object):
    """Client SDK for interacting with Dukcapil with AsliRI"""

    def __init__(self, api_key, api_url, application, pass_criteria=None):
        self.api_key = api_key
        self.api_url = api_url
        self.headers = {'Content-Type': 'application/json', 'token': self.api_key}
        self.application = application
        if application:
            detokenized_application = detokenize_for_model_object(
                PiiSource.APPLICATION,
                [{'customer_xid': application.customer.customer_xid, 'object': application}],
                force_get_local_data=True,
            )
            self.application = detokenized_application[0]
        self.pass_criteria = pass_criteria
        self.request_data = None

    def is_application_valid(self, validation_data, errors=None):
        from juloserver.personal_data_verification.constants import (
            DUKCAPIL_DATA_NOT_FOUND_ERRORS,
        )

        if not validation_data:
            if (
                errors
                and 'message' in errors
                and errors['message'] in DUKCAPIL_DATA_NOT_FOUND_ERRORS
            ):
                return False
            return True
        validation_fields = ['name', 'birthdate', 'birthplace']
        results = [validation_data[field] for field in validation_fields]
        counter = 0
        for result in results:
            if result:
                counter = +1

        if len(results) == len(validation_fields) and counter >= self.pass_criteria:
            return True
        else:
            return False

    def save_api_response(self, response, status):
        data = {
            "application_id": self.application.id,
            "status": str(status),
            "source": 'AsliRI',
            "trx_id": response.get('trx_id', self.request_data.get('trx_id')),
        }
        validation_data = response.get('data')
        if status == 200:
            data["errors"] = response.get('errors')
            data["ref_id"] = response.get('ref_id')
            validation_data["birthplace"] = validation_data["pob"]
            validation_data["birthdate"] = validation_data["dob"]
            validation_data.pop('pob')
            validation_data.pop('dob')
            data = {**data, **validation_data} if validation_data else data
        else:
            data["errors"] = response.get('error')
            data["message"] = response.get('message')
        dukcapil_response = DukcapilResponse.objects.create(**data)
        return validation_data, dukcapil_response.errors

    def log_api_response(self, results):
        method = (
            'juloserver.personal_data_verification.'
            'clients.dukcapil_client.DukcapilClient.get_api_response'
        )
        log_dict = {'method': method, 'response': results}
        if results.get('status', None) in [200, '200']:
            logger.info(log_dict)
        else:
            logger.warning(log_dict)

    def get_api_response(self, endpoint):
        try:
            json_data = JSONRenderer().render(self.request_data).decode('ascii')
            response = requests.post(
                self.api_url + endpoint, data=json_data, headers=self.headers, timeout=10
            )
            results = response.json()
            if results:
                self.log_api_response(results)
            return results, results.get('status')
        except requests.exceptions.Timeout:
            return {}, 'API Timeout'

    def hit_dukcapil_api(self):
        try:
            serializer = DukcapilApplicationSerializer(
                self.application, context={'application': self.application}
            )
            self.request_data = serializer.data
            response, status = self.get_api_response(endpoint='verify_biometric_basic')
            validation_data, errors = self.save_api_response(response, status)
            is_application_valid = self.is_application_valid(validation_data, errors)

            logger.info(
                {
                    'method': 'hit_dukcapil_api',
                    'application_id': str(self.application.id),
                    'is_application_valid': is_application_valid,
                }
            )

            return is_application_valid
        except Exception as exception:
            logger.info(
                {
                    'method': 'hit_dukcapil_api',
                    'exception': str(exception),
                    'application_id': str(self.application.id),
                }
            )
            return True

    def get_dukcapil_remaining_balance(self, parameters):
        try:
            response = requests.get(
                self.api_url + 'remaining_access', headers=self.headers, timeout=10
            )
            results = response.json()
            product_balances = []
            low_balance_products = []
            default_threshold = parameters.get('default_threshold')
            if results.get('status') == 200:
                data = results.get('data', None)
                if data and isinstance(data, list):
                    for product in data:
                        url = product.get('url').replace('/', '')
                        remaining_balance = product.get('remainingAccess')
                        balance_threshold = parameters.get(url, default_threshold)
                        product_data = {'url': url, 'remaining_balance': remaining_balance}
                        product_balances.append(DukcapilAsliriBalance(**product_data))
                        if int(remaining_balance) < int(balance_threshold):
                            low_balance_products.append(product_data)
                    if product_balances:
                        DukcapilAsliriBalance.objects.bulk_create(product_balances)
            else:
                DukcapilAsliriBalance.objects.create(
                    status=results.get('status'),
                    error=results.get('error'),
                    message=results.get('message'),
                )
            return product_balances, low_balance_products
        except Exception as e:
            logger.info({'method': 'get_dukcapil_remaining_balance', 'exception': str(e)})
            DukcapilAsliriBalance.objects.create(error=str(e))
            return None, None
