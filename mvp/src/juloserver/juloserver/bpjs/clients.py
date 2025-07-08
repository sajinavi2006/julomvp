import json
import logging
from builtins import object

import requests
import urllib3.exceptions
from django.conf import settings
from requests.adapters import HTTPAdapter, MaxRetryError, Retry, RetryError
from requests.auth import HTTPBasicAuth
from rest_framework.status import HTTP_200_OK, HTTP_201_CREATED

from juloserver.bpjs.constants import BrickCodes, BrickSetupClient
from juloserver.bpjs.exceptions import BrickBpjsException
from juloserver.bpjs.models import BpjsAPILog
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import FeatureSetting

logger = logging.getLogger(__name__)


class TongdunClient(object):
    def __init__(
        self,
        partner_code,
        partner_key,
        app_name_android,
        app_name_web,
        box_token_android,
        box_token_web,
        login_base_url,
        interface_api_base_url,
    ):
        self.partner_code = partner_code
        self.partner_key = partner_key
        self.app_name_android = app_name_android
        self.app_name_web = app_name_web
        self.box_token_android = box_token_android
        self.box_token_web = box_token_web
        self.partner_code = partner_code
        self.partner_key = partner_key
        self.app_name_android = app_name_android
        self.login_base_url = login_base_url
        self.interface_api_base_url = interface_api_base_url

    def get_bpjs_data(self, task_id, customer_id, application_id):
        params = {"task_id": task_id}
        url = self.interface_api_base_url + "?partner_code={}&partner_key={}".format(
            self.partner_code, self.partner_key
        )
        logger.info(
            {
                "action": "get_bpjs_data",
                "interface_api_base_url": url,
                "task_id": task_id,
            }
        )
        result = requests.post(url, json=params)
        if result.status_code not in [HTTP_200_OK]:
            err_msg = (
                "failed to get bpjs details of customer from tongdun "
                "for customer={}, application={}:{} ".format(
                    customer_id, application_id, result.text
                )
            )

            raise JuloException(err_msg)

        return result


class AnaserverClient(object):
    def __init__(self, anaserver_token, anaserver_base_url):
        self.anaserver_token = anaserver_token
        self.anaserver_base_url = anaserver_base_url

    def send_bpjs_data(self, bpjs_data, customer_id, application_id):
        headers = {"Authorization": "Token %s" % self.anaserver_token}
        data = {
            "bpjs_details": json.dumps(bpjs_data.json()),
            "customer_id": customer_id,
            "application_id": application_id,
        }
        logger.info(
            {
                "action": "send_bpjs_data",
                "url": self.anaserver_base_url + "/api/bpjs/v1/create/",
                "customer_id": customer_id,
                "application_id": application_id,
            }
        )
        ana_result = requests.post(
            self.anaserver_base_url + "/api/bpjs/v1/create/", data=data, headers=headers
        )

        if ana_result.status_code not in [HTTP_200_OK, HTTP_201_CREATED]:
            err_msg = (
                "failed to pass bpjs details of customer to anaserver "
                "for customer={}, application={}:{} ".format(
                    customer_id, application_id, ana_result.text
                )
            )
            raise JuloException(err_msg)

        return ana_result

    def get_bpjs_data(self, application_id):
        headers = {"Authorization": "Token %s" % self.anaserver_token}
        data = {"application_id": application_id}
        url = self.anaserver_base_url + "/api/bpjs/v1/get-details/"
        logger.info({"action": "get_bpjs_data", "url": url, "application_id": application_id})
        response = requests.post(url, data=data, headers=headers)

        if response.status_code not in [HTTP_200_OK]:
            error_message = (
                "Failed to get BPJS details for "
                "application: {} status: {} "
                "error: {}".format(application_id, response.status_code, response.text)
            )
            raise JuloException(error_message)

        return response.json()


