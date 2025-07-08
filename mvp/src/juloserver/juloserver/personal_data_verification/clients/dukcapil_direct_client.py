import json
import logging
from builtins import object
from time import sleep

import requests
from django.core.serializers.json import DjangoJSONEncoder
from requests.adapters import HTTPAdapter
from rest_framework.renderers import JSONRenderer
from urllib3 import Retry

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst
from juloserver.personal_data_verification.constants import (
    DUKCAPIL_KEY_MAPPING,
    DukcapilDirectError,
    DukcapilResponseSourceConst,
    EXTRA_FIELDS,
    VERIFICATION_FIELDS,
)
from juloserver.personal_data_verification.models import (
    DukcapilAPILog,
    DukcapilCallbackInfoAPILog,
    DukcapilResponse,
)
from juloserver.personal_data_verification.serializers import (
    DukcapilOfficialStoreSerializer,
    DukcapilOfficialVerifySerializer,
)
from juloserver.julo.models import FeatureSetting
from juloserver.personal_data_verification.tasks import notify_dukcapil_direct_low_balance

from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object

logger = logging.getLogger(__name__)

sentry_client = get_julo_sentry_client()


class DukcapilDirectClient(object):
    """Client SDK for interacting with Official Dukcapil API's"""

    def __init__(
        self,
        username,
        password,
        api_token,
        organization_id,
        organization_name,
        verify_api_url,
        store_api_url,
        application,
        pass_criteria=None,
    ):
        self.username = username
        self.password = password
        self.api_token = api_token
        self.organization_id = organization_id
        self.organization_name = organization_name
        self.verify_api_url = verify_api_url
        self.store_api_url = store_api_url
        self.headers = {'Content-Type': 'application/json'}
        detokenized_application = detokenize_for_model_object(
            PiiSource.APPLICATION,
            [{'customer_xid': application.customer.customer_xid, 'object': application}],
            force_get_local_data=True,
        )
        self.application = detokenized_application[0]
        self.pass_criteria = pass_criteria
        self.request_data = None
        self.json_request_data = None
        self.response_data = None
        self.validation_data = None
        self.dukcapil_response = None
        self.latency = None
        self.validation_results = []

    def _parse_validation_data(self):
        validation_data_to_save = {}
        for field in VERIFICATION_FIELDS + EXTRA_FIELDS:
            value = self.validation_data.get(field, '').lower()
            if value:
                field_value = True if 'sesuai' in value and 'tidak' not in value else False
                validation_data_to_save[DUKCAPIL_KEY_MAPPING[field]] = field_value
                if field in VERIFICATION_FIELDS:
                    self.validation_results.append(field_value)
        return validation_data_to_save

    def _is_application_valid(self):
        if not self.dukcapil_response:
            return True

        return self.dukcapil_response.is_eligible()

    def save_verify_api_response(self, response, status):
        from django.conf import settings

        data = {
            "application_id": self.application.id,
            "status": str(status),
            "source": DukcapilResponseSourceConst.DIRECT,
        }
        if str(status) == '200' and response:
            content = response.get('content')
            if content and isinstance(content, list):
                self.validation_data = content[0]
            if self.validation_data and 'RESPON' in self.validation_data:
                data['errors'] = self.validation_data.get('RESPONSE_CODE')
                data['message'] = self.validation_data.get('RESPON')
            else:
                if self.validation_data.get('RESPONSE_CODE') == '05':
                    data['errors'] = DukcapilDirectError.EMPTY_QUOTA
                validation_data_to_save = self._parse_validation_data()
                data = {**data, **validation_data_to_save}
        elif str(status) == DukcapilDirectError.API_TIMEOUT:
            data['errors'] = DukcapilDirectError.API_TIMEOUT

        self.dukcapil_response = DukcapilResponse.objects.create(**data)

        if settings.ENVIRONMENT == "prod":
            self.notify_low_quota(response)

        masking_request_data = {
            **self.request_data,
            **{'password': '********'},
        }
        json_request_data = JSONRenderer().render(masking_request_data).decode('ascii')

        DukcapilAPILog.objects.create(
            dukcapil_response_id=self.dukcapil_response.id,
            api_type='POST',
            http_status_code=status,
            request=json_request_data,
            response=str(self.response_data),
            latency=self.latency,
        )
        return self.validation_data

    def notify_low_quota(self, response):
        from juloserver.personal_data_verification.constants import FeatureNameConst as PDVConstant

        dukcapil_setting = FeatureSetting.objects.get_or_none(
            feature_name=PDVConstant.DUKCAPIL_VERIFICATION,
        )
        low_balance_start = 27000
        decrement = 2000
        if dukcapil_setting and dukcapil_setting.parameters.get('low_balance_quota_alert'):
            low_balance_start = dukcapil_setting.parameters.get('low_balance_quota_alert')

        available_thresholds = []
        threshold = low_balance_start
        while True:
            available_thresholds.append(threshold)
            threshold = threshold - decrement
            if threshold < 0:
                break

        if response.get('quotaLimiter') and response.get('quotaLimiter') in available_thresholds:
            notify_dukcapil_direct_low_balance(response.get('quotaLimiter'))

    def get_api_response(self, url):
        self.json_request_data = JSONRenderer().render(self.request_data).decode('ascii')
        max_retry_attempt = 2
        for retry in range(max_retry_attempt):
            # NOTES why verify false
            # Dukcapil is using https://ip.address
            response = requests.post(
                url,
                data=self.json_request_data,
                headers=self.headers,
                timeout=10,
                verify=False,
            )
            if response.status_code in [200]:
                break

            sleep(1)  # 1 second delay

        self.latency = response.elapsed.total_seconds()
        if response:
            self.response_data = response.json()

        return self.response_data, response.status_code

    def send_callback_request(self, method, url, **kwargs):
        logger_data = {
            'module': 'personal_data_verification',
            'method': 'DukcapilDirectClient::send_request',
            'data': {'method': method, 'url': url, **kwargs},
        }
        logger.info({**logger_data, 'message': 'Sending request to Direct Dukcapil Callback API'})

        # Retry if ConnectionError for 3 times with exponential backoff 2 seconds (0, 2, 4)
        retries = Retry(connect=3, backoff_factor=2)
        with requests.session() as session:
            session.mount(url, HTTPAdapter(max_retries=retries))
            response = session.request(method, url, timeout=(10, 30), **kwargs)

        logger.info(
            {
                **logger_data,
                'message': 'Receive response from Direct Dukcapil Callback API',
                'response_status': response.status_code,
                'response': response.text,
                'elapsed_time': response.elapsed.total_seconds(),
            }
        )

        return response

    def hit_dukcapil_official_api(self):
        from juloserver.pii_vault.constants import PiiSource
        from juloserver.partnership.utils import partnership_detokenize_sync_object_model
        from juloserver.julo.product_lines import ProductLineCodes

        try:
            serializer = DukcapilOfficialVerifySerializer(self.application)
            serializer_data = serializer.data

            if (
                self.application.partner
                and self.application.product_line_code == ProductLineCodes.AXIATA_WEB
            ):
                partnership_customer_data = self.application.partnership_customer_data
                customer_xid = self.application.customer.customer_xid
                detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
                    PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                    partnership_customer_data,
                    customer_xid,
                    ['nik'],
                )

                value = detokenize_partnership_customer_data.nik
                if serializer_data.get('NIK'):
                    serializer_data['NIK'] = value

            self.request_data = {
                **serializer_data,
                **{'user_id': self.username, 'password': self.password},
            }
            response, status = self.get_api_response(self.verify_api_url)
            self.save_verify_api_response(response, status)
            is_application_valid = self._is_application_valid()
            return is_application_valid
        except requests.exceptions.RequestException as exception:
            logger.error(
                {
                    'method': 'hit_dukcapil_official_api',
                    'message': 'Request Exception',
                    'exc_type': type(exception),
                    'exc_message': str(exception),
                    'application_id': str(self.application.id),
                }
            )
            sentry_client.captureException()
            if exception.response is not None:
                self.save_verify_api_response({}, exception.response.status_code)
                return True

            if isinstance(exception, requests.exceptions.Timeout):
                self.save_verify_api_response({}, DukcapilDirectError.API_TIMEOUT)
                return False

            return True
        except Exception as exception:
            # TODO: Need to move the exception handler to higher level function.
            logger.exception(
                {
                    'method': 'hit_dukcapil_official_api',
                    'exc_type': type(exception),
                    'exc_message': str(exception),
                    'application_id': str(self.application.id),
                }
            )
            sentry_client.captureException()
            return True

    def mock_hit_dukcapil_official_api(self):
        import time

        self.json_request_data = JSONRenderer().render(self.request_data).decode('ascii')

        dukcapil_mock_feature = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.DUKCAPIL_MOCK_RESPONSE_SET,
        )
        time.sleep(dukcapil_mock_feature.parameters['latency'] / 1000)

        status = 200
        response_value = dukcapil_mock_feature.parameters['response_value']

        data = {"application_id": self.application.id, "status": str(status), "source": 'Dukcapil'}
        if str(status) == '200' and response_value['response']:
            content = response_value['response']
            data = {**data, **content}

        self.dukcapil_response = DukcapilResponse.objects.create(**data)
        DukcapilAPILog.objects.create(
            dukcapil_response=self.dukcapil_response,
            api_type='POST',
            http_status_code=status,
            request=self.json_request_data,
            response=str(response_value['log']),
            latency=dukcapil_mock_feature.parameters['latency'] / 1000,
        )

        is_application_valid = self._is_application_valid()
        return is_application_valid

    def hit_dukcapil_official_store_api(self):
        serializer = DukcapilOfficialStoreSerializer([self.application], many=True)
        headers = {'Authorization': 'Bearer {}'.format(self.api_token)}
        form_data = [
            {
                'id_lembaga': self.organization_id,
                'nama_lembaga': self.organization_name,
                'data': serializer.data,
            }
        ]

        status_code = None
        response_data = None
        latency = None
        try:
            response = self.send_callback_request(
                'POST', self.store_api_url, headers=headers, json=form_data
            )
            response_data = response.json()
            response_message = response_data.get('message')
            latency = response.elapsed.total_seconds()
            status_code = response.status_code
        except Exception as exception:
            response_data = '{}: {}'.format(type(exception).__name__, str(exception))
            logger.warning(
                {
                    'module': 'juloserver.personal_data_verification.clients',
                    'method': 'hit_dukcapil_official_store_api',
                    'exception': response_data,
                    'application_id': str(self.application.id),
                }
            )
            return False, None
        finally:
            # Save the log even if there is exception
            DukcapilCallbackInfoAPILog.objects.create(
                application_id=self.application.id,
                api_type='POST',
                request=json.dumps(form_data, cls=DjangoJSONEncoder),
                http_status_code=status_code,
                response=str(response_data),
                latency=latency,
            )

        return response_message == 'Success', response_message

    def mock_hit_dukcapil_official_store_api(self):
        from juloserver.julo.constants import FeatureNameConst

        serializer = DukcapilOfficialStoreSerializer([self.application], many=True)
        form_data = [
            {
                'id_lembaga': self.organization_id,
                'nama_lembaga': self.organization_name,
                'data': serializer.data,
            }
        ]

        dukcapil_mock_feature = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.DUKCAPIL_CALLBACK_MOCK_RESPONSE_SET,
        )
        if not dukcapil_mock_feature:
            return False, None

        response_status = dukcapil_mock_feature.parameters['response_status']
        response_data = dukcapil_mock_feature.parameters['response']
        response_message = dukcapil_mock_feature.parameters['response_message']
        latency = dukcapil_mock_feature.parameters['latency'] / 1000

        # Save the log even if there is exception
        DukcapilCallbackInfoAPILog.objects.create(
            application_id=self.application.id,
            api_type='POST',
            request=json.dumps(form_data, cls=DjangoJSONEncoder),
            http_status_code=response_status,
            response=str(response_data),
            latency=latency,
        )

        return response_message == 'Success', response_message
