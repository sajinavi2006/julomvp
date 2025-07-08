import json
from unittest import mock
from unittest.mock import call, patch

import requests
import responses
from django.test import TestCase
from requests.exceptions import Timeout
from responses import matchers

from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    CustomerFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    CreditScoreFactory
)
from juloserver.personal_data_verification.models import (
    BureauDeviceIntelligence,
    BureauEmailAttributes,
    BureauEmailSocial,
    BureauMobileIntelligence,
    BureauPhoneSocial)
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.personal_data_verification.constants import FeatureNameConst, BureauConstants
from juloserver.personal_data_verification.clients import get_bureau_client
from juloserver.personal_data_verification.tasks import (
    trigger_bureau_alternative_data_services_apis,
    fetch_bureau_sdk_services_data)


class TestBureauServices(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(customer_xid="1234567890")
        self.application = ApplicationJ1Factory(
            email='testemail@gmail.com', application_xid="123456789", customer=self.customer)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.BUREAU_SERVICES,
            parameters={},
            is_active=True)

    def test_is_feature_active(self):
        client = get_bureau_client(self.application, None)
        self.assertEqual(client.is_feature_active(), True)
        self.feature_setting.is_active = False
        self.feature_setting.save()
        self.feature_setting.refresh_from_db()
        self.assertEqual(client.is_feature_active(), False)

    def test_is_application_eligible(self):
        credit_score = CreditScoreFactory(application_id=self.application.id)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL)
        self.application.save()
        client = get_bureau_client(self.application, None)
        self.assertEqual(client.is_application_eligible(), False)
        credit_score.score = 'B'
        credit_score.save()
        credit_score.refresh_from_db()
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        client = get_bureau_client(self.application, None)
        self.assertEqual(client.is_application_eligible(), True)
        
    
    @mock.patch('juloserver.personal_data_verification.clients.bureau_client.BureauClient.get_api_response')
    def test_hit_bureau_api_email_social(self, mock_api_response):
        credit_score = CreditScoreFactory(
            application_id=self.application.id, score='B')
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        client = get_bureau_client(self.application, None)
        client.service = BureauConstants.EMAIL_SOCIAL
        mock_api_response.return_value = {}, 200
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertEqual(errors, None)
        BureauEmailSocial.objects.all().delete()
        mock_api_response.return_value = {'errors': 'Error happened'}, 400
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertNotEqual(errors, None)
    

    @mock.patch('juloserver.personal_data_verification.clients.bureau_client.BureauClient.get_api_response')
    def test_hit_bureau_api_phone_social(self, mock_api_response):
        credit_score = CreditScoreFactory(
            application_id=self.application.id, score='B')
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        client = get_bureau_client(self.application, None)
        client.service = BureauConstants.PHONE_SOCIAL
        mock_api_response.return_value = {}, 200
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertEqual(errors, None)
        BureauPhoneSocial.objects.all().delete()
        mock_api_response.return_value = {'errors': 'Error happened'}, 400
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertNotEqual(errors, None)
    

    @mock.patch('juloserver.personal_data_verification.clients.bureau_client.BureauClient.get_api_response')
    def test_hit_bureau_api_mobile_intelligence(self, mock_api_response):
        credit_score = CreditScoreFactory(
            application_id=self.application.id, score='B')
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        client = get_bureau_client(self.application, None)
        client.service = BureauConstants.MOBILE_INTELLIGENCE
        mock_api_response.return_value = {}, 200
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertEqual(errors, None)
        BureauMobileIntelligence.objects.all().delete()
        mock_api_response.return_value = {'errors': 'Error happened'}, 400
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertNotEqual(errors, None)
    

    @mock.patch('juloserver.personal_data_verification.clients.bureau_client.BureauClient.get_api_response')
    def test_hit_bureau_api_email_attributes(self, mock_api_response):
        credit_score = CreditScoreFactory(
            application_id=self.application.id, score='B')
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        client = get_bureau_client(self.application, None)
        client.service = BureauConstants.EMAIL_ATTRIBUTES
        mock_api_response.return_value = {}, 200
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertEqual(errors, None)
        BureauEmailAttributes.objects.all().delete()
        mock_api_response.return_value = {'errors': 'Error happened'}, 400
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertNotEqual(errors, None)
    

    @mock.patch('juloserver.personal_data_verification.clients.bureau_client.BureauClient.get_api_response')
    def test_hit_bureau_api_device_intelligence(self, mock_api_response):
        credit_score = CreditScoreFactory(
            application_id=self.application.id, score='B')
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)
        self.application.save()
        client = get_bureau_client(self.application, None)
        client.service = BureauConstants.DEVICE_INTELLIGENCE
        mock_api_response.return_value = {}, 200
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertEqual(errors, None)
        mock_api_response.return_value = {'errors': 'Error happened'}, 400
        bureau_object, errors = client.hit_bureau_api()
        self.assertIsNotNone(bureau_object)
        self.assertNotEqual(errors, None)