class BrickClient(object):
    """
    BPJS Brick Client for request to the endpoint Brick.
    """

    def __init__(self, brick_client_id, brick_client_secret, brick_base_url):
        self.client_id = brick_client_id
        self.client_secret = brick_client_secret
        self.base_url = brick_base_url
        self.max_retry = BrickSetupClient.BRICK_MAX_RETRY_PROCESS
        self.scraper = None
        self.token = None

    def get_auth_token(self):
        url = self.base_url + "/v1/auth/token"
        response = requests.get(url, auth=HTTPBasicAuth(self.client_id, self.client_secret))

        message = None
        if response.status_code != 200:
            message = "[Response provider]: " + str(response.json())
            logger.error(
                {
                    "message": message,
                    "class": str(self.__class__.__name__),
                    "path": "[Provider Brick]: /v1/auth/token",
                    "action": "Get Public Access Token Brick",
                }
            )

        self.store_to_log_table(response=response, error_message=message)
        return response

    def _call_income_api(self, path, user_access_token):
        # set header request
        header = {"Authorization": "Bearer " + user_access_token}
        # path url
        url = self.base_url + path

        request_try = requests.Session()
        retries = Retry(
            total=self.max_retry,
            backoff_factor=0.1,
            status_forcelist=[400, 500, 401, 503, 404],
            method_whitelist=["GET"],
            raise_on_status=False,
        )
        request_try.mount("https://", HTTPAdapter(max_retries=retries))

        try:
            response = request_try.get(url, headers=header)
            if response.status_code is not BrickCodes.BRICK_GET_INFO_SUCCESS_CODE:
                error_message = "[Provider status code: {}] {}".format(
                    response.status_code, response.json()["message"]
                )
                logger.error(
                    {
                        "message": "[Response provider]: " + str(response.json()),
                        "class": str(self.__class__.__name__),
                        "path": "[Provider Brick]: " + path,
                        "action": "Get Information User to Brick Server",
                    }
                )

                self.store_to_log_table(error_message=error_message, response=response)
                raise BrickBpjsException(error_message)

            if "data" not in response.json():
                error_message = "Not found key [data] in response."
                self.store_to_log_table(error_message=error_message, response=response)
                raise BrickBpjsException(error_message)

            self.store_to_log_table(response=response)
            return response
        except RetryError as error:
            logger.error(
                {
                    "message": "Retry Error: " + str(error),
                    "class": str(self.__class__.__name__),
                    "path": "[Provider Brick]: " + path,
                    "action": "Retry Mechanism",
                }
            )
            raise BrickBpjsException("Retry Error: {}".format(str(error)))
        except MaxRetryError as error:
            logger.error(
                {
                    "message": "Retry Error: " + str(error),
                    "class": str(self.__class__.__name__),
                    "path": "[Provider Brick]: " + path,
                    "action": "MaxRetry Mechanism",
                }
            )
            raise BrickBpjsException("Max Retry Error: {}".format(str(error)))

    def store_to_log_table(self, response=None, error_message=None):
        headers = None
        body = None
        url = None
        if hasattr(response.request, "headers"):
            headers = response.request.headers
        if hasattr(response.request, "body"):
            body = response.request.body
        if hasattr(response.request, "url"):
            url = response.request.url
        self.scraper.log_api_call(
            **{
                "api_type": 'GET',
                "http_status_code": str(response.status_code),
                "query_params": str(url),
                "request": "header: " + str(headers) + " body: " + str(body),
                "response": str(response.json()),
                "error_message": error_message,
            }
        )

    def get_income_employment(self):
        """
        Client request for get brick data employment or data company
        """

        path = "/v1/income/employment"
        # Call setup brick employment data
        response = self._call_income_api(path, self.token)
        if response.status_code is not BrickCodes.BRICK_GET_INFO_SUCCESS_CODE:
            logger.error(
                {
                    "message": "Get Information Brick [status_code] " + str(response.status_code),
                    "class": str(self.__class__.__name__),
                    "path": "[Provider Brick]: " + path,
                    "action": "Get Information Company",
                }
            )
        return response

    def get_income_profile(self):
        """
        Client request for get data General Info (Profile data) from Brick Server by
        user_access_token
        """

        path = "/v1/income/general"
        # Call setup brick employment data
        response = self._call_income_api(path, self.token)
        if response.status_code is not BrickCodes.BRICK_GET_INFO_SUCCESS_CODE:
            logger.error(
                {
                    "message": "Get Information Brick [status_code] " + str(response.status_code),
                    "class": str(self.__class__.__name__),
                    "path": "[Provider Brick]: " + path,
                    "action": "Get Information Profile",
                }
            )
        return response

    def get_income_salary(self):
        """
        Client request for get data salary or data payment from Brick Server by user_access_token
        """

        path = "/v1/income/salary"
        # Call setup brick employment data
        response = self._call_income_api(path, self.token)
        if response.status_code is not BrickCodes.BRICK_GET_INFO_SUCCESS_CODE:
            logger.error(
                {
                    "message": "Get Information Brick [status_code] " + str(response.status_code),
                    "class": str(self.__class__.__name__),
                    "path": "[Provider Brick]: " + path,
                    "action": "Get Information Payment",
                }
            )
        return response

    def set_scraper_instance(self, scraper):
        self.scraper = scraper
        return self

    def set_user_access_token(self, token):
        self.token = token
        return self

    set_token = set_user_access_token


