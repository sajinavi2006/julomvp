from __future__ import print_function
from builtins import str
from collections import OrderedDict

import mock
from mock import MagicMock, patch
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from django.utils import timezone
from django.test import TestCase, override_settings
from datetime import (
    time,
    timedelta,
    datetime,
)
from django.conf import settings
import json

from juloserver.integapiv1.authentication import CommProxyAuthentication
from juloserver.julo.tests.factories import LenderFactory
from juloserver.account.models import AccountTransaction
from juloserver.disbursement.constants import DisbursementVendors
from juloserver.disbursement.tasks import process_callback_from_ayoconnect
from juloserver.disbursement.tests.factories import NameBankValidationFactory, DisbursementFactory
from juloserver.grab.tests.factories import GrabLoanDataFactory
from juloserver.julo.models import (
    VoiceCallRecord,
    PaybackTransaction,
    FeatureNameConst,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    LoanFactory,
    PaymentFactory,
    CashbackTransferTransactionFactory,
    WorkflowFactory,
    ProductLineFactory,
    ProductLookupFactory,
    LenderFactory,
    CustomerFactory,
    PartnerFactory,
    StatusLookupFactory,
    AuthUserFactory,
    PaymentMethodFactory,
    AccountingCutOffDateFactory,
    PaybackTransactionFactory,
    FeatureSettingFactory,
)
from juloserver.julo.models import StatusLookup
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountLimitFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tasks import update_payment_status_subtask
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.integapiv1.services import AyoconnectBeneficiaryCallbackService
from juloserver.grab.models import (
    PaymentGatewayVendor,
    PaymentGatewayCustomerData, PaymentGatewayTransaction
)
from juloserver.account.constants import AccountConstant
from juloserver.disbursement.constants import AyoconnectBeneficiaryStatus
from rest_framework.status import (HTTP_400_BAD_REQUEST,
                                   HTTP_404_NOT_FOUND,
                                   HTTP_200_OK)
from juloserver.disbursement.exceptions import AyoconnectCallbackError
from juloserver.integapiv1.constants import (
    BCA_SNAP_PARTNER_NAME,
    EXPIRY_TIME_TOKEN_BCA_SNAP,
    SnapVendorChoices,
    FaspaySnapInquiryResponseCodeAndMessage,
)
from juloserver.integapiv1.services import (
    generate_snap_expiry_token,
    generate_snap_signature,
    faspay_generate_string_to_sign,
)
from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from unittest.mock import (
    ANY,
    MagicMock,
)
from juloserver.autodebet.constants import FeatureNameConst as AutoDebetFeatureNameConst
from juloserver.integapiv1.utils import generate_signature_asymmetric
from juloserver.minisquad.constants import DialerSystemConst
from juloserver.minisquad.models import DialerTask
from juloserver.julo.constants import FeatureNameConst

client = APIClient()

PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAxbPcN5FesqsJS0qVjEjwKG9Z1qpEh1TAOesK3D4L2uQnUJlD
l4645xMdVZaF/E3CxX7hc6XgbP9XUMi0rY97d5IChGyRo+kZ+R6q2FhAtaScaxrO
pYtRBnLpIjeL6RVR3BNs9Wdf6XU8lGOUz0qQzWsjwWuUyzJnEiZsrzZokOco8xdy
LM8PkdXHnxW23tHKptfG1fzY5ExWLelDMsWiyzU0xOReaCPFBwRjL6vbrASjBcVX
yUvFfxQlSP1oQrC7XyrV3OwviwagEg7KheXS80wcafTA1MiowmmEZk5J/VrN6AvB
j/12HnLUoAj4WantfGeUEFZn0NlV2+6WTYh13wIDAQABAoIBAB1QFqWyixzomR8t
ttCu+9Sy9doLMs/x8/JidCDFnlJdI6sink/5XFb+kYngIIuRKADKWDkibg0bKuIS
cB+Pt5m571+dDVcFN9GlB2W+aBHGj16eAeevqVrQbNqi676qZ5G+25fjNOhTdqD1
xtmZT7D1Yr7J6azbE0cwpUqxQX3CVXhUh20FEN/p0Ef81a1JLecAcJaFxEmPJQhm
tgMMG8QqVUjwaOCLf81TWnK3zPMvGBBDFR9gU4R7Qq/5ZckJffhA/kudtL/CDwy/
/s44qjyX2rXOpfPxFqOHW5qunJxKZkPnbRmfQN/s/kSbjEUwgPl9G2CoXXr0CHfw
Etbm3/kCgYEA80OAGmWWB3lEMZ67V4MOG5mwyrJAQsKq87IHNIpbMUXcz2zdlEA3
uQcFJs5UuCoBTR0JG+TE/za40wpdyZBBuX7Wjlz2NUYuwQTM++7cWXoLCWTgtW5c
u6uvdyV2FNrWMSGrvNmOhwKAGzbjpkKTzIrLKhC+8PBQPd0UCMBx1+sCgYEA0A2y
lzQzlLPv0acrkLNXREtYXgpvgRlYtT9SQJARvicoQCm+0YHvW3Z+zp9nbdRDRRCe
X9DjHlxpW+hCrdWSQe3YcMstbOmj0UcwlrSO2aDSpugP96AXSfDQyNUw2kw/yHlm
w0TZJXSUAb1nX0vWFAjfOt9TOcX3NQd0VoQPMN0CgYAr5XhOSxqBir5lfdEsf3ei
P1+JlBTIdzxF8VAfiP/fqk2oGGr7f4MOnletovniqaHGeoDUSbnKm+NKIcq+vos9
n8eztM6w2lNBfU5H/9g/RSiMr2llE98j9l0ZUOc36C1SfFLzJwbzEd5wCr2VmNn2
xOzYUGFENPkl0Kj201M3tQKBgHPzvl3QxRKSOg0hWwFZQkCYsVYwALb1ll/lO4Uq
BglxL1ibK3L+NJVH9CJZ6r3mN9uNCIckFwA7xqhnSIozZkECOseaJOX3TMp9H5JO
bPLTU7Ob0BJVEcWuxd24G3L+Xenv5xrbCx5522cg1TTiQhyGWUspXevr7fuK/Qae
sQytAoGBAIAKpwbx6UlqoxIkVh6VdQx5/C1u8M8FU3f65B1io44roRZZxtcLHLOX
4hiNn3MvsQ1zlsfmwMKN/nrpoiBMbYTT+BVw+u4YlhCGbmxEBD4iYVnm7d754Q/q
Av8FuKlGob2FxcDOvXdaFAbNsN9fMufOQlZqX3Sc2AY5YCGr2Mll
-----END RSA PRIVATE KEY-----"""

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxbPcN5FesqsJS0qVjEjw
KG9Z1qpEh1TAOesK3D4L2uQnUJlDl4645xMdVZaF/E3CxX7hc6XgbP9XUMi0rY97
d5IChGyRo+kZ+R6q2FhAtaScaxrOpYtRBnLpIjeL6RVR3BNs9Wdf6XU8lGOUz0qQ
zWsjwWuUyzJnEiZsrzZokOco8xdyLM8PkdXHnxW23tHKptfG1fzY5ExWLelDMsWi
yzU0xOReaCPFBwRjL6vbrASjBcVXyUvFfxQlSP1oQrC7XyrV3OwviwagEg7KheXS
80wcafTA1MiowmmEZk5J/VrN6AvBj/12HnLUoAj4WantfGeUEFZn0NlV2+6WTYh1
3wIDAQAB
-----END PUBLIC KEY-----"""


class TestEmailEventCallbackView(APITestCase):
    def test_delivery_status_received(self):
        """"""

        # Create a fake SmsHistory

        # Call the API to update the status
        pass

    def test_requred_params_missing(self):
        """"""
        pass

    def test_message_id_not_found(self):
        """"""
        pass


class JuloNexmoRobocallClient(APIClient):
    def send_request(self, identifier, dtmf):
        url = '/api/integration/v1/callbacks/voice-call/ptp_payment_reminder/{}/'.format(identifier)
        data = {
            "dtmf": dtmf,
            "conversation_uuid": "5efe6463-e994-4b3d-b4bf-33a4f62a4472"
        }
        return self.post(url, data, format='json')


