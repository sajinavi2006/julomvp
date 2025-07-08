import mock
from mock import ANY, patch
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from django.test.utils import override_settings

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
)
from juloserver.autodebet.clients import AutodebetXenditClient
from juloserver.pin.tests.factories import TemporarySessionFactory


def mock_request_xendit(method, request_path, data, account=None, headers=None):
    if request_path == '/customers':
        data = {
            "id": "239c16f4-866d-43e8-9341-7badafbc019f",
            "reference_id": "demo_1475801962607",
            "email": "customer@website.com",
            "mobile_number": None,
            "given_names": "John",
            "description": None,
            "middle_name": None,
            "surname": None,
            "phone_number": None,
            "nationality": None,
            "addresses": None,
            "date_of_birth": None,
            "metadata": None
        }
    elif request_path == '/linked_account_tokens/auth':
        data = {
            "id": "lat-aa620619-124f-41db-995b-66a52abe036a",
            "customer_id": "ba830b92-4177-476e-b097-2ad5ae4d3e55",
            "channel_code": "DC_BRI",
            "authorizer_url": None,
            "status": "SUCCESS",
            "metadata": None
        }
    else:
        data = {
            "id": "lat-aa620619-124f-41db-995b-66a52abe036a",
            "customer_id": "239c16f4-866d-43e8-9341-7badafbc019f",
            "channel_code": "DC_BRI",
            "status": "SUCCESS"
        }

    return data, None


@override_settings(BROKER_BACKEND = 'memory')
class TestRegisterBRIApi(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)

    def create_bri_account(self):
        data = {
            "user_email" : "lorem@gmail.com",
            "user_phone" : "0812348320",
            "card_number" : "1234",
            "expired_date" : "05/24"
        }
        res = self.client.post('/api/autodebet/bri/v1/registration', data=data)

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_activate_BRI_account(self, mock_send_request):
        data = {
            "user_email" : "lorem@gmail.com",
            "user_phone" : "0812348320",
            "card_number" : "1234",
            "expired_date" : "05/24"
        }
        res = self.client.post('/api/autodebet/bri/v1/registration', data=data)
        assert res.status_code == 200

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_verify_activate_BRI_otp_account(self, mock_send_request):
        self.create_bri_account()
        data = {
            "otp" : "123456"
        }
        res = self.client.post('/api/autodebet/bri/v1/otp/verify/activation', data=data)
        assert res.status_code == 200

    @patch.object(AutodebetXenditClient, 'send_request', side_effect=mock_request_xendit)
    def test_verify_activate_BRI_otp_account(self, mock_send_request):
        data = {
            "otp" : "123456"
        }
        res = self.client.post('/api/autodebet/bri/v1/otp/verify/activation', data=data)
        assert res.status_code == 400


class TestDeactivationBRIApi(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)

    @patch('juloserver.autodebet.views.views_bri_api_v1.process_bri_account_revocation')
    def test_deactiveation_bri(self, mock_process_bri_account_revocation):
        session_token = TemporarySessionFactory(user=self.user)
        data = {
            "session_token" : session_token.access_key,
            'require_expire_session_token': True
        }
        mock_process_bri_account_revocation.return_value = None
        res = self.client.post('/api/autodebet/bri/v1/deactivation', data=data)
        self.assertEqual(res.status_code, 200)
        session_token.refresh_from_db()
        self.assertEqual(session_token.is_locked, False)  # No need to check session token again