class BPJSDirectClient(object):
    ERROR_KEYS = {
        "string": [
            "Kuota harian Anda telah habis.",  # zero_quota
            "Masa berlaku PKS belum efektif atau telah berakhir.",  # pks_ended
        ],
        "contains": [
            "non aktif",  # inactive
        ],
    }

    EMAIL_RECIPIENTS_WHEN_ERROR_NON_PROD = [
        "fathur.rohman@julofinance.com",
        "faulince.huang@julofinance.com",
    ]

    EMAIL_RECIPIENTS_WHEN_ERROR = [
        "errandyno.rumengan@julofinance.com",
        "alvin.tri@julofinance.com",
        "rizky.djong@julofinance.com",
        "ciptoning.hestomo@julofinance.com",
        "faulince.huang@julofinance.com",
        "kurnia.putranti@bpjsketenagakerjaan.go.id",
        "aldhi.aditya@bpjsketenagakerjaan.go.id",
        "nanda.juliansyah@bpjsketenagakerjaan.go.id",
        "rizky.noviandri@bpjsketenagakerjaan.go.id",
        "chandra.kirana@bpjsketenagakerjaan.go.id",
    ]

    def __init__(self, base_url):
        self.base_url = base_url

    @classmethod
    def get_email_recipients_when_error(cls):
        if settings.ENVIRONMENT != "prod":
            return cls.EMAIL_RECIPIENTS_WHEN_ERROR_NON_PROD
        return cls.EMAIL_RECIPIENTS_WHEN_ERROR

    def post(self, path, headers, data):
        url = '{}{}'.format(self.base_url, path)

        response = requests.post(url, json=data, headers=headers)

        return response

    def retrieve_bpjs_direct_data(self, token, req_id, data, _application_id, _customer_id):
        headers = {
            "Authorization": "Bearer " + token,
            "X-Req-Id": req_id,
            "Content-Type": "application/json",
        }

        path = "api/ClrTKByFieldScore"

        response = self.post(path, headers, data)

        message = None
        if response.status_code != 200:
            message = "[Response provider]: " + str(response.json())

        self.store_to_log_table(
            api_type="POST",
            response=response,
            error_message=message,
            application_id=_application_id,
            customer_id=_customer_id,
        )

        self.send_email_when_error(response)

        return response

    def mock_retrieve_bpjs_direct_data(self, token, req_id, data, _application_id, _customer_id):
        import time

        headers = {
            "Authorization": "Bearer " + token,
            "X-Req-Id": req_id,
            "Content-Type": "application/json",
        }

        path = "api/ClrTKByFieldScore"

        bpjs_mock_feature = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.BPJS_MOCK_RESPONSE_SET,
        )
        exception_raised = bpjs_mock_feature.parameters['exception']

        if exception_raised:
            if exception_raised == 'JSONDecodeError':
                raise json.decoder.JSONDecodeError("Mock JSONDecodeError", "{}", 0)
            elif exception_raised == 'ReadTimeout':
                raise urllib3.exceptions.ReadTimeoutError(None, None, 'Mock ReadTimeoutError')

        time.sleep(bpjs_mock_feature.parameters['latency'] / 1000)
        response = bpjs_mock_feature.parameters['response_value']

        message = "Mock Data"

        data = {
            "api_type": "POST",
            "http_status_code": 200,
            "query_params": path,
            "request": "header: " + str(headers) + " body: " + str(data),
            "response": str(response),
            "error_message": message,
        }

        data["application_id"] = _application_id
        data["customer_id"] = _customer_id
        data["service_provider"] = "bpjs_direct"
        BpjsAPILog.objects.create(**data)

        return response

    def send_email_when_error(self, response):
        from juloserver.julo.clients import get_julo_email_client

        email_client = get_julo_email_client()

        has_error = False
        message = None
        error_message = None

        response = response.json()
        try:
            message = response["msg"]
        except KeyError:
            has_error = True
            error_message = "Null value"

        if message in self.ERROR_KEYS["string"]:
            has_error = True
            error_message = message

        for contain in self.ERROR_KEYS["contains"]:
            if not message:
                continue

            if contain in message:
                has_error = True
                error_message = message

        if not has_error:
            return

        content = (
            "<p>Dear stakeholders, </p>"
            "<p>BPJS direct receive the following error: <strong>{}</strong>.<br/>"
            "Please follow up error above!</p>"
            "<p>Thank you.</p>"
        ).format(error_message)

        subject_env = (
            " ({} env)".format(settings.ENVIRONMENT) if settings.ENVIRONMENT != "prod" else ""
        )

        email_client.send_email(
            subject="[Error] BPJS Direct {}".format(subject_env),
            content=content,
            email_to=",".join(self.get_email_recipients_when_error()),
        )

    def store_to_log_table(
        self,
        api_type=None,
        response=None,
        error_message=None,
        application_id=None,
        customer_id=None,
    ):
        from juloserver.bpjs.models import BpjsAPILog

        headers = None
        body = None
        url = None
        if hasattr(response.request, "headers"):
            headers = response.request.headers
        if hasattr(response.request, "body"):
            body = response.request.body
        if hasattr(response.request, "url"):
            url = response.request.url
        data = {
            "api_type": api_type,
            "http_status_code": str(response.status_code),
            "query_params": str(url),
            "request": "header: " + str(headers) + " body: " + str(body),
            "response": str(response.json()),
            "error_message": error_message,
        }

        data["application_id"] = application_id
        data["customer_id"] = customer_id
        data["service_provider"] = "bpjs_direct"
        BpjsAPILog.objects.create(**data)