class TestNexmoVoice(APITestCase):
    client_class = JuloNexmoRobocallClient

    def setUp(self):
        self.voice_record = VoiceCallRecord.objects.create(
            conversation_uuid="5efe6463-e994-4b3d-b4bf-33a4f62a4472")
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.voice_record1 = VoiceCallRecord.objects.create(
            conversation_uuid="5efe6463-e994-4b3d-b4bf-33a4f62a4472")
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer
        )
        self.application1 = ApplicationFactory(
            customer=self.customer,
            account=self.account
        )
        self.loan1 = LoanFactory(
            account=self.account,
            customer=self.customer,
            application=self.application1
        )
        self.account_payment = AccountPaymentFactory(account=self.account)

    def test_nexmo_input_webhook_1(self):
        response = self.client.send_request(str(self.payment.id), dtmf=None)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_nexmo_input_webhook_2(self):
        response = self.client.send_request(str(self.payment.id), dtmf='1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_nexmo_input_webhook_3(self):
        response = self.client.send_request(str(76757665), dtmf='1')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nexmo_input_webhook_4(self):
        response = self.client.send_request(str(self.account_payment.id), dtmf='1')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class JuloGopayMidtransEventCallbackViewClient(APIClient):
    def send_request(self, transfer_status, reference_no):
        url = '/api/integration/v1/callbacks/gopay-cashback'
        data = {
            'reference_no': reference_no,
            'status': transfer_status
        }
        print('send here')
        return self.post(url, data, format='json')


class TestGopayMidtransEventCallbackView(APITestCase):
    client_class = JuloGopayMidtransEventCallbackViewClient

    def setUp(self):
        pass

    @patch('juloserver.integapiv1.views.GopayService')
    def test_success(self, mock_gopay_service):
        transfer_id = '111111'
        CashbackTransferTransactionFactory(transfer_id=transfer_id)
        response = self.client.send_request('completed', transfer_id)
        mock_gopay_service().process_refund_cashback_gopay.assert_called_once()
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class JuloAyoconnectDisbursementClient(APIClient):
    def send_request(self, data):
        url = '/api/integration/v1/callbacks/ayoconnect/disbursement'
        return self.post(url, data, format='json')

    def get_body_success_1(self):
        body = {
            "code": 201,
            "message": "ok",
            "responseTime": "20220308090632",
            "transactionId": "159ouooehqg0x6bwmf83odql0mesh45g",
            "referenceNumber": "f4377dfe8f0843aa915e201173b1d922",
            "customerId": "AYOCON-7WJMOA",
            "details": {
                "A-Correlation-ID": "E4uxpHFwkWsgHqMWpa0anKXGBCHu3f7j",
                "amount": "10001.00",
                "currency": "IDR",
                "status": 1,
                "beneficiaryId": "BE_5369559683",
                "remark": "DISBURSEMENT",
                "transactionReferenceNumber": "c7f8903db5c24b55b4f648efe57a0d1d"
            }
        }
        return body

    def get_body_success_0(self):
        body = {
            "code": 201,
            "message": "ok",
            "responseTime": "20221122080132",
            "transactionId": "hSt5dfPPhByNCDDSc2g4GXDvGghJVWar",
            "referenceNumber": "e014a3b8960842c99b09a6cd82560e15",
            "customerId": "AYOCON-11U7HJ6Y",
            "details": {
                "A-Correlation-ID": "Cx4FMLSQ3ySqR28emPmuTYFw9zijMSPF",
                "amount": "10000",
                "currency": "IDR",
                "status": 0,
                "beneficiaryId": "BE_476a580c78",
                "remark": "Testing",
                "transactionReferenceNumber": "c7f8903db5c24b55b4f648efe57a0d1d"
            }
        }
        return body

    def get_body_failure_4(self):
        body = {
            "code": 503,
            "message": "service.unavailable",
            "responseTime": "20221128124910",
            "transactionId": "Fouov4JuUp1G8Wd4NoJwXwFACTEzCza0",
            "referenceNumber": "7b338707c6aa4fd3b09167703eb8ada8",
            "customerId": "AYOCON-AN6U8FF4",
            "details": {
                "A-Correlation-ID": "4yK92IwrqAzAWvwUc12OXHFDjXxIrcnT",
                "amount": "10500",
                "currency": "IDR",
                "status": 4,
                "beneficiaryId": "BE_6216d5ee00",
                "remark": "DISBURSEMENT",
                "transactionReferenceNumber": "90b5a636950e45b284514f336b21ab66",
                "errors": [
                    {
                        "code": "0401",
                        "message": "error.validator.0401",
                        "details": "Account does not have sufficient balance"
                    }
                ],
            },
        }
        return body

    def get_body_success_with_failed_status(self):
        body = {
            "code": 503,
            "message": "service.unavailable",
            "responseTime": "20230904130422",
            "transactionId": "pn9U64lCsv9lPQNVLJHKhISe6MHNPaOU",
            "referenceNumber": "6b0197b04aaa4eeb94bd84d8271a5a6e",
            "customerId": "AYOCON-1352B3X2",
            "details": {
                "A-Correlation-ID": "RZFvJPj8p9NvPrXaGiETDukOmb07zvAj",
                "amount": "11500.00",
                "currency": "IDR",
                "status": 4,
                "beneficiaryId": "BE_53983d9d34",
                "remark": "DISBURSEMENT",
                "transactionReferenceNumber": "6b0197b04aaa4eeb94bd84d8271a5a6e",
                "errors": [
                    {
                        "code": "0201",
                        "message": "error.internal.0201",
                        "details": "Internal server error. Please check with Ayoconnect Team.",
                    }
                ],
            },
        }
        return body

    def get_body_success_with_failed_system_under_maintenance(self):
        body = {
            "code": 503,
            "message": "service.unavailable",
            "responseTime": "20230904130422",
            "transactionId": "pn9U64lCsv9lPQNVLJHKhISe6MHNPaOX",
            "referenceNumber": "6b0197b04aaa4eeb94bd84d8271a5a6X",
            "customerId": "AYOCON-1352B3X1",
            "details": {
                "A-Correlation-ID": "RZFvJPj8p9NvPrXaGiETDukOmb07zvAX",
                "amount": "11500.00",
                "currency": "IDR",
                "status": 4,
                "beneficiaryId": "BE_53983d9d31",
                "remark": "DISBURSEMENT",
                "transactionReferenceNumber": "6b0197b04aaa4eeb94bd84d8271a5a6X",
                "errors": [
                    {
                        "code": "0924",
                        "message": "error.validator.0924",
                        "details": "System under maintenance. Please reach out to customer support for further assistance.",
                    }
                ],
            },
        }
        return body


class TestAyoconnectDisbursement(APITestCase):
    client_class = JuloAyoconnectDisbursementClient

    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name=GRAB_ACCOUNT_LOOKUP_NAME
        )
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.account_limit = AccountLimitFactory(account=self.account)
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.GRAB)
        self.application_status_code = StatusLookupFactory(code=190)
        self.partner = PartnerFactory(name="grab")
        self.application = ApplicationFactory(
            customer=self.customer,
            product_line=self.product_line,
            account=self.account,
            application_status=self.application_status_code,
            workflow=self.workflow
        )
        self.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        self.product_lookup = ProductLookupFactory(
            product_line=self.product_line, admin_fee=40000)
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='HELLOQWE')
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=self.loan_status,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=6)),
            application=None
        )
        self.grab_loan_data = GrabLoanDataFactory(
            loan=self.loan,
        )
        payments = self.loan.payment_set.all()

        for idx, payment in enumerate(payments):
            payment.due_date = timezone.localtime(timezone.now()) + timedelta(
                days=idx - 3)
            update_payment_status_subtask(payment.id)
            payment.is_restructured = False
            payment.account_payment = AccountPaymentFactory(
                due_date=timezone.localtime(timezone.now()) + timedelta(days=idx + 3),
                account=self.account
            )
            payment.account_payment.is_restructured = True
            payment.save()
        self.disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT
        )

        WorkflowFactory(name='LegacyWorkflow')
        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")

    @mock.patch('juloserver.integapiv1.views.process_callback_from_ayoconnect.delay')
    def test_ayoconnect_disbursement_api_callback_view_success(self, mocked_processing):
        transaction_id = self.client.get_body_success_1()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        correlation_id = self.client.get_body_success_1().get("details").get("A-Correlation-ID")
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        mocked_processing.return_value = None
        response = self.client.send_request(data=self.client.get_body_success_1())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disbursement.refresh_from_db()
        mocked_processing.assert_called()

    @mock.patch('juloserver.integapiv1.views.process_callback_from_ayoconnect.delay')
    def test_ayoconnect_disbursement_api_callback_view_pending(self, mocked_processing):
        transaction_id = self.client.get_body_success_0()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        correlation_id = self.client.get_body_success_0().get("details").get("A-Correlation-ID")
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        mocked_processing.return_value = None
        response = self.client.send_request(data=self.client.get_body_success_0())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disbursement.refresh_from_db()
        mocked_processing.assert_called()

    def test_ayoconnect_disbursement_api_callback_view_failed_not_found(self):
        transaction_id = self.client.get_body_failure_4()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        response = self.client.send_request(data=self.client.get_body_failure_4())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        disbursement.refresh_from_db()

    @mock.patch('juloserver.integapiv1.views.process_callback_from_ayoconnect.delay')
    def test_ayoconnect_disbursement_api_callback_view_missing_disbursement(self,
                                                                            mocked_processing):
        mocked_processing.return_value = None
        response = self.client.send_request(data=self.client.get_body_success_0())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @mock.patch('juloserver.loan.services.lender_related.'
                'trigger_submit_grab_disbursal_creation.delay')
    @mock.patch.object(AccountTransaction.objects, 'create')
    def test_process_callback_from_ayoconnect_success_1(self, mocked_object, mocked_capture_call):
        transaction_id = self.client.get_body_success_1()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        correlation_id = self.client.get_body_success_1().get("details").get("A-Correlation-ID")
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        mocked_object.return_value = None
        mocked_capture_call.return_value = None
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        self.loan.lender = LenderFactory()
        self.loan.disbursement_id = disbursement.id
        self.loan.save()
        process_callback_from_ayoconnect(self.client.get_body_success_1())
        self.loan.refresh_from_db()
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, 'COMPLETED')
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.CURRENT)
        mocked_object.assert_called()
        mocked_capture_call.assert_called()

    @mock.patch('juloserver.loan.services.lender_related.'
                'trigger_submit_grab_disbursal_creation.delay')
    def test_process_callback_from_ayoconnect_success_0(self, mocked_capture_call):
        transaction_id = self.client.get_body_success_0()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        correlation_id = self.client.get_body_success_0().get("details").get("A-Correlation-ID")
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        mocked_capture_call.return_value = None
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        self.loan.disbursement_id = disbursement.id
        self.loan.save()
        process_callback_from_ayoconnect(self.client.get_body_success_0())
        self.loan.refresh_from_db()
        disbursement.refresh_from_db()
        self.loan.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, 'PENDING')
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        mocked_capture_call.assert_not_called()

    @mock.patch('juloserver.integapiv1.views.process_callback_from_ayoconnect.delay')
    def test_ayoconnect_disbursement_api_callback_insufficient_balance(self, mocked_processing):
        from juloserver.integapiv1.serializers import AyoconnectDisbursementCallbackSerializer
        from juloserver.disbursement.constants import AyoconnectConst
        correlation_id = self.client.get_body_failure_4().get("details").get("A-Correlation-ID")
        transaction_id = self.client.get_body_failure_4().get("transactionId")
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        mocked_processing.return_value = None
        response = self.client.send_request(data=self.client.get_body_failure_4())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disbursement.refresh_from_db()
        mocked_processing.assert_called()

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=self.loan_status,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=6)),
            application=None
        )
        loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        loan.lender = LenderFactory()
        loan.disbursement_id = disbursement.id
        loan.save()

        serializer = AyoconnectDisbursementCallbackSerializer(data=self.client.get_body_failure_4())
        serializer.is_valid()
        data = serializer.validated_data

        process_callback_from_ayoconnect(data)
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.reason, AyoconnectConst.INSUFFICIENT_BALANCE_MESSAGE)

    @mock.patch(
        'juloserver.loan.services.lender_related.' 'trigger_submit_grab_disbursal_creation.delay'
    )
    @mock.patch.object(AccountTransaction.objects, 'create')
    @mock.patch(
        'juloserver.loan.services.loan_related.' 'handle_loan_prize_chance_on_loan_status_change'
    )
    def test_process_callback_from_ayoconnect_success_j1(
            self, mocked_prize, mocked_object, mocked_capture_call
    ):
        transaction_id = self.client.get_body_success_1()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING',
        )
        correlation_id = self.client.get_body_success_1().get("details").get("A-Correlation-ID")
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        self.workflow.name = "JuloOneWorkflow"
        self.workflow.save()
        self.loan.product.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.loan.product.save()
        mocked_prize.return_value = None
        mocked_object.return_value = None
        mocked_capture_call.return_value = None
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING
        )
        self.loan.lender = LenderFactory()
        self.loan.disbursement_id = disbursement.id
        self.loan.save()
        process_callback_from_ayoconnect(self.client.get_body_success_1())
        self.loan.refresh_from_db()
        disbursement.refresh_from_db()
        self.assertEqual(disbursement.disburse_status, 'COMPLETED')
        self.assertEqual(self.loan.loan_status_id, LoanStatusCodes.CURRENT)
        mocked_object.assert_called()
        mocked_capture_call.assert_not_called()

    @mock.patch(
        'juloserver.loan.services.lender_related.trigger_submit_grab_disbursal_creation.delay')
    @mock.patch.object(AccountTransaction.objects, 'create')
    def test_process_callback_from_ayoconnect_loan_220(self, mocked_object, mocked_capture_call):
        transaction_id = self.client.get_body_success_1()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        correlation_id = self.client.get_body_success_1().get("details").get("A-Correlation-ID")
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        mocked_object.return_value = None
        mocked_capture_call.return_value = None
        self.loan.loan_status = StatusLookupFactory(
            status_code=LoanStatusCodes.CURRENT)
        self.loan.lender = LenderFactory()
        self.loan.disbursement_id = disbursement.id
        self.loan.save()
        with self.assertRaises(AyoconnectCallbackError) as context:
            process_callback_from_ayoconnect(self.client.get_body_success_1())
        self.assertTrue("reach 220" in str(context.exception))
        mocked_object.assert_not_called()
        mocked_capture_call.assert_not_called()

    @mock.patch('juloserver.integapiv1.views.process_callback_from_ayoconnect.delay')
    def test_ayoconnect_disbursement_api_callback_multiple_callback_with_different_transaction_id(
            self, mocked_processing):
        transaction_id = self.client.get_body_success_0()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        correlation_id = self.client.get_body_success_0().get("details").get("A-Correlation-ID")
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        mocked_processing.return_value = None
        response = self.client.send_request(data=self.client.get_body_success_0())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disbursement.refresh_from_db()
        mocked_processing.assert_called()

        body_with_different_transaction_id = {
            "code": 201,
            "message": "ok",
            "responseTime": "20220308090632",
            "transactionId": "159ouooehqg0x6bwmf83odql0mesh45g",
            "referenceNumber": "f4377dfe8f0843aa915e201173b1d922",
            "customerId": "AYOCON-7WJMOA",
            "details": {
                "A-Correlation-ID": correlation_id,
                "amount": "10001.00",
                "currency": "IDR",
                "status": 1,
                "beneficiaryId": "BE_5369559683",
                "remark": "DISBURSEMENT",
                "transactionReferenceNumber": "c7f8903db5c24b55b4f648efe57a0d1d"
            }
        }

        response = self.client.send_request(data=body_with_different_transaction_id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disbursement.refresh_from_db()
        mocked_processing.assert_called()

    @mock.patch('juloserver.integapiv1.views.process_callback_from_ayoconnect.delay')
    def test_ayoconnect_disbursement_api_callback_multiple_callback_with_different_correlation_id(
            self, mocked_processing):
        transaction_id = self.client.get_body_success_0()['transactionId']
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING'
        )
        correlation_id = self.client.get_body_success_0().get("details").get("A-Correlation-ID")
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id
        )
        mocked_processing.return_value = None
        response = self.client.send_request(data=self.client.get_body_success_0())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disbursement.refresh_from_db()
        mocked_processing.assert_called()

        body_with_different_transaction_id = {
            "code": 201,
            "message": "ok",
            "responseTime": "20220308090632",
            "transactionId": transaction_id,
            "referenceNumber": "f4377dfe8f0843aa915e201173b1d922",
            "customerId": "AYOCON-7WJMOA",
            "details": {
                "A-Correlation-ID": "E4uxpHFwkWsgHqMWpa0anKXGBCHu3f7j",
                "amount": "10001.00",
                "currency": "IDR",
                "status": 1,
                "beneficiaryId": "BE_5369559683",
                "remark": "DISBURSEMENT",
                "transactionReferenceNumber": "c7f8903db5c24b55b4f648efe57a0d1d"
            }
        }

        response = self.client.send_request(data=body_with_different_transaction_id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        disbursement.refresh_from_db()
        mocked_processing.assert_called()

    @patch("juloserver.loan.tasks.lender_related.loan_disbursement_retry_task.apply_async")
    def test_ayoconnect_disbursement_api_callback_with_failed_status(self, mock_disbursement_retry):
        from juloserver.integapiv1.serializers import AyoconnectDisbursementCallbackSerializer
        from juloserver.disbursement.constants import AyoconnectConst

        correlation_id = (
            self.client.get_body_success_with_failed_status().get("details").get("A-Correlation-ID")
        )
        transaction_id = self.client.get_body_success_with_failed_status().get("transactionId")
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING',
        )
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id,
        )

        response = self.client.send_request(data=self.client.get_body_success_with_failed_status())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disbursement.refresh_from_db()

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=self.loan_status,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=6)),
            application=None,
        )
        loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        loan.lender = LenderFactory()
        loan.disbursement_id = disbursement.id
        loan.save()

        serializer = AyoconnectDisbursementCallbackSerializer(
            data=self.client.get_body_success_with_failed_status()
        )
        serializer.is_valid()
        data = serializer.validated_data

        process_callback_from_ayoconnect(data)
        disbursement.refresh_from_db()
        mock_disbursement_retry.assert_called_with(
            (ANY, AyoconnectConst.MAX_FAILED_RETRIES), eta=ANY
        )

    @patch("juloserver.loan.tasks.lender_related.loan_disbursement_retry_task.apply_async")
    def test_ayoconnect_disbursement_api_callback_with_failed_system_under_maintenance(
        self, mock_disbursement_retry
    ):
        from juloserver.integapiv1.serializers import AyoconnectDisbursementCallbackSerializer
        from juloserver.disbursement.constants import AyoconnectConst

        correlation_id = (
            self.client.get_body_success_with_failed_system_under_maintenance()
            .get("details")
            .get("A-Correlation-ID")
        )
        transaction_id = self.client.get_body_success_with_failed_system_under_maintenance().get(
            "transactionId"
        )
        disbursement = DisbursementFactory(
            name_bank_validation=self.name_bank_validation,
            method=DisbursementVendors.AYOCONNECT,
            disburse_id=transaction_id,
            disburse_status='PENDING',
        )
        PaymentGatewayTransaction.objects.create(
            disbursement_id=disbursement.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            correlation_id=correlation_id,
        )

        response = self.client.send_request(
            data=self.client.get_body_success_with_failed_system_under_maintenance()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        disbursement.refresh_from_db()

        loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            name_bank_validation_id=self.name_bank_validation.id,
            product=self.product_lookup,
            loan_status=self.loan_status,
            sphp_accepted_ts=timezone.localtime(timezone.now() - timedelta(days=6)),
            application=None,
        )
        loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING)
        loan.lender = LenderFactory()
        loan.disbursement_id = disbursement.id
        loan.save()

        serializer = AyoconnectDisbursementCallbackSerializer(
            data=self.client.get_body_success_with_failed_system_under_maintenance()
        )
        serializer.is_valid()
        data = serializer.validated_data

        process_callback_from_ayoconnect(data)
        disbursement.refresh_from_db()
        mock_disbursement_retry.assert_called_with(
            (ANY, AyoconnectConst.MAX_FAILED_RETRIES), eta=ANY
        )


