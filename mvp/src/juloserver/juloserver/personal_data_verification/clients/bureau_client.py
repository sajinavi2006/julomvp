import logging
from builtins import object

import requests

from django.apps import apps
from rest_framework.renderers import JSONRenderer

from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import FeatureSetting, CreditScore
from juloserver.personal_data_verification.constants import BureauConstants, FeatureNameConst

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class BureauClient(object):
    """Client SDK for interacting with Bureau"""

    def __init__(self, username, password,
                 application, api_url, service,
                 session_id):
        self.username = username
        self.password = password
        self.api_url = api_url
        self.headers = {'content-type': 'application/json',
                        'accept': 'application/json'}
        self.application = application
        self.request_data = None
        self.service = service
        self.session_id = session_id

    def is_feature_active(self):
        return FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.BUREAU_SERVICES,
            is_active=True).exists()

    def is_application_eligible(self):
        credit_score = CreditScore.objects.filter(application_id=self.application.id).last()
        is_c_score = True if credit_score and credit_score.score in ['C', '--'] else False
        if self.application.is_julo_one() and \
                self.application.status >= ApplicationStatusCodes.FORM_PARTIAL and \
                credit_score and not is_c_score:
            return True
        return False

    def save_api_response(self, response, status):
        data_to_save = {"application_id": self.application.id,
                        "status": str(status),
                        "raw_data": response}
        errors = response.get('errors', response.get('error', None))
        if errors:
            data_to_save['errors'] = str(errors)
        bureau_model = apps.get_model('personal_data_verification',
                                      BureauConstants.SERVICE_MODEL_MAPPING.get(self.service))
        bureau_object = bureau_model.objects.create(**data_to_save)
        return bureau_object, bureau_object.errors

    def has_existing_success_alternate_service_data(self):
        bureau_model = apps.get_model('personal_data_verification',
                                      BureauConstants.SERVICE_MODEL_MAPPING.get(self.service))
        bureau_object = bureau_model.objects.filter(
            application_id=self.application.id, status='200').last()
        return bureau_object

    def log_api_response(self, results):
        method = (
            'juloserver.personal_data_verification.'
            'clients.bureau.client.BureauClient.get_api_response'
        )
        log_dict = {'method': method, 'response': results}
        if results.get('status', None) in [200, '200']:
            logger.info(log_dict)
        else:
            logger.warning(log_dict)

    def get_api_response(self):
        try:
            json_data = JSONRenderer().render(self.request_data).decode('ascii')
            response = requests.post(
                self.api_url, data=json_data, headers=self.headers,
                timeout=10, auth=(self.username, self.password))
            results = response.json()
            if results:
                self.log_api_response(results)
            return results, response.status_code
        except requests.exceptions.Timeout:
            return {}, 'API Timeout'

    def hit_bureau_api(self):
        try:
            if self.service in BureauConstants.sdk_services():
                self.request_data = {'sessionId': self.session_id,
                                     'rawSignals': True
                                     }
            else:
                existing_object = self.has_existing_success_alternate_service_data()
                if existing_object:
                    return existing_object, None
                serializer_class = BureauConstants.SERVICE_SERIALIZER_MAPPING[self.service]
                serializer = serializer_class(self.application)
                self.request_data = serializer.data
            response, status = self.get_api_response()
            bureau_object, errors = self.save_api_response(response, status)
            return bureau_object, errors
        except Exception as exception:
            logger.info(
                {
                    'method': 'hit_bureau_api',
                    'exception': str(exception),
                    'application_id': str(self.application.id),
                }
            )
            sentry_client.captureException()
            return None, str(exception)
