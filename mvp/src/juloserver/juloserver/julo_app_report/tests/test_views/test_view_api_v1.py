from django.test import TestCase
from rest_framework.test import APIClient, APITestCase

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    ProductLineFactory,
    WorkflowFactory,
)


class TestCrashReport(TestCase):

    def setUp(self):

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.workflow = WorkflowFactory(name="JuloOneWorkflow", handler="JuloOneWorkflowHandler")
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)

        WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        ProductLineFactory(product_line_code=1)
        self.payload = {
            "android_id": "c32d6eee0040052a",
            "device_name": "docomo",
            "response": None,
            "request": None,
        }
        self.base_url = "/api/app-reports/v1/crash-reports"

    def test_case_is_success(self):
        """
        Test case with partial data capture
        """

        response = self.client.post(self.base_url, data=self.payload)
        self.assertEqual(response.status_code, 200)

    def test_case_failed_for_application_not_found(self):
        """
        Test case for application id is not found
        """

        self.payload['application_id'] = 1111111
        response = self.client.post(self.base_url, data=self.payload)
        self.assertEqual(response.status_code, 400)

    def test_case_is_success_with_full_data(self):
        """
        Test Case for full data capture
        """

        self.payload['request'] = "{'phone': '08781721313123'}"
        self.payload['response'] = "{'status': 500, 'message': 'No value present', 'data': None}"
        self.payload['application_id'] = self.application.id

        response = self.client.post(self.base_url, data=self.payload)
        self.assertEqual(response.status_code, 200)