class TestAyoconnectBeneficiaryCallbackView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/integration/v1/callbacks/ayoconnect/beneficiary"

        self.ayo_service = AyoconnectBeneficiaryCallbackService()
        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.workflow = WorkflowFactory(name='GrabWorkflow')
        self.application = ApplicationFactory(customer=self.customer, workflow=self.workflow)
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
            account_lookup=AccountLookupFactory(workflow=self.application.workflow)
        )

        self.ayoconnect_payment_gateway_vendor = PaymentGatewayVendor.objects.create(
            name="ayoconnect")

        self.beneficiary_id = "test123"
        self.external_customer_id = "JULO-XXI"
        self.payment_gateway_customer_data = PaymentGatewayCustomerData.objects.create(
            customer_id=self.customer.id,
            payment_gateway_vendor=self.ayoconnect_payment_gateway_vendor,
            beneficiary_id=self.beneficiary_id,
            external_customer_id=self.external_customer_id
        )

    def test_successful_callback(self):
        payload = {
            "code": 200,
            "customerId": self.external_customer_id,
            "details": {
                "beneficiaryId": self.beneficiary_id,
                "status": 1,
                "accountType": "testing"
            }
        }

        payment_gateway_customer_data = PaymentGatewayCustomerData.objects. \
            filter(beneficiary_id=self.beneficiary_id).last()
        self.assertIsNone(payment_gateway_customer_data.status)
        self.assertIsNone(payment_gateway_customer_data.account_type)
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, HTTP_200_OK)

        payment_gateway_customer_data = PaymentGatewayCustomerData.objects. \
            filter(beneficiary_id=self.beneficiary_id).last()
        self.assertEqual(payment_gateway_customer_data.status, AyoconnectBeneficiaryStatus.ACTIVE)
        self.assertEqual(payment_gateway_customer_data.account_type, "testing")

    def test_successful_callback_no_account_type(self):
        payload = {
            "code": 200,
            "customerId": self.external_customer_id,
            "details": {
                "beneficiaryId": self.beneficiary_id,
                "status": 1
            }
        }

        payment_gateway_customer_data = PaymentGatewayCustomerData.objects. \
            filter(beneficiary_id=self.beneficiary_id).last()
        self.assertIsNone(payment_gateway_customer_data.status)
        self.assertIsNone(payment_gateway_customer_data.account_type)
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, HTTP_200_OK)

        payment_gateway_customer_data = PaymentGatewayCustomerData.objects. \
            filter(beneficiary_id=self.beneficiary_id).last()
        self.assertEqual(payment_gateway_customer_data.status, AyoconnectBeneficiaryStatus.ACTIVE)
        self.assertIsNone(payment_gateway_customer_data.account_type)

    def test_successful_callback_beneficiary_id_not_found(self):
        payload = {
            "code": 200,
            "customerId": self.external_customer_id,
            "details": {
                "beneficiaryId": "not-exists-beneficiary-id",
                "status": 1
            }
        }
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, HTTP_404_NOT_FOUND)

    def test_successful_callback_invalid_payload(self):
        payloads = [
            {},
            {"code": "200"},
            {"code": 200, "details": {}},
            {"code": 200, "details": {"beneficiaryId": self.external_customer_id}},
            {"code": 200, "details": {"beneficiaryId": self.external_customer_id, "status": 1}}]

        n_error = [1, 3, 3, 2, 1]

        for index, payload in enumerate(payloads):
            resp = self.client.post(self.url, payload, format='json')
            self.assertEqual(resp.status_code, HTTP_400_BAD_REQUEST)
            self.assertEqual(n_error[index], len(resp.json()))

    @patch(
        "juloserver.integapiv1.views.AyoconnectBeneficiaryCallbackView.svc.process_unsuccess_callback")
    def test_unsuccessful_callback(self, mock_process_unsuccess_callback):
        mock_process_unsuccess_callback.return_value = True
        payload = {
            "code": 500,
            "customerId": self.external_customer_id,
            "details": {"beneficiaryId": self.beneficiary_id, "status": 1},
        }
        resp = self.client.post(self.url, payload, format='json')
        mock_process_unsuccess_callback.assert_called_once_with(self.external_customer_id, None)
        self.assertEqual(resp.status_code, HTTP_200_OK)

    @patch(
        "juloserver.integapiv1.views.AyoconnectBeneficiaryCallbackView.svc.process_unsuccess_callback"
    )
    def test_unsuccessful_callback_with_error_code(self, mock_process_unsuccess_callback):
        mock_process_unsuccess_callback.return_value = True
        payload = {
            "code": 503,
            "customerId": self.external_customer_id,
            "details": {
                "beneficiaryId": self.beneficiary_id,
                "status": 0,
                "errors": [
                    {
                        "code": "0924",
                        "message": "error.validator.0924",
                        "details": "System under maintenance.",
                    }
                ],
            },
        }
        resp = self.client.post(self.url, payload, format='json')
        mock_process_unsuccess_callback.assert_called_once_with(self.external_customer_id, "0924")
        self.assertEqual(resp.status_code, HTTP_200_OK)

    @patch(
        "juloserver.integapiv1.views.AyoconnectBeneficiaryCallbackView.svc.process_unsuccess_callback"
    )
    def test_unsuccessful_callback_external_user_id_not_found(
        self, mock_process_unsuccess_callback
    ):
        mock_process_unsuccess_callback.return_value = False
        payload = {
            "code": 500,
            "customerId": self.external_customer_id,
            "details": {"beneficiaryId": self.beneficiary_id, "status": 1},
        }
        resp = self.client.post(self.url, payload, format='json')
        mock_process_unsuccess_callback.assert_called_once_with(self.external_customer_id, None)
        self.assertEqual(resp.status_code, HTTP_404_NOT_FOUND)

    def test_unsuccessful_callback_invalid_payload(self):
        payload = {"code": 500, "details": {"beneficiaryId": self.beneficiary_id, "status": 1}}
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, HTTP_400_BAD_REQUEST)

    def test_successful_callback_invalid_status(self):
        payload = {
            "code": 200,
            "customerId": self.external_customer_id,
            "details": {
                "beneficiaryId": self.beneficiary_id,
                "status": 4,
                "accountType": "testing"
            }
        }

        payment_gateway_customer_data = PaymentGatewayCustomerData.objects. \
            filter(beneficiary_id=self.beneficiary_id).last()
        self.assertIsNone(payment_gateway_customer_data.status)
        self.assertIsNone(payment_gateway_customer_data.account_type)
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, HTTP_400_BAD_REQUEST)

    def test_successful_callback_invalid_customer_id(self):
        payloads = [
            {
                "code": 200,
                "details": {
                    "beneficiaryId": self.beneficiary_id,
                    "status": 1,
                    "accountType": "testing"
                }
            },
            {
                "code": 200,
                "customerId": None,
                "details": {
                    "beneficiaryId": self.beneficiary_id,
                    "status": 1,
                    "accountType": "testing"
                }
            }, {

                "code": 200,
                "customerId": "not-valid",
                "details": {
                    "beneficiaryId": self.beneficiary_id,
                    "status": 1,
                    "accountType": "testing"
                }
            }
        ]
        expected_response = [
            HTTP_400_BAD_REQUEST,
            HTTP_400_BAD_REQUEST,
            HTTP_404_NOT_FOUND
        ]

        for index, payload in enumerate(payloads):
            resp = self.client.post(self.url, payload, format='json')
            self.assertEqual(resp.status_code, expected_response[index])

    def test_successful_callback_with_optional_field(self):
        payload = {
            'code': 201,
            'message': 'ok',
            'responseTime': '20231017043918',
            'transactionId': '0a7d407068ae43e4a37f17069a803812',
            'referenceNumber': '8821498107b146ecaf88ca6b876c6588',
            'customerId': self.external_customer_id,
            'details': {
                'A-Correlation-ID': '6d87a0cb94c14c6f94d5cfbb00e50de3',
                'beneficiaryAccountNumber': '646601019599535',
                'beneficiaryBankCode': 'BRINIDJA',
                'beneficiaryBankName': 'Bank BRI',
                'beneficiaryId': self.beneficiary_id,
                'beneficiaryName': 'LUKMAN',
                'accountType': '',
                'status': 1
            }
        }

        payment_gateway_customer_data = PaymentGatewayCustomerData.objects.filter(
            beneficiary_id=self.beneficiary_id).last()
        self.assertIsNone(payment_gateway_customer_data.status)
        self.assertIsNone(payment_gateway_customer_data.account_type)
        resp = self.client.post(self.url, payload, format='json')
        payment_gateway_customer_data.refresh_from_db()
        self.assertEqual(resp.status_code, HTTP_200_OK)
        self.assertEqual(payload.get('details').get('status'), payment_gateway_customer_data.status)


