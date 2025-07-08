from datetime import timedelta

from django.test import Client, TestCase
from django.conf import settings
from unittest.mock import patch

from django.utils import timezone


from juloserver.fraud_security.constants import FraudApplicationBucketType
from juloserver.fraud_security.tests.factories import FraudApplicationBucketFactory
from juloserver.geohash.models import AddressGeolocationGeohash
from juloserver.geohash.tests.factories import AddressGeolocationGeohashFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    AddressGeolocationFactory,
    FeatureSettingFactory,
    ImageFactory,
)
from app_status.services import fraudops_dashboard
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from django.contrib.auth.models import Group

# Create your tests here.


class AjaxFraudShowSimilarFacesTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.BO_DATA_VERIFIER)
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.client.force_login(self.user)
        ApplicationHistoryFactory(application_id=self.application.id, status_new=105)
        self.address_geolocation = AddressGeolocationFactory(application=self.application)
        self.address_geolocation_geohash = AddressGeolocationGeohashFactory(
            address_geolocation=self.address_geolocation,
            geohash6='efg007', geohash8="abc123", geohash9="xyz789")
        self.image = ImageFactory(
            image_type="selfie", image_source=self.application.pk,
            url="test.jpg")

        self.user_1 = AuthUserFactory()
        self.customer_1 = CustomerFactory(user=self.user_1)
        self.application_1 = ApplicationJ1Factory(customer=self.customer_1)
        ApplicationHistoryFactory(application_id=self.application_1.id, status_new=105)
        self.address_geolocation_1 = AddressGeolocationFactory(application=self.application_1)
        self.address_geolocation_geohash_1 = AddressGeolocationGeohashFactory(
            address_geolocation=self.address_geolocation_1,
            geohash6='efg007', geohash8="abc123", geohash9="xyz789")
        self.image_1 = ImageFactory(
            image_type="selfie", image_source=self.application_1.pk,
            url="test_1.jpg")
        self.selfie_geohash_crm_image_limit_feature_setting = FeatureSettingFactory(
            feature_name='selfie_geohash_crm_image_limit',
            parameters={'days': 1},
            is_active=False,
        )

    def _generate_application_geohash(
        self,
        geohash6='efg007',
        geohash8="abc123",
        geohash9="xyz789",
        image_url='test_1.jpg'
    ):
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        application = ApplicationJ1Factory(customer=customer)
        ApplicationHistoryFactory(application_id=application.id, status_new=105)
        address_geolocation = AddressGeolocationFactory(application=application)
        AddressGeolocationGeohashFactory(
            address_geolocation=address_geolocation,
            geohash8=geohash8, geohash9=geohash9, geohash6=geohash6)
        image = ImageFactory(
            image_type="selfie", image_source=application.pk,
            url=image_url)
        return application, image

    def test_ajax_fraud_show_similar_faces(self):
        response = self.client.get(
            '/app_status/ajax_fraud_show_similar_faces/',
            {'application_id': self.application_1.pk, 'type': 'geohash8'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['content-type'], 'application/json')
        self.assertIn('data', response.json())
        self.assertEqual(response.json()['geohash6'], 'efg007')
        self.assertEqual(response.json()['geohash8'], 'abc123')
        self.assertEqual(response.json()['geohash9'], 'xyz789')
        self.assertEqual(len(response.json()['data']), 1)

        # Assert data
        self.assertEqual(response.json()['data'][0]['application_id'], self.application.pk)
        self.assertIn(
            'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/test.jpg?OSSAccessKeyId=',
            response.json()['data'][0]['url'],
        )

        # Assert current current_selfie_data
        self.assertEqual(
            response.json()['current_selfie_data']['application_id'],
            self.application_1.pk,
        )
        self.assertIn(
            'https://julofiles-localhost.oss-ap-southeast-5.aliyuncs.com/test_1.jpg?OSSAccessKeyId=',
            response.json()['current_selfie_data']['url'],
        )

    def test_ajax_fraud_show_similar_faces_duplicate_application(self):
        application, image = self._generate_application_geohash()
        ApplicationHistoryFactory(application_id=application.id, status_new=105)
        response = self.client.get(
            '/app_status/ajax_fraud_show_similar_faces/',
            {'application_id': self.application_1.pk, 'type': 'geohash8', 'limit': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['content-type'], 'application/json')
        self.assertIn('data', response.json())
        self.assertEqual(response.json()['geohash6'], 'efg007')
        self.assertEqual(response.json()['geohash8'], 'abc123')
        self.assertEqual(response.json()['geohash9'], 'xyz789')
        self.assertEqual(len(response.json()['data']), 2, response.json()['data'])

    def test_ajax_fraud_show_similar_faces_no_selfie_image(self):
        application, image = self._generate_application_geohash()
        image.delete()
        response = self.client.get(
            '/app_status/ajax_fraud_show_similar_faces/',
            {'application_id': self.application_1.pk, 'type': 'geohash8', 'limit': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['content-type'], 'application/json')
        self.assertIn('data', response.json())
        self.assertEqual(response.json()['geohash6'], 'efg007')
        self.assertEqual(response.json()['geohash8'], 'abc123')
        self.assertEqual(response.json()['geohash9'], 'xyz789')
        self.assertEqual(len(response.json()['data']), 2)
        self.assertEqual(response.json()['data'][1]['url'], '/images/icons/ic-placeholder.png')

    def test_ajax_fraud_show_similar_faces_jturbo_j1(self):
        application, image = self._generate_application_geohash()
        application.update_safely(product_line_id=ProductLineCodes.TURBO)
        response = self.client.get(
            '/app_status/ajax_fraud_show_similar_faces/',
            {'application_id': self.application_1.pk, 'type': 'geohash8', 'limit': 2}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['content-type'], 'application/json')
        self.assertIn('data', response.json())
        self.assertEqual(response.json()['geohash6'], 'efg007')
        self.assertEqual(response.json()['geohash8'], 'abc123')
        self.assertEqual(response.json()['geohash9'], 'xyz789')
        self.assertEqual(len(response.json()['data']), 2, response.json()['data'])

    def test_ajax_fraud_show_similar_faces_bad_request(self):
        response = self.client.post('/app_status/ajax_fraud_show_similar_faces/')
        self.assertEqual(response.status_code, 405)

    def test_ajax_fraud_show_similar_faces_invalid_params(self):
        response = self.client.get('/app_status/ajax_fraud_show_similar_faces/', {'type': 'geohash8'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response['content-type'], 'application/json')
        self.assertIn('message', response.json())
        self.assertEqual(response.json()['message'], 'Please enter a valid Params')

    def test_ajax_fraud_show_similar_faces_invalid_type(self):
        response = self.client.get(
            '/app_status/ajax_fraud_show_similar_faces/', {'application_id': self.application_1.pk, 'type': 'invalid_type'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response['content-type'], 'application/json')
        self.assertIn('message', response.json())
        self.assertEqual(response.json()['message'], 'Please use a valid type')

    def test_ajax_fraud_show_similar_faces_application_not_found(self):
        response = self.client.get('/app_status/ajax_fraud_show_similar_faces/', {'application_id': 999, 'type': 'geohash8'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response['content-type'], 'application/json')
        self.assertIn('message', response.json())
        self.assertEqual(response.json()['message'], 'Application not found')

    def test_selfie_geohash_crm_image_limit_feature_setting_is_on(self):
        self.selfie_geohash_crm_image_limit_feature_setting.update_safely(is_active=True)
        self.application.update_safely(
            cdate=timezone.localtime(timezone.now()).date() - timedelta(days=2),
        )
        self.image.update_safely(
            cdate=timezone.localtime(timezone.now()).date() - timedelta(days=2),
        )
        response = self.client.get(
            '/app_status/ajax_fraud_show_similar_faces/',
            {'application_id': self.application_1.pk, 'type': 'geohash8'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['content-type'], 'application/json')
        self.assertIn('data', response.json())
        self.assertEqual(response.json()['geohash6'], 'efg007')
        self.assertEqual(response.json()['geohash8'], 'abc123')
        self.assertEqual(response.json()['geohash9'], 'xyz789')
        self.assertEqual(len(response.json()['data']), 0)


class TestFraudopsDashboard(TestCase):
    def test_empty(self):
        ret_val = fraudops_dashboard()
        expected_result = {
            'to_do': {
                'velocity_model_geohash': 0,
                'selfie_in_geohash': 0,
            },
            'label': [
                '115: Velocity - Geohash',
                '115: Selfie in Geohash',
            ]
        }
        self.assertEqual(expected_result, ret_val)

    def test_count_selfie_in_geohash(self):
        FraudApplicationBucketFactory.create_batch(
            1,
            type=FraudApplicationBucketType.SELFIE_IN_GEOHASH,
            is_active=True,
        )
        FraudApplicationBucketFactory.create_batch(
            3,
            type=FraudApplicationBucketType.SELFIE_IN_GEOHASH,
            is_active=False,
        )
        FraudApplicationBucketFactory.create_batch(
            5,
            type=FraudApplicationBucketType.VELOCITY_MODEL_GEOHASH,
            is_active=True,
        )
        ret_val = fraudops_dashboard()
        self.assertEqual(1, ret_val['to_do']['selfie_in_geohash'])
