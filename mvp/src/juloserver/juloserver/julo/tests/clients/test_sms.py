from datetime import datetime

from django.test.testcases import TestCase
from django.utils import timezone
from mock import patch

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.application_flow.factories import ExperimentSettingFactory
from juloserver.julo.clients.infobip import JuloInfobipClient
from juloserver.julo.clients.sms import JuloSmsClient
from juloserver.julo.constants import (
    VendorConst,
    WorkflowConst,
)
from juloserver.julo.models import SmsHistory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationJ1Factory,
    CommsProviderLookupFactory,
    CustomerFactory,
    ProductLineFactory,
    SmsHistoryFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform, Product
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.streamlined_communication.models import SmsVendorRequest
from juloserver.streamlined_communication.test.factories import (
    StreamlinedCommunicationFactory, StreamlinedMessageFactory
)
from juloserver.grab.constants import GrabSMSTemplateCodes
from juloserver.julo.clients import get_julo_sms_client
class TestJuloSendExperiment(TestCase):
    def setUp(self):
        self.streamlined_communication = StreamlinedCommunicationFactory()
        self.customer = CustomerFactory()
        self.experiment_setting = ExperimentSettingFactory(
            code='PrimarySMSVendorsABTest',
            criteria={"monty": [0, 1, 2, 3], "infobip": [4, 5, 6], "alicloud": [7, 8, 9]},
            start_date=datetime(2022, 12, 1),
            end_date=datetime(2022, 12, 31),
            is_active=True
        )

    @patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    @patch('juloserver.julo.clients.sms.Reminder')
    def test_send_sms_experiment_monty_main_vendor_in_experiment(self, mock_reminder, mock_send_sms):
        self.account = AccountFactory(
            id=1002,
            customer=self.customer,
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            ),
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationJ1Factory(customer=self.customer, account=self.account)

        mock_send_sms.return_value = (
            'Message mock',
            {'messages': [
                {'julo_sms_vendor': 'monty'}
            ]}
        )
        mock_reminder.create_j1_reminder_history.return_value = None

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 12, 2)
        ):
            sms_client = JuloSmsClient()
            sms_client.sms_automated_comm_j1(self.account_payment, 'Test message',
                                            self.streamlined_communication.template_code, 'Payment')

            sms_client.send_sms.assert_called_once_with(
                is_otp=False,
                phone_number='+6281218926858',
                message='Test message'
            )

    @patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms_infobip_primary')
    @patch('juloserver.julo.clients.sms.Reminder')
    def test_send_sms_experiment_infobip_main_vendor_in_experiment(self, mock_reminder, mock_send_sms):
        self.account = AccountFactory(id=1005, customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

        mock_send_sms.return_value = (
            'Message mock',
            {'messages': [
                {'julo_sms_vendor': 'infobip'}
            ]}
        )
        mock_reminder.create_j1_reminder_history.return_value = None

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 12, 2)
        ):
            sms_client = JuloSmsClient()
            sms_client.send_sms_experiment(self.application.mobile_phone_1, 'Test message', 5)

            sms_client.send_sms_infobip_primary.assert_called_once_with(
                is_otp=False,
                phone_number='+6281218926858',
                message='Test message'
            )

    @patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms_alicloud_primary')
    @patch('juloserver.julo.clients.sms.Reminder')
    def test_send_sms_experiment_alicloud_main_vendor_in_experiment(self, mock_reminder, mock_send_sms):
        self.account = AccountFactory(id=1009, customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

        mock_send_sms.return_value = (
            'Message mock',
            {'messages': [
                {'julo_sms_vendor': 'alicloud'}
            ]}
        )
        mock_reminder.create_j1_reminder_history.return_value = None

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 12, 2)
        ):
            sms_client = JuloSmsClient()
            sms_client.send_sms_experiment(self.application.mobile_phone_1, 'Test message', 9)

            sms_client.send_sms_alicloud_primary.assert_called_once_with(
                is_otp=False,
                phone_number='+6281218926858',
                message='Test message'
            )

    @patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    @patch('juloserver.julo.clients.sms.Reminder')
    def test_send_sms_experiment_with_experiment_disabled(self, mock_reminder, mock_send_sms):
        self.account = AccountFactory(id=1004, customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

        mock_send_sms.return_value = (
            'Message mock',
            {'messages': [
                {'julo_sms_vendor': 'monty'}
            ]}
        )
        mock_reminder.create_j1_reminder_history.return_value = None

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 11, 29)
        ):
            sms_client = JuloSmsClient()
            sms_client.send_sms_experiment(self.application.mobile_phone_1, 'Test message', 4)

            sms_client.send_sms.assert_called_once_with(
                is_otp=False,
                phone_number='+6281218926858',
                message='Test message'
            )

    @patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    @patch('juloserver.julo.clients.sms.Reminder')
    def test_send_sms_multiple_application_different_workflow(self, mock_reminder, mock_send_sms):
        self.account = AccountFactory(
            id=1002,
            customer=self.customer,
            account_lookup=AccountLookupFactory(
                workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
            ),
        )
        self.account_payment = AccountPaymentFactory(account=self.account)
        # JTurbo Application
        ApplicationFactory(
            mobile_phone_1='0812189268581',
            customer=self.customer,
            account=self.account,
            application_status=StatusLookupFactory(status_code=191),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.JULO_STARTER),
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
        )
        # J1 Application
        ApplicationJ1Factory(
            mobile_phone_1='0812189268582',
            customer=self.customer,
            account=self.account,
            application_status=StatusLookupFactory(status_code=121),
        )

        mock_send_sms.return_value = (
            'Message mock',
            {'messages': [
                {'julo_sms_vendor': 'monty'}
            ]}
        )
        mock_reminder.create_j1_reminder_history.return_value = None

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 12, 2)
        ):
            sms_client = JuloSmsClient()
            sms_client.sms_automated_comm_j1(self.account_payment, 'Test message',
                                            self.streamlined_communication.template_code, 'Payment')

            sms_client.send_sms.assert_called_once_with(
                is_otp=False,
                phone_number='+62812189268581',
                message='Test message'
            )