PARTNER_ID = '11'
CHANNEL_ID = '22'


@override_settings(BCA_SNAP_CLIENT_SECRET_INBOUND='client-secret')
@override_settings(BCA_SNAP_CHANNEL_ID_OUBTOND=CHANNEL_ID)
@override_settings(BCA_SNAP_COMPANY_VA_OUTBOND=PARTNER_ID)
class TestBcaSnapInquiryBills(TestCase):
    def setUp(self):
        self.client = APIClient()
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=420)
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(
            customer=self.customer, loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        )
        self.payments = []
        total_due_amount = 0
        total_interest_amount = 0
        total_principal_amount = 0
        total_late_fee_amount = 0
        for i in range(2):
            payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
            )
            self.payments.append(payment)
            total_due_amount += payment.due_amount
            total_interest_amount += payment.installment_interest
            total_principal_amount += payment.installment_principal
            total_late_fee_amount += payment.late_fee_amount

        self.account_payment.due_amount = total_due_amount
        self.account_payment.interest_amount = total_interest_amount
        self.account_payment.principal_amount = total_principal_amount
        self.account_payment.late_fee_amount = total_late_fee_amount
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, virtual_account=self.virtual_account
        )
        self.url_inquiry = '/bca/openapi/v1.0/transfer-va/inquiry'
        self.today_datetime = timezone.localtime(timezone.now())
        self.client_secret = 'secret'
        self.user_snap = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_snap, name=BCA_SNAP_PARTNER_NAME)
        self.happy_path_data = {
            "partnerServiceId": " 10994",
            "customerNo": "123456789",
            "virtualAccountNo": " 10994123456789",
            "trxDateInit": "2022-02-12T17:29:57+07:00",
            "channelCode": 6011,
            "language": "",
            "amount": 2000,
            "hashedSourceAccountNo": "",
            "sourceBankCode": "014",
            "additionalInfo": {"value": ""},
            "passApp": "",
            "inquiryRequestId": "202202110909311234500001136963",
        }
        FeatureSettingFactory(
            is_active=True,
            feature_name=AutoDebetFeatureNameConst.REPAYMENT_DETOKENIZE,
        )

    @patch('juloserver.autodebet.utils.detokenize_pii_data')
    @patch('juloserver.integapiv1.views.get_redis_client')
    def test_inquiry_should_success(self, mock_redis_client, mock_detokenize_pii_data):
        mock_detokenize_pii_data.return_value = [
            {'detokenized_values': {'fullname': 'value', 'virtual_account': '123456789'}}
        ]
        mock_redis_client.return_value.get.return_value = None
        snap_timestamp = "2022-02-12T17:29:57+07:00"
        expiry_token = generate_snap_expiry_token(SnapVendorChoices.BCA)
        token = expiry_token.key
        headers = {
            "access_token": token,
            "x_timestamp": snap_timestamp,
        }
        signature = generate_snap_signature(
            headers,
            self.happy_path_data,
            'POST',
            settings.BCA_SNAP_CLIENT_SECRET_INBOUND,
            self.url_inquiry,
        )

        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer ' + token,
            HTTP_X_TIMESTAMP=snap_timestamp,
            HTTP_X_SIGNATURE=signature,
            HTTP_X_EXTERNAL_ID='1',
            HTTP_CONTENT_TYPE="application/json",
            HTTP_X_PARTNER_ID=PARTNER_ID,
            HTTP_CHANNEL_ID=CHANNEL_ID,
        )
        response = self.client.post(self.url_inquiry, data=self.happy_path_data, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '2002400')
        self.assertEqual(response['responseMessage'], "Success")

    @patch('juloserver.integapiv1.views.get_redis_client')
    def test_inquiry_should_failed_when_token_expiry(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = None
        snap_timestamp = "2022-02-12T17:29:57+07:00"
        expiry_token = generate_snap_expiry_token(SnapVendorChoices.BCA)
        expiry_token.update_safely(
            generated_time=self.today_datetime - timedelta(seconds=EXPIRY_TIME_TOKEN_BCA_SNAP + 500)
        )
        token = expiry_token.key
        headers = {
            "access_token": expiry_token.key,
            "x_timestamp": snap_timestamp,
        }
        signature = generate_snap_signature(
            headers,
            self.happy_path_data,
            'POST',
            settings.BCA_SNAP_CLIENT_SECRET_INBOUND,
            self.url_inquiry,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer ' + token,
            HTTP_X_TIMESTAMP=snap_timestamp,
            HTTP_X_SIGNATURE=signature,
            HTTP_X_EXTERNAL_ID='1',
            HTTP_CONTENT_TYPE="application/json",
            HTTP_X_PARTNER_ID=PARTNER_ID,
            HTTP_CHANNEL_ID=CHANNEL_ID,
        )
        response = self.client.post(self.url_inquiry, data=self.happy_path_data, format='json')
        self.assertEqual(response.status_code, 401, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '4012401')
        self.assertEqual(response['responseMessage'], "Invalid Token (B2B)")
        self.assertFalse(PaybackTransaction.objects.exists())


@override_settings(BCA_SNAP_CHANNEL_ID_OUBTOND=CHANNEL_ID)
@override_settings(BCA_SNAP_COMPANY_VA_OUTBOND=PARTNER_ID)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class BcaSnapPaymentFlagInvocationView(TestCase):
    def setUp(self):
        self.client = APIClient()
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=420)
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(
            customer=self.customer, loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        )
        self.payments = []
        total_due_amount = 0
        total_interest_amount = 0
        total_principal_amount = 0
        total_late_fee_amount = 0
        for i in range(2):
            payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
            )
            self.payments.append(payment)
            total_due_amount += payment.due_amount
            total_interest_amount += payment.installment_interest
            total_principal_amount += payment.installment_principal
            total_late_fee_amount += payment.late_fee_amount

        self.account_payment.due_amount = total_due_amount
        self.account_payment.interest_amount = total_interest_amount
        self.account_payment.principal_amount = total_principal_amount
        self.account_payment.late_fee_amount = total_late_fee_amount
        self.account_payment.status_id = 320
        self.account_payment.paid_amount = 0
        self.account_payment.save()
        self.virtual_account_postfix = '086615071609'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, virtual_account=self.virtual_account
        )
        self.url_repayment = '/bca/openapi/v1.0/transfer-va/payment'
        self.today_datetime = timezone.localtime(timezone.now())
        self.client_secret = 'secret'
        self.user_snap = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_snap, name=BCA_SNAP_PARTNER_NAME)
        self.external_id = '1'
        self.payback_trx = PaybackTransactionFactory(
            customer=self.customer,
            account=self.account,
            transaction_date=datetime.today(),
            payment_method=self.payment_method,
            transaction_id='202202110909311234500001136963',
            is_processed=False,
        )
        self.paid_value = 20000
        self.happy_path_data = {
            "partnerServiceId": " 10994",
            "customerNo": "086615071609",
            "virtualAccountNo": " 10994086615071609",
            "virtualAccountName": "prod only",
            "virtualAccountEmail": "",
            "virtualAccountPhone": "",
            "trxId": "",
            "paymentRequestId": "202202110909311234500001136963",
            "channelCode": 6011,
            "hashedSourceAccountNo": "",
            "sourceBankCode": "014",
            "paidAmount": {"value": "{}.00".format(self.paid_value), "currency": "IDR"},
            "cumulativePaymentAmount": 0,
            "paidBills": "",
            "totalAmount": {"value": "1618000.00", "currency": "IDR"},
            "trxDateTime": "2022-02-12T17:29:57+07:00",
            "referenceNo": "00113696201",
            "journalNum": "",
            "paymentType": "",
            "flagAdvise": "N",
            "subCompany": "00000",
            "billDetails": [],
            "freeTexts": [],
            "additionalInfo": {"value": ""},
        }

    @patch('juloserver.integapiv1.views.get_redis_client')
    def test_payment_notification_should_success(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = None
        snap_timestamp = "2022-02-12T17:29:57+07:00"
        expiry_token = generate_snap_expiry_token(SnapVendorChoices.BCA)
        token = expiry_token.key
        headers = {
            "access_token": token,
            "x_timestamp": snap_timestamp,
        }
        signature = generate_snap_signature(
            headers,
            self.happy_path_data,
            'POST',
            settings.BCA_SNAP_CLIENT_SECRET_INBOUND,
            self.url_repayment,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer ' + token,
            HTTP_X_TIMESTAMP=snap_timestamp,
            HTTP_X_SIGNATURE=signature,
            HTTP_X_EXTERNAL_ID=self.external_id,
            HTTP_CONTENT_TYPE="application/json",
            HTTP_X_PARTNER_ID=PARTNER_ID,
            HTTP_CHANNEL_ID=CHANNEL_ID,
        )
        response = self.client.post(self.url_repayment, data=self.happy_path_data, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '2002500')
        self.assertEqual(response['responseMessage'], "Success")
        self.payback_trx.refresh_from_db()
        self.assertTrue(self.payback_trx.is_processed)
        self.account_payment.refresh_from_db()
        self.assertEqual(self.account_payment.paid_amount, self.paid_value)

    @patch('juloserver.integapiv1.views.get_redis_client')
    def test_payment_notification_should_failed_when_token_expiry(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = None
        snap_timestamp = "2022-02-12T17:29:57+07:00"
        expiry_token = generate_snap_expiry_token(SnapVendorChoices.BCA)
        expiry_token.update_safely(
            generated_time=self.today_datetime - timedelta(seconds=EXPIRY_TIME_TOKEN_BCA_SNAP + 500)
        )
        token = expiry_token.key
        headers = {
            "access_token": token,
            "x_timestamp": snap_timestamp,
        }
        signature = generate_snap_signature(
            headers,
            self.happy_path_data,
            'POST',
            settings.BCA_SNAP_CLIENT_SECRET_INBOUND,
            self.url_repayment,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer ' + token,
            HTTP_X_TIMESTAMP=snap_timestamp,
            HTTP_X_SIGNATURE=signature,
            HTTP_X_EXTERNAL_ID=self.external_id,
            HTTP_CONTENT_TYPE="application/json",
            HTTP_X_PARTNER_ID=PARTNER_ID,
            HTTP_CHANNEL_ID=CHANNEL_ID,
        )
        response = self.client.post(self.url_repayment, data=self.happy_path_data, format='json')
        self.assertEqual(response.status_code, 401, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '4012501')
        self.assertEqual(response['responseMessage'], "Invalid Token (B2B)")
        self.payback_trx.refresh_from_db()
        self.assertFalse(self.payback_trx.is_processed)
        self.account_payment.refresh_from_db()
        self.assertEqual(self.account_payment.paid_amount, 0)

    @patch('juloserver.integapiv1.views.get_redis_client')
    def test_payment_notification_should_failed_when_external_id_conflict(self, mock_redis_client):
        redis_value = {
            "responseCode": "4042512",
            "responseMessage": "Invalid Bill/Virtual Account [Not Found]",
            "virtualAccountData": {
                "paymentFlagReason": {
                    "english": "virtual account not found",
                    "indonesia": "virtual account tidak ditemukan",
                },
                "partnerServiceId": "10994",
                "customerNo": "0866644955109",
                "virtualAccountNo": "982347",
                "virtualAccountName": "prod only",
                "virtualAccountEmail": "",
                "virtualAccountPhone": "",
                "trxId": "",
                "paymentRequestId": "10994086615071609",
                "paidAmount": {"value": "", "currency": ""},
                "paidBills": "",
                "totalAmount": {"value": "", "currency": ""},
                "trxDateTime": "2023-09-10T17:29:57+07:00",
                "referenceNo": "00113696201",
                "journalNum": "",
                "paymentType": "",
                "flagAdvise": "N",
                "paymentFlagStatus": "01",
                "billDetails": [],
                "freeTexts": [{"english": "", "indonesia": ""}],
            },
            "additionalInfo": {},
        }
        mock_redis_client.return_value.get.return_value = json.dumps(redis_value)
        snap_timestamp = "2022-02-12T17:29:57+07:00"
        expiry_token = generate_snap_expiry_token(SnapVendorChoices.BCA)
        token = expiry_token.key
        headers = {
            "access_token": token,
            "x_timestamp": snap_timestamp,
        }
        signature = generate_snap_signature(
            headers,
            self.happy_path_data,
            'POST',
            settings.BCA_SNAP_CLIENT_SECRET_INBOUND,
            self.url_repayment,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION='Bearer ' + token,
            HTTP_X_TIMESTAMP=snap_timestamp,
            HTTP_X_SIGNATURE=signature,
            HTTP_X_EXTERNAL_ID=self.external_id,
            HTTP_CONTENT_TYPE="application/json",
            HTTP_X_PARTNER_ID=PARTNER_ID,
            HTTP_CHANNEL_ID=CHANNEL_ID,
        )
        response = self.client.post(self.url_repayment, data=self.happy_path_data, format='json')
        self.assertEqual(response.status_code, 409, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '4092500')
        self.assertEqual(response['responseMessage'], "Conflict")


class TestFaspaySnapAuthentication(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

        dt = datetime.now()
        self.x_timestamp = datetime.timestamp(dt)
        self.x_partner_id = 554433
        self.x_external_id = 223344
        self.x_channel_id = 12345

        self.payload = {
            'partnerServiceId': '  88899',
            'customerNo': '12345678901234567890',
            'virtualAccountNo': '1099408127565657',
            'inquiryRequestId': 'test+xxxx+202404281',
        }
        self.endpoint = '/faspay-snap/v1.0/transfer-va/inquiry'
        self.method = "POST"

        self.string_to_sign = faspay_generate_string_to_sign(
            self.payload, self.method, self.endpoint, self.x_timestamp
        )
        self.x_signature = 'signature-123'
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )

    @patch('juloserver.integapiv1.security.verify_asymmetric_signature')
    @patch('juloserver.integapiv1.views.get_redis_client')
    @override_settings(FASPAY_SNAP_PUBLIC_KEY='faspay-snap-public-key')
    def test_failed_authenticated(self, mock_redis_client, mock_verify_login: MagicMock) -> None:
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE='121212312',
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )
        mock_verify_login.return_value = False
        mock_redis_client.return_value.get.return_value = None
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json()['responseCode'],
            FaspaySnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
        )

    @override_settings(FASPAY_SNAP_PUBLIC_KEY='faspay-snap-public-key')
    @patch('juloserver.integapiv1.views.get_redis_client')
    def test_failed_authenticated_mandatory_header(self, mock_redis_client) -> None:
        mock_redis_client.return_value.get.return_value = None
        self.client.credentials(
            HTTP_X_SIGNATURE='121212312',
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )
        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json()['responseCode'],
            FaspaySnapInquiryResponseCodeAndMessage.UNAUTHORIZED_SIGNATURE.code,
        )


