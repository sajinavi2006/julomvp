import pytest
from django.test.testcases import TestCase

from juloserver.bpjs.services import (
    check_submitted_bpjs,
    create_or_update_bpjs_task_from_tongdun_callback,
    generate_bpjs_login_url_via_tongdun,
)
from juloserver.bpjs.services.bpjs import Bpjs
from juloserver.bpjs.tests.factories import SdBpjsProfileFactory
from juloserver.bpjs.utils import get_http_referrer
from juloserver.julo.tests.factories import ApplicationFactory, CustomerFactory


class TestJuloOneService(TestCase):
    @classmethod
    def tearDownClass(cls):
        pass

    @classmethod
    def setUpClass(cls):
        cls.application = ApplicationFactory()

    def test_check_submitted_bpjs(self):
        result = check_submitted_bpjs(self.application)
        self.assertEqual(result, False)

        SdBpjsProfileFactory(
            application_id=self.application.id, customer_id=self.application.customer.id
        )
        result = check_submitted_bpjs(self.application)
        self.assertEqual(result, True)


class TestBpjsService(TestCase):
    @classmethod
    def tearDownClass(cls):
        pass

    @classmethod
    def setUpClass(cls):
        cls.application = ApplicationFactory()

    def test_generate_bpjs_login_url_via_tongdun(self):
        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        app_type = "web_cermati_home"

        with pytest.raises(LookupError) as e:
            generate_bpjs_login_url_via_tongdun(customer.id, application.id, app_type)
        self.assertEqual(str(e.value), "Bpjs application type not found.")

        app_type = "app"
        response = generate_bpjs_login_url_via_tongdun(customer.id, application.id, app_type)
        self.assertIsNotNone(response)

    def test_create_or_update_bpjs_task_from_tongdun_callback(self):
        customer_id = "1000001350"
        application_id = "2000001409"
        data_source = "app"
        data = {
            "notify_data": "",
            "code": 1,
            "message": "The task has been submitted successfully",
            "passback_params": "1000001350_2000001409_app_julo",
            "task_id": "TASKPR105002202004151222090900200666",
        }
        response = create_or_update_bpjs_task_from_tongdun_callback(
            data, customer_id, application_id, data_source
        )
        self.assertIsNotNone(response)

    # def test_check_bpjs_task_for_application(self):
    #     application_id = 2000001409
    #     bpjs_task_dict = dict(customer_id=1000001350,
    #                           application_id=2000001409,
    #                           task_id='TASKPR105002202004151222090900200666')
    #     BpjsTask.objects.create(**bpjs_task_dict)
    #     response = check_bpjs_task_for_application(application_id)
    #     self.assertIsNotNone(response)

    def test_check_submit_bpjs(self):
        response = check_submitted_bpjs(self.application)
        self.assertIsNotNone(response)

    def test_retrieve_and_store_bpjs_data(self):
        response = check_submitted_bpjs(self.application)
        self.assertIsNotNone(response)

    def test_generate_url_login_brick(self):
        """
        Test generate url for login via Brick
        """
        from django.http import HttpRequest

        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        factory_request = HttpRequest()
        factory_request.META["SERVER_NAME"] = "127.0.0.1"
        factory_request.META["SERVER_PORT"] = "8001"

        bpjs = Bpjs()
        bpjs.provider = bpjs.PROVIDER_BRICK
        bpjs.set_request(factory_request)
        bpjs.with_application(application)
        bpjs.public_access_token = "xxxxxxxxxxxxxxxxx"
        login_url = bpjs.get_full_widget_url()

        self.assertIsNotNone(login_url)

    def test_generate_url_login_brick_condition_fail_1(self):
        """
        Test generate url for login via Brick
        """
        from django.http import HttpRequest

        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        factory_request = HttpRequest()
        factory_request.META["SERVER_NAME"] = None
        factory_request.META["SERVER_PORT"] = None
        factory_request.META["HTTP_HOST"] = None

        with self.assertRaises(Exception) as e:
            bpjs = Bpjs()
            bpjs.provider = bpjs.PROVIDER_BRICK
            bpjs.set_request(factory_request)
            bpjs.with_application(application)
            bpjs.public_access_token = "xxxxxxxxxxxxxxxxx"
            bpjs.get_full_widget_url()
        self.assertTrue(str(e), "Error to get Host: {}".format(None))

    def test_generate_url_login_brick_condition_fail_env(self):
        """
        Test generate url for login via Brick
        """
        from django.conf import settings
        from django.http import HttpRequest

        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        factory_request = HttpRequest()
        factory_request.META["SERVER_NAME"] = None
        factory_request.META["SERVER_PORT"] = None
        factory_request.META["HTTP_HOST"] = None
        settings.BRICK_WIDGET_BASE_URL = None

        with self.assertRaises(Exception) as e:
            bpjs = Bpjs()
            bpjs.provider = bpjs.PROVIDER_BRICK
            bpjs.set_request(factory_request)
            bpjs.with_application(application)
            bpjs.public_access_token = "xxxxxxxxxxxxxxxxx"
            bpjs.get_full_widget_url()

        self.assertTrue(str(e), "BRICK_WIDGET_BASE_URL: {}".format(settings.BRICK_WIDGET_BASE_URL))

    def test_get_referer_fail(self):
        """
        Test get referer when condition fails.
        """
        from django.http import HttpRequest

        factory_request = HttpRequest()
        factory_request.META["SERVER_NAME"] = None
        factory_request.META["SERVER_PORT"] = None
        factory_request.META["HTTP_HOST"] = None

        with self.assertRaises(Exception) as e:
            get_http_referrer(factory_request)
        self.assertTrue(str(e), "Error get host in http_referer.")

    def test_get_referer_success(self):
        """
        Test get referer when condition fails.
        """
        from django.http import HttpRequest

        factory_request = HttpRequest()
        factory_request.META["SERVER_NAME"] = "127.0.0.1"
        factory_request.META["SERVER_PORT"] = "8001"
        http_referer = get_http_referrer(factory_request)
        self.assertIsNotNone(http_referer)
