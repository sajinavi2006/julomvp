import pytest
from mock import patch

from django.test.testcases import TestCase

from juloserver.application_form.exceptions import JuloProductPickerException
from juloserver.application_form.services.product_picker_service import proceed_select_product
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import Application, OnboardingEligibilityChecking
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    WorkflowFactory,
    StatusLookupFactory,
    DeviceFactory,
    ApplicationHistoryFactory,
    OnboardingFactory,
    OnboardingEligibilityCheckingFactory,
)
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory


class TestProceedSelectProductForFirstTime(TestCase):
    pass


class TestProceedSelectProductForReapply(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(can_reapply=False)
        self.workflow_jstarter = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        WorkflowStatusPathFactory(
            status_previous=0, status_next=100, workflow=self.workflow_jstarter
        )
        self.onboarding = OnboardingFactory(id=7)
        self.device = DeviceFactory(customer=self.customer)
        self.data = {
            "onboarding_id": self.onboarding.id,
            "app_version": "7.5.4",
            # "web_version": "",
            "device_id": self.device.id,
            "customer_id": self.customer.id,
            "ip_address": "192.168.10.1",
            "is_suspicious_ip": False,
            "is_rooted_device": False,
        }

    @patch(
        'juloserver.application_form.services.product_picker_service.suspicious_ip_app_fraud_check'
    )
    @patch('juloserver.application_form.services.product_picker_service.generate_address_location')
    @patch(
        'juloserver.application_form.services.product_picker_service.send_sms_for_webapp_dropoff_customers_x100'
    )
    def test_when_customer_not_in_reapply_mode(self, m1, m2, m3):
        self.customer.can_reapply = False
        self.customer.save()
        self.assertEqual(self.customer.application_set.count(), 0)
        self.assertFalse(self.customer.can_reapply)

        OnboardingEligibilityCheckingFactory(customer=self.customer, bpjs_check=1)
        proceed_select_product(self.data)

        app = Application.objects.filter(customer=self.customer)
        self.assertEqual(app.count(), 1)
        oec = OnboardingEligibilityChecking.objects.filter(customer=self.customer).last()
        self.assertEqual(oec.application.id, app.last().id)

    def test_duplicate_application(self):
        ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)
        self.assertEqual(self.customer.application_set.count(), 1)
        self.customer.can_reapply = True
        self.customer.save()

        proceed_select_product(self.data)

        cnt = Application.objects.filter(customer=self.customer).count()
        self.assertEqual(cnt, 2)

    def test_return_error_when_reapply_and_has_status_x133(self):
        self.customer.can_reapply = True
        self.customer.save()
        status133 = StatusLookupFactory(status_code=133)
        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)
        application.application_status = status133
        application.save()

        with pytest.raises(JuloProductPickerException) as e:
            proceed_select_product(self.data)

        self.assertEqual(str(e.value), "Existing application not allowed to reapply")

    def test_return_error_when_reapply_to_jstar_and_has_status_x135_through_x121(self):
        self.customer.can_reapply = True
        self.customer.save()
        status135 = StatusLookupFactory(status_code=135)
        application = ApplicationFactory(customer=self.customer, workflow=self.workflow_jstarter)
        application.application_status = status135
        application.save()
        ApplicationHistoryFactory(status_old=121, status_new=135, application_id=application.id)

        with pytest.raises(JuloProductPickerException) as e:
            proceed_select_product(self.data)

        self.assertEqual(str(e.value), "Existing application not allowed to reapply")
