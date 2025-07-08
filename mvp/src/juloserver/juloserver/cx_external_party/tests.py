from datetime import date, datetime, timedelta

from django.test.testcases import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from mock import patch
from rest_framework.test import APIClient

from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.cx_external_party.crypto import ApiCrypto, get_crypto
from juloserver.cx_external_party.models import CXExternalParty
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    ApplicationNoteFactory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
)


class TestAPIToken(TestCase):
    CX_FERNET_SECRET_KEY = "HqVYhGBZwsHylv-MaEJ674Aa8yzxscmVr7BXWw58VtY="

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def setUp(self):
        self.client = APIClient()
        self.keyword_auth = "Api-Key "
        _, key = CXExternalParty.api_key.create_api_key(name="test")
        self.client.credentials(HTTP_AUTHORIZATION=self.keyword_auth + key)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_create_api_token(self):
        obj = CXExternalParty.api_key.create_api_key(name="julo")
        self.assertIsNotNone(obj)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_generate_api_token(self):
        payload = {
            "_pk": 1,
            "_name": "test",
            "_exp": None,
        }
        key = ApiCrypto().generate(payload)
        self.assertIsNotNone(key)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_assign_user_token(self):
        payload = {
            "api_key": "123456abcde",
            "identifier": "test",
            "user_exp": None,
        }
        key = ApiCrypto().assign_user_token(payload)
        self.assertIsNotNone(key)

    @override_settings(CX_FERNET_SECRET_KEY=None)
    def test_secret_key_not_defined(self):
        payload = {
            "_pk": 1,
            "_name": "test",
            "_exp": None,
        }
        with self.assertRaisesMessage(KeyError, "A CX Fernet Secret is not defined."):
            ApiCrypto().generate(payload)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_decrypt_api_token(self):
        payload = {
            "_pk": 1,
            "_name": "test",
            "_exp": None,
        }
        key = ApiCrypto().generate(payload)
        data = ApiCrypto().decrypt(key)
        self.assertEqual(payload, data)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_generate_user_token(self):
        self.user_auth = AuthUserFactory(email="test@julofinance.com", is_staff=True)
        data = {'identifier': self.user_auth.email}
        response = self.client.post('/api/cx-external-party/user-token/', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_failed_not_found_generate_user_token(self):
        data = {'identifier': "test@julofinance.com"}
        response = self.client.post('/api/cx-external-party/user-token/', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.data["errors"][0]["identifier"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_failed_domain_invalid_generate_user_token(self):
        data = {'identifier': "test@test.com"}
        response = self.client.post('/api/cx-external-party/user-token/', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.data["errors"][0]["identifier"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_generate_user_token_without_identifier(self):
        data = {'identifier': ""}
        response = self.client.post('/api/cx-external-party/user-token/', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.data["errors"][0]["identifier"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_generate_user_token_invalid_user_exp(self):
        data = {'identifier': "test@julofinance.com", 'user_exp': "1710305297"}
        response = self.client.post('/api/cx-external-party/user-token/', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.data["errors"][0]["user_exp"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_generate_user_token_invalid_identifier(self):
        data = {'identifier': "123456789", 'user_exp': "1710305297"}
        response = self.client.post('/api/cx-external-party/user-token/', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIsNotNone(response.data["errors"][0]["identifier"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_detail_external_info(self):
        response = self.client.get('/api/cx-external-party/info/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    @patch(
        'juloserver.cx_external_party.authentication.CXAPIKeyAuthentication._authenticate_credentials'
    )
    def test_not_found_detail_external_info(self, mock_creds):
        mock_creds.return_value = None, None
        response = self.client.get('/api/cx-external-party/info/')
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(response.data["data"])


class TestExternalAPIToken(TestCase):
    CX_FERNET_SECRET_KEY = "HqVYhGBZwsHylv-MaEJ674Aa8yzxscmVr7BXWw58VtY="

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth, nik="123456789123")
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)

        self.client = APIClient()
        _, key = CXExternalParty.api_key.create_api_key(name="test")

        today = timezone.localtime(timezone.now()).replace(tzinfo=None).replace(microsecond=0)
        user_expiry_date = today + timedelta(days=1)
        exp_timestamp = datetime.strptime(str(user_expiry_date), "%Y-%m-%d %H:%M:%S").timestamp()
        payload = {"api_key": key, "identifier": "test@julofinance.com", "user_exp": exp_timestamp}
        _, user_token = get_crypto().assign_user_token(payload)

        self.keyword_auth = "Api-Key "
        self.client.credentials(HTTP_AUTHORIZATION=self.keyword_auth + user_token)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_detail_user_info(self):
        response = self.client.get('/api/cx-external-party/user-detail/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_customer_info(self):
        ApplicationFactory(customer=self.customer, account=self.account)
        params = "nik={}&email={}".format(self.customer.nik, self.customer.email)
        response = self.client.get('/api/cx-external-party/customer-info/?' + params)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_failed_customer_info_nik_not_found(self):
        ApplicationFactory(customer=self.customer, account=self.account)
        params = "nik={}&email={}".format('', self.customer.email)
        response = self.client.get('/api/cx-external-party/customer-info/?' + params)
        self.assertEqual(response.status_code, 400)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_not_found_customer_info(self):
        ApplicationFactory(customer=self.customer, account=self.account)
        params = "nik={}&email={}".format('123456789', self.customer.email)
        response = self.client.get('/api/cx-external-party/customer-info/?' + params)
        self.assertEqual(response.status_code, 404)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    @patch('juloserver.cx_external_party.services.get_customer')
    def test_not_found_application_customer_info(self, mock_customer):
        mock_customer.return_value = self.customer
        params = "nik={}&email={}".format('123456789', self.customer.email)
        response = self.client.get('/api/cx-external-party/customer-info/?' + params)
        self.assertEqual(response.status_code, 404)

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_security_info(self):
        ApplicationFactory(customer=self.customer, account=self.account)
        params = "nik={}&email={}".format(self.customer.nik, self.customer.email)
        response = self.client.get('/api/cx-external-party/security-info/?' + params)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_verify_document(self):
        ApplicationFactory(customer=self.customer, account=self.account)
        params = "nik={}&email={}".format(self.customer.nik, self.customer.email)
        response = self.client.get('/api/cx-external-party/app-document-verify-info/?' + params)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_customer_loan(self):
        ApplicationFactory(customer=self.customer, account=self.account)
        LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
        )
        params = "nik={}&email={}&use_case=loan_amount".format(
            self.customer.nik, self.customer.email
        )
        response = self.client.get('/api/cx-external-party/loan-data/?' + params)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_customer_account_payment(self):
        ApplicationFactory(customer=self.customer, account=self.account)
        LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
        )
        AccountPaymentFactory(account=self.account, due_date=date.today() + timedelta(days=4))
        params = "nik={}&email={}&use_case=due_date".format(self.customer.nik, self.customer.email)
        response = self.client.get('/api/cx-external-party/account-payment-data/?' + params)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_success_last_application_status(self):
        application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_status=StatusLookupFactory(status_code=190),
        )
        application_history = ApplicationHistoryFactory(
            application_id=application.id, status_old=190, status_new=191
        )
        ApplicationNoteFactory(
            application_id=application.id,
            added_by=self.user_auth,
            application_history_id=application_history.id,
        )
        params = "nik={}&email={}&use_case=due_date".format(self.customer.nik, self.customer.email)
        response = self.client.get('/api/cx-external-party/user-application-status/?' + params)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["data"]['application_last_history'])
        self.assertIsNotNone(response.data["data"]['application_note'])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_last_application_status_no_application(self):
        params = "nik={}&email={}&use_case=due_date".format(self.customer.nik, self.customer.email)
        response = self.client.get('/api/cx-external-party/user-application-status/?' + params)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["errors"][0], "Application not found.")
        self.assertIsNone(response.data["data"])

    @override_settings(CX_FERNET_SECRET_KEY=CX_FERNET_SECRET_KEY)
    def test_last_application_status_no_history_note(self):
        ApplicationFactory(
            customer=self.customer,
            account=self.account,
            application_status=StatusLookupFactory(status_code=190),
        )
        params = "nik={}&email={}&use_case=due_date".format(self.customer.nik, self.customer.email)
        response = self.client.get('/api/cx-external-party/user-application-status/?' + params)
        self.assertEqual(response.status_code, 200)
        self.assertDictEqual(response.data["data"]['application_last_history'], {})
        self.assertDictEqual(response.data["data"]['application_note'], {})
