import json
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from juloserver.api_token.models import ExpiryToken as Token
from juloserver.julo.tests.factories import (
    AuthUserFactory, CustomerFactory, ApplicationFactory, FeatureSettingFactory
)
from juloserver.historical.models import BioSensorHistory


class TestStoreBioSensorHistory(APITestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_application_notfound(self):
        data = [dict(
            accelerometer_data=[1, 2, 3],
            gyroscope_data=[0, 2, 4],
            gravity_data=[5, 5, 5],
            rotation_data=[0, 4, 5],
            orientation='1',
            al_activity='2',
            al_fragment='HomePage',
            created_at='2022-05-09 17:00:00'
        )]
        result = self.client.post('/api/historical/v1/bio-sensor-histories',
                                  data={'application_id': 99999999999, 'histories': data})
        assert result.status_code == 404

    def test_store_success(self):
        data = {
            'application_id': self.application.id,
            'histories': [
                {
                    'accelerometer_data': [1, 2, 3],
                    'gyroscope_data': [0, 2, 4],
                    'gravity_data': [5, 5, 5],
                    'rotation_data': [0, 4, 5],
                    'orientation': '1',
                    'al_activity': '2',
                    'al_fragment': 'HomePage',
                    'created_at': '2022-05-09 17:00:00'
                }
            ]
        }
        result = self.client.post('/api/historical/v1/bio-sensor-histories',
                                  json.dumps(data), content_type='application/json')
        assert result.status_code == 200
        data = BioSensorHistory.objects.filter(application_id=self.application.id)
        assert len(data) == 1


class TestPreStoreBioSensorHistory(APITestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.token, created = Token.objects.get_or_create(user=self.user_auth)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)

    def test_feature_off(self):
        # feature off
        result = self.client.get('/api/historical/v1/pre-bio-sensor-histories')
        assert result.status_code == 200
        assert result.json()['data']['is_active'] == False
        # parameters are null
        FeatureSettingFactory(
            is_active=True,
            feature_name='bio-sensor_history'
        )
        result = self.client.get('/api/historical/v1/pre-bio-sensor-histories')
        assert result.status_code == 200
        assert result.json()['data']['is_active'] == False

    def test_feature_on(self):
        # parameters are null
        FeatureSettingFactory(
            is_active=True,
            feature_name='bio_sensor_history',
            parameters={
                'scrape_period': 5
            }
        )
        result = self.client.get('/api/historical/v1/pre-bio-sensor-histories')
        assert result.status_code == 200
        assert result.json()['data'] == {'is_active': True, 'config': {'scrape_period': 5}}
