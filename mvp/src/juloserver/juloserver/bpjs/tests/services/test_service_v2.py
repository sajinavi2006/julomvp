from unittest.mock import Mock, patch

import pytest
from django.test import TestCase
from requests.models import Response

from juloserver.bpjs import get_brick_client
from juloserver.bpjs.models import BpjsAPILog
from juloserver.bpjs.services.bpjs import Bpjs
from juloserver.bpjs.services.providers import Brick
from juloserver.bpjs.tests.factories import (
    BpjsUserAccessFactory,
    SdBpjsCompanyScrapeFactory,
    SdBpjsPaymentScrapeFactory,
    SdBpjsProfileScrapeFactory,
)
from juloserver.julo.models import Application
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    WorkflowFactory,
)

requests = Mock()


class TestBrickService(TestCase):
    def setUp(self):

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.user_access_token = "123131321321312313"

        self.bpjs = Bpjs()
        self.bpjs.provider = self.bpjs.PROVIDER_BRICK

        self.brick = Brick(self.application)

    @patch("juloserver.bpjs.clients.BrickClient.get_income_salary")
    @patch("juloserver.bpjs.clients.BrickClient.get_income_employment")
    @patch("juloserver.bpjs.clients.BrickClient.get_income_profile")
    def test_success_save_all_data(self, mock_get, mock_get2, mock_get3):
        """
        Success scenario save all data with correct application id
        """

        response = Response()
        response.status_code = 200
        response.url = "/test/v1/income/general"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = (
            b'{"status": 200,"message": "OK","data": '
            b'{"name": "Pasek Sujana","ktpNumber": "039348","bpjsCardNumber": "019238", '
            b'"npwpNumber": null,"dob": "19-04-1986", "phoneNumber": "+6285334207735",'
            b'"address": "Jl. Bawal No. 341, Tegal 35786, JaBar",'
            b'"gender": "LAKI-LAKI",'
            b'"totalBalance": "4556700",'
            b'"bpjsCards": [{"number": "019238", "balance": "4556700"}],'
            b'"type": "bpjs-tk","institutionId": 14}}'
        )

        mock_get.return_value = response
        result = get_brick_client(self.user_access_token).get_income_profile()

        response2 = Response()
        response2.status_code = 200
        response2.url = "/test/v1/income/employment"
        response2.body = None
        response2.headers = {"Content-Type": "application/json"}
        response2._content = (
            b'{"status": 200,"message": "OK",'
            b'"data": [{"latestSalary":"10000000","companyName": "PT XYZ",'
            b'"monthName": "01-08-2021","salary": "13400000", "latestPaymentDate": "09-01-2020",'
            b'"workingMonth": "13",  "status": "Aktif","bpjsCardNumber": "019238","type": "bpjs-tk","institutionId": 14},'
            b'{"latestSalary":"13400000", "companyName": "PT. XYZ","monthName": "01-07-2021","salary":"13400000",'
            b'"latestPaymentDate": "09-01-2020","workingMonth": "7",  "status": "Aktif", '
            b'"bpjsCardNumber": "019238","type": "bpjs-tk","institutionId": 14}]}'
        )

        mock_get2.return_value = response2
        result2 = get_brick_client(self.user_access_token).get_income_employment()

        response3 = Response()
        response3.status_code = 200
        response3.url = "/test/v1/income/salary"
        response3.body = None
        response3.headers = {"Content-Type": "application/json"}
        response3._content = (
            b'{"status":200,"message":"OK","data":'
            b'[{"companyName":"PT. XYZ","monthName":"01-08-2021",'
            b'"salary":"13400000",'
            b'"bpjsCardNumber":"019238","type":"bpjs-tk","institutionId":14}]}'
        )
        mock_get3.return_value = response3

        result3 = get_brick_client(self.user_access_token).get_income_salary()
        result_saved = self.bpjs.with_application(self.application).store_user_information(
            self.user_access_token
        )

        assert mock_get.called
        assert mock_get2.called
        assert mock_get3.called
        self.assertEqual(True, result_saved)

    @patch("juloserver.bpjs.clients.BrickClient.get_income_salary")
    @patch("juloserver.bpjs.clients.BrickClient.get_income_employment")
    @patch("juloserver.bpjs.clients.BrickClient.get_income_profile")
    def test_success_save_with_profile_none(self, mock_get, mock_get2, mock_get3):
        """
        Success scenario save all data with correct application id
        """

        response = Response()
        response.status_code = 200
        response.url = "/test/v1/income/general"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = b'{"status": 200,"message": "OK","data": null}'

        mock_get.return_value = response
        result = get_brick_client(self.user_access_token).get_income_profile()

        response2 = Response()
        response2.status_code = 200
        response2.url = "/test/v1/income/employment"
        response2.body = None
        response2.headers = {"Content-Type": "application/json"}
        response2._content = (
            b'{"status": 200,"message": "OK",'
            b'"data": [{"latestSalary":"10000000","companyName": "PT XYZ",'
            b'"monthName": "01-08-2021","salary": "13400000", "latestPaymentDate": "09-01-2020",'
            b'"workingMonth": "13",  "status": "Aktif","bpjsCardNumber": "019238","type": "bpjs-tk","institutionId": 14},'
            b'{"latestSalary":"13400000", "companyName": "PT. XYZ","monthName": "01-07-2021","salary":"13400000",'
            b'"latestPaymentDate": "09-01-2020","workingMonth": "7",  "status": "Aktif", '
            b'"bpjsCardNumber": "019238","type": "bpjs-tk","institutionId": 14}]}'
        )

        mock_get2.return_value = response2
        result2 = get_brick_client(self.user_access_token).get_income_employment()

        response3 = Response()
        response3.status_code = 200
        response3.url = "/test/v1/income/salary"
        response3.body = None
        response3.headers = {"Content-Type": "application/json"}
        response3._content = (
            b'{"status":200,"message":"OK","data":'
            b'[{"companyName":"PT. XYZ","monthName":"01-08-2021",'
            b'"salary":"13400000",'
            b'"bpjsCardNumber":"019238","type":"bpjs-tk","institutionId":14}]}'
        )
        mock_get3.return_value = response3

        result3 = get_brick_client(self.user_access_token).get_income_salary()
        result_saved = self.bpjs.with_application(self.application).store_user_information(
            self.user_access_token
        )

        assert mock_get.called
        assert mock_get2.called
        assert mock_get3.called
        self.assertEqual(True, result_saved)

    @patch("juloserver.bpjs.clients.BrickClient.get_income_salary")
    @patch("juloserver.bpjs.clients.BrickClient.get_income_employment")
    @patch("juloserver.bpjs.clients.BrickClient.get_income_profile")
    def test_success_save_with_profile_empty(self, mock_get, mock_get2, mock_get3):
        """
        Success scenario save all data with correct application id
        """

        response = Response()
        response.status_code = 200
        response.url = "/test/v1/income/general"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = b'{"status": 200,"message": "OK","data": ""}'

        mock_get.return_value = response
        result = get_brick_client(self.user_access_token).get_income_profile()

        response2 = Response()
        response2.status_code = 200
        response2.url = "/test/v1/income/employment"
        response2.body = None
        response2.headers = {"Content-Type": "application/json"}
        response2._content = (
            b'{"status": 200,"message": "OK",'
            b'"data": [{"latestSalary":"10000000","companyName": "PT XYZ",'
            b'"monthName": "01-08-2021","salary": "13400000", "latestPaymentDate": "09-01-2020",'
            b'"workingMonth": "13",  "status": "Aktif","bpjsCardNumber": "019238","type": "bpjs-tk","institutionId": 14},'
            b'{"latestSalary":"13400000", "companyName": "PT. XYZ","monthName": "01-07-2021","salary":"13400000",'
            b'"latestPaymentDate": "09-01-2020","workingMonth": "7",  "status": "Aktif", '
            b'"bpjsCardNumber": "019238","type": "bpjs-tk","institutionId": 14}]}'
        )

        mock_get2.return_value = response2
        result2 = get_brick_client(self.user_access_token).get_income_employment()

        response3 = Response()
        response3.status_code = 200
        response3.url = "/test/v1/income/salary"
        response3.body = None
        response3.headers = {"Content-Type": "application/json"}
        response3._content = (
            b'{"status":200,"message":"OK","data":'
            b'[{"companyName":"PT. XYZ","monthName":"01-08-2021",'
            b'"salary":"13400000",'
            b'"bpjsCardNumber":"019238","type":"bpjs-tk","institutionId":14}]}'
        )
        mock_get3.return_value = response3

        result3 = get_brick_client(self.user_access_token).get_income_salary()
        result_saved = self.bpjs.with_application(self.application).store_user_information(
            self.user_access_token
        )

        assert mock_get.called
        assert mock_get2.called
        assert mock_get3.called
        self.assertEqual(True, result_saved)

    @patch("juloserver.bpjs.clients.BrickClient._call_income_api")
    def test_save_data_profile_incomplete_key(self, mock_get):
        """
        Scenario for response incomplete for key "data"
        """
        response = Response()
        response.status_code = 200
        response._content = b'{"status": "success"}'
        mock_get.return_value = response

        result = get_brick_client(self.user_access_token).get_income_profile()

        try:
            assert mock_get.called
            self.brick.profile_response = result
            self.brick.save_profile_info()
        except Exception as error:
            self.assertEqual("Not found key [data] in response.", str(error))

    @patch("juloserver.bpjs.clients.BrickClient._call_income_api")
    def test_save_profile_data(self, mock_get):

        response = Response()
        response.status_code = 200
        response._content = (
            b'{"status": 200,"message": "OK","data": '
            b'{"name": "Pasek Sujana","ktpNumber": "039348","bpjsCardNumber": "019238", '
            b'"npwpNumber": null,"dob": "19-04-1986", "phoneNumber": "+6285334207735",'
            b'"address": "Jl. Bawal No. 341, Tegal 35786, JaBar",'
            b'"gender": "LAKI-LAKI",'
            b'"totalBalance": "4556700",'
            b'"bpjsCards": [{"number": "019238", "balance": "4556700"}],'
            b'"type": "bpjs-tk","institutionId": 14}}'
        )
        mock_get.return_value = response

        result = get_brick_client(self.user_access_token).get_income_profile()

        assert mock_get.called
        self.brick.profile_response = result
        result_saved = self.brick.save_profile_info()
        self.assertIsNotNone(result_saved)

    @patch("juloserver.bpjs.clients.BrickClient._call_income_api")
    def test_save_company_data(self, mock_get):

        profile_data = SdBpjsProfileScrapeFactory(application_id=self.application.id)
        response = Response()
        response.status_code = 200
        response._content = (
            b'{"status": 200,"message": "OK",'
            b'"data": [{"latestSalary":"10000000","companyName": "PT. XYZ",'
            b'"monthName": "01-08-2021","salary": "13400000", "latestPaymentDate": "09-01-2020",'
            b'"workingMonth": "13",  "status": "Aktif","bpjsCardNumber": "019238","type": "bpjs-tk","institutionId": 14},'
            b'{"latestSalary":"13400000", "companyName": "PT. XYZ","monthName": "01-07-2021","salary":"13400000",'
            b'"latestPaymentDate": "09-01-2020","workingMonth": "7",  "status": "Aktif", '
            b'"bpjsCardNumber": "019238","type": "bpjs-tk","institutionId": 14}]}'
        )
        mock_get.return_value = response

        result = get_brick_client(self.user_access_token).get_income_employment()

        assert mock_get.called
        self.brick.company_response = result
        self.brick.profile = profile_data
        result_saved = self.brick.save_company_data()
        self.assertEqual(True, result_saved)

    def test_has_company(self):
        profile = SdBpjsProfileScrapeFactory(application_id=self.application.id)
        SdBpjsCompanyScrapeFactory(profile=profile)

        self.bpjs.application = self.application
        self.assertTrue(self.bpjs.has_company)

    def test_has_profile(self):
        SdBpjsProfileScrapeFactory(application_id=self.application.id)

        self.bpjs.application = self.application
        self.assertTrue(self.bpjs.has_profile)

    def test_is_submitted(self):
        SdBpjsProfileScrapeFactory(application_id=self.application.id)

        self.bpjs.application = self.application
        self.assertTrue(self.bpjs.is_submitted)

    def test_is_scraped(self):
        profile = SdBpjsProfileScrapeFactory(application_id=self.application.id)
        SdBpjsCompanyScrapeFactory(profile=profile)

        self.bpjs.application = self.application
        self.assertTrue(self.bpjs.is_scraped)

    def test_is_not_scraped(self):
        self.bpjs.application = self.application
        self.assertFalse(self.bpjs.is_scraped)

    def test_is_identity_match(self):
        profile = SdBpjsProfileScrapeFactory(
            application_id=self.application.id, identity_number=self.application.ktp
        )

        self.bpjs.application = self.application
        self.assertTrue(self.bpjs.is_identity_match)

    def test_is_identity_not_match(self):
        SdBpjsProfileScrapeFactory(application_id=self.application.id, identity_number=298734892)

        self.bpjs.application = self.application
        self.assertFalse(self.bpjs.is_identity_match)

    def test_status_verified(self):
        BpjsUserAccessFactory(application_id=self.application.id)

        self.bpjs.application = self.application
        self.assertEqual(self.bpjs.status, "verified")

    def test_status_not_verified(self):
        profile = SdBpjsProfileScrapeFactory(application_id=self.application.id)

        self.bpjs.application = self.application
        self.assertEqual(self.bpjs.status, "not-verified")

    def test_generate_pdf_failed_when_no_profile(self):
        from juloserver.bpjs.exceptions import BrickBpjsException

        with pytest.raises(BrickBpjsException) as exception:
            self.bpjs.application = self.application
            self.bpjs.generate_pdf()

        self.assertEqual(
            str(exception.value),
            "No BPJS profile data for application_id {}".format(self.application.id),
        )

    def test_generate_pdf_failed_when_no_company(self):
        from juloserver.bpjs.exceptions import BrickBpjsException

        profile = SdBpjsProfileScrapeFactory(application_id=self.application.id)

        with pytest.raises(BrickBpjsException) as exception:
            self.bpjs.application = self.application
            self.bpjs.generate_pdf()

        self.assertEqual(str(exception.value), "Either profile or companies is empty")

    @patch("juloserver.bpjs.clients.BrickClient._call_income_api")
    def test_response_failure_condition(self, mock):
        """
        Failure scenario save data with correct application id
        """

        response = Response()
        response.status_code = 401
        response.url = "/test/v1/income/general"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = b'{"status":401,"message":"Unauthorized","data":""}'

        mock.return_value = response

        result = get_brick_client(self.user_access_token).get_income_profile()

        api_log = BpjsAPILog.objects.filter(application=self.application).last()

        assert mock.called
        self.assertIsNone(api_log)

    def test_services_store_bpjs_from_brick(self):
        """
        Test method fortask Get Information User
        """
        from django.conf import settings

        from juloserver.bpjs.services.providers.brick import store_bpjs_from_brick
        from juloserver.julo.services2.encryption import AESCipher

        application_xid = self.application.application_xid
        aes = AESCipher(settings.BRICK_SALT)
        user_access_credential = aes.encrypt(self.user_access_token)
        with self.assertRaises(Exception) as e:
            store_bpjs_from_brick(application_xid, user_access_credential)
        self.assertTrue(str(e), "[Provider status code: 401] Unauthorized")

    def test_services_store_bpjs_not_credentials(self):
        """
        Test method for Get Information User with scenario empty credentials
        """
        from django.conf import settings

        from juloserver.bpjs.services.providers.brick import store_bpjs_from_brick
        from juloserver.julo.services2.encryption import AESCipher

        application_xid = self.application.application_xid
        aes = AESCipher(settings.BRICK_SALT)
        user_access_credential = None
        with self.assertRaises(Exception) as e:
            store_bpjs_from_brick(application_xid, user_access_credential)
        self.assertTrue(str(e), "[Celery] Brick Get Information - User Access Token not found.")

    def test_services_store_bpjs_not_application(self):
        """
        Test method for Get Information User with scenario not application
        """
        from django.conf import settings

        from juloserver.bpjs.services.providers.brick import store_bpjs_from_brick
        from juloserver.julo.services2.encryption import AESCipher

        application_xid = "1231313123131"
        aes = AESCipher(settings.BRICK_SALT)
        user_access_credential = aes.encrypt(self.user_access_token)
        with self.assertRaises(Exception) as e:
            store_bpjs_from_brick(application_xid, user_access_credential)
        self.assertTrue(str(e), "[Celery] Brick Get Information - Application not found.")