class TestFaspaySnapInquirySetup(TestCase):
    def setUp(self):
        self.client = APIClient()
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=420)
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(
            customer=self.customer, loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        )
        self.payments = []
        total_due_amount = 0
        total_interest_amount = 0
        total_principal_amount = 0
        total_late_fee_amount = 0
        for i in range(2):
            payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
            )
            self.payments.append(payment)
            total_due_amount += payment.due_amount
            total_interest_amount += payment.installment_interest
            total_principal_amount += payment.installment_principal
            total_late_fee_amount += payment.late_fee_amount

        self.account_payment.due_amount = total_due_amount
        self.account_payment.interest_amount = total_interest_amount
        self.account_payment.principal_amount = total_principal_amount
        self.account_payment.late_fee_amount = total_late_fee_amount
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, virtual_account=self.virtual_account
        )
        self.virtual_account_prohibit = '18888012345'
        self.payment_method_prohibit = PaymentMethodFactory(
            customer=self.customer,
            virtual_account=self.virtual_account_prohibit,
            payment_method_code=188880,
        )
        self.feature_setting = FeatureSettingFactory(
            parameters={
                "payment_method_code": [str(self.payment_method_prohibit.payment_method_code)],
            },
            feature_name=FeatureNameConst.REPAYMENT_PROHIBIT_VA_PAYMENT,
        )

        dt = datetime.now()
        self.x_timestamp = datetime.timestamp(dt)
        self.x_partner_id = 10994
        self.x_external_id = 223344
        self.x_channel_id = 12345

        self.payload = {
            'partnerServiceId': '  10994',
            'customerNo': '12345678901234567890',
            'virtualAccountNo': ' 10994123456789',
            'inquiryRequestId': 'test+xxxx+202404281',
        }
        self.payload_prohibit = {
            'partnerServiceId': '  188880',
            'customerNo': '12345',
            'virtualAccountNo': '  18888012345',
            'inquiryRequestId': 'testprohibit+xxxx+202404281',
        }
        self.endpoint = '/faspay-snap/v1.0/transfer-va/inquiry'
        self.method = "POST"

        self.string_to_sign = faspay_generate_string_to_sign(
            self.payload, self.method, self.endpoint, self.x_timestamp
        )
        self.x_signature = 'signature-123'
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=self.x_signature,
            HTTP_X_PARTNER_ID=self.x_partner_id,
            HTTP_X_EXTERNAL_ID=self.x_external_id,
            HTTP_CHANNEL_ID=self.x_channel_id,
        )


