from future import standard_library
standard_library.install_aliases()
from urllib.parse import urlencode

from django.test import TestCase
from django.test import Client

from django.contrib.auth.models import User
from django.test import override_settings

from juloserver.julo.tests.factories import FeatureSettingFactory

testing_middleware = [
    'django_cookies_samesite.middleware.CookiesSameSite',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # 3rd party middleware classes
    'juloserver.julo.middleware.DeviceIpMiddleware',
    'cuser.middleware.CuserMiddleware',
    'juloserver.julocore.restapi.middleware.ApiLoggingMiddleware',
    'juloserver.standardized_api_response.api_middleware.StandardizedApiURLMiddleware']


@override_settings(MIDDLEWARE=testing_middleware)
class TestAdmin2(TestCase):

    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.special_event_config = FeatureSettingFactory(
            feature_name='special_event_binary')

    def test_get_feature_setting_from(self):
        res = self.client.get(
            '/xgdfat82892ddn/julo/featuresetting/%s/change/' % self.special_event_config.id)
        assert res.status_code == 200

    def test_update_special_feature_setting_case_1(self):
        data = urlencode({
            "is_active": "on",
            "province": "DI Yogyakarta",
            "min_age": "",
            "max_age": "55",
            "job_type": "Pengusaha",
            "job_industry": "Entertainment / Event",
            "job_description": "Admin",
        })
        response = self.client.post(
            "/xgdfat82892ddn/julo/featuresetting/%s/change/" % self.special_event_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 302

    def test_update_special_feature_setting_case_2(self):
        self.special_event_config.parameters = {"job_industry": ["Design / Seni"]}
        self.special_event_config.save()
        data = urlencode({
            "is_active": "on",
            "province": "DI Yogyakarta",
            "min_age": "",
            "max_age": "55",
            "job_type": "Pengusaha",
            "job_industry": "Entertainment / Event",
            "job_description": "Admin",
        })
        response = self.client.post(
            "/xgdfat82892ddn/julo/featuresetting/%s/change/" % self.special_event_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 302

    def test_update_special_feature_setting_case_3(self):
        data = urlencode({
            "is_active": "on",
            "province": "DI Yogyakarta",
            "min_age": "56",
            "max_age": "55",
            "job_type": "Pengusaha",
            "job_industry": "Entertainment / Event",
            "job_description": "Admin",
        })
        response = self.client.post(
            "/xgdfat82892ddn/julo/featuresetting/%s/change/" % self.special_event_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200
