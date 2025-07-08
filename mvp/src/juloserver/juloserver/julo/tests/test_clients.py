from builtins import str
from builtins import object
import pytest
import mock
from django.test.testcases import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta, datetime, date
import json

from juloserver.apiv2.tests.test_apiv2_views import CustomerFactory
from juloserver.julo.exceptions import SmsNotSent
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    PaymentMethodLookupFactory,
    PartnerFactory,
    PaymentMethodFactory,
    LoanFactory,
    ShortenedUrlFactory,
    PaymentFactory,
    ApplicationHistoryFactory,
    PaymentEventFactory,
    FeatureSettingFactory,
    DeviceFactory,
    SepulsaTransactionFactory,
    CustomerFactory,
    CashbackTransferTransactionFactory,
    AwsFaceRecogLogFactory,
    PartnerPurchaseItemFactory,
    ImageFactory
)
from juloserver.cootek.tests.factories import StatementFactory, CustomerCreditLimitFactory, \
    AccountCreditLimitFactory
from juloserver.julo.clients.pn import JuloPNClient
from juloserver.julo.clients.mintos import JuloMintosClient
from juloserver.lenderinvestment.models import SbMintosPaymentSendin, MintosQueueStatus, MintosLoanListStatus, \
    ExchangeRate
from juloserver.lenderinvestment.services import get_mintos_loan_id
from juloserver.julo.clients import get_julo_email_client, get_julo_sms_client, get_julo_pn_client
from juloserver.julo.exceptions import EmailNotSent
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.models import ApplicationStatusCodes
from juloserver.payback.constants import CashbackPromoConst
import pytz
from juloserver.julo.product_lines import ProductLineCodes
from django.conf import settings
from juloserver.julo.partners import PartnerConstant

from juloserver.julo.exceptions import JuloException
from juloserver.julo.constants import FeatureNameConst

from juloserver.moengage.constants import UNSENT_MOENGAGE
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    ImageType,
)
from juloserver.streamlined_communication.test.factories import StreamlinedCommunicationFactory

from juloserver.streamlined_communication.constant import SmsTspVendorConstants
from juloserver.streamlined_communication.test.factories import (
    TelcoServiceProviderFactory,
    SmsTspVendorConfigFactory,
)



@pytest.mark.django_db
class TestJuloSmsClient(object):
    def test_sms_custom_payment_reminder(self):
        pass


