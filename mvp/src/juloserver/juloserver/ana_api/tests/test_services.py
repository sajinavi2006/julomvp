from django.test.testcases import TestCase
from rest_framework.test import APIClient

from juloserver.ana_api.services import predict_bank_scrape
from juloserver.apiv2.tests.factories import EtlJobFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
)


class TestEtlNotificationUpdateStatus(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.etl_job = None
        self.application = None

    def test_predict_bank_scrape_failed(self):
        self.application = ApplicationFactory()
        self.etl_job = EtlJobFactory(application_id=self.application.id, status='failed')
        is_success = predict_bank_scrape(self.application)
        self.assertFalse(is_success)
