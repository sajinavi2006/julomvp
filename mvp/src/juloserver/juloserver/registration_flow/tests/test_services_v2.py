from mock import patch
from django.test.utils import override_settings

from rest_framework.test import APIClient
from django.test import TestCase

from juloserver.registration_flow.services.v2 import process_register_phone_number
from juloserver.julo.tests.factories import (
    WorkflowFactory,
    ProductLineFactory,
    ProductLine,
    Customer,
    Application,
    AuthUserFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.application_flow.models import ApplicationRiskyCheck


def new_julo1_product_line():
    if not ProductLine.objects.filter(product_line_code=1).exists():
        ProductLineFactory(product_line_code=1)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestProcessRegister(TestCase):
    def setUp(self) -> None:
        self.client_wo_auth = APIClient()
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        new_julo1_product_line()
        self.path = WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.julo_one_workflow,
        )
        self.user = AuthUserFactory(username='0883231231231')

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.registration_flow.services.v2.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.registration_flow.services.v2.process_application_status_change')
    @patch('juloserver.registration_flow.serializers.get_latest_app_version', return_value='2.2.2')
    def test_create_success(
        self,
        _mock_get_latest_app_version,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        data = {
            'phone': '0883231231231',
            'app_version': '2.2.2',
            'pin': '012355',
            'gcm_reg_id': '2312312321312',
            'android_id': 'testandroidid',
            'imei': 'fakeimeiid',
            'latitude': 20.0,
            'longitude': 10.0,
            'appsflyer_device_id': 999999,
            'advertising_id': 999999,
        }
        result = process_register_phone_number(data)
        customer = Customer.objects.filter(phone=data['phone']).last()
        application = Application.objects.get(customer=customer)
        self.assertEqual(customer.id, result['customer']['id'])
        self.assertEqual(application.id, result['applications'][0]['id'])
        self.assertEqual(application.onboarding_id, 2)

    @patch('juloserver.pii_vault.services.tokenize_data_task')
    @patch('juloserver.registration_flow.services.v2.suspicious_ip_app_fraud_check.delay')
    @patch('juloserver.apiv2.tasks.generate_address_from_geolocation_async')
    @patch('juloserver.julo.tasks.create_application_checklist_async')
    @patch('juloserver.registration_flow.services.v2.process_application_status_change')
    @patch('juloserver.registration_flow.serializers.get_latest_app_version', return_value='2.2.2')
    def test_create_with_root_device(
        self,
        _mock_get_latest_app_version,
        _mock_change_status,
        mock_create_application_checklist_async,
        mock_generate_address_from_geolocation_async,
        mock_vpn_detection,
        mock_tokenize_data_task,
    ):
        data = {
            'phone': '0883231231231',
            'app_version': '2.2.2',
            'pin': '012355',
            'gcm_reg_id': '2312312321312',
            'android_id': 'testandroidid',
            'imei': 'fakeimeiid',
            'latitude': 20.0,
            'longitude': 10.0,
            'appsflyer_device_id': 999999,
            'is_rooted_device': True,
        }
        result = process_register_phone_number(data)
        customer = Customer.objects.filter(phone=data['phone']).last()
        application = Application.objects.get(customer=customer)
        application_risky_check = ApplicationRiskyCheck.objects.get(application=application)
        self.assertEqual(customer.id, result['customer']['id'])
        self.assertEqual(application.id, result['applications'][0]['id'])
        self.assertEqual(application_risky_check.is_rooted_device, True)