class TestFaspaySnapInquirySuccess(TestFaspaySnapInquirySetup, TestCase):
    @patch('juloserver.integapiv1.security.verify_asymmetric_signature')
    @patch('juloserver.integapiv1.views.get_redis_client')
    @override_settings(FASPAY_SNAP_PUBLIC_KEY='faspay-snap-public-key')
    def test_inquiry_success(self, mock_redis_client, mock_verify_login: MagicMock):
        mock_verify_login.return_value = True
        mock_redis_client.return_value.get.return_value = None

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '2002400')
        self.assertEqual(response['responseMessage'], "Success")
        self.assertTrue(PaybackTransaction.objects.exists())


class TestFaspaySnapInquiryFailed(TestFaspaySnapInquirySetup, TestCase):
    @patch('juloserver.integapiv1.security.verify_asymmetric_signature')
    @patch('juloserver.integapiv1.views.get_redis_client')
    @override_settings(FASPAY_SNAP_PUBLIC_KEY='faspay-snap-public-key')
    def test_inquiry_failed_when_external_id_conflict(
        self, mock_redis_client, mock_verify_login: MagicMock
    ):
        mock_verify_login.return_value = True

        redis_value = {
            "responseCode": "2002400",
            "responseMessage": "Success",
            "virtualAccountData": {
                "partnerServiceId": "  10994",
                "customerNo": "12345678901234567890",
                "virtualAccountNo": "10994123456789",
                "virtualAccountName": "prod only",
                "virtualAccountEmail": "tester418@julofinance.com",
                "virtualAccountPhone": "08214543435",
                "inquiryRequestId": "test+xxxx+202404282",
                "totalAmount": {"value": "521600.00", "currency": "IDR"},
            },
        }
        mock_redis_client.return_value.get.return_value = json.dumps(redis_value)

        response = self.client.post(self.endpoint, data=self.payload, format='json')
        self.assertEqual(response.status_code, 409, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '4092400')
        self.assertEqual(response['responseMessage'], "Conflict")

    @patch('juloserver.integapiv1.security.verify_asymmetric_signature')
    @patch('juloserver.integapiv1.views.get_redis_client')
    @override_settings(FASPAY_SNAP_PUBLIC_KEY='faspay-snap-public-key')
    def test_inquiry_should_failed_mandatory_field(
        self, mock_redis_client, mock_verify_login: MagicMock
    ):
        mock_verify_login.return_value = True
        mock_redis_client.return_value.get.return_value = None

        response = self.client.post(self.endpoint)
        self.assertEqual(response.status_code, 400, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '4002402')
        self.assertEqual(response['responseMessage'], "Missing Mandatory Field partnerServiceId")

    @patch('juloserver.integapiv1.security.verify_asymmetric_signature')
    @patch('juloserver.integapiv1.views.get_redis_client')
    @override_settings(FASPAY_SNAP_PUBLIC_KEY='faspay-snap-public-key')
    def test_inquiry_payment_prohibit(self, mock_redis_client, mock_verify_login: MagicMock):
        mock_verify_login.return_value = True
        mock_redis_client.return_value.get.return_value = None

        response = self.client.post(self.endpoint, data=self.payload_prohibit, format='json')
        self.assertEqual(response.status_code, 500, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '5002400')
        self.assertEqual(response['responseMessage'], "General Error")