class TestJuloInfobipClient(TestCase):
    def setUp(self):
        self.data = {
            'results': [{
                'messageId': '126123',
                'to': '62231920312',
                'from': 'SMS Info',
                'text': 'Test Text',
                'status': {
                    'groupId': 3,
                    'groupName': 'DELIVERED',
                    'id': 5,
                    'name': 'DELIVERED_TO_HANDSET',
                    'description': 'Message delivered to handset'
                },
                'error': {
                    'groupId': 0,
                    'groupName': 'OK',
                    'id': 0,
                    'name': 'NO_ERROR',
                    'description': 'No Error',
                    'permanent': False
                }
            }]
        }
        self.infobip_provider = CommsProviderLookupFactory(
            provider_name=VendorConst.INFOBIP.capitalize()
        )

    @patch('juloserver.julo.clients.infobip.logger')
    def test_infobip_client_fetch_sms_report_with_sms_history_none(self, mock_logger):
        infobip_client = JuloInfobipClient()
        infobip_client.fetch_sms_report(self.data['results'])

        mock_logger.info.assert_called_once_with({
            'message': 'Infobip send unregistered messsageId',
            'message_id': '126123',
            'data': self.data['results']
        })

    def test_infobip_client_fetch_sms_report_with_sms_history_exist(self):
        SmsHistoryFactory(
            message_id='126123',
            status='sent_to_provider',
            comms_provider=self.infobip_provider
        )

        infobip_client = JuloInfobipClient()
        infobip_client.fetch_sms_report(self.data['results'])

        sms_history = SmsHistory.objects.get(message_id='126123')
        sms_vendor_request_count = SmsVendorRequest.objects.filter(
            vendor_identifier='126123'
        ).count()
        self.assertEqual('DELIVERED', sms_history.status)
        self.assertEqual(self.infobip_provider.id, sms_history.comms_provider.id)
        self.assertEqual(sms_vendor_request_count, 1)

    @patch('juloserver.julo.clients.infobip.logger')
    def test_infobip_client_fetch_sms_report_with_error_report(self, mock_logger):
        self.data['results'][0]['error'] = {
            'groupId': 1,
            'groupName': 'HANDSET_ERRORS',
            'id': 32,
            'name': 'EC_SM_DELIVERY_FAILURE',
            'description': 'SM Delivery Failure',
            'permanent': False
        }

        SmsHistoryFactory(
            message_id='126123',
            status='sent_to_provider',
            comms_provider=self.infobip_provider
        )

        infobip_client = JuloInfobipClient()
        infobip_client.fetch_sms_report(self.data['results'])

        mock_logger.warning.assert_called_once_with({
            'message': 'Infobip returns error',
            'message_id': '126123',
            'error': 'EC_SM_DELIVERY_FAILURE - SM Delivery Failure',
            'error_id': 32
        })

        sms_history = SmsHistory.objects.get(message_id='126123')
        sms_vendor_request_count = SmsVendorRequest.objects.filter(
            vendor_identifier='126123'
        ).count()
        self.assertEqual('FAILED', sms_history.status)
        self.assertEqual(32, sms_history.delivery_error_code)
        self.assertEqual(self.infobip_provider.id, sms_history.comms_provider.id)
        self.assertEqual(sms_vendor_request_count, 1)


class TestGrabSMS(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer,
                                              mobile_phone_1='6281245789865')
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_CREATED)
        self.template_code = GrabSMSTemplateCodes.GRAB_SMS_APP_100_EXPIRE_IN_ONE_DAY
        self.application.save()
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="content"
        )
        self.streamlined_comms = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.SMS,
            template_code=self.template_code,
            product=Product.SMS.GRAB,
            status_code_id=ApplicationStatusCodes.FORM_CREATED,
            message=self.streamlined_message,
            extra_conditions=None,
            dpd=None,
            ptp=None

        )

    @patch('juloserver.julo.clients.sms.JuloSmsClient.send_sms')
    def test_send_sms_experiment_monty_main_vendor_in_experiment(self, mock_send_sms):
        julo_sms_client = get_julo_sms_client()
        mock_send_sms.return_value = (
            'Message mock',
            {'messages': [
                {'julo_sms_vendor': 'nexmo',
                 'status': '0',
                 'message-id': '123'
                 }
            ]}
        )
        julo_sms_client.send_grab_sms_based_on_template_code(
            self.template_code, self.application
        )
        self.assertFalse(SmsHistory.objects.filter(message_id='123').exists())
        self.streamlined_comms.is_active = True
        self.streamlined_comms.save()
        julo_sms_client.send_grab_sms_based_on_template_code(
            self.template_code, self.application
        )
        self.assertTrue(SmsHistory.objects.filter(message_id='123').exists())
