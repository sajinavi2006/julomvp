from future import standard_library
standard_library.install_aliases()
from urllib.parse import urlencode

from django.test.testcases import TestCase
from django.test import Client

from django.contrib.auth.models import User
from django.test import override_settings

from juloserver.julo.tests.factories import PartnerFactory, GlobalPaymentMethodFactory
from juloserver.julo.tests.factories import ProductLookupFactory
from juloserver.julo.tests.factories import PartnerOriginationDataFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import ProductLine

from juloserver.cootek.tests.factories import CootekConfigurationFactory

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
class TestCootekConfig(TestCase):

    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.bl_partner = PartnerFactory(name='bukalapak_paylater')
        self.client.login(username=self.username, password=self.password)

    def test_get_cootek_admin(self):
        res = self.client.get('/xgdfat82892ddn/cootek/cootekconfiguration/')
        assert res.status_code == 200

    def test_get_cootek_from(self):
        cootek_config = CootekConfigurationFactory()
        res = self.client.get('/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/' % cootek_config.id)
        assert res.status_code == 200

    def test_get_cootek_from_post_case_1(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Exactly',
            'called_at': 0,
            'called_to': '',
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '%s' % cootek_config.cootek_robot.id,
            'tag_status': 'A',
            'loan_ids': '1',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200

    def test_get_cootek_from_post_case_2(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Exactly',
            'called_at': -1,
            'called_to': '',
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '%s' % cootek_config.cootek_robot.id,
            'tag_status': 'A',
            'loan_ids': '1',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200

    def test_get_cootek_from_post_case_3(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': self.bl_partner.id,
            'criteria': '',
            'dpd_condition': 'Exactly',
            'called_at': -2,
            'called_to': '',
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '%s' % cootek_config.cootek_robot.id,
            'tag_status': 'A',
            'loan_ids': '1',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200

    def test_get_cootek_from_post_case_4(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Exactly',
            'called_at': -2,
            'called_to': '',
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '',
            'tag_status': 'A',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200

    def test_get_cootek_from_post_case_5(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Exactly',
            'called_at': -1,
            'called_to': '',
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '',
            'tag_status': 'A',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200

    def test_get_cootek_from_post_case_6(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Exactly',
            'called_at': 0,
            'called_to': '',
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '',
            'tag_status': 'A',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200

    def test_get_cootek_from_post_case_7(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Exactly',
            'called_at': 2,
            'called_to': 1,
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '',
            'tag_status': 'All',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200

    def test_get_cootek_from_post_case_8(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Range',
            'called_at': 2,
            'called_to': 'df',
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '',
            'tag_status': 'A',
            'loan_ids': '12-10'
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200


    def test_get_cootek_from_post_case_9(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Range',
            'called_at': 2,
            'called_to': 1,
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '',
            'tag_status': 'A',
            'loan_ids': '12-abc'
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200


    def test_get_cootek_from_post_case_10(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Range',
            'called_at': 2,
            'called_to': '',
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '',
            'tag_status': 'A',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200


    def test_get_cootek_from_post_case_10(self):
        cootek_config = CootekConfigurationFactory()
        data = urlencode({
            'strategy_name': 'asda',
            'partner': '',
            'criteria': '',
            'dpd_condition': 'Range',
            'called_at': '',
            'called_to': 2,
            'time_to_start': '14:49:17',
            'number_of_attempts': 1,
            'cootek_robot': '',
            'tag_status': 'A',
        })
        response = self.client.post(
            "/xgdfat82892ddn/cootek/cootekconfiguration/%s/change/" % cootek_config.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200


@override_settings(MIDDLEWARE=testing_middleware)
class TestGlobalPaymentMethod(TestCase):

    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)

    def test_get_payment_method_view_admin(self):

        res = self.client.get('/xgdfat82892ddn/julo/globalpaymentmethod/')
        assert res.status_code == 200

    def test_get_payment_method_view_from(self):
        payment_method = GlobalPaymentMethodFactory(
            feature_name='BCA 1', is_active=True, is_priority=True, impacted_type='Primary',
            payment_method_code='001')
        res = self.client.get('/xgdfat82892ddn/julo/globalpaymentmethod/%s/change/' % payment_method.id)
        assert res.status_code == 200

    def test_update_payment_method_view(self):
        payment_method = GlobalPaymentMethodFactory(
            feature_name='BCA 2', is_active=True, is_priority=True, impacted_type='Primary',
            payment_method_code='002')

        data = urlencode({
            'is_active': 'on',
            'impacted_type': 'Primary',
            'is_priority': 'on',
            'parameters': ''
        })
        response = self.client.post(
            "/xgdfat82892ddn/julo/globalpaymentmethod/%s/change/" % payment_method.id,
            data, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 302


class TestPartnerOrginationDataAdmin(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'jerr123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.partner_origination_data = PartnerOriginationDataFactory()
        self.partner = PartnerFactory(name='axiata')
        self.partner_origination_data.partner = self.partner
        self.partner_origination_data.save()
        self.product_lookup = ProductLookupFactory()
        self.product_lookup.origination_fee_pct = self.partner_origination_data.origination_fee
        self.product_lookup.product_line = ProductLine.objects.get_or_none(
            product_line_code=ProductLineCodes.AXIATA1)
        self.product_lookup.save()

    def test_partner_origination_data_admin(self):
        res = self.client.get('/xgdfat82892ddn/julo/partneroriginationdata/{}/change/'.format(
            self.partner_origination_data.id
        ))
        assert res.status_code == 200

    def test_partner_origination_data_admin_save(self):
        data = {
            'interest_rate': 0.75,
            'admin_fee': 11000,
            '_save': 'Save'
        }
        res = self.client.post('/xgdfat82892ddn/julo/partneroriginationdata/{}/change/'.format(
            self.partner_origination_data.id), data=data,
            content_type="application/x-www-form-urlencoded")
        assert res.status_code == 200

    def test_partner_origination_data_add(self):
        data = {
            'origination_fee': 0.001,
            'interest_rate': 10,
            'admin_fee': 200,
            'partner': self.partner.id,
            '_save': 'Save'
        }
        res = self.client.post('/xgdfat82892ddn/julo/partneroriginationdata/add/',
                               data=data, content_type="application/x-www-form-urlencoded")
        assert res.status_code == 200
