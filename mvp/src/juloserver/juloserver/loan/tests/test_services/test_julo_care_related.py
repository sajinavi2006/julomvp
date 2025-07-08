from unittest.mock import MagicMock
import requests

from mock import patch

from rest_framework.status import HTTP_200_OK

from django.test.testcases import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.models import StatusLookup
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationJ1Factory,
    CustomerFactory,
    LoanFactory,
    ProductLineFactory,
    StatusLookupFactory,
)
from juloserver.ana_api.tests.factories import SdDevicePhoneDetailFactory

from juloserver.loan.clients import get_julo_care_client
from juloserver.loan.services.julo_care_related import (
    get_eligibility_status,
    julo_care_create_policy,
)
from juloserver.loan.tests.factories import LoanJuloCareFactory


class TestServiceJuloCare(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.customer_no_device = CustomerFactory()

        status_code = StatusLookupFactory(status_code=420)
        self.account = AccountFactory(customer=self.customer, status=status_code)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)

        self.account_no_device = AccountFactory(
            customer=self.customer_no_device, status=status_code
        )
        self.application_no_device = ApplicationJ1Factory(
            customer=self.customer_no_device, account=self.account_no_device
        )

    @patch('juloserver.loan.clients.julo_care.JULOCaresClient.send_request')
    def test_get_eligibility_status(self, mock_send_request):
        sd_device_phone_detail = SdDevicePhoneDetailFactory(customer_id=self.customer.id)

        is_eligible, response_data = get_eligibility_status(
            self.customer_no_device, list_loan_tenure=[]
        )
        self.assertEqual(is_eligible, False)
        self.assertEqual(response_data, {})

        mock_send_request.return_value = {"data": {}, "error": None, "success": False}
        is_eligible, response_data = get_eligibility_status(self.customer, list_loan_tenure=[])
        self.assertEqual(is_eligible, False)
        self.assertEqual(response_data, {})

        mock_send_request.return_value = {
            "data": {
                "eligible": True,
                'minimum_eligible_loan_amount': 100000,
                "insurance_info": {
                    "insurance_description": "some description related to insurance program",
                    "insurance_premium": {
                        "3": 6000,
                        "4": 8000,
                        "5": 10000,
                        "6": 12000,
                        "12": 20000,
                    },
                },
            },
            "error": None,
            "success": True,
        }
        is_eligible, response_data = get_eligibility_status(self.customer, list_loan_tenure=[3])
        self.assertEqual(is_eligible, True)
        self.assertEqual(response_data, {'3': 6000})

        is_eligible, response_data = get_eligibility_status(
            self.customer, list_loan_tenure=[1], loan_amount=500000
        )
        self.assertEqual(is_eligible, True)
        self.assertEqual(response_data, {})

        mock_send_request.return_value = {
            "data": {},
            "error": None,
            "success": True,
        }
        is_eligible, response_data = get_eligibility_status(self.customer, list_loan_tenure=[3])
        self.assertEqual(is_eligible, False)
        self.assertEqual(response_data, {})

        customer = self.customer
        old_xid = customer.customer_xid
        customer.customer_xid = None
        customer.save()
        is_eligible, response_data = get_eligibility_status(customer, list_loan_tenure=[3])
        customer.customer_xid = old_xid
        customer.save()
        self.assertEqual(is_eligible, False)
        self.assertEqual(response_data, {})

        device_brand = 'xiaomi'
        device_model = 'Redmi Note 8'
        os_version = 30
        list_loan_tenure = [3]
        is_eligible, response_data = get_eligibility_status(
            customer=self.customer,
            list_loan_tenure=list_loan_tenure,
            loan_amount=0,
            device_brand=device_brand,
            device_model=device_model,
            os_version=os_version,
        )
        self.assertEqual(is_eligible, False)
        self.assertEqual(response_data, {})
        mock_send_request.assert_called_with(
            '/v1/eligibility',
            'post',
            json={
                "customer_xid": self.customer.customer_xid,
                "device_brand_name": device_brand,
                "device_model_name": device_model,
                "api_level": os_version,
                "list_loan_tenure": list_loan_tenure,
            },
        )

        is_eligible, response_data = get_eligibility_status(
            customer=self.customer,
            list_loan_tenure=list_loan_tenure,
            loan_amount=0,
            device_brand=None,
            device_model=None,
            os_version=None,
        )
        self.assertEqual(is_eligible, False)
        self.assertEqual(response_data, {})
        mock_send_request.assert_called_with(
            '/v1/eligibility',
            'post',
            json={
                "customer_xid": self.customer.customer_xid,
                "device_brand_name": sd_device_phone_detail.brand,
                "device_model_name": sd_device_phone_detail.model,
                "api_level": int(sd_device_phone_detail.sdk),
                "list_loan_tenure": list_loan_tenure,
            },
        )

        # When a field in device info is not sent (value is None), will use data from ana table
        get_eligibility_status(
            customer=self.customer,
            list_loan_tenure=list_loan_tenure,
            loan_amount=0,
            device_brand=None,
            device_model=device_model,
            os_version=os_version,
        )
        mock_send_request.assert_called_with(
            '/v1/eligibility',
            'post',
            json={
                "customer_xid": self.customer.customer_xid,
                "device_brand_name": sd_device_phone_detail.brand,
                "device_model_name": sd_device_phone_detail.model,
                "api_level": int(sd_device_phone_detail.sdk),
                "list_loan_tenure": list_loan_tenure,
            },
        )

        # When a field in device info is empty string, will use data from ana table
        get_eligibility_status(
            customer=self.customer,
            list_loan_tenure=list_loan_tenure,
            loan_amount=0,
            device_brand=device_brand,
            device_model='',
            os_version=os_version,
        )
        mock_send_request.assert_called_with(
            '/v1/eligibility',
            'post',
            json={
                "customer_xid": self.customer.customer_xid,
                "device_brand_name": sd_device_phone_detail.brand,
                "device_model_name": sd_device_phone_detail.model,
                "api_level": int(sd_device_phone_detail.sdk),
                "list_loan_tenure": list_loan_tenure,
            },
        )

    def test_get_eligibility_status_failed_loan_status(self):
        loan = LoanFactory(
            loan_status=StatusLookup.objects.get(status_code=StatusLookup.FUND_DISBURSAL_FAILED),
            customer=self.customer_no_device,
        )
        is_eligible, response_data = get_eligibility_status(
            self.customer_no_device, list_loan_tenure=[]
        )
        self.assertEqual(is_eligible, False)
        self.assertEqual(response_data, {})

        loan.loan_status = StatusLookup.objects.get(status_code=StatusLookup.CURRENT_CODE)
        loan.save()

    @patch('requests.post')
    def test_send_request(self, mock_request):
        def json_func():
            return {
                "data": {
                    "eligible": True,
                    "insurance_info": {
                        "insurance_description": "some description related to insurance program",
                        "insurance_premium": {
                            "3": 6000,
                            "4": 8000,
                            "5": 10000,
                            "6": 12000,
                            "12": 20000,
                        },
                    },
                },
                "error": None,
                "success": True,
            }

        julo_care_client = get_julo_care_client()

        mock_response = requests.Response()
        mock_response.status_code = HTTP_200_OK
        mock_response.json = json_func
        mock_response.request = requests.request
        mock_request.return_value = mock_response

        api_response = julo_care_client.send_request(
            '/v1/eligibility',
            'post',
            json={
                "customer_xid": 123,
                "device_brand_name": "Samsung",
                "device_model_name": "A-SM123",
                "api_level": '9',
                "list_loan_tenure": [3],
            },
        )
        self.assertIsNotNone(api_response)

    @patch('juloserver.loan.clients.julo_care.JULOCaresClient.send_request')
    def test_julo_care_create_policy(self, mock_send_request):
        loan = LoanFactory()
        customer = loan.customer
        loan_julo_care = LoanJuloCareFactory(loan=loan)

        mock_send_request.return_value = {"success": True}

        json_data = {
            "customer_xid": customer.customer_xid,
            "device_brand": "",
            "device_model_name": "",
            "api_level": "",
            "email": customer.email,
            "fullname": customer.fullname,
            "insurance_premium": loan_julo_care.insurance_premium,
            "loan_tenure": loan.loan_duration,
            "phone_number": customer.phone,
            "product_identifier_number": "",
            "product_identifier_type": "IMEI",
            "transaction_id": loan.loan_xid,
        }

        # device info in LoanJuloCare is null and no data in SdDevicePhoneDetail
        self.assertFalse(julo_care_create_policy(loan, loan_julo_care))

        # device info in LoanJuloCare is null and have data in SdDevicePhoneDetail
        # => use data in SdDevicePhoneDetail
        sd_device_phone_detail = SdDevicePhoneDetailFactory(customer_id=customer.id)

        self.assertTrue(julo_care_create_policy(loan, loan_julo_care))
        json_data['device_brand'] = sd_device_phone_detail.brand
        json_data['device_model_name'] = sd_device_phone_detail.model
        json_data['api_level'] = int(sd_device_phone_detail.sdk)
        mock_send_request.assert_called_with("/v1/policy", "post", json=json_data)

        # device info in LoanJuloCare is not null => use data in LoanJuloCare
        loan_julo_care.device_brand = "Samsung"
        loan_julo_care.device_model = "A-SM123"
        loan_julo_care.os_version = 32
        loan_julo_care.save()
        self.assertTrue(julo_care_create_policy(loan, loan_julo_care))
        json_data['device_brand'] = loan_julo_care.device_brand
        json_data['device_model_name'] = loan_julo_care.device_model
        json_data['api_level'] = loan_julo_care.os_version
        mock_send_request.assert_called_with("/v1/policy", "post", json=json_data)

        # a field in device info in LoanJuloCare is null => use data in SdDevicePhoneDetail
        loan_julo_care.device_brand = None
        loan_julo_care.save()
        self.assertTrue(julo_care_create_policy(loan, loan_julo_care))
        json_data['device_brand'] = sd_device_phone_detail.brand
        json_data['device_model_name'] = sd_device_phone_detail.model
        json_data['api_level'] = int(sd_device_phone_detail.sdk)
        mock_send_request.assert_called_with("/v1/policy", "post", json=json_data)

    @patch('juloserver.loan.services.julo_care_related.get_julo_care_client')
    def test_get_eligibility_status_julover(self, mock_julo_care_client):
        SdDevicePhoneDetailFactory(customer_id=self.customer.id)
        mock_client = MagicMock()
        mock_julo_care_client.return_value = mock_client
        mock_client.send_request.return_value = {
            "data": {
                "eligible": True,
                'minimum_eligible_loan_amount': 100000,
                "insurance_info": {
                    "insurance_description": "some description related to insurance program",
                    "insurance_premium": {
                        "3": 6000,
                        "4": 8000,
                        "5": 10000,
                        "6": 12000,
                        "12": 20000,
                    },
                },
            },
            "error": None,
            "success": True,
        }
        is_eligible, _ = get_eligibility_status(self.customer, list_loan_tenure=[3])
        self.assertEqual(is_eligible, True)

        # make it julover
        self.application.product_line = ProductLineFactory.julover()
        self.application.save()

        is_eligible, _ = get_eligibility_status(self.customer, list_loan_tenure=[3])
        self.assertEqual(is_eligible, False)