class TestMintosPaymentSending(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        payment_number = 1
        queue_type = 'payment_sendin'
        self.mintos_queue_status = MintosQueueStatus.objects.create(
            loan_id=self.loan.id,
            payment_number=payment_number,
            queue_type=queue_type,
        )
        today = timezone.localtime(timezone.now())
        self.sb_payment = SbMintosPaymentSendin.objects.create(
            loan_id=self.mintos_queue_status.loan_id,
            payment_schedule_number=self.mintos_queue_status.payment_number,
            payment_date=today,
            cdate=datetime.today()
        )
        exchange_rate = ExchangeRate.objects.create(
            source='payment'
        )
        MintosLoanListStatus.objects.create(
            application_xid=self.loan.application.application_xid,
            exchange_rate=exchange_rate,
            mintos_send_in_ts=today,
            mintos_loan_id=238928
        )

    @mock.patch('juloserver.julo.clients.mintos.JuloMintosClient.get_loans')
    def test_payment_sendin(self, mock_get_loans):
        response = {}
        sendin_data = {}
        data = {"data":
                    {"loan": {"status": "finished"},
                     "payment_summary": {
                         "next_payment_delayed_interest": "0.0000000000000000",
                         "next_payment_late_payment_fee": "0.0000000000000000"},
                     "payment_schedule": [
                         {"sum": "46.9231958333329051",
                          "delayed_amount": "0.0000000000000000",
                          "interest_amount": "2.6731958333329051",
                          "received_amount": "0.0000000000000000",
                          "penalties_amount": "0.0000000000000000",
                          "principal_amount": "44.2500000000000000",
                          "total_remaining_principal": "221.2300000000000000",
                          "accumulated_interest_amount": "0.0000000000000000"}]}}
        mock_get_loans.return_value = data
        minton_loan_id = get_mintos_loan_id(self.loan.id)
        base_url = "https://mintos.api.com/lender-api/v2/"
        token = "ad2fri0hjuv8oiuhy9btrvia7bvhitdirnbvf5"
        client_class = JuloMintosClient(base_url, token)

        response, sendin_data = client_class.payment_sendin(minton_loan_id, self.sb_payment, self.loan)
        assert response == response
        assert sendin_data == sendin_data


class TestJuloPNs(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.client = JuloPNClient()

    @mock.patch('juloserver.julo.clients.pn.JuloPNClient.send_downstream_message')
    def test_sphp_sign_ready_reminder(self, mocked_send_pn):
        mocked_send_pn.return_value = 200
        response = self.client.send_reminder_sign_sphp(self.application.id)
        mocked_send_pn.asser_called_once()
        self.assertIsNotNone(response)


class ObjectMock(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MockResponse(object):
    def __init__(self, resp_data, code=200, msg='OK'):
        self.resp_data = resp_data
        self.code = code
        self.msg = msg
        self.headers = {'content-type': 'text/plain; charset=utf-8'}

    def read(self):
        return self.resp_data

    def getcode(self):
        return self.code


class TestObjectEmailClient(TestCase):
    def setUp(self):
        self.subject = "Subject Title"
        self.content = "Just dummy content"
        self.cc = "unis.badri2@julofinance.com"
        self.cc_multiple = "unis.badri2@julofinance.com,unis.badri3@julofinance.com"
        self.receiver = "unis.badri@julofinance.com"
        self.receiver_list = ["unis.badri@julofinance.com"]
        self.receiver_name = "Unis Badri"
        self.reply_to = "unis.badri@julofinance.com"
        self.sender = "information@julofinance.com"
        self.sender_include_name = "Julo Info<information@julofinance.com>"
        self.sender_name = "Julo Info"
        self.attachments = {
            "content": "",
            "filename": "",
            "type": ""
        }
        self.content_type = "text/plain"
        self.template = "email_notif_100v"
        self.change_reason = "This is reason 1-That is reason 1,This is reason 2-That is reason 2"
        self.url = "https://www.julofinance.com"
        self.datetime = "2020-09-09 23:00:00"

        self.mocked_status_code = 200
        self.mocked_body = "Response body"
        self.mocked_headers = "Response headers"

        self.side_effects = [Exception("not timeout"), Exception("timed out"),
                             Exception("timed out"), Exception("timed out"),
                             Exception("timed out"), Exception("timed out"),
                             Exception("timed out"), Exception("timed out"),
                             Exception("timed out")] + ([mock.DEFAULT] * 150)

        self.partner = PartnerFactory()
        self.application = ApplicationFactory(partner=self.partner)

        self.application_history = ApplicationHistoryFactory(application_id=self.application.id,
                                                             status_new=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED)

        self.loan = LoanFactory(application=self.application)
        self.loan.fund_transfer_ts = datetime.now(tz=pytz.timezone(settings.TIME_ZONE))

        self.payment = PaymentFactory(loan=self.loan)

        self.customer_info = {
            'customer': self.loan.customer,
            'bank_code': '',
            'va_number': '',
            'bank_name': '',
        }

        self.payment_info = {
            'new_payment_structures': [
                {
                    "payment_number": 1,
                    "due_date": datetime.now(tz=pytz.timezone(settings.TIME_ZONE)),
                    "due_amount": 250000
                }
            ],
            'total_due_amount': 255000,
            'due_amount': 235000,
            'late_fee_discount': 20000,
            'chosen_tenure': 5,
            'prerequisite_amount': 30000,
            'due_date': date.today(),
            'tenure_extension': 4
        }

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test__exception_mail_not_sent(self, mocker):
        client = get_julo_email_client()

        mocker.return_value.status_code = self.mocked_status_code
        mocker.side_effect = Exception("not timeout")

        with self.assertRaises(Exception) as context:
            client.send_email(self.subject, self.content, self.receiver)

        self.assertTrue('not timeout' in str(context.exception))

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test__exception_timeout_send_email(self, mocker):
        client = get_julo_email_client()

        mocker.return_value.status_code = self.mocked_status_code
        mocker.side_effect = [Exception("timed out"), Exception("timed out")]

        try:
            client.send_email(self.subject, self.content, self.receiver, retry_max=1)
        except Exception as e:
            self.assertEqual(str(e), "timed out")

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_send_email(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, body, headers = client.send_email(self.subject, self.content, self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

        status_code, body, headers = client.send_email(self.subject, self.content, self.receiver,
                                                       self.sender_include_name, self.cc)

        self.assertEqual(status_code, self.mocked_status_code)

        status_code, body, headers = client.send_email(self.subject, self.content, self.receiver,
                                                       self.sender_include_name, self.cc_multiple)

        self.assertEqual(status_code, self.mocked_status_code)

        status_code, body, headers = client.send_email(self.subject, self.content, self.receiver_list,
                                                       self.sender)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_custom_payment_reminder(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, body, headers = client.email_custom_payment_reminder(self.receiver, self.subject, self.content)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_payment_reminder(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        ptp_date = date.today()
        ptp_date = ptp_date.replace(day=23)

        self.payment.due_date = date.today()
        self.payment.ptp_date = ptp_date
        self.payment.save()

        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, '+4')

        self.assertEqual(status_code, self.mocked_status_code)

        # PTP None
        self.payment.ptp_date = None
        self.payment.save()

        PaymentMethodLookupFactory()

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.BRI1
        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, '+4')

        self.assertEqual(status_code, self.mocked_status_code)

        # MTL day 2
        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1
        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, 2)

        self.assertEqual(status_code, self.mocked_status_code)

        # MTL day 4
        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL2
        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, 4)

        self.assertEqual(status_code, self.mocked_status_code)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.STL1
        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, '4')

        self.assertEqual(status_code, self.mocked_status_code)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.PEDEMTL1
        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, '4')

        self.assertEqual(status_code, self.mocked_status_code)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.PEDESTL1
        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, '4')

        self.assertEqual(status_code, self.mocked_status_code)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.LAKU1
        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, '4')

        self.assertEqual(status_code, self.mocked_status_code)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.ICARE1
        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, '4')

        self.assertEqual(status_code, None)

    @mock.patch("juloserver.julo.clients.email.process_streamlined_comm")
    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_exception_email_payment_reminder(self, mocker, mocked_streamline):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)
        mocked_streamline.side_effect = Exception("exception")

        ptp_date = date.today()
        ptp_date = ptp_date.replace(day=23)

        self.payment.due_date = date.today()
        self.payment.ptp_date = ptp_date
        self.payment.save()

        status_code, headers, subject, msg = client.email_payment_reminder(self.payment, '+4')

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_100v(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_100v(self.application.customer)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_110(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_110(self.application)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_111(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_111(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_131(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_131(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_133(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_133(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_135(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_135(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_136(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_136(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_137(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_137(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_138(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_138(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_139(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_139(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_142(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_142(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_143(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_143(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_161(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_161(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_171(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notification_171(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_180(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self.application.partner.name = PartnerConstant.PEDE_PARTNER
        self.application.product_line.product_line_code = ProductLineCodes.STL1

        status_code, headers, subject, msg = client.email_notification_180(self.application, self.change_reason)

        self.assertEqual(status_code, self.mocked_status_code)

        self.application.partner.name = PartnerConstant.DOKU_PARTNER
        self.application.product_line.product_line_code = PartnerConstant.PEDE_PARTNER

        status_code, headers, subject, msg = client.email_notification_180(self.application, self.change_reason)

        self.assertEqual(status_code, None)

        status_code, headers, subject, msg = client.email_notification_180(self.application, self.change_reason)

        self.assertEqual(status_code, None)

        self.application.product_line.product_line_code = ProductLineCodes.CTL1

        status_code, headers, subject, msg = client.email_notification_180(self.application, self.change_reason)

        self.assertEqual(status_code, None)

    @mock.patch("juloserver.julo.clients.email.get_pdf_content_from_html")
    @mock.patch("juloserver.julo.clients.email.get_application_sphp")
    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notification_180_with_email_settings(self, mocker, mocked_sphp_application,
                                                        mocked_content_from_html):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                       headers=self.mocked_headers)
        mocked_sphp_application.return_value = "<html></html>"
        mocked_content_from_html.return_value = "GBYDGWDWYDVYWDWYDVWUW"

        email_setting = {
            'send_to_partner': True,
            'attach_sphp_partner': True,
            'partner_setting': ObjectMock(partner_email_list=self.receiver),
            'email_setting': ObjectMock(customer_email_content="ABC", partner_email_content="DEF")
        }

        self.application.partner.name = PartnerConstant.PEDE_PARTNER

        # contract number not exists
        status_code, headers, subject, msg = client.email_notification_180(self.application, self.change_reason, True,
                                                                           email_setting)

        self.assertEqual(status_code, self.mocked_status_code)

        # contract number exists
        PartnerPurchaseItemFactory(application_xid=self.application.application_xid)
        status_code, headers, subject, msg = client.email_notification_180(self.application, self.change_reason, True,
                                                                           email_setting)

        self.assertEqual(status_code, self.mocked_status_code)

        email_setting['send_to_partner_customer'] = True
        email_setting['attach_sphp_partner_customer'] = True
        status_code, headers, subject, msg = client.email_notification_180(self.application, self.change_reason, False,
                                                                           email_setting)

        self.assertEqual(status_code, self.mocked_status_code)

        self.application.partner = None
        email_setting['send_to_julo_customer'] = True
        email_setting['attach_sphp_julo_customer'] = True
        status_code, headers, subject, msg = client.email_notification_180(self.application, self.change_reason, False,
                                                                           email_setting)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_julo_review_challenge_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_julo_review_challenge_blast(self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")

    def test_email_julo_review_challenge_2_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)
        status_code, headers, subject, msg = client.email_julo_review_challenge_2_blast(self.receiver,
                                                                                        self.receiver_name, 50000)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_reminder_105(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self.application.email = None
        status_code, headers, subject, msg = client.email_reminder_105(self.application)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_partner_daily_report(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers = client.email_partner_daily_report("test.csv",
                                                                 'SELECT name AS description FROM partner LIMIT 10',
                                                                 self.subject, self.content, self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notif_balance_sepulsa_low(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, body, headers = client.email_notif_balance_sepulsa_low(50000, self.subject)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notif_grab(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, body, headers = client.email_notif_grab(self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_fraud_alert(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_fraud_alert(self.loan)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_lebaran_promo(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_lebaran_promo(self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_loc_notification(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, message = client.email_loc_notification(self.receiver, self.content)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_followup_105_110(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_followup_105_110(self.application)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_courtesy(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self.application.email = None
        status_code, headers, msg, subject = client.email_courtesy(self.application)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_reminder_grab(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_reminder_grab(self.payment, "email_notif_grab")

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_paid_of_grab(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_paid_of_grab(self.receiver, "email_notif_grab")

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_market_survey_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_market_survey_blast(self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_promo_asian_games_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_promo_asian_games_blast(self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_early_payment_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_early_payment_blast(self.receiver, "t-2", self.receiver_name)

        self.assertEqual(status_code, self.mocked_status_code)

        status_code, headers, subject, msg = client.email_early_payment_blast(self.receiver, "t0", self.receiver_name)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_va_notification(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_va_notification(self.application)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_coll_campaign_sept_21_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_coll_campaign_sept_21_blast(self.receiver, "Test: HP Samsung",
                                                                                      self.receiver_name)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_remarketing_106_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.remarketing_106_blast(self.receiver, "Pria", self.receiver_name)

        self.assertEqual(status_code, self.mocked_status_code)

        status_code, headers, subject, msg = client.remarketing_106_blast(self.receiver, "Wanita", self.receiver_name)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_agreement_email(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, message = client.agreement_email(self.receiver, self.content, self.subject)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_notification_permata_prefix_email(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, message = client.notification_permata_prefix_email(self.receiver, self.content)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_custom_for_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.custom_for_blast(self.receiver, "Pria", self.receiver_name,
                                                                     self.subject, self.template)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_reconfirmation_175(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_reconfirmation_175(self.receiver, self.receiver_name,
                                                                             datetime.now(
                                                                                 tz=pytz.timezone(settings.TIME_ZONE)),
                                                                             "Bank Mandiri", "111111111111111111",
                                                                             "Unis Badri", self.template)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_lottery_winner_blast(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_lottery_winner_blast(self.receiver, self.receiver_name)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_partner_reminder_email(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, body, headers = client.partner_reminder_email(self.receiver, self.receiver_name, self.url,
                                                                   self.subject)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("urllib.request")
    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_cashback_management_email(self, mocker, mocked_email_service):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)
        mocked_email_service.urlopen.return_value = MockResponse("Julo Finance")

        status_code, body, headers = client.cashback_management_email(self.receiver,
                                                                      CashbackPromoConst.EMAIL_TYPE_APPROVER_NOTIF, {
                                                                          'promo_name': '',
                                                                          'approval_link': '',
                                                                          'rejection_link': '',
                                                                          'department': '',
                                                                          'document_url': 'https://www.julofinance.com/test.csv',
                                                                          'filename': 'test.csv'
                                                                      })

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_waive_pede_campaign(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        payment_method = PaymentMethodFactory(loan=self.loan)
        payment_method.payment_method_name = "INDOMARET"
        payment_method.save()

        self.loan.customer.gender = "Pria"
        status_code, headers, subject, msg = client.email_waive_pede_campaign(self.loan, 1000000, 10000, 25000, 50000)

        self.assertEqual(status_code, self.mocked_status_code)

        self.loan.customer.gender = "Wanita"
        status_code, headers, subject, msg = client.email_waive_pede_campaign(self.loan, 1000000, 10000, 25000, 50000)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_notification_permata_new_va_email(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, message = client.notification_permata_new_va_email(self.receiver, self.content)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_waive_sell_off_campaign(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self.loan.customer.gender = "Pria"
        status_code, body, headers = client.email_waive_sell_off_campaign(self.loan, 1000000, 10000, 100, 1000, 100,
                                                                          self.subject)

        self.assertEqual(status_code, self.mocked_status_code)

        self.loan.customer.gender = "Wanita"
        status_code, body, headers = client.email_waive_sell_off_campaign(self.loan, 1000000, 10000, 100, 1000, 100,
                                                                          self.subject)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notify_backup_va(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_notify_backup_va(self.application.customer, "Unis", "0140",
                                                                           "GENERIC", "217436453734")

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_loan_refinancing_eligibility(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        settings.JULO_WEB_URL = "https://www.julofinance.com/"

        self.application.customer.gender = "Pria"
        status_code, headers, subject, body_msg = client.email_loan_refinancing_eligibility(self.application.customer,
                                                                                            "JHBGUGD*@DUGDUI@DGDFVD#GB@#")

        self.assertEqual(status_code, self.mocked_status_code)

        self.application.customer.gender = "Wanita"
        status_code, headers, subject, body_msg = client.email_loan_refinancing_eligibility(self.application.customer,
                                                                                            "JHBGUGD*@DUGDUI@DGDFVD#GB@#")

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_loan_refinancing_request(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self.customer_info['customer'].gender = "Pria"
        status_code, headers, subject, body_msg = client.email_loan_refinancing_request(self.customer_info,
                                                                                        self.payment_info)

        self.assertEqual(status_code, self.mocked_status_code)

        self.customer_info['customer'].gender = "Wanita"
        status_code, headers, subject, body_msg = client.email_loan_refinancing_request(self.customer_info,
                                                                                        self.payment_info)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_loan_refinancing_success(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self.application.customer.gender = "Pria"
        status_code, headers, subject, body_msg = client.email_loan_refinancing_success(self.application.customer)

        self.assertEqual(status_code, self.mocked_status_code)

        self.application.customer.gender = "Wanita"
        status_code, headers, subject, body_msg = client.email_loan_refinancing_success(self.application.customer)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.models.Loan.get_oldest_unpaid_payment")
    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_notify_loan_selloff(self, mocker, mock_get_oldest_unpaid_payment):
        client = get_julo_email_client()
        self.payment.due_date = datetime.today().date() - timedelta(days=5)
        self.payment.save()
        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)
        mock_get_oldest_unpaid_payment.return_value = self.payment
        assert self.loan.get_oldest_unpaid_payment() == self.payment
        status_code, headers, subject, msg, template = client.email_notify_loan_selloff(self.loan, {
            'total_outstanding': '',
            'ajb_number': '',
            'ajb_date': '',
            'buyer_vendor_name': '',
            'collector_vendor_name': '',
            'collector_vendor_phone': ''
        })

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_osp_recovery(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_osp_recovery({}, self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_early_payoff_campaign(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg = client.email_early_payoff_campaign({'fullname_with_title': ''},
                                                                                self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_covid_refinancing_approved_for_all_product(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self._prepare_email_covid_refinancing_data()

        status_code, headers, subject, msg, template = client.email_covid_refinancing_approved_for_all_product(
            self.customer_info, self.payment_info, self.subject, "email_pede_oct.html", self.url)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_covid_refinancing_activated_for_all_product(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, subject, msg, template = client.email_covid_refinancing_activated_for_all_product(
            self.application.customer, self.subject, 'email_pede_oct.html', self.payment, self.url)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_lebaran_campaign_2020(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        date_param = datetime.now()
        date_param_24_4 = date_param.replace(day=24, month=4)
        date_param_9_5 = date_param.replace(day=9, month=5)

        # Partner
        self.application.gender = "Pria"

        status_code, headers, subject, msg, template = client.email_lebaran_campaign_2020(self.application,
                                                                                          date_param_24_4, self.url,
                                                                                          self.url, True)

        self.assertEqual(status_code, self.mocked_status_code)

        # Covering gender control structure
        self.application.gender = "Wanita"

        status_code, headers, subject, msg, template = client.email_lebaran_campaign_2020(self.application,
                                                                                          date_param_9_5, self.url,
                                                                                          self.url, True)

        self.assertEqual(status_code, self.mocked_status_code)

        # Non partner
        self.application.gender = ""
        status_code, headers, subject, msg, template = client.email_lebaran_campaign_2020(self.application,
                                                                                          date_param_24_4, self.url,
                                                                                          self.url, False)

        self.assertEqual(status_code, self.mocked_status_code)

        status_code, headers, subject, msg, template = client.email_lebaran_campaign_2020(self.application,
                                                                                          date_param_9_5, self.url,
                                                                                          self.url, False)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_covid_refinancing_opt(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self._prepare_email_covid_refinancing_data()

        status_code, headers, subject, msg, template_code = client.email_covid_refinancing_opt({
            'customer': self.loan.customer,
            'encrypted_uuid': ''
        }, self.subject, "email_pede_oct.html", "")

        self.assertEqual(status_code, self.mocked_status_code)

    def _prepare_email_covid_refinancing_data(self):
        ApplicationFactory(customer=self.loan.customer)
        application_set = self.loan.customer.application_set.all()

        for number, application in enumerate(application_set):
            application.customer_credit_limit = None
            application.is_deleted = False
            application.save()

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_covid_refinancing_approved_for_r4(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self._prepare_email_covid_refinancing_data()

        self.payment_info["total_discount_percent"] = 2
        self.payment_info["total_payments"] = 200000

        status_code, headers, subject, msg = client.email_covid_refinancing_approved_for_r4(
            self.customer_info, self.payment_info, self.subject, "email_pede_oct.html", self.url)

        self.assertEqual(status_code, self.mocked_status_code)

        status_code, headers, subject, msg = client.email_covid_refinancing_approved_for_r4(
            self.customer_info, self.payment_info, self.subject, "covid_refinancing/covid_r4_approved_email.html",
            self.url)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_covid_pending_refinancing_approved_for_all_product(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        self._prepare_email_covid_refinancing_data()

        status_code, headers, subject, msg, template = client.email_covid_pending_refinancing_approved_for_all_product(
            self.customer_info, self.payment_info, self.subject, "email_pede_oct.html")

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_intelix_error_report(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, body, headers, message = client.email_intelix_error_report("Failure", self.receiver)

        self.assertEqual(status_code, self.mocked_status_code)

    @mock.patch("juloserver.julo.clients.email.JuloEmailClient.send_email_with_sendgrid")
    def test_email_bni_va_generation_limit_alert(self, mocker):
        client = get_julo_email_client()

        mocker.return_value = ObjectMock(status_code=self.mocked_status_code, body=self.mocked_body,
                                         headers=self.mocked_headers)

        status_code, headers, msg = client.email_bni_va_generation_limit_alert(980000, self.subject, self.receiver_list, self.cc_multiple)

        self.assertEqual(status_code, self.mocked_status_code)


@override_settings(SUSPEND_SIGNALS=True)
class TestObjectSMSClient(TestCase):
    def setUp(self):
        self.partner = PartnerFactory()
        self.application = ApplicationFactory(partner=self.partner)

        self.application_history = ApplicationHistoryFactory(application_id=self.application.id,
                                                             status_new=
                                                             ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED)

        self.loan = LoanFactory(application=self.application)
        self.loan.fund_transfer_ts = datetime.now(tz=pytz.timezone(settings.TIME_ZONE))

        self.payment = PaymentFactory(loan=self.loan, ptp_date=date.today())

        self.payment_event = PaymentEventFactory(payment=self.payment)
        self.statement = StatementFactory()

        self.phone_number = "081234831889"
        self.message = "Test unit sms"
        self.change_reason = "Change reason content"
        self.template_code = "lebaran20_sms_reminder_1_mtl"
        self.e_form_voucher = "GHSYI"
        self.expired_day = "2020-09-09"
        self.product_line_code = ProductLineCodes.MTL1
        self.ptp_date = date.today()
        self.due_days = 4
        self.va_number = "43654656547767"
        self.dpd = "2020-09-09"
        self.due_amount = 200000
        self.payment_url = "https://www.julofinance.com"
        self.day = 5
        self.campaign_date = date.today()
        self.context = {
            'loan_amount': self.application.loan.loan_amount,
            'loan_duration': self.application.loan.loan_duration,
            'shortened_url': settings.URL_SHORTENER_BASE
        }

        self.context_streamline = {
            'amount': "20000"
        }

        self.expected_result = "0A0000000123ABCD1"
        self.mocked_nexmo_response = ObjectMock(content=json.dumps({
            "message-count": "1",
            "messages": [
                {
                    "to": "447700900000",
                    "message-id": self.expected_result,
                    "status": "0",
                    "remaining-balance": "3.14159265",
                    "message-price": "0.03330000",
                    "network": "12345",
                    "client-ref": "my-personal-reference",
                    "account-ref": "customer1234"
                }
            ]
        }))

        self.mocked_monty_response = ObjectMock(content=json.dumps({
            "SMS": [
                {
                    "ErrorCode": "0",
                    "DestinationAddress": "081234831888",
                    "Id": self.expected_result
                }
            ]
        }))

        settings.NEXMO_API_BL_KEY = "BYFFBUSVF"
        settings.NEXMO_API_BL_SECRET = "BYGSYFD"

        settings.MONTY_NON_OTP_API_USERNAME = "BYFFBUSVF"
        settings.MONTY_NON_OTP_API_PASSWORD = "BYFFBUSVF"
        settings.MONTY_API_URL = "BYFFBUSVF"
        settings.MONTY_API_USERNAME = "BYFFBUSVF"
        settings.MONTY_API_PASSWORD = "BYFFBUSVF"

        TelcoServiceProviderFactory(
            provider_name=SmsTspVendorConstants.TELKOMSEL,
            telco_code=['0812']
        )
        SmsTspVendorConfigFactory(
            tsp=SmsTspVendorConstants.TELKOMSEL,
            primary=SmsTspVendorConstants.NEXMO,
            backup=SmsTspVendorConstants.MONTY
        )

    @mock.patch("juloserver.julo.clients.sms.requests.get")
    def test_exception_send_sms_monty(self, mocker):
        client = get_julo_sms_client()

        mocker.side_effect = Exception("Not sent")

        FeatureSettingFactory(feature_name=FeatureNameConst.MONTY_SMS, is_active=True)

        with self.assertRaises(JuloException) as context:
            client.send_sms_monty(self.phone_number, self.message, is_otp=False)

        self.assertIsInstance(context.exception, SmsNotSent)

    @mock.patch("juloserver.julo.clients.sms.requests.get")
    def test_send_sms_monty(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_monty_response

        FeatureSettingFactory(feature_name=FeatureNameConst.MONTY_SMS, is_active=True)

        message, api_response = client.send_sms_monty("+" + self.phone_number, self.message, is_otp=True)

        self.assertEqual(api_response["messages"][0]["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_exception_send_sms_nexmo(self, mocker):
        client = get_julo_sms_client()

        mocker.side_effect = Exception("Not sent")

        with self.assertRaises(JuloException) as context:
            client.send_sms_nexmo(self.phone_number, self.message, is_paylater=False, is_otp=False)

        self.assertIsInstance(context.exception, SmsNotSent)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_send_sms_nexmo(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.send_sms_nexmo(self.phone_number, self.message, is_paylater=False, is_otp=False)

        self.assertEqual(api_response["messages"][0]["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_send_sms(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        msg, api_response = client.send_sms(self.phone_number, self.message, is_otp=False)

        self.assertEqual(api_response["messages"][0]["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_legal_document_resubmission(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_legal_document_resubmission(self.application, "Change-Reason,Chane-Reason2")

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_due_today(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        result = client.sms_payment_due_today(self.payment)

        self.assertEqual(result, None)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1
        self.payment.due_date = date.today()

        message, api_response, template = client.sms_payment_due_today(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_due_in2(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        result = client.sms_payment_due_in2(self.payment)

        self.assertEqual(result, None)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1
        self.payment.due_date = date.today()

        message, api_response, template = client.sms_payment_due_in2(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_due_in7(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        self.payment.due_date = date.today()

        result = client.sms_payment_due_in7(self.payment)

        self.assertEqual(result, None)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1

        message, api_response, template = client.sms_payment_due_in7(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_due_in4(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        self.payment.due_date = date.today()

        message, api_response, template = client.sms_payment_due_in4(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

        self.payment.ptp_date = None

        # MTL
        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1

        message, api_response, template = client.sms_payment_due_in4(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

        # STL
        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.STL1

        message, api_response, template = client.sms_payment_due_in4(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_dpd_1(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_payment_dpd_1(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_dpd_3(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_payment_dpd_3(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_dpd_5(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_payment_dpd_5(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_dpd_7(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_payment_dpd_7(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_dpd_10(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.STL1
        self.payment.ptp_date = date.today()

        result = client.sms_payment_dpd_10(self.payment)

        self.assertEqual(result, None)

        self.payment.ptp_date = None
        self.payment.due_date = date.today()

        message, api_response, template = client.sms_payment_dpd_10(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_dpd_21(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1

        message, api_response, template = client.sms_payment_dpd_21(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_custom_payment_reminder(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_custom_payment_reminder(self.phone_number, self.message)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_ptp_update(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_payment_ptp_update(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_kyc_in_progress(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_kyc_in_progress(self.phone_number, self.e_form_voucher)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_resubmission_request_reminder(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_resubmission_request_reminder(self.application, self.expired_day)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_event_end_year(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_event_end_year(self.phone_number)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_reminder_138(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_reminder_138(self.phone_number)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.process_streamlined_comm")
    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_send_sms_streamline(self, mocker, mocked_process_streamlined_comm):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        mocked_process_streamlined_comm.return_value = None

        result = client.send_sms_streamline(self.template_code,
                                                self.context_streamline, self.application)

        self.assertEqual(result, None)

        mocked_process_streamlined_comm.return_value = "Exist"

        message, api_response, template = client.send_sms_streamline(self.template_code,
                                                                     self.context_streamline, self.application)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_reminder_175(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_reminder_175(self.phone_number)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_reminder_135_21year(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_reminder_135_21year(self.application)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_grab_notification(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_grab_notification(self.phone_number, reminder=True)

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response = client.sms_grab_notification(self.phone_number, reminder=False)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_lebaran_promo(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_lebaran_promo(self.application, self.payment_event)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_loc_notification(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_loc_notification(self.phone_number, self.message)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_va_notification(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_va_notification(self.application)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_experiment(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_experiment(self.payment, 'dpd_10')

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, template = client.sms_experiment(self.payment, 'due_in')

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, template = client.sms_experiment(self.payment, 'due_today')

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, template = client.sms_experiment(self.payment, 'dpd_1')

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, template = client.sms_experiment(self.payment, 'dpd_3')

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, template = client.sms_experiment(self.payment, 'dpd_5')

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, template = client.sms_experiment(self.payment, 'dpd_7')

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, template = client.sms_experiment(self.payment, 'dpd_21')

        self.assertEqual(api_response["message-id"], self.expected_result)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1

        message, api_response, template = client.sms_experiment(self.payment, 'dpd_21')

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_agreement(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_agreement(self.phone_number, self.message)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_prefix_change_notification(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.prefix_change_notification(self.phone_number, self.message)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_blast_custom(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.blast_custom(self.phone_number, self.template_code, context=None)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_custom_paylater_reminder(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_custom_paylater_reminder(self.phone_number, self.message)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_premium_otp(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.premium_otp(self.phone_number, self.message, False)

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response = client.premium_otp(self.phone_number, self.message, True)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_reminder_172(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_reminder_172(self.phone_number)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_loan_approved(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_loan_approved(self.application)

        self.assertEqual(api_response["message-id"], self.expected_result)

        # has shortened url
        ShortenedUrlFactory()
        message, api_response, template = client.sms_loan_approved(self.application)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_reminder_replaced_wa(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1
        self.payment.ptp_date = date.today()

        result = client.sms_payment_reminder_replaced_wa(self.payment)

        self.assertEqual(result, None)

        self.payment.ptp_date = None
        self.payment.due_date = date.today()

        message, api_response, template = client.sms_payment_reminder_replaced_wa(self.payment)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_payment_reminder_replaced_wa_for_bukalapak(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_payment_reminder_replaced_wa_for_bukalapak(self.statement,
                                                                                      self.template_code,
                                                                                      self.loan.customer)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_get_sms_templates(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        template = client.get_sms_templates(self.product_line_code, self.ptp_date, self.due_days, "Pria")

        self.assertEqual(template, 'sms_ptp_mtl_' + ('+' + str(self.due_days) if self.due_days > 0 else str(self.due_days)))

        template = client.get_sms_templates(ProductLineCodes.STL1, date.today(), self.due_days, "Wanita")

        self.assertEqual(template,
                         'sms_ptp_stl_' + ('+' + str(self.due_days) if self.due_days > 0 else str(self.due_days)))

        # PEDE STL product line
        template = client.get_sms_templates(ProductLineCodes.PEDESTL1, None, self.due_days, "Pria")

        self.assertEqual(template,
                         'pedestl_sms_dpd_' + ('+' + str(self.due_days) if self.due_days > 0 else str(self.due_days)))

        template = client.get_sms_templates(ProductLineCodes.PEDESTL2, date.today(), self.due_days, "Wanita")

        self.assertEqual(template,
                         'sms_ptp_pedestl_' + ('+' + str(self.due_days) if self.due_days > 0 else str(self.due_days)))

        # PEDE MTL product line
        template = client.get_sms_templates(ProductLineCodes.PEDEMTL1, None, self.due_days, "Pria")

        self.assertEqual(template,
                         'pedemtl_sms_dpd_' + ('+' + str(self.due_days) if self.due_days > 0 else str(self.due_days)))

        template = client.get_sms_templates(ProductLineCodes.PEDEMTL2, date.today(), self.due_days, "Wanita")

        self.assertEqual(template,
                         'sms_ptp_pedemtl_' + ('+' + str(self.due_days) if self.due_days > 0 else str(self.due_days)))

        # LAKU6 product line
        template = client.get_sms_templates(ProductLineCodes.LAKU1, None, self.due_days, "Pria")

        self.assertEqual(template,
                         'laku6mtl_sms_dpd_' + ('+' + str(self.due_days) if self.due_days > 0 else str(self.due_days)))

        template = client.get_sms_templates(ProductLineCodes.LAKU2, date.today(), self.due_days, "Wanita")

        self.assertEqual(template,
                         'sms_ptp_laku6_' + ('+' + str(self.due_days) if self.due_days > 0 else str(self.due_days)))

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_notify_bukalapak_customer_va_generated(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_notify_bukalapak_customer_va_generated(self.template_code,
                                                                                  self.loan.customer, self.va_number,
                                                                                  self.dpd, self.due_amount)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_automated_comm(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, template = client.sms_automated_comm(self.payment, self.message, self.template_code)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_osp_recovery_promo(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_osp_recovery_promo(self.phone_number, is_change_template=False)

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response = client.sms_osp_recovery_promo(self.phone_number, is_change_template=True)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_lebaran_campaign_2020(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        self.campaign_date = self.campaign_date.replace(day=26, month=4)
        message, api_response, template_code, content_message = client.sms_lebaran_campaign_2020(self.application,
                                                                                                 self.campaign_date,
                                                                                                 self.payment_url,
                                                                                                 is_partner=False)

        self.assertEqual(api_response["message-id"], self.expected_result)

        self.campaign_date = self.campaign_date.replace(day=6, month=5)
        message, api_response, template_code, content_message = client.sms_lebaran_campaign_2020(self.application,
                                                                                                 self.campaign_date,
                                                                                                 self.payment_url,
                                                                                                 is_partner=False)

        self.assertEqual(api_response["message-id"], self.expected_result)

        self.campaign_date = self.campaign_date.replace(day=26, month=4)
        message, api_response, template_code, content_message = client.sms_lebaran_campaign_2020(self.application,
                                                                                                 self.campaign_date,
                                                                                                 self.payment_url,
                                                                                                 is_partner=True)

        self.assertEqual(api_response["message-id"], self.expected_result)

        self.campaign_date = self.campaign_date.replace(day=6, month=5)
        message, api_response, template_code, content_message = client.sms_lebaran_campaign_2020(self.application,
                                                                                                 self.campaign_date,
                                                                                                 self.payment_url,
                                                                                                 is_partner=True)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_repayment_awareness_campaign(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response = client.sms_repayment_awareness_campaign(self.loan.customer.fullname, 17,
                                                                        self.phone_number)

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response = client.sms_repayment_awareness_campaign(self.loan.customer.fullname, 24,
                                                                        self.phone_number)

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response = client.sms_repayment_awareness_campaign(self.loan.customer.fullname, 1,
                                                                        self.phone_number)

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response = client.sms_repayment_awareness_campaign(self.loan.customer.fullname, 8,
                                                                        self.phone_number)

        self.assertEqual(api_response["message-id"], self.expected_result)

    @mock.patch("juloserver.julo.clients.sms.requests.post")
    def test_sms_campaign_for_noncontacted_customer(self, mocker):
        client = get_julo_sms_client()

        mocker.return_value = self.mocked_nexmo_response

        message, api_response, phone_number = client.sms_campaign_for_noncontacted_customer(self.phone_number,
                                                                                            self.loan.customer.fullname,
                                                                                            1)

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, phone_number = client.sms_campaign_for_noncontacted_customer(self.phone_number,
                                                                                            self.loan.customer.fullname,
                                                                                            2)

        self.assertEqual(api_response["message-id"], self.expected_result)

        message, api_response, phone_number = client.sms_campaign_for_noncontacted_customer(self.phone_number,
                                                                                            self.loan.customer.fullname,
                                                                                            3)

        self.assertEqual(api_response["message-id"], self.expected_result)

        with self.assertRaises(JuloException) as context:
            client.sms_campaign_for_noncontacted_customer(self.phone_number,
                                                      self.loan.customer.fullname,
                                                      4)

        self.assertIsInstance(context.exception, JuloException)


@override_settings(SUSPEND_SIGNALS=True)
class TestObjectPushNotificationClient(TestCase):
    def setUp(self):
        customer = CustomerFactory()
        device = DeviceFactory(customer=customer)

        self.partner = PartnerFactory()
        self.application = ApplicationFactory(partner=self.partner, customer=customer)

        self.application_history = ApplicationHistoryFactory(application_id=self.application.id,
                                                             status_new=
                                                             ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED)

        self.loan = LoanFactory(application=self.application)
        self.loan.fund_transfer_ts = datetime.now(tz=pytz.timezone(settings.TIME_ZONE))

        self.device = DeviceFactory(customer=self.loan.customer)
        self.payment = PaymentFactory(loan=self.loan, ptp_date=date.today())

        self.payment_event = PaymentEventFactory(payment=self.payment)
        self.statement = StatementFactory()
        self.sepulsa_transaction = SepulsaTransactionFactory(customer=customer)
        self.cashback_transaction = CashbackTransferTransactionFactory(application_id=self.application.id)

        self.aws_face_recognition = AwsFaceRecogLogFactory()

        self.gcm_reg_id = "IUGDWUIGDWGDWUIDGWIDGWIDGWDIWGDWDWDWGDIWGD"
        self.payment_number = ""
        self.payment_status_code = ""
        self.product_line_code = ""
        self.credit_score = "A-"
        self.pn_type = "pn1_21h"
        self.hour = 21
        self.due_date = date.today()
        self.payment_id = self.application.id
        self.message = ""
        self.heading_title = ""
        self.template_code = ""
        self.buttons = ""
        self.cashback_amt = ""
        self.pn_type = ""
        self.notification_template = {
            "title": 'title',
            "body": 'body',
            "click_action": 'click_action',
            "destination_page": 'destination_page',
            "image_url": 'image_url'
        }
        self.message = ""
        self.image_url = ""
        self.title = ""
        self.transaction_status = ""
        self.notif_text = ""
        self.first_name = ""
        self.va_method = ""
        self.va_number = ""
        self.cashback = ""
        self.success = True

        self.mocked_response = ObjectMock(status_code=200)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_etl_finished(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_etl_finished(self.application, True, False)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        response = client.inform_etl_finished(self.application, False, True)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_offers_made(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_offers_made(self.loan.customer.fullname, self.gcm_reg_id,
                                             self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_legal_document(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_legal_document(self.loan.customer.fullname, self.gcm_reg_id,
                                                self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_legal_document_resubmission(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_legal_document_resubmission(self.loan.customer.fullname, self.gcm_reg_id,
                                                             self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_legal_document_resubmitted(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_legal_document_resubmitted(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_legal_document_signed(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_legal_document_signed(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_loan_has_started(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_loan_has_started(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.process_streamlined_comm")
    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_payment_received(self, mocker, mocked_process_streamlined_comm):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response
        mocked_process_streamlined_comm.return_value = "Exist"

        response = client.inform_payment_received(self.gcm_reg_id, self.payment_number, self.application.id, self.product_line_code, self.payment_status_code)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_payment_due_soon(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        self.payment.ptp_date = None
        self.payment.due_date = date.today()
        response = client.inform_payment_due_soon(self.payment)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        self.payment.ptp_date = date.today()
        self.payment.due_date = None
        response = client.inform_payment_due_soon(self.payment)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_payment_due_today(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        self.payment.ptp_date = None
        self.payment.due_date = date.today()
        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1

        response = client.inform_payment_due_today(self.payment)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        self.payment.ptp_date = date.today()
        self.payment.due_date = None
        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1

        response = client.inform_payment_due_today(self.payment)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_mtl_payment(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        self.payment.due_date = date.today()
        response = client.inform_mtl_payment(self.payment, status=None, dpd=None)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_stl_payment(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response
        self.payment.due_date = date.today()

        response = client.inform_stl_payment(self.payment, status=None)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_reminder_upload_document(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.reminder_upload_document(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_reminder_docs_resubmission(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.reminder_docs_resubmission(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_reminder_verification_call_ongoing(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.reminder_verification_call_ongoing(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_reminder_app_status_105(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.reminder_app_status_105(self.gcm_reg_id, self.application.id,
                                                  self.credit_score)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_docs_submitted(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_docs_submitted(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_sphp_signed(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_sphp_signed(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_submission_approved(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_submission_approved(self.loan.customer.fullname, self.gcm_reg_id,
                                                     self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_send_pn_playstore_rating(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.send_pn_playstore_rating(self.loan.customer.fullname, self.gcm_reg_id,
                                                   self.application.id, self.message, self.image_url, self.title)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_remainder_for_playstore_rating(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.remainder_for_playstore_rating(self.loan.customer.fullname, self.gcm_reg_id,
                                                         self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_payment_late(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_payment_late(self.payment)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        self.payment.ptp_date = date.today()

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.MTL1
        response = client.inform_payment_late(self.payment)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        self.payment.loan.application.product_line.product_line_code = ProductLineCodes.STL1
        response = client.inform_payment_late(self.payment)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        self.payment.ptp_date = None
        self.payment.due_date = date.today()
        response = client.inform_payment_late(self.payment)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        # application = ApplicationFactory()
        # loan = LoanFactory(application=application)
        # payment = PaymentFactory(loan=loan)
        # payment.due_date = date.today()
        #
        # response = client.inform_payment_late(payment)
        #
        # self.assertEqual(response, ObjectMock)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_email_verified(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_email_verified(self.gcm_reg_id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_docs_resubmission(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_docs_resubmission(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        aws_recognitions = self.aws_face_recognition.__class__.objects.filter(application=self.application).all()

        for index, aws_recognition in enumerate(aws_recognitions):
            aws_recognition.application_id = self.application.id
            aws_recognition.is_quality_check_passed = False
            aws_recognition.save()

        response = client.inform_docs_resubmission(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_docs_verified(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_docs_verified(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_trigger_location(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.trigger_location(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_verification_call_ongoing(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_verification_call_ongoing(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_kyc_in_progress(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.kyc_in_progress(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_alert_rescrape(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.alert_rescrape(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_infrom_cashback_sepulsa_transaction(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        self.sepulsa_transaction.status = 'success'

        response = client.infrom_cashback_sepulsa_transaction(self.loan.customer, "success")

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        response = client.infrom_cashback_sepulsa_transaction(self.loan.customer, "failed")

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        response = client.infrom_cashback_sepulsa_transaction(self.loan.customer, "other")

        self.assertEqual(response, None)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_notify_lebaran_promo(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.notify_lebaran_promo(self.application)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_infrom_loc_sepulsa_transaction(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        self.sepulsa_transaction.transaction_status = 'success'

        response = client.infrom_loc_sepulsa_transaction(self.sepulsa_transaction)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        self.sepulsa_transaction.transaction_status = 'failed'
        response = client.infrom_loc_sepulsa_transaction(self.sepulsa_transaction)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        self.sepulsa_transaction.transaction_status = 'others'
        response = client.infrom_loc_sepulsa_transaction(self.sepulsa_transaction)

        self.assertEqual(response, None)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_loc_notification(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_loc_notification(self.gcm_reg_id, self.message)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_alert_retrofix_credit_score(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.alert_retrofix_credit_score(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_transfer_cashback_finish(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_transfer_cashback_finish(self.cashback_transaction, self.success)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        response = client.inform_transfer_cashback_finish(self.cashback_transaction, False)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_loc_reset_pin_finish(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_loc_reset_pin_finish(self.gcm_reg_id, self.message)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_get_cashback_promo_asian_games(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_get_cashback_promo_asian_games(self.loan.customer)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_asian_games_campaign(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_asian_games_campaign(self.loan.customer)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        response = client.inform_asian_games_campaign(CustomerFactory())

        self.assertEqual(response, False)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_va_notification(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_va_notification(self.loan.customer)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_early_payment_promo(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.early_payment_promo(self.gcm_reg_id, self.notif_text)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_robocall_notification(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_robocall_notification(self.loan.customer, self.application.id,
                                                       self.payment_id, dpd=None, type=None)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_loan_paid_off_rating(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.loan_paid_off_rating(self.loan.customer)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_complete_form_notification(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.complete_form_notification(self.loan.customer)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_notifications_enhancements_v1(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.notifications_enhancements_v1(self.loan.customer, self.notification_template)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_pn_backup_va(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.pn_backup_va(self.gcm_reg_id, self.first_name, self.va_method, self.va_number)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_pn_face_recognition(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.pn_face_recognition(self.gcm_reg_id, self.message)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_inform_old_version_reinstall(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.inform_old_version_reinstall(self.gcm_reg_id, self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_cashback_transfer_complete_osp_recovery_apr2020(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.cashback_transfer_complete_osp_recovery_apr2020(self.application.id,
                                                                          self.gcm_reg_id, self.cashback_amt)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_notify_lebaran_campaign_2020_mtl(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        param_date = date.today()
        param_date = param_date.replace(day=27, month=4)
        response = client.notify_lebaran_campaign_2020_mtl(self.application, param_date)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        param_date = param_date.replace(day=29, month=4)
        response = client.notify_lebaran_campaign_2020_mtl(self.application, param_date)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        param_date = param_date.replace(day=1, month=5)
        response = client.notify_lebaran_campaign_2020_mtl(self.application, param_date)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        param_date = param_date.replace(day=3, month=5)
        response = client.notify_lebaran_campaign_2020_mtl(self.application, param_date)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        param_date = param_date.replace(day=7, month=5)
        response = client.notify_lebaran_campaign_2020_mtl(self.application, param_date)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

        param_date = param_date.replace(day=1, month=1)
        response = client.notify_lebaran_campaign_2020_mtl(self.application, param_date)

        self.assertEqual(response, None)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_automated_payment_reminder(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.automated_payment_reminder(self.payment, self.message, self.heading_title,
                                                     self.template_code,
                                                     self.buttons)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_automated_payment_reminder_with_image(self, mocker):
        self.streamlined_communication = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.PN,
            template_code='j1_pn_T-5_backup',
            moengage_template_code='j1_pn_T-5',
            is_automated=True,
            is_active=True,
            extra_conditions=UNSENT_MOENGAGE,
            time_sent='16:0',
            dpd=-5
        )
        self.image = ImageFactory(image_source=self.streamlined_communication.id, image_type=ImageType.STREAMLINED_PN)
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.automated_payment_reminder(self.payment, self.message, self.heading_title,
                                                     self.template_code,
                                                     self.buttons, self.image)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_send_pn_depracated_app(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.send_pn_depracated_app(self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)

    @mock.patch("juloserver.julo.clients.pn.requests.post")
    def test_send_reminder_sign_sphp(self, mocker):
        client = get_julo_pn_client()

        mocker.return_value = self.mocked_response

        response = client.send_reminder_sign_sphp(self.application.id)

        self.assertEqual(response.status_code, self.mocked_response.status_code)
