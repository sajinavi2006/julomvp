from __future__ import absolute_import
import mock
from django.test import TestCase
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
from juloserver.julo_privyid.tasks import upload_document_privy, update_data_privy_user
from ..services.privy_services import request_otp_to_privy


class TestPrivyTasks(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        # self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer)
        self.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.INACTIVE)
        self.loan = LoanFactory(
            customer=self.customer,
            application=self.application,
            loan_xid=1000200300,
            loan_status=self.loan_status,
        )
        self.privy_customer = PrivyCustomerFactory(
            customer=self.customer, privy_id="ABC123"
        )
        self.privy_document = PrivyDocumentFactory(
            privy_customer=self.privy_customer,
            application_id=self.application,
            loan_id=None,
        )

    @mock.patch("juloserver.julo_privyid.tasks.upload_document_to_privy")
    def test_upload_document_privy(self, mocked_upload_document):
        mocked_upload_document.return_value = self.privy_document
        return_value = upload_document_privy(self.application.id)
        self.assertTrue(return_value)
        mocked_upload_document.assert_called()

    @mock.patch("juloserver.julo_privyid.tasks.re_upload_privy_user_photo")
    def test_update_data_privy_user(self, mocked_reupload):
        mocked_reupload.return_value = True
        return_value = update_data_privy_user(self.application.id)
        self.assertTrue(return_value)
        mocked_reupload.assert_called()

    @mock.patch("juloserver.julo_privyid.services.privy_services.request_otp_to_privy")
    @mock.patch("juloserver.julo_privyid.services.privy_services.get_otp_token_privy")
    @mock.patch(
        "juloserver.julo_privyid.clients.privy.JuloPrivyClient.request_otp_token"
    )
    def test_request_otp_to_privy(self, mocked_otp, mocked_get, mocked_request):
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
        api_data["response_status_code"] = 201
        mocked_otp.return_value = ({}, api_data)
        return_value = request_otp_to_privy("token", self.loan, self.privy_customer)
        self.assertTrue(return_value)
        mocked_otp.assert_called()

        api_data["response_status_code"] = 400
        mocked_otp.return_value = ({}, api_data)
        mocked_get.return_value = None
        mocked_request.return_value = True
        return_value = request_otp_to_privy("token", self.loan, self.privy_customer)
        self.assertTrue(return_value)
        mocked_request.assert_called()
        mocked_get.assert_called()
