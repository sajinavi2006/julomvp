from django.core.urlresolvers import reverse
from rest_framework.test import APITestCase
from mock import patch
import pytest
from juloserver.application_flow.factories import ApplicationPathTagStatusFactory
from juloserver.fraud_security.serializers import BlacklistWhitelistAddSerializer
from juloserver.fraud_security.tests.factories import FraudApplicationBucketFactory
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    AuthUserFactory,
    GroupFactory,
    StatusLookupFactory,
    CustomerFactory,
)
from juloserver.pin.models import BlacklistedFraudster


class TestFraudSecurityPageView(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = GroupFactory(name='fraudops')
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

    def test_post_blacklist(self):
        post_data = {"type": "blacklist", "data": "android_id_1\nandroid_id_2", "reason": "reason"}
        res = self.client.post('/fraud_security/security', post_data)

        self.assertEqual(200, res.status_code)
        self.assertEqual(2, BlacklistedFraudster.objects.count())
        self.assertEqual(self.user.id, BlacklistedFraudster.objects.first().added_by_id)


class TestFraudApplicationList(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = GroupFactory(name='fraudops')
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        ApplicationPathTagStatusFactory(application_tag='is_revive_mtl', status=1)

    @pytest.mark.skip(reason="Flaky caused by 29 Feb")
    def test_show_115(self):
        invalid_applications = ApplicationJ1Factory.create_batch(
            2,
            application_status=StatusLookupFactory(status_code=115),
        )
        valid_buckets = FraudApplicationBucketFactory.create_batch(2)
        url = reverse('fraud_security:app-bucket-list', kwargs={'bucket_type': 'selfie_in_geohash'})
        res = self.client.get(url)

        self.assertEqual(200, res.status_code)
        for valid_bucket in valid_buckets:
            self.assertContains(res, valid_bucket.application.customer.email)

        for application in invalid_applications:
            self.assertNotContains(res, application.customer.email)


class TestDeviceIdentityView(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.customer = CustomerFactory()
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.application.customer = CustomerFactory(user=self.user)
        self.application.save()
        self.data = {
            "julo_device_id": "abc123def"
        }

    @patch('juloserver.julo.models.Device.objects.create')
    def test_post_success_response(self, mock_device_objects_create):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        expected_response = {
                "success": True,
                "data": {
                    "message": "Success store device identity"
                },
                "errors": []
            }
        request_body = self.data
        response = self.client.post('/fraud_security/device-identity', request_body)
        mock_device_objects_create.return_value = None
        assert mock_device_objects_create.call_count == 1
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected_response)

    @patch('juloserver.julo.models.Device.objects.create')
    def test_failed_request_not_contain_julo_device_id(self, mock_device_objects_create):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.data = {}
        expected_response = {
                "success": False,
                "data": None,
                "errors": [
                    "julo_device_id is empty"
                ]
            }
        request_body = self.data
        response = self.client.post('/fraud_security/device-identity', request_body)
        mock_device_objects_create.return_value = None
        assert mock_device_objects_create.call_count == 0
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), expected_response)

    @patch('juloserver.julo.models.Device.objects.create')
    def test_failed_julo_device_id_empty(self, mock_device_objects_create):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.data = {
            'julo_device_id': ''
        }
        expected_response = {
                "success": False,
                "data": None,
                "errors": [
                    "julo_device_id is empty"
                ]
            }
        request_body = self.data
        response = self.client.post('/fraud_security/device-identity', request_body)
        mock_device_objects_create.return_value = None
        assert mock_device_objects_create.call_count == 0
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), expected_response)
