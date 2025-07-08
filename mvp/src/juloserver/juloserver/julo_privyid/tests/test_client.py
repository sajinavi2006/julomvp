import mock
from django.test import TestCase
from juloserver.julo_privyid.clients.privy import JuloPrivyClient
from juloserver.julo_privyid.clients.privyid import JuloPrivyIDClient
from .factories import PrivyCustomerFactory, PrivyDocumentFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
    ImageFactory
)
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.account.tests.factories import AccountFactory


class TestPrivyClient(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account
        )
        self.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_xid=1000200300,
            loan_status=self.loan_status,
        )
        self.privy_customer = PrivyCustomerFactory(
            customer=self.customer, privy_id="ABC123"
        )
        self.privy_document = PrivyDocumentFactory(
            privy_customer=self.privy_customer, application_id=None, loan_id=self.loan
        )

        self.client = JuloPrivyClient(
            "base_url",
            "merchant_key",
            "username",
            "secret_key",
            "enterprise_token",
            "enterprise_id",
        )
        self.client1 = JuloPrivyIDClient(
            "base_url",
            "merchant_key",
            "username",
            "secret_key",
            "enterprise_token",
            "enterprise_id",
        )

    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.make_request")
    def test_register_status(self, mocked_request):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "email": "rufina+waiverr603@julofinance.com",
                "phone": "+628147536408",
                "status": "waiting",
                "userToken": "Token",
            },
            "message": "Waiting for Verification",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        mocked_request.return_value = api_data
        token = self.privy_customer.privy_customer_token
        return_data, return_api_data = self.client.register_status(token)
        mocked_request.assert_called_once()
        self.assertDictEqual(return_data, api_data["response_json"]["data"])
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.make_request")
    def test_document_status(self, mocked_request):
        api_data = dict()
        api_data["response_json"] = {
            "code": 200,
            "data": {
                "title": "DEVPR2779_3000008063.pdf",
                "docToken": "docToken",
                "recipients": [
                    {
                        "type": "Signer",
                        "privyId": "DEV-JU1612",
                        "signedAt": None,
                        "signatoryStatus": "In Progress",
                    },
                    {
                        "type": "Signer",
                        "privyId": "DEVPR2779",
                        "signedAt": None,
                        "signatoryStatus": "In Progress",
                    },
                ],
                "urlDocument": "UrlDoc",
                "documentStatus": "In Progress",
            },
            "message": "Successfully get a status document",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        token = self.privy_document.privy_document_token
        mocked_request.return_value = api_data
        return_data, return_api_data = self.client.get_document_status(token)
        mocked_request.assert_called_once()
        self.assertDictEqual(return_data, api_data["response_json"]["data"])
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.make_request")
    def test_upload_document(self, mocked_request):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "docToken": "docToken",
                "recipients": [
                    {
                        "type": "Signer",
                        "privyId": "DEV-JU1612",
                        "enterpriseToken": "token",
                    },
                    {"type": "Signer", "privyId": "DEVPR0130", "enterpriseToken": None},
                ],
                "urlDocument": "urlDoc",
            },
            "message": "Document successfully upload and shared",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        mocked_request.return_value = api_data
        return_data, return_api_data = self.client.upload_document(
            self.privy_customer.privy_id, self.loan.id
        )
        mocked_request.assert_called_once()
        self.assertDictEqual(return_data, api_data["response_json"]["data"])
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.make_request")
    def test_create_token(self, mocked_request):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "token": "Token",
                "created_at": "2020-11-30T09:53:49.000+07:00",
                "expired_at": "2020-12-02T09:53:49.000+07:00",
            },
            "message": "User token successfully created",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        mocked_request.return_value = api_data
        return_data, return_api_data = self.client.create_token(
            self.privy_customer.privy_id
        )
        mocked_request.assert_called_once()
        self.assertDictEqual(return_data, api_data["response_json"]["data"])
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.make_request")
    def test_request_otp_token(self, mocked_request):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {},
            "message": "OTP sent to +628778483xxxx",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        mocked_request.return_value = api_data
        return_data, return_api_data = self.client.request_otp_token("token")
        mocked_request.assert_called_once()
        self.assertDictEqual(return_data, api_data["response_json"]["data"])
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.make_request")
    def test_confirm_otp_token(self, mocked_request):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {},
            "message": "OTP sent to +628778483xxxx",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        mocked_request.return_value = api_data
        otp_code = "1234"
        return_data, return_api_data = self.client.confirm_otp_token(otp_code, "token")
        mocked_request.assert_called_once()
        self.assertDictEqual(return_data, api_data["response_json"]["data"])
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.make_request")
    def test_sign_document(self, mocked_request):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "document": [
                    {
                        "title": "DEVBR5893_3.pdf",
                        "docToken": "docToken",
                        "templateId": "juloPOA001",
                    }
                ],
                "documentStatus": "Completed",
            },
            "message": "Document successfully sign",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        mocked_request.return_value = api_data
        return_data, return_api_data = self.client.sign_document(
            [self.privy_document.privy_document_token], "token"
        )
        mocked_request.assert_called_once()
        self.assertIsNone(return_data)
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch("juloserver.julo_privyid.clients.privy.requests.post")
    def test_make_request(self, mocked_request):
        request_path = "/registration/status"
        request_type = "post"
        request_data = {"token": "user_token"}
        response_data = {
            "code": 201,
            "data": {
                "email": "rufina+waiverr604@julofinance.com",
                "phone": "+6282213480074",
                "status": "waiting",
                "userToken": "token",
            },
            "message": "Waiting for Verification",
        }
        magic_mock = mock.MagicMock()
        magic_mock.raise_for_status.return_value = None
        magic_mock.json.return_value = response_data
        mocked_request.return_value = magic_mock

        return_api_data = self.client.make_request(
            request_path, request_type, data=request_data
        )
        mocked_request.assert_called()

    @mock.patch('juloserver.julo_privyid.clients.privy.open')
    @mock.patch('juloserver.julo_privyid.clients.privy.ImageReader.open')
    @mock.patch('juloserver.julo_privyid.clients.privy.urllib.request.urlopen')
    @mock.patch('juloserver.julo_privyid.clients.privy.BytesIO')
    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.send_request")
    def test_register(self, mocked_request, mocked_string_io, mocked_url,
                      mocked_image, mocked_open):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "email": "rufina+waiverr603@julofinance.com",
                "phone": "+628147536408",
                "status": "waiting",
                "userToken": "Token",
            },
            "message": "Waiting for Verification",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        images_1 = ImageFactory(image_source=self.application.id, image_type="ktp_self",
                                image_status=0)
        images_2 = ImageFactory(image_source=self.application.id, image_type="crop_selfie",
                                image_status=0)
        mocked_open.return_value = mock.MagicMock(spec=open)
        mocked = mock.MagicMock()
        mocked.read.return_value = u'hello'
        mocked_string_io.return_value = b'Test_Binary'
        mocked_magic = mock.MagicMock()
        mocked_magic.save.return_value = None
        mocked_image.return_value = mocked_magic
        mocked_request.return_value = api_data
        token = self.privy_customer.privy_customer_token
        mocked_url.return_value = mocked
        return_api_data = self.client.register(self.application)
        mocked_request.assert_called_once()
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch('juloserver.julo_privyid.clients.privy.open')
    @mock.patch('juloserver.julo_privyid.clients.privy.ImageReader.open')
    @mock.patch('juloserver.julo_privyid.clients.privy.urllib.request.urlopen')
    @mock.patch('juloserver.julo_privyid.clients.privy.BytesIO')
    @mock.patch("juloserver.julo_privyid.clients.privy.JuloPrivyClient.make_request")
    def test_reregister(self, mocked_request, mocked_string_io, mocked_url,
                        mocked_image, mocked_open):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "email": "rufina+waiverr603@julofinance.com",
                "phone": "+628147536408",
                "status": "waiting",
                "userToken": "Token",
            },
            "message": "Waiting for Verification",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        api_data["response_status_code"] = 200
        images_1 = ImageFactory(image_source=self.application.id, image_type="ktp_self_ops",
                                image_status=0)
        mocked_open.return_value = mock.MagicMock(spec=open)
        mocked = mock.MagicMock()
        mocked.read.return_value = u'hello'
        mocked_string_io.return_value = b'Test_Binary'
        mocked_magic = mock.MagicMock()
        mocked_magic.save.return_value = None
        mocked_image.return_value = mocked_magic
        mocked_request.return_value = api_data
        token = self.privy_customer.privy_customer_token
        mocked_url.return_value = mocked
        _, return_api_data = self.client.reregister_photos('ktp',
                                                        self.privy_customer.privy_customer_token,
                                                        self.application.id,
                                                        images_1)
        mocked_request.assert_called_once()
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch('juloserver.julo_privyid.clients.privyid.open')
    @mock.patch('juloserver.julo_privyid.clients.privyid.ImageReader.open')
    @mock.patch('juloserver.julo_privyid.clients.privyid.urllib.request.urlopen')
    @mock.patch('juloserver.julo_privyid.clients.privyid.BytesIO')
    @mock.patch("juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request")
    def test_register_legacy(self, mocked_request, mocked_string_io, mocked_url,
                      mocked_image, mocked_open):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "email": "rufina+waiverr603@julofinance.com",
                "phone": "+628147536408",
                "status": "waiting",
                "userToken": "Token",
            },
            "message": "Waiting for Verification",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        images_1 = ImageFactory(image_source=self.application.id, image_type="ktp_self_ops",
                                image_status=0)
        images_2 = ImageFactory(image_source=self.application.id, image_type="crop_selfie",
                                image_status=0)
        mocked_open.return_value = mock.MagicMock(spec=open)
        mocked = mock.MagicMock()
        mocked.read.return_value = u'hello'
        mocked_string_io.return_value = b'Test_Binary'
        mocked_magic = mock.MagicMock()
        mocked_magic.save.return_value = None
        mocked_image.return_value = mocked_magic
        mocked_request.return_value = api_data
        token = self.privy_customer.privy_customer_token
        mocked_url.return_value = mocked
        return_api_data = self.client1.registration_proccess(self.application)
        mocked_request.assert_called_once()
        self.assertDictEqual(return_api_data, api_data)

    @mock.patch('juloserver.julo_privyid.clients.privyid.open')
    @mock.patch('juloserver.julo_privyid.clients.privyid.ImageReader.open')
    @mock.patch('juloserver.julo_privyid.clients.privyid.urllib.request.urlopen')
    @mock.patch('juloserver.julo_privyid.clients.privyid.BytesIO')
    @mock.patch("juloserver.julo_privyid.clients.privyid.JuloPrivyIDClient.send_request")
    def test_reregister_legacy(self, mocked_request, mocked_string_io, mocked_url,
                      mocked_image, mocked_open):
        api_data = dict()
        api_data["response_json"] = {
            "code": 201,
            "data": {
                "email": "rufina+waiverr603@julofinance.com",
                "phone": "+628147536408",
                "status": "waiting",
                "userToken": "Token",
            },
            "message": "Waiting for Verification",
        }
        api_data["request_params"] = {
            "url": "URL",
            "data": {"token": "Token"},
            "files": None,
            "params": None,
            "headers": {"Merchant-Key": "Key"},
        }
        images_1 = ImageFactory(image_source=self.application.id, image_type="ktp_self_ops",
                                image_status=0)
        mocked_open.return_value = mock.MagicMock(spec=open)
        mocked = mock.MagicMock()
        mocked.read.return_value = u'hello'
        mocked_string_io.return_value = b'Test_Binary'
        mocked_magic = mock.MagicMock()
        mocked_magic.save.return_value = None
        mocked_image.return_value = mocked_magic
        mocked_request.return_value = api_data
        token = self.privy_customer.privy_customer_token
        mocked_url.return_value = mocked
        return_api_data = self.client1.reregistration_photos(
            'ktp', self.privy_customer.privy_customer_token, self.application.id)
        mocked_request.assert_called_once()
        self.assertDictEqual(return_api_data, api_data)