class TestLoggingAPI(TestCase):
    def setUp(self):

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        # data logging
        self.data_log = {
            "application_id": self.application.id,
            "service_provider": "brick",
            "api_type": "GET",
        }

    @patch("juloserver.bpjs.clients.BrickClient")
    def test_create_data_logging_profile_condition_failure(self, mock):
        """
        Test for scenario failure and save it to logging by response.
        """

        response = Response()
        response.status_code = 500
        response.url = "/test/v1/income/general"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = (
            b'{"timestamp":"2021-12-28T08:42:32.228+00:00",'
            b'"status":500,'
            b'"error":"Internal Server Error",'
            b'"path":"/test/v1/income/general"}'
        )
        mock_response = response
        mock.return_value = mock_response

        result = get_brick_client()

        self.data_log["http_status_code"] = str(result.status_code)
        self.data_log["query_params"] = str(result.url)
        self.data_log["request"] = "header: " + str(result.headers) + " body: " + str(result.body)
        self.data_log["response"] = str(result.json())
        self.data_log["error_message"] = str(result.json()["error"])

        Bpjs(application=self.application).log_api_call(**self.data_log)

        # check result
        is_exists = BpjsAPILog.objects.filter(application_id=self.application.id).exists()

        assert mock.called
        self.assertTrue(is_exists)

    @patch("juloserver.bpjs.clients.BrickClient")
    def test_create_data_logging_profile_condition_success(self, mock):
        """
        Test for scenario success and save it to logging by response.
        """

        response = Response()
        response.status_code = 200
        response.url = "/test/v1/income/general"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = (
            b'{"status":200,"message":"OK",'
            b'"data":'
            b'{"name":"Pasek Sujana",'
            b'"ktpNumber":"039348",'
            b'"bpjsCardNumber":"019238",'
            b'"npwpNumber":null,'
            b'"dob":"19-04-1986",'
            b'"phoneNumber":"+6285334207735",'
            b'"address":"Jl. Bawal No. 341, Tegal 35786, JaBar",'
            b'"gender":"LAKI-LAKI","totalBalance":"4556700",'
            b'"bpjsCards":[{"number":"019238","balance":"4556700"}],"type":"bpjs-tk","institutionId":14}}'
        )
        mock_response = response
        mock.return_value = mock_response

        result = get_brick_client()

        self.data_log["http_status_code"] = str(result.status_code)
        self.data_log["query_params"] = str(result.url)
        self.data_log["request"] = "header: " + str(result.headers) + " body: " + str(result.body)
        self.data_log["response"] = str(result.json())
        self.data_log["error_message"] = ""

        Bpjs(application=self.application).log_api_call(**self.data_log)

        # check result
        is_exists = BpjsAPILog.objects.filter(application_id=self.application.id).exists()

        assert mock.called
        self.assertTrue(is_exists)

    @patch("juloserver.bpjs.clients.BrickClient")
    def test_create_data_logging_company_condition_success(self, mock):
        """
        Test for scenario success and save it to logging by response.
        """

        response = Response()
        response.status_code = 200
        response.url = "/test/v1/income/employment"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = (
            b'{"status":200,'
            b'"message":"OK",'
            b'"data":'
            b'[{"latestSalary":"10000000",'
            b'"companyName":"PT XYZ",'
            b'"latestPaymentDate":"09-01-2020",'
            b'"workingMonth":"13","status":"Aktif",'
            b'"bpjsCardNumber":"019239",'
            b'"type":"bpjs-tk",'
            b'"institutionId":14},'
            b'{"latestSalary":"13400000",'
            b'"companyName":"PT XYZ",'
            b'"latestPaymentDate":"01-08-2021",'
            b'"workingMonth":"7",'
            b'"status":"Aktif",'
            b'"bpjsCardNumber":"019238",'
            b'"type":"bpjs-tk","institutionId":14}]}'
        )
        mock_response = response
        mock.return_value = mock_response

        result = get_brick_client()

        self.data_log["http_status_code"] = str(result.status_code)
        self.data_log["query_params"] = str(result.url)
        self.data_log["request"] = "header: " + str(result.headers) + " body: " + str(result.body)
        self.data_log["response"] = str(result.json())
        self.data_log["error_message"] = ""

        Bpjs(application=self.application).log_api_call(**self.data_log)
        # check result
        is_exists = BpjsAPILog.objects.filter(application_id=self.application.id).exists()
        assert mock.called
        self.assertTrue(is_exists)

    @patch("juloserver.bpjs.clients.BrickClient")
    def test_create_data_logging_payment_condition_success(self, mock):
        """
        Test for scenario success and save it to logging by response.
        """

        response = Response()
        response.status_code = 200
        response.url = "/test/v1/income/salary"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = (
            b'{"status":200,'
            b'"message":"OK",'
            b'"data":[{"companyName":'
            b'"PT. XYZ",'
            b'"monthName":"01-08-2021",'
            b'"salary":"13400000",'
            b'"bpjsCardNumber":"019238",'
            b'"type":"bpjs-tk",'
            b'"institutionId":14}]}'
        )

        mock_response = response
        mock.return_value = mock_response

        result = get_brick_client()

        self.data_log["http_status_code"] = str(result.status_code)
        self.data_log["query_params"] = str(result.url)
        self.data_log["request"] = "header: " + str(result.headers) + " body: " + str(result.body)
        self.data_log["response"] = str(result.json())
        self.data_log["error_message"] = ""

        Bpjs(application=self.application).log_api_call(**self.data_log)

        # check result
        is_exists = BpjsAPILog.objects.filter(application_id=self.application.id).exists()
        assert mock.called
        self.assertTrue(is_exists)

    @patch("juloserver.bpjs.clients.BrickClient")
    def test_create_data_logging_payment_condition_failure(self, mock):
        """
        Test for scenario success and save it to logging by response.
        """

        response = Response()
        response.status_code = 401
        response.url = "/test/v1/income/salary"
        response.body = None
        response.headers = {"Content-Type": "application/json"}
        response._content = b'{"status":401,"message":"Unauthorized","data":""}'

        mock_response = response
        mock.return_value = mock_response

        result = get_brick_client()

        self.data_log["http_status_code"] = str(result.status_code)
        self.data_log["query_params"] = str(result.url)
        self.data_log["request"] = "header: " + str(result.headers) + " body: " + str(result.body)
        self.data_log["response"] = str(result.json())
        self.data_log["error_message"] = ""

        # save data to logging table
        Bpjs(application=self.application).log_api_call(**self.data_log)

        # check result
        is_exists = BpjsAPILog.objects.filter(application_id=self.application.id).exists()
        assert mock.called
        self.assertTrue(is_exists)