@patch('juloserver.cootek.tasks.process_call_customer_via_cootek')
@override_settings(JWT_SECRET_KEY="secret-jwt")
class TestCallCustomerCootekView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/comm-proxy/v1/send/two-way-robocall/'
        self.token = 'Bearer ' + CommProxyAuthentication.generate_token("omnichannel")
        self.client.credentials(HTTP_AUTHORIZATION=self.token)
        self.mock_task = MagicMock()
        self.mock_task.id = "task-id-1"
        self.success_body = {
            "customers": [
                {"customer_id": 1234, "current_account_payment_id": 12},
                {"customer_id": 1235, "current_account_payment_id": 123},
            ],
            "campaign_data": {
                "campaign_name": "test-campaign",
                "campaign_id": 1,
            },
            "data": {
                "task_type": "test-task",
                "robot_id": "54321",
                "start_time": "13:11",
                "end_time": "15:13",
                "attempt": 3,
                "intention_list": ["A", "B", "C"],
                "is_group_method": False,
            },
        }
        self.expected_validated_data = OrderedDict(
            [
                (
                    "customers",
                    [
                        OrderedDict(
                            [
                                ("customer_id", "1234"),
                                ("current_account_payment_id", "12"),
                            ]
                        ),
                        OrderedDict(
                            [
                                ("customer_id", "1235"),
                                ("current_account_payment_id", "123"),
                            ]
                        ),
                    ],
                ),
                (
                    "campaign_data",
                    OrderedDict([("campaign_name", "test-campaign"), ("campaign_id", "1")]),
                ),
                (
                    "data",
                    OrderedDict(
                        [
                            ("task_type", "test-task"),
                            ("robot_id", "54321"),
                            ("start_time", time(hour=13, minute=11)),
                            ("end_time", time(hour=15, minute=13)),
                            ("attempt", 3),
                            ("intention_list", ["A", "B", "C"]),
                            ("is_group_method", False),
                        ]
                    ),
                ),
            ]
        )

    def test_success_post(self, mock_process_call_customer_via_cootek):
        mock_process_call_customer_via_cootek.delay.return_value = self.mock_task

        response = self.client.post(
            self.url,
            data=self.success_body,
            format='json',
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"success": True, "data": {"task_id": "task-id-1"}, "errors": []}, response.json()
        )
        mock_process_call_customer_via_cootek.delay.assert_called_once_with(
            "omnichannel",
            self.expected_validated_data,
        )

    def test_invalid_post(self, mock_process_call_customer_via_cootek):
        mock_process_call_customer_via_cootek.delay.return_value = self.mock_task

        self.success_body["data"]["task_type"] = ""
        response = self.client.post(
            self.url,
            data=self.success_body,
            format='json',
        )
        mock_process_call_customer_via_cootek.delay.assert_not_called()

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            {
                "success": False,
                "data": {
                    "data": {
                        "task_type": ["This field may not be blank."],
                    },
                },
                "errors": ["invalid request body"],
            },
            response.json(),
        )


class TestFaspaySnapPaymentView(TestCase):
    def setUp(self):
        self.client = APIClient()
        AccountingCutOffDateFactory()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=420)
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan = LoanFactory(
            customer=self.customer, loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        )
        self.payments = []
        total_due_amount = 0
        total_interest_amount = 0
        total_principal_amount = 0
        total_late_fee_amount = 0
        for i in range(2):
            payment = PaymentFactory(
                payment_status=self.account_payment.status,
                due_date=self.account_payment.due_date,
                account_payment=self.account_payment,
                loan=self.loan,
            )
            self.payments.append(payment)
            total_due_amount += payment.due_amount
            total_interest_amount += payment.installment_interest
            total_principal_amount += payment.installment_principal
            total_late_fee_amount += payment.late_fee_amount

        self.account_payment.due_amount = total_due_amount
        self.account_payment.interest_amount = total_interest_amount
        self.account_payment.principal_amount = total_principal_amount
        self.account_payment.late_fee_amount = total_late_fee_amount
        self.account_payment.status_id = 320
        self.account_payment.paid_amount = 0
        self.account_payment.save()
        self.virtual_account_postfix = '086615071609'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            customer=self.customer, virtual_account=self.virtual_account
        )
        self.url_repayment = '/faspay-snap/v1.0/transfer-va/payment'
        self.url_repayment_relative = self.url_repayment[self.url_repayment.find('/v1.0') :]
        self.today_datetime = timezone.localtime(timezone.now())
        self.client_secret = 'secret'
        self.user_snap = AuthUserFactory()
        self.partner = PartnerFactory(user=self.user_snap, name=BCA_SNAP_PARTNER_NAME)
        self.external_id = '1'
        self.partner_id = '01'
        self.channel_id = '9901'
        self.transaction_id = '202202110909311234500001136963'
        self.payback_trx = PaybackTransactionFactory(
            customer=self.customer,
            account=self.account,
            transaction_date=datetime.today(),
            payment_method=self.payment_method,
            inquiry_request_id=self.transaction_id,
            is_processed=False,
            transaction_id=None,
        )
        self.paid_value = 20000
        self.happy_path_data = {
            "partnerServiceId": " 10994",
            "customerNo": "086615071609",
            "virtualAccountNo": " 10994086615071609",
            "virtualAccountName": "prod only",
            "paymentRequestId": self.transaction_id,
            "paidAmount": {"value": "{}.00".format(self.paid_value), "currency": "IDR"},
            "trxDateTime": "2022-02-12T17:29:57+07:00",
            "referenceNo": "123412341234",
        }
        self.x_timestamp = "2022-02-12T17:29:57+07:00"

    @patch('juloserver.integapiv1.views.get_redis_client')
    @override_settings(FASPAY_SNAP_PUBLIC_KEY=PUBLIC_KEY)
    def test_payment_notification_should_success(self, mock_redis_client):
        mock_redis_client.return_value.get.return_value = None
        string_to_sign = faspay_generate_string_to_sign(
            self.happy_path_data, 'post', self.url_repayment_relative, self.x_timestamp
        )
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=generate_signature_asymmetric(PRIVATE_KEY, string_to_sign),
            HTTP_X_EXTERNAL_ID=self.external_id,
            HTTP_X_PARTNER_ID=self.partner_id,
            HTTP_CHANNEL_ID=self.channel_id,
            HTTP_CONTENT_TYPE="application/json",
        )
        response = self.client.post(self.url_repayment, data=self.happy_path_data, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '2002500')
        self.assertEqual(response['responseMessage'], "Success")
        self.payback_trx.refresh_from_db()
        self.assertIsNotNone(self.payback_trx.transaction_id)

    @patch('juloserver.integapiv1.views.get_redis_client')
    @override_settings(FASPAY_SNAP_PUBLIC_KEY=PUBLIC_KEY)
    def test_payment_notification_should_failed_when_external_id_conflict(self, mock_redis_client):
        redis_value = {
            "responseCode": "4042512",
            "responseMessage": "Invalid Bill/Virtual Account [Not Found]",
            "virtualAccountData": {
                "partnerServiceId": "10994",
                "customerNo": "0866644955109",
                "virtualAccountNo": "982347",
                "virtualAccountName": "prod only",
                "paymentRequestId": self.transaction_id + '1',
                "paidAmount": {"value": "", "currency": ""},
                "trxDateTime": "2023-09-10T17:29:57+07:00",
                "referenceNo": "1234123412341234",
            },
            "additionalInfo": {},
        }
        mock_redis_client.return_value.get.return_value = json.dumps(redis_value)
        string_to_sign = faspay_generate_string_to_sign(
            self.happy_path_data, 'post', self.url_repayment_relative, self.x_timestamp
        )
        self.client.credentials(
            HTTP_X_TIMESTAMP=self.x_timestamp,
            HTTP_X_SIGNATURE=generate_signature_asymmetric(PRIVATE_KEY, string_to_sign),
            HTTP_X_EXTERNAL_ID=self.external_id,
            HTTP_X_PARTNER_ID=self.partner_id,
            HTTP_CHANNEL_ID=self.channel_id,
            HTTP_CONTENT_TYPE="application/json",
        )
        response = self.client.post(self.url_repayment, data=self.happy_path_data, format='json')
        self.assertEqual(response.status_code, 409, response.content)
        response = response.json()
        self.assertEqual(response['responseCode'], '4092500')
        self.assertEqual(response['responseMessage'], "Conflict")
        self.payback_trx.refresh_from_db()
        self.assertFalse(self.payback_trx.is_processed)
        self.account_payment.refresh_from_db()
        self.assertEqual(self.account_payment.paid_amount, 0)


