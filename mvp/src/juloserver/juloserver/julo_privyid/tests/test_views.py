import json
import mock
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from .factories import PrivyCustomerFactory, PrivyDocumentFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    LoanFactory,
    StatusLookupFactory,
)
from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.statuses import LoanStatusCodes


class TestPrivyViews(APITestCase):
    def setUp(self):
        self.client = APIClient()
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
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.user.auth_expiry_token.key)

    @mock.patch("juloserver.julo_privyid.views.check_customer_status")
    def test_customer_status_view(self, mocked_status):
        mocked_status.return_value = {
            "privy_status": "verified",
            "is_privy_mode": True,
            "is_failover_active": False,
            "failed": False,
        }
        res = self.client.get("/api/julo_privy/v1/customer-status-privy/")
        self.assertEqual(res.status_code, 200)
        mocked_status.assert_called()

    @mock.patch("juloserver.julo_privyid.views.check_document_status_for_upload")
    def test_document_status_view(self, mocked_status):
        mocked_status.return_value = ("In Progress", True, False)
        res = self.client.get(
            "/api/julo_privy/v1/document-status-privy/" "{}/".format(self.loan.loan_xid)
        )
        self.assertEqual(res.status_code, 200)
        mocked_status.assert_called()

    @mock.patch("juloserver.julo_privyid.views.upload_document_privy_service")
    def test_document_upload_view(self, mocked_status):
        body = {"loan_xid": self.loan.loan_xid, "max_count": 3, "retry_count": 1}
        mocked_status.return_value = None
        res = self.client.post(
            "/api/julo_privy/v1/document-upload-privy/",
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        mocked_status.assert_called()

    @mock.patch("juloserver.julo_privyid.views.request_otp_privy_service")
    def test_request_otp_view(self, mocked_status):
        body = {"loan_xid": self.loan.loan_xid}
        mocked_status.return_value = "9567971575"
        res = self.client.post(
            "/api/julo_privy/v1/request-otp-privy/",
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        mocked_status.assert_called()

    @mock.patch("juloserver.julo_privyid.views.confirm_otp_privy_service")
    def test_confirm_otp_view(self, mocked_status):
        body = {"loan_xid": self.loan.loan_xid, "otp_code": "1234"}
        mocked_status.return_value = None
        res = self.client.post(
            "/api/julo_privy/v1/confirm-otp-privy/",
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        mocked_status.assert_called()

    @mock.patch("juloserver.julo_privyid.views.sign_document_privy_service")
    def test_document_sign_view(self, mocked_status):
        body = {"loan_xid": self.loan.loan_xid}
        mocked_status.return_value = None
        res = self.client.post(
            "/api/julo_privy/v1/document-sign-privy/",
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        mocked_status.assert_called()

    @mock.patch("juloserver.julo_privyid.views.get_failover_feature")
    @mock.patch("juloserver.julo_privyid.views.get_privy_feature")
    def test_feature_settings_view(self, mocked_privy, mocked_failover):
        mocked_privy.return_value = True
        mocked_failover.return_value = False
        res = self.client.get("/api/julo_privy/v1/feature-status/")
        self.assertEqual(res.status_code, 200)
        mocked_privy.assert_called()
        mocked_failover.assert_called()


class TestPrivyLegacyViews(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            customer=self.customer, loan_xid=1000200300, loan_status=self.loan_status
        )
        self.privy_customer = PrivyCustomerFactory(
            customer=self.customer, privy_id="ABC123"
        )
        self.privy_document = PrivyDocumentFactory(
            privy_customer=self.privy_customer, application_id=self.application
        )
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.user.auth_expiry_token.key)

    @mock.patch(
        "juloserver.julo_privyid.views.update_digital_signature_face_recognition"
    )
    @mock.patch("juloserver.julo_privyid.views.check_status_privy_user")
    @mock.patch("juloserver.julo_privyid.views.get_failover_feature")
    @mock.patch("juloserver.julo_privyid.views.get_privy_feature")
    def test_customer_status(
        self, mocked_privy, mocked_failover, mocked_status, mocked_update_face
    ):
        mocked_privy.return_value = True
        mocked_failover.return_value = False
        mocked_status.return_value = (self.privy_customer, {'code': 200})
        mocked_update_face.return_value = None
        res = self.client.get("/api/julo_privy/v1/customer-status/")
        self.assertEqual(res.status_code, 200)
        mocked_privy.assert_called()
        mocked_failover.assert_called()
        mocked_status.assert_called()
        mocked_update_face.assert_called()

    @mock.patch("juloserver.julo_privyid.views.check_privy_document_status")
    @mock.patch("juloserver.julo_privyid.views.get_failover_feature")
    @mock.patch("juloserver.julo_privyid.views.get_privy_feature")
    def test_document_status(self, mocked_privy, mocked_failover, mocked_status):
        mocked_privy.return_value = True
        mocked_failover.return_value = False
        mocked_status.return_value = self.privy_document
        res = self.client.get("/api/julo_privy/v1/document-status/")
        self.assertEqual(res.status_code, 200)
        mocked_privy.assert_called()
        mocked_failover.assert_called()
        mocked_status.assert_called()

    @mock.patch("juloserver.julo_privyid.views.request_otp_to_privy")
    @mock.patch("juloserver.julo_privyid.views.get_otp_token")
    def test_request_otp(self, mocked_get_token, mocked_request_token):
        mocked_get_token.return_value = "token"
        mocked_request_token.return_value = True
        res = self.client.post("/api/julo_privy/v1/request-otp/")
        self.assertEqual(res.status_code, 200)
        mocked_get_token.assert_called()
        mocked_request_token.assert_called()

    @mock.patch("juloserver.julo_privyid.views.confirm_otp_to_privy")
    @mock.patch("juloserver.julo_privyid.views.get_otp_token")
    def test_confirm_otp(self, mocked_get_token, mocked_confirm_token):
        mocked_get_token.return_value = "token"
        body = {"otp_code": "1234"}
        mocked_confirm_token.return_value = True
        res = self.client.post(
            "/api/julo_privy/v1/confirm-otp/",
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        mocked_get_token.assert_called()
        mocked_confirm_token.assert_called()

    @mock.patch("juloserver.julo_privyid.views.get_otp_token")
    @mock.patch("juloserver.julo_privyid.views.check_privy_document_status")
    @mock.patch("juloserver.julo_privyid.views.proccess_signing_document")
    def test_sign_document(self, mocked_sign, mocked_status, mocked_token):
        mocked_sign.return_value = self.privy_document
        mocked_status.return_value = None
        mocked_token.return_value = "token"
        res = self.client.post("/api/julo_privy/v1/document-sign/")
        self.assertEqual(res.status_code, 200)
        mocked_sign.assert_called()
        mocked_status.assert_called()
        mocked_token.assert_called()

    @mock.patch("juloserver.julo_privyid.views.get_privy_document_data")
    @mock.patch("juloserver.julo_privyid.views.upload_document_privy.delay")
    def test_document_upload(self, mocked_status, mocked_get):
        body = {"max_count": 3, "retry_count": 1}
        mocked_status.return_value = None
        res = self.client.post(
            "/api/julo_privy/v1/document-upload/",
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        mocked_get.return_value = None
        res = self.client.post(
            "/api/julo_privy/v1/document-upload/",
            data=json.dumps(body),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        mocked_status.assert_called()