@mock.patch('juloserver.integapiv1.views.get_redis_client')
@mock.patch('juloserver.minisquad.tasks2.dialer_system_task.send_airudder_request_data_to_airudder')
class TestCallCustomerAiRudderPDSView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = '/api/comm-proxy/v1/send/ai-rudder-task/'
        self.token = 'Bearer ' + CommProxyAuthentication.generate_token("omnichannel")
        self.client.credentials(HTTP_AUTHORIZATION=self.token)

    def test_minimal_request(
        self, mock_send_airudder_request_data_to_airudder, mock_get_redis_client
    ):
        request_data = {
            "bucket_name": "omnichannel_1234",
            "batch_number": 12,
            "airudder_config": {
                "groupName": "GROUP_BUCKET_1",
                "start_time": "08:00",
                "end_time": "20:00",
            },
            "customers": [
                {
                    "account_payment_id": "1",
                    "account_id": "2",
                    "customer_id": "123124123",
                    "phonenumber": "+6281234567890",
                    "nama_customer": "John Doe",
                }
            ],
        }
        response = self.client.post(self.url, data=request_data, format='json')

        # Assert Backend data
        dialer_task = DialerTask.objects.get(type="omnichannel|omnichannel_1234|12")
        self.assertEqual(DialerSystemConst.AI_RUDDER_PDS, dialer_task.vendor)
        mock_send_airudder_request_data_to_airudder.delay.assert_called_once_with(
            dialer_task.id,
            "comm_proxy::send_airudder_task::omnichannel|omnichannel_1234|12",
        )
        mock_get_redis_client.return_value.set.assert_called_once_with(
            "comm_proxy::send_airudder_task::omnichannel|omnichannel_1234|12",
            json.dumps(request_data),
            ex=21600,
        )

        # Assert response data
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"success": True, "data": {"dialer_task_id": dialer_task.id}, "errors": []},
        )

    def test_invalid_bucket_name_format(self, *args):
        request_data = {
            "bucket_name": "omnichannel|1234",
            "batch_number": 12,
            "airudder_config": {
                "groupName": "GROUP_BUCKET_1",
                "start_time": "08:00",
                "end_time": "20:00",
            },
            "customers": [
                {
                    "account_payment_id": "1",
                    "customer_id": "123124123",
                    "phonenumber": "+6281234567890",
                    "nama_customer": "John Doe",
                }
            ],
        }
        response = self.client.post(self.url, data=request_data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_invalid_customer_data(self, *args):
        # missing nama_customer
        request_data = {
            "bucket_name": "omnichannel_1234",
            "batch_number": 12,
            "airudder_config": {
                "groupName": "GROUP_BUCKET_1",
                "start_time": "08:00",
                "end_time": "20:00",
            },
            "customers": [
                {
                    "account_payment_id": "1",
                    "customer_id": "123124123",
                    "phonenumber": "+6281234567890",
                }
            ],
        }
        response = self.client.post(self.url, data=request_data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_invalid_time_field_data(self, *args):
        request_data = {
            "bucket_name": "omnichannel_1234",
            "batch_number": 12,
            "airudder_config": {
                "groupName": "GROUP_BUCKET_1",
                "start_time": "invalid-time",
                "end_time": "20:00",
            },
            "customers": [
                {
                    "account_id": "2",
                    "account_payment_id": "3212341",
                    "customer_id": "123124123",
                    "phonenumber": "+6281234567890",
                    "nama_customer": "John Doe",
                }
            ],
        }
        response = self.client.post(self.url, data=request_data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_success_full_data(self, *args):
        request_data = {
            "bucket_name": "omnichannel_1234",
            "batch_number": 0,
            "airudder_config": {
                "groupName": "GROUP_BUCKET_1",
                "start_time": "08:00",
                "end_time": "20:00",
                "autoQA": "N",
                "acwTime": "30",
                "ringLimit": "0",
                "rest_times": [["12:00", "13:00"]],
                "slotFactor": 0,
                "dialingMode": "0",
                "maxLostRate": "5",
                "qaLimitRate": "100",
                "repeatTimes": "3",
                "callInterval": "0",
                "dialingOrder": [
                    "mobile_phone_2",
                    "no_telp_pasangan",
                    "no_telp_kerabat",
                    "telp_perusahaan",
                ],
                "qaLimitLength": "0",
                "autoSlotFactor": "1",
                "bulkCallInterval": "300",
                "contactNumberInterval": "300",
                "timeFrameStatus": "on",
                "timeFrames": [
                    {"repeatTimes": 4, "contactInfoSource": "original_source"},
                    {"repeatTimes": 5, "contactInfoSource": "original_source"},
                    {"repeatTimes": 3, "contactInfoSource": "original_source"},
                    {"repeatTimes": 3, "contactInfoSource": "original_source"},
                ],
                "resultStrategies": "on",
                "resultStrategiesConfig": [
                    {
                        "oper": "==",
                        "title": "Level2",
                        "value": "WPC",
                        "action": [1, 2],
                        "dncDay": 1,
                    },
                    {"oper": "==", "title": "Level2", "value": "ShortCall", "action": [1]},
                ],
                "callRecordingUpload": "on",
            },
            "customers": [
                {
                    "account_payment_id": "1",
                    "account_id": "2",
                    "customer_id": "1",
                    "phonenumber": "1",
                    "nama_customer": "1",
                    "nama_perusahaan": "",
                    "posisi_karyawan": "",
                    "dpd": "",
                    "total_denda": "",
                    "potensi_cashback": "",
                    "total_seluruh_perolehan_cashback": "",
                    "total_due_amount": "",
                    "total_outstanding": "",
                    "angsuran_ke": "",
                    "tanggal_jatuh_tempo": "",
                    "nama_pasangan": "",
                    "nama_kerabat": "",
                    "hubungan_kerabat": "",
                    "alamat": "",
                    "kota": "",
                    "jenis_kelamin": "",
                    "tgl_lahir": "",
                    "tgl_gajian": "",
                    "tujuan_pinjaman": "",
                    "tgl_upload": "",
                    "va_bca": "",
                    "va_permata": "",
                    "va_maybank": "",
                    "va_alfamart": "",
                    "va_indomaret": "",
                    "va_mandiri": "",
                    "tipe_produk": "",
                    "last_pay_date": "",
                    "last_pay_amount": "",
                    "partner_name": "",
                    "last_agent": "",
                    "last_call_status": "",
                    "refinancing_status": "",
                    "activation_amount": "",
                    "program_expiry_date": "",
                    "customer_bucket_type": "",
                    "promo_untuk_customer": "",
                    "zip_code": "",
                    "mobile_phone_2": "",
                    "telp_perusahaan": "",
                    "mobile_phone_1_2": "",
                    "mobile_phone_2_2": "",
                    "no_telp_pasangan": "",
                    "mobile_phone_1_3": "",
                    "mobile_phone_2_3": "",
                    "no_telp_kerabat": "",
                    "mobile_phone_1_4": "",
                    "mobile_phone_2_4": "",
                    "angsuran_per_bulan": "",
                    "uninstall_indicator": "",
                    "fdc_risky": "",
                    "status_refinancing_lain": "",
                }
            ],
        }

        response = self.client.post(self.url, data=request_data, format='json')
        self.assertEqual(response.status_code, 200, response.json())

    def test_invalid_required_time_frames(self, *args):
        request_data = {
            "bucket_name": "omnichannel_1234",
            "batch_number": 12,
            "airudder_config": {
                "groupName": "GROUP_BUCKET_1",
                "start_time": "08:00",
                "end_time": "20:00",
                "timeFrameStatus": "on",
                "timeFrames": [],
            },
            "customers": [
                {
                    "account_payment_id": "1",
                    "account_id": "2",
                    "customer_id": "123124123",
                    "phonenumber": "+6281234567890",
                    "nama_customer": "John Doe",
                }
            ],
        }
        response = self.client.post(self.url, data=request_data, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": {'airudder_config': {'timeFrames': ['timeFrames is mandatory']}},
                "errors": ['invalid request body'],
            },
        )

    def test_invalid_result_strategies_config(self, *args):
        request_data = {
            "bucket_name": "omnichannel_1234",
            "batch_number": 12,
            "airudder_config": {
                "groupName": "GROUP_BUCKET_1",
                "start_time": "08:00",
                "end_time": "20:00",
                "timeFrameStatus": "on",
                "timeFrames": [
                    {"repeatTimes": 4, "contactInfoSource": "original_source"},
                    {"repeatTimes": 5, "contactInfoSource": "original_source"},
                    {"repeatTimes": 3, "contactInfoSource": "original_source"},
                    {"repeatTimes": 3, "contactInfoSource": "original_source"},
                ],
                "resultStrategiesConfig": [],
            },
            "customers": [
                {
                    "account_id": "2",
                    "account_payment_id": "1",
                    "customer_id": "123124123",
                    "phonenumber": "+6281234567890",
                    "nama_customer": "John Doe",
                }
            ],
        }
        response = self.client.post(self.url, data=request_data, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "success": False,
                "data": {
                    'airudder_config': {
                        'resultStrategiesConfig': ['resultStrategiesConfig is mandatory']
                    }
                },
                "errors": ['invalid request body'],
            },
        )
