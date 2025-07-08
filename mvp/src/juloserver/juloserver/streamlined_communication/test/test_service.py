from builtins import str
from builtins import object
from unittest import skip
from unittest.mock import (
    patch,
    MagicMock,
)

import mock
from django.test.testcases import TestCase
from django.utils import timezone
from django.conf import settings
from datetime import datetime, timedelta

from django.test.utils import override_settings
from rest_framework import status

import juloserver.streamlined_communication.services
from juloserver.cfs.tests.factories import CfsTierFactory
from juloserver.julo.tasks import send_automated_comm_sms
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    LoanFactory,
    CustomerFactory,
    ApplicationFactory,
    ApplicationHistoryFactory,
    PaymentFactory,
    ImageFactory,
    StatusLookup,
    LoanHistoryFactory,
    PaymentMethodFactory,
    StatusLookupFactory,
    ApplicationJ1Factory,
    DocumentFactory,
    MobileFeatureSettingFactory,
    ExperimentSettingFactory,
    FDCInquiryFactory,
    FDCInquiryLoanFactory,
    OnboardingFactory,
    FeatureSettingFactory,
)
from django.contrib.auth.models import User, Group

from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    PageType,
)
from juloserver.streamlined_communication.exceptions import StreamlinedCommunicationException
from juloserver.streamlined_communication.models import (
    StreamlinedMessage,
    StreamlinedCommunication,
    StreamlinedCommunicationParameterList,
    StreamlinedCommunicationFunctionList,
    PnAction,
)
from juloserver.julo.models import Payment, VendorDataHistory
from juloserver.nexmo.models import RobocallCallingNumberChanger
from juloserver.streamlined_communication.services import (
    PushNotificationService,
    get_push_notification_service,
    is_holiday,
    process_streamlined_comm,
    process_streamlined_comm_email_subject,
    get_pn_action_buttons,
    process_streamlined_comm_context_base_on_model_and_parameter,
    process_convert_params_to_data,
    format_info_card_for_android,
    format_info_card_data,
    create_and_upload_image_assets_for_streamlined,
    is_already_have_transaction,
    process_streamlined_comm_without_filter,
    process_streamlined_comm_context_base_on_model,
    is_info_card_expired,
    process_streamlined_comm_context_for_ptp,
    process_partner_sms_message,
    checking_rating_shown,
    validate_action,
    upload_image_assets_for_streamlined_pn,
    is_julo_card_transaction_completed_action,
    is_eligible_for_deep_link,
    determine_ipa_banner_experiment,
    show_ipa_banner,
)
from juloserver.julo.constants import (
    VoiceTypeStatus,
    MobileFeatureNameConst,
    WorkflowConst,
)
from juloserver.julo.clients.voice_v2 import JuloVoiceClientV2
from juloserver.julo.services import get_nexmo_from_phone_number
from juloserver.julo.tests.factories import WorkflowFactory
from juloserver.nexmo.tests.factories import RobocallCallingNumberChangerFactory
from juloserver.julo.services2.voice import get_voice_template
from juloserver.streamlined_communication.test.factories import (
    HolidayFactory,
    InfoCardPropertyFactory,
    ButtonInfoCardFactory,
    StreamlinedMessageFactory,
    StreamlinedCommunicationFactory,
)
from juloserver.streamlined_communication.constant import (
    CardProperty,
    ImageType,
)
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory, AccountPropertyFactory
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    JuloOneCodes,
    PaymentStatusCodes,
)
from juloserver.reminder.models import CallRecordUrl
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.payment_point.constants import TransactionMethodCode
from dateutil.relativedelta import relativedelta
from juloserver.julo.constants import OnboardingIdConst
from juloserver.julo.constants import FeatureNameConst

PACKAGE_NAME = 'juloserver.streamlined_communication.services'


class TestService(TestCase):
    def setUp(self):
        message_email = StreamlinedMessage.objects.create(message_content="<html><body>Test Email</body></html>")
        message_email_2 = StreamlinedMessage.objects.create(message_content="<html><body>Test Email 2</body></html>")
        message_pn = StreamlinedMessage.objects.create(message_content="Test PN")
        message_pn_with_param = StreamlinedMessage.objects.create(message_content="PN Hi {{firstname}}",
                                                                  parameter="{firstname}")
        message_sms = StreamlinedMessage.objects.create(message_content="Test SMS")
        message_wa = StreamlinedMessage.objects.create(message_content="Test WA")
        message_ian_110 = StreamlinedMessage.objects.create(message_content="Test IAN 110")
        message_ian_120 = StreamlinedMessage.objects.create(message_content="Test IAN 120")
        message_pn_with_param_fullname = StreamlinedMessage.objects.create(message_content="PN Hi {{fullname}}",
                                                                           parameter="{fullname}")
        message_pn_with_action_buttons = StreamlinedMessage.objects.create(message_content="Test PN with Action Buttons")

        # test same template_code different criteria
        streamlined_test_email = StreamlinedCommunication.objects.create(
            status_code_id=110,
            communication_platform=CommunicationPlatform.EMAIL,
            message=message_email,
            template_code='email_110')
        streamlined_test_email_2 = StreamlinedCommunication.objects.create(
            status_code_id=110,
            communication_platform=CommunicationPlatform.EMAIL,
            template_code='email_110',
            message=message_email_2,
            criteria={"is_with_criteria": True})
        # test with and without parameter
        streamlined_test_pn_with_param = StreamlinedCommunication.objects.create(
            status_code_id=110,
            communication_platform=CommunicationPlatform.PN,
            template_code='pn_110_with_param',
            message=message_pn_with_param)
        streamlined_test_pn_without_param = StreamlinedCommunication.objects.create(
            status_code_id=110,
            communication_platform=CommunicationPlatform.PN,
            template_code='pn_110_without',
            message=message_pn,
        )
        self.streamlined_test_pn_with_param = streamlined_test_pn_with_param
        streamlined_test_pn_with_param_fullname = StreamlinedCommunication.objects.create(
            status_code_id=110,
            communication_platform=CommunicationPlatform.PN,
            template_code='pn_110_with_param_fullname',
            message=message_pn_with_param_fullname,
        )
        # test only template_code without status_code
        streamlined_test_sms = StreamlinedCommunication.objects.create(
            communication_platform=CommunicationPlatform.SMS,
            template_code='sms_reminder',
            message=message_sms,
        )
        # test only status without template_code
        streamlined_test_wa = StreamlinedCommunication.objects.create(
            communication_platform=CommunicationPlatform.WA,
            status_code_id=110,
            message=message_wa,
        )
        # test same template_code different status_code
        streamlined_test_ian_110 = StreamlinedCommunication.objects.create(
            status_code_id=110,
            communication_platform=CommunicationPlatform.IAN,
            template_code='ian_reminder',
            message=message_ian_110,
        )
        streamlined_test_ian_120 = StreamlinedCommunication.objects.create(
            status_code_id=120,
            communication_platform=CommunicationPlatform.IAN,
            template_code='ian_reminder',
            message=message_ian_120,
        )

        self.same_template_code_different_criteria_false = dict(status_code_id=110, template_code='email_110',
                                                                communication_platform=CommunicationPlatform.EMAIL,
                                                                criteria__isnull=True)
        self.same_template_code_different_criteria_true = dict(status_code_id=110, template_code='email_110',
                                                               communication_platform=CommunicationPlatform.EMAIL,
                                                               criteria__is_with_criteria=True)
        self.with_param = dict(status_code_id=110,
                               communication_platform=CommunicationPlatform.PN,
                               template_code='pn_110_with_param')
        self.without_param = dict(status_code_id=110,
                                  communication_platform=CommunicationPlatform.PN,
                                  template_code='pn_110_without')
        self.only_template_code = dict(communication_platform=CommunicationPlatform.SMS,
                                       template_code='sms_reminder')
        self.only_status_code = dict(communication_platform=CommunicationPlatform.WA,
                                     status_code_id=110)
        self.different_template_same_status_code_110 = dict(status_code_id=110,
                                                          communication_platform=CommunicationPlatform.IAN,
                                                          template_code='ian_reminder')
        self.different_template_same_status_code_120 = dict(status_code_id=120,
                                                          communication_platform=CommunicationPlatform.IAN,
                                                          template_code='ian_reminder')
        self.streamlined_email = streamlined_test_email
        self.streamlined_sms = streamlined_test_sms
        streamlined_parameterlist = StreamlinedCommunicationParameterList.objects.create(
            parameter_name='test',
            platform='SMS',
            example='test_example',
            description='test_description'
        )
        self.streamlined_parameterlist = streamlined_parameterlist
        streamlined_function_list = StreamlinedCommunicationFunctionList.objects.create(
            function_name='test_function',
            description='function description',
            communication_platform=CommunicationPlatform.EMAIL
        )
        self.streamlined_function_list = streamlined_function_list
        self.streamlined_wa = streamlined_test_wa
        self.streamlined_test_pn_with_param_fullname = streamlined_test_pn_with_param_fullname
        self.streamlined_test_pn_with_buttons= StreamlinedCommunication.objects.create(
            type='Payment Reminder',
            communication_platform=CommunicationPlatform.PN,
            template_code='MTL_T0',
            message=message_pn_with_action_buttons)
        self.pn_action = PnAction.objects.create(
            streamlined_communication=self.streamlined_test_pn_with_buttons,
            order=1,
            title="Hubungi Kami",
            action="email",
            target="collections@julo.co.id"
        )
        self.streamlined_parameterlist_sms = StreamlinedCommunicationParameterList.objects.create(
            parameter_name='sms_fullname',
            platform='SMS',
            example='test_example',
            description='test_description',
            parameter_model_value={
                'accountpayment': 'model.account.customer.fullname.title()',
                'application': 'model.customer.fullname.title()',
            }
        )
        self.streamlined_parameterlist_sms1 = StreamlinedCommunicationParameterList.objects.create(
            parameter_name='sms_firstname',
            platform='SMS',
            example='test_example',
            description='test_description',
            parameter_model_value={
                'accountpayment': 'model.account.customer.first_name_only',
                'application': 'model.customer.first_name_only',
            }
        )

    def test_same_template_code_different_criteria(self):
        email_without_criteria = process_streamlined_comm(self.same_template_code_different_criteria_false)
        email_with_criteria = process_streamlined_comm(self.same_template_code_different_criteria_true)
        self.assertNotEquals(
            email_without_criteria,
            email_with_criteria
        )
        self.assertTrue(len(email_without_criteria) > 0)
        self.assertTrue(len(email_with_criteria) > 0)

    def test_with_param_and_without(self):
        param = {'firstname': 'julo'}
        self.assertEqual(process_streamlined_comm(self.with_param, param), "PN Hi julo")
        self.assertEqual(process_streamlined_comm(self.without_param, param), "Test PN")

    def test_only_template_code_and_only_status_code(self):
        self.assertNotEquals(
            process_streamlined_comm(self.only_template_code),
            ""
        )
        self.assertNotEquals(
            process_streamlined_comm(self.only_status_code),
            ""
        )

    def test_different_template_same_status_code(self):
        for_110 = process_streamlined_comm(self.different_template_same_status_code_110)
        for_120 = process_streamlined_comm(self.different_template_same_status_code_120)
        self.assertNotEquals(
            for_110,
            for_120
        )
        self.assertTrue(len(for_110) > 0)
        self.assertTrue(len(for_120) > 0)

    def test_process_email_subject(self):
        subject = "unit test for subject {{title}} with cashback {{cashback}}"
        context = {
            "title": "Julo",
            "cashback": "Rp. 1000"
        }
        subject = process_streamlined_comm_email_subject(subject, context)
        self.assertTrue(subject == "unit test for subject Julo with cashback Rp. 1000")

    def test_process_streamlined_comm_context_base_on_model_and_parameter(self):
        streamlined_comm = self.streamlined_test_pn_with_param_fullname
        payment = Payment.objects.not_paid_active().filter(id=4000000302)
        self.assertNotEquals(
            process_streamlined_comm_context_base_on_model_and_parameter(
                streamlined_comm,
                payment,
                is_with_header=True
            ),
            ""
        )

    def test_get_pn_action_buttons(self):
        buttons = get_pn_action_buttons(self.streamlined_test_pn_with_buttons.id)
        expected_buttons = [
            {
                "id": self.pn_action.id,
                "order": self.pn_action.order,
                "title": self.pn_action.title,
                "action": self.pn_action.action,
                "target": self.pn_action.target
            }
        ]
        assert buttons == expected_buttons

    def test_process_streamlined_comm_failed(self):
        filter_ = {
            "template_code": "unit_test_not_found"
        }
        streamlined_comm = process_streamlined_comm(filter_)
        assert streamlined_comm == ""

    def test_streamlined_comm_without_filter(self):
        available_context = {
            "firstname": "unit_test_name"
        }
        message = process_streamlined_comm_without_filter(
            self.streamlined_test_pn_with_param, available_context)
        assert message == "PN Hi unit_test_name"

    def test_process_streamlined_comm_with_model(self):
        application = ApplicationFactory(ktp='123123')
        message = StreamlinedMessage.objects.create(
            message_content="ktp anda {{ktp}}",
            parameter="{ktp}")
        self.streamlined_test_pn_with_param.message = message
        self.streamlined_test_pn_with_param.save()
        message = process_streamlined_comm_context_base_on_model(
            self.streamlined_test_pn_with_param, application)
        assert message == "ktp anda 123123"

    def test_process_streamlined_comm_context_base_on_model_param(self):
        application = ApplicationFactory(ktp='123123')
        message = StreamlinedMessage.objects.create(
            message_content="ktp anda {{ktp}}",
            parameter=("ktp", ))
        self.streamlined_test_pn_with_param.message = message
        self.streamlined_test_pn_with_param.save()
        message = process_streamlined_comm_context_base_on_model_and_parameter(
            self.streamlined_test_pn_with_param, application)
        assert message == "ktp anda 123123"

    def test_is_already_have_transaction(self):
        user_auth = AuthUserFactory()
        customer = CustomerFactory(user=user_auth)
        account = AccountFactory(customer=customer)
        assert is_already_have_transaction(customer) is False
        AccountPaymentFactory(account=account)
        assert is_already_have_transaction(customer) is True

    def test_process_streamlined_comm_context_for_ptp(self):
        customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='Testing')
        application = ApplicationFactory(customer=customer, workflow=self.workflow)
        status_190 = StatusLookup.objects.get(status_code=190)
        account = AccountFactory(customer=application.customer)
        account_payment = AccountPaymentFactory(account=account)

        application.application_status = status_190
        application.workflow.name = 'JuloOneWorkflow'
        application.account = account
        application.save()

        payment_method = PaymentMethodFactory(
            customer=customer, is_primary=True, loan=None)
        context = process_streamlined_comm_context_for_ptp(account_payment,
                                                 application,
                                                 True)
        self.assertIsNotNone(context['firstname'])

    def test_process_partner_sms_message(self):
        customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='Testing')
        application = ApplicationFactory(customer=customer, workflow=self.workflow)
        status_105 = StatusLookup.objects.get(status_code=105)
        account = AccountFactory(customer=application.customer)

        application.application_status = status_105
        application.workflow.name = 'JuloOneWorkflow'
        application.account = account
        application.save()

        partner_sms_template_content = 'Halo {{sms_fullname}}, yuk, selesaikan proses pendaftaran melalui link ini'
        message = process_partner_sms_message(partner_sms_template_content, application)
        self.assertIn(customer.fullname.title(), message)

    def test_process_partner_sms_message_for_status_100(self):
        customer = CustomerFactory()
        self.workflow = WorkflowFactory(name='Testing')
        application = ApplicationFactory(customer=customer, workflow=self.workflow)
        status_100 = StatusLookup.objects.get(status_code=100)
        workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )

        application.application_status = status_100
        application.workflow = workflow
        application.save()

        partner_sms_template_content = 'Halo {{sms_firstname}}, yuk, selesaikan proses pendaftaran melalui link ini'
        message = process_partner_sms_message(partner_sms_template_content, application)
        self.assertIn(customer.first_name_only, message)


@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestListStreamlined(TestCase):
    def setUp(self):
        group = Group(name="product_manager")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.client.force_login(self.user)
        message_email = StreamlinedMessage.objects.create(message_content="<html><body>Test Email</body></html>")
        message_sms = StreamlinedMessage.objects.create(message_content="Test SMS")
        self.message_robocall = StreamlinedMessage.objects.create(message_content="Test robocall")
        message_wa = StreamlinedMessage.objects.create(message_content="Test WA")
        message_pn = StreamlinedMessage.objects.create(message_content="Test PN")
        today = timezone.localtime(timezone.now())
        self.time_sent_hour = today.hour + 1
        if self.time_sent_hour == 24:
            self.time_sent_hour = 0
        if today.hour == 0:
            self.time_passed_sent_hour = 23
        else:
            self.time_passed_sent_hour = today.hour - 1
        # test same template_code different criteria
        streamlined_test_email = StreamlinedCommunication.objects.create(
            status_code_id=110,
            communication_platform=CommunicationPlatform.EMAIL,
            message=message_email,
            template_code='email_110')
        # test only template_code without status_code
        streamlined_test_sms = StreamlinedCommunication.objects.create(
            communication_platform=CommunicationPlatform.SMS,
            template_code='sms_reminder',
            message=message_sms,
        )
        # test only status without template_code
        streamlined_test_wa = StreamlinedCommunication.objects.create(
            communication_platform=CommunicationPlatform.WA,
            status_code_id=110,
            message=message_wa,
        )
        streamlined_test_email_reminder = StreamlinedCommunication.objects.create(
            dpd=-1,
            communication_platform=CommunicationPlatform.EMAIL,
            message=message_email,
            is_active=True,
            product='mtl',
            type='Payment Reminder',
            is_automated=True,
            time_sent='{}:30'.format(str(self.time_sent_hour)),
            subject='Test Subject',
            template_code='email_reminder-1')
        streamlined_test_email_reminder_passed = StreamlinedCommunication.objects.create(
            dpd=-2,
            communication_platform=CommunicationPlatform.EMAIL,
            message=message_email,
            is_active=True,
            product='mtl',
            type='Payment Reminder',
            is_automated=True,
            time_sent='{}:30'.format(str(self.time_passed_sent_hour)),
            subject='Test Subject',
            template_code='email_reminder-2')
        streamlined_test_email_ptp_reminder = StreamlinedCommunication.objects.create(
            ptp=-1,
            communication_platform=CommunicationPlatform.EMAIL,
            message=message_email,
            is_active=True,
            product='mtl',
            type='Payment Reminder',
            is_automated=True,
            time_sent='{}:30'.format(str(self.time_sent_hour)),
            subject='Test Subject',
            template_code='email_reminder_ptp-1')
        StreamlinedCommunication.objects.create(
            dpd=-1,
            communication_platform=CommunicationPlatform.PN,
            message=message_pn,
            is_active=True,
            product='mtl',
            type='Payment Reminder',
            is_automated=True,
            time_sent='{}:30'.format(str(self.time_sent_hour)),
            subject='Test Subject',
            template_code='pn_reminder-1'
        )
        StreamlinedCommunication.objects.create(
            dpd=-1,
            communication_platform=CommunicationPlatform.SMS,
            message=message_sms,
            is_active=True,
            product='mtl',
            type='Payment Reminder',
            is_automated=True,
            time_sent='{}:30'.format(str(self.time_sent_hour)),
            subject='Test Subject',
            template_code='sms_reminder-1'
        )
        sms_refinancing = StreamlinedCommunication.objects.create(
            dpd=-2,
            communication_platform=CommunicationPlatform.SMS,
            message=message_sms,
            is_active=True,
            product='mtl',
            type='Payment Reminder',
            is_automated=True,
            time_sent='{}:30'.format(str(self.time_sent_hour)),
            subject='Test Subject',
            template_code='sms_mtl_ref_pending_dpd_2'
        )
        self.sms_refinancing = sms_refinancing
        self.streamlined_email = streamlined_test_email
        self.streamlined_test_email_reminder = streamlined_test_email_reminder
        self.streamlined_sms = streamlined_test_sms
        streamlined_parameterlist = StreamlinedCommunicationParameterList.objects.create(
            parameter_name='test',
            platform='SMS',
            example='test_example',
            description='test_description'
        )
        self.streamlined_parameterlist = streamlined_parameterlist
        streamlined_function_list = StreamlinedCommunicationFunctionList.objects.create(
            function_name='test_function',
            description='function description',
            communication_platform=CommunicationPlatform.EMAIL
        )
        self.streamlined_function_list = streamlined_function_list
        self.streamlined_wa = streamlined_test_wa
        self.streamlined_test_email_ptp_reminder = streamlined_test_email_ptp_reminder
        self.streamlined_test_email_reminder_passed = streamlined_test_email_reminder_passed
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.application.product_line_id = 10
        self.application.save()
        self.payment.due_date = datetime.now() + timedelta(days=5)
        self.payment.save()
        self.test_robocall_content = '[{"action": "talk", "voiceName": "Damayanti", ' \
                                     '"text": "Selamat {{greet}} {{ name_with_title }}, \
                                     pelunasan JULO Anda{{ due_amount }} rupiah akan jatuh tempo dalam' \
                                     ' {{ days_before_due_date }} hari."},{"action": "input", ' \
                                     '"maxDigits": 1,"eventUrl": ["{{input_webhook_url}}"]}]'
        self.test_robocall_data = {
            'is_account_payment': 'false',
            'payment': 4000000302,
            'phone': 6281976547614,
            'test_content': self.test_robocall_content
        }

    def test_access_streamlined_view(self):
        # access base on dpd
        response = self.client.get('/streamlined_communication/list/', {"dpd": -1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # access base on application status
        response = self.client.get('/streamlined_communication/list/', {"application_status": 105})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # access by ptp
        response = self.client.get('/streamlined_communication/list/', {"ptp": -1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get('/streamlined_communication/list/', {"status_dpd": -1, "until_paid": 5})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.get(
            '/streamlined_communication/list/',
            {"status_dpd_upper": 5, "status_dpd_lower": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.get(
            '/streamlined_communication/list/',
            {"until_paid": 5, "status_dpd_lower": 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        CallRecordUrl.objects.create(
            recording_uuid="unit_test_record_1"
        )
        response = self.client.get(
            '/streamlined_communication/download_call_record/',
            {"record_uuid": "unit_test_record_1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.get(
            '/streamlined_communication/download_call_record/',
            {"record_uuid": "unit_test_record_2"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_streamlined_post_view(self):
        data_for_save = [
            {
                'active_tab': 'email',
                'update_msg_id_automated_email': str(self.streamlined_email.id)
            },
            {
                'active_tab': 'sms',
                'update_msg_id_active_sms': str(self.streamlined_sms.id)
            },
            {
                'active_tab': 'sms',
                'delete_msg_id_sms': str(self.streamlined_sms.id)
            },
            {
                'active_tab': 'parameterlist',
                'update_msg_id_active_parameterlist': str(self.streamlined_parameterlist.id)
            },
            {
                'active_tab': 'parameterlist',
                'delete_msg_id_parameterlist': str(self.streamlined_parameterlist.id)
            },
            {
                'active_tab': 'functionlist',
                'updated_message_id_functionlist': str(self.streamlined_function_list.id),
                'function-{}'.format(str(self.streamlined_function_list.id)):
                    'update function',
                'description-function-{}'.format(str(self.streamlined_function_list.id)):
                    'update description',
                'platform-function-{}'.format(str(self.streamlined_function_list.id)):
                    CommunicationPlatform.EMAIL,
            },
            {
                'active_tab': 'functionlist',
                'deleted_message_id_functionlist': str(self.streamlined_function_list.id)
            },
            {
                'active_tab': 'functionlist',
                'new_message_id_functionlist': '99',
                'function-99': 'test add function name',
                'description-function-99': 'test add description function',
                'platform-function-99': CommunicationPlatform.EMAIL,
            },
            {
                'active_tab': 'WA',
                'new_message_id_WA': '98',
                'message-98': 'new WA message',
                'description-98': 'new WA description',
                'status-98': 'new WA status',
                'dpd': -2,
            },
            {
                'active_tab': 'WA',
                'updated_message_id_WA': str(self.streamlined_wa.id),
                'message-{}'.format(str(self.streamlined_wa.id)): 'update message',
                'description-{}'.format(str(self.streamlined_wa.id)): 'update description',
                'status-{}'.format(str(self.streamlined_wa.id)): 'update status',
            },
            {
                'active_tab': 'WA',
                'deleted_message_id_WA': str(self.streamlined_wa.id),
            },
        ]
        for data_for_send in data_for_save:
            response = self.client.post('/streamlined_communication/list/', data_for_send)
            self.assertEqual(response.status_code, status.HTTP_302_FOUND)

    def test_update_detail_email(self):
        data = {
            'email_category': 'normal',
            'email_type': 'Payment Reminder',
            'email_product': 'mtl',
            'email_hour': str(self.time_sent_hour),
            'email_minute': '30',
            'email_subject': 'test subject',
            'email_template_code': 'email_reminder-1',
            'email_content': '<html><head></head><body>bla bla</body></html>',
            'email_description': 'description',
            'email_msg_id': self.streamlined_test_email_reminder.id,
            'dpd': -1,
            'ptp': '',
            'application_status': '',
            'email_parameters': 'test_parameter',
            'pre_header': 'test pre_header',
            'partners_selection': "",
            'partners_selection_action': None
        }
        response = self.client.post('/streamlined_communication/update_email_details', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['status'], 'Success')
        data = {
            'email_category': 'normal',
            'email_type': 'Payment Reminder',
            'email_product': 'mtl',
            'email_hour': str(self.time_sent_hour),
            'email_minute': '30',
            'email_subject': 'test subject',
            'email_template_code': 'email_reminder_ptp-1',
            'email_content': '<html><head></head><body>bla bla</body></html>',
            'email_description': 'description',
            'email_msg_id': self.streamlined_test_email_ptp_reminder.id,
            'dpd': '',
            'ptp': -1,
            'application_status': '',
            'email_parameters': 'test_parameter',
            'pre_header': 'test pre_header'
        }
        response = self.client.post('/streamlined_communication/update_email_details', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['status'], 'Success')

    def test_update_sms_details(self):
        data = {
            'sms_type': 'Payment Reminder',
            'sms_product': 'mtl',
            'sms_hour': str(self.time_sent_hour),
            'sms_minute': '30',
            'sms_template_code': 'email_reminder-1',
            'sms_content': 'change unit test message',
            'sms_description': 'description change',
            'sms_parameters': '',
            'sms_msg_id': self.streamlined_sms.id,
            'dpd': -1,
            'ptp': 1,
            'dpd_from': '',
            'dpd_until': '',
            'application_status': 110,
        }
        response = self.client.post('/streamlined_communication/update_sms_details', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['status'], 'Success')
        data = {
            'sms_type': 'Payment Reminder',
            'sms_product': 'mtl',
            'sms_hour': str(self.time_sent_hour),
            'sms_minute': '30',
            'sms_template_code': 'email_reminder-2',
            'sms_content': 'change unit test message',
            'sms_description': 'description change',
            'sms_parameters': '',
            'sms_msg_id': '',
            'dpd': -2,
            'ptp': 2,
            'dpd_from': '',
            'dpd_until': '',
            'application_status': 115,
        }
        response = self.client.post('/streamlined_communication/update_sms_details', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['status'], 'Success')

    @skip(reason="Flaky")
    def test_send_automated(self):
        from juloserver.julo.tasks import send_automated_comms
        send_automated_comms.delay()

    def test_send_automated_comm_sms(self):
        send_automated_comm_sms.delay(self.sms_refinancing.id)

    def test_update_robocall_details_view(self):
        robocall = StreamlinedCommunication.objects.create(
            dpd=-2,
            communication_platform=CommunicationPlatform.ROBOCALL,
            message=self.message_robocall,
            is_active=True,
            product='mtl',
            type='Payment Reminder',
            is_automated=True,
            time_sent='{}:30'.format(str(self.time_sent_hour)),
            subject='Test Subject',
            template_code='sms_mtl_ref_pending_dpd_2',
            criteria={'segment': 'bull'},
            julo_gold_status='execute',
        )
        data = {
            'robocall_msg_id': robocall.id,
            'robocall_type': 'Payment Reminder',
            'robocall_product': 'nexmo_mtl',
            'robocall_attempts': 3,
            'robocall_time_out_duration': 30,
            'robocall_template_code': 'nexmo_robocall_mtl_-3',
            'robocall_content': '',
            'robocall_description': 'this Robocall is send on  dpd=-3 for mtl',
            'robocall_call_time': '8:0,10:0,12:0',
            'robocall_call_function': 'send_voice_payment_reminder',
            'robocall_parameters': 'name_with_title',
            'robocall_exclude_risky': 'true',
            'dpd': -3,
            'ptp': '',
            'application_status': '',
            'robocall_segment': 'bull',
            'robocall_julo_gold_status': 'execute',
        }
        response = self.client.post('/streamlined_communication/update_robocall_details', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_parameterlist_details(self):
        data = {
            'parameterlist_parameter': 'test',
            'parameterlist_platform': 'SMS',
            'parameterlist_example': 'test_example',
            'parameterlist_description': 'test_description',
            'parameterlist_msg_id': self.streamlined_parameterlist.id,
        }

        response = self.client.post('/streamlined_communication/update_parameterlist_details', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['status'], 'Success')

    def test_update_parameterlist_details_1(self):
        data = {
            'parameterlist_parameter': 'test',
            'parameterlist_platform': 'SMS',
            'parameterlist_example': 'test_example',
            'parameterlist_description': 'test_description',
            'parameterlist_msg_id': '',
        }

        response = self.client.post('/streamlined_communication/update_parameterlist_details', data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['data']['status'], 'Success')

    def test_process_convert_params_to_data(self):
        identifier = 4000000302
        input_webhook_url = ''.join([settings.BASE_URL,
                                     '/api/integration/v1/callbacks/voice-call/',
                                     VoiceTypeStatus.PAYMENT_REMINDER,
                                     '/',
                                     str(identifier)
                                     ])
        context = {
            'name_with_title': 'test name',
            'due_amount': 500000,
            'input_webhook_url': input_webhook_url,
            'greet': 'pagi',
            'days_before_due_date': 5
        }
        result = process_convert_params_to_data(self.test_robocall_content, context)
        self.assertIsNotNone(result)

    def test_nexmo_robocall_test_with_no_payment(self):
        response = self.client.post('/streamlined_communication/nexmo_robocall_test',
                                    self.test_robocall_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_nexmo_from_phone_number_without_default(self):
        result = get_nexmo_from_phone_number()
        self.assertIsNotNone(result)

    @skip('UT is deprecated. Should be deleted when '
          'juloserver.julo.services.get_nexmo_from_phone_number is obsolete.')
    def test_get_nexmo_from_phone_number_with_default(self):
        robocall = RobocallCallingNumberChanger.objects.create(
            name='default_number', default_number=settings.NEXMO_PHONE_NUMBER
        )
        result = get_nexmo_from_phone_number()
        self.assertIsNotNone(result)

    @skip('UT is deprecated. Should be deleted when '
          'juloserver.julo.services.get_nexmo_from_phone_number is obsolete.')
    def test_get_nexmo_from_phone_number_with_start_and_end_date(self):
        start_date = datetime.now() - timedelta(days=1)
        end_date = datetime.now() + timedelta(days=1)
        default_number = '6285574671770'
        test_to_call_number = '123456789012'
        robocall = RobocallCallingNumberChanger.objects.create(
            default_number=default_number,
            test_to_call_number=test_to_call_number,
            start_date=start_date,
            end_date=end_date
        )
        result = get_nexmo_from_phone_number()
        self.assertIsNotNone(result)

    @mock.patch('juloserver.julo.services2.voice.get_voice_template')
    def test_nexmo_robocall_test_template(self, mocked_template):
        self.robocall_calling_number_changer = RobocallCallingNumberChangerFactory
        mocked_template.return_value = "[{'action': 'record', 'eventUrl': " \
                                       "['https://api-dev.julofinance.com/api/integration/" \
                                       "v1/callbacks/voice-call-recording-callback']}, {u'action': u'talk'," \
                                       " u'text': u'Selamat siangIbu Deassy, angsuran JULO Anda 1620000 rupiah " \
                                       "akan jatuh tempodalam 5 hari.', u'voiceName': u'Damayanti'}, {u'action': " \
                                       "u'talk', u'text': u'Bayar sekarang dan dapatkan kesbek sebesar 1 kali.', " \
                                       "u'voiceName': u'Damayanti'}, {u'action': u'talk', u'text': u'Tekan 1 untuk " \
                                       "konfirmasi. Terima kasih', u'voiceName': u'Damayanti'}, {u'action': u'input', " \
                                       "u'maxDigits': 1, u'eventUrl': [u'https://api-dev.julofinance.com/api/" \
                                       "integration/v1/callbacks/voice-call/payment_reminder/4000001468'], " \
                                       "'timeOut': 3}]"
        voice_client = JuloVoiceClientV2(1, 2, 2, 3, 'ppp', 5, 6)
        voice_client.create_call = mock.Mock(return_value={
            "dtmf": None,
            "conversation_uuid": "5efe6463-e994-4b3d-b4bf-33a4f62a4472",
            "uuid": "f3624a46-ae73-4b18-82f3-5a2a6910d899",
            "status": "started",
            "direction": "outbound"
        })
        streamlined_id = None
        template_code = 'nexmo_robocall_test'
        response = voice_client.payment_reminder('1234567890', self.payment.id,
                                                 streamlined_id, template_code,
                                                 self.test_robocall_content)
        self.assertIsNotNone(response)

    @mock.patch('juloserver.streamlined_communication.views.get_voice_client_v2')
    def test_nexmo_robocall_test_ajax(self, mocked_client):
        data = {
            'is_account_payment': 'false',
            'payment': self.payment.id,
            'phone': 6281976547614,
            'test_content': self.test_robocall_content
        }
        response = self.client.post('/streamlined_communication/nexmo_robocall_test',
                                    data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.streamlined_communication.views.get_voice_client_v2')
    def test_nexmo_robocall_test_ajax_account_payment(self, mock_get_voice_client_v2):
        account_payment = AccountPaymentFactory()
        data = {
            'is_account_payment': 'true',
            'payment': account_payment.id,
            'test_content': '',
            'phone': '0987654321'
        }
        response = self.client.post('/streamlined_communication/nexmo_robocall_test', data)
        self.assertEqual(response.status_code, 200)
        mock_get_voice_client_v2().account_payment_reminder.assert_called_once()
        vendor_data = VendorDataHistory.objects.filter(account_payment=account_payment).first()
        self.assertIsNotNone(vendor_data)

    def test_get_voice_template_without_template_name(self):
        identifier = self.payment.id
        streamlined_id = None
        test_robocall_content = None
        result = get_voice_template(
            VoiceTypeStatus.PAYMENT_REMINDER, identifier,
            streamlined_id, test_robocall_content)
        self.assertIsNotNone(result)

    def test_get_voice_template_with_template_name_none(self):
        self.payment.due_date = datetime.now()
        self.payment.save()
        identifier = self.payment.id
        streamlined_id = None
        test_robocall_content = None
        result = get_voice_template(
            VoiceTypeStatus.PAYMENT_REMINDER, identifier,
            streamlined_id, test_robocall_content)
        self.assertIsNone(result)


class TestModelsButtonInfo(TestCase):
    def setUp(self):
        self.info_card = InfoCardPropertyFactory()
        self.button = ButtonInfoCardFactory()
        self.image = ImageFactory()

    def test_card_background_image(self):
        self.image.image_source = self.info_card.id
        self.image.image_type = CardProperty.IMAGE_TYPE.card_background_image
        self.image.save()
        images = self.info_card.card_background_image
        self.assertIsNotNone(images)

    def test_card_background_image_url(self):
        self.image.image_source = self.info_card.id
        self.image.image_type = CardProperty.IMAGE_TYPE.card_background_image
        self.image.url = 'www.google.com'
        self.image.save()
        return_value = self.info_card.card_background_image_url
        self.assertEqual(return_value, 'https://{}.oss-ap-southeast-5.aliyuncs.com/www.google.com'.format(
            settings.OSS_PUBLIC_ASSETS_BUCKET))


class TestServiceForInfoCard(TestCase):
    def setUp(self):
        self.info_card = InfoCardPropertyFactory()
        self.button = ButtonInfoCardFactory(info_card_property=self.info_card)
        self.image_button = ImageFactory(
            image_source=self.button.id,
            image_type=CardProperty.IMAGE_TYPE.button_background_image)
        self.image_background = ImageFactory(
            image_source=self.info_card.id,
            image_type=CardProperty.IMAGE_TYPE.card_background_image)

    def test_format_info_card_data(self):
        streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        StreamlinedCommunicationFactory(
            message=streamlined_message,
            communication_platform=CommunicationPlatform.INFO_CARD
        )
        qs = StreamlinedCommunication.objects.filter(
            communication_platform=CommunicationPlatform.INFO_CARD
        )
        assert len(format_info_card_data(qs)) > 0

    def test_format_info_card_for_android(self):
        available_context = {}
        streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        streamlined_comm = StreamlinedCommunicationFactory(
            message=streamlined_message
        )
        assert type(format_info_card_for_android(streamlined_comm, available_context)) == dict
        result = format_info_card_for_android(streamlined_comm, available_context)
        self.assertEquals(streamlined_comm.id, result["streamlined_communication_id"])

    def test_format_info_card_for_android_for_type_youtube_video(self):
        available_context = {}
        self.info_card.youtube_video_id = 'nWkUpYeRTMQ'
        streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        streamlined_comm = StreamlinedCommunicationFactory(
            message=streamlined_message
        )
        assert type(format_info_card_for_android(streamlined_comm, available_context)) == dict
        result = format_info_card_for_android(streamlined_comm, available_context)
        self.assertEquals(self.info_card.youtube_video_id, result["youtube_video_id"])

    @mock.patch('juloserver.streamlined_communication.services.os.path.splitext')
    @mock.patch('juloserver.streamlined_communication.services.functions.upload_handle_media')
    @mock.patch('juloserver.streamlined_communication.services.upload_file_to_oss')
    def test_upload_image_for_info_card(self, mocked_functions, mocked_upload, mocked_os):
        mocked_os.return_value = ('image_name', '.png')
        mocked_functions.return_value = dict(file_name='image_name.png')
        mocked_upload.return_value = dict(file_name='image_name.png')

        class ImageFile(object):
            name = 'image_file_name_unit_test.png'

        image_file = ImageFile()
        assert create_and_upload_image_assets_for_streamlined(
            self.info_card.id, image_type=CardProperty.IMAGE_TYPE.button_background_image,
            image_file=image_file,
        )
        assert create_and_upload_image_assets_for_streamlined(
            self.info_card.id, image_type=CardProperty.IMAGE_TYPE.button_background_image,
            image_file=image_file, is_update=True
        )
        assert create_and_upload_image_assets_for_streamlined(
            self.info_card.id, image_type="unit_test_new_image",
            image_file=image_file, is_update=True
        )


    def test_new_models_property(self):
        assert self.info_card.card_background_image is not None
        assert self.info_card.card_background_image_url
        ImageFactory(
            image_source=self.info_card.id,
            image_type=CardProperty.IMAGE_TYPE.card_optional_image)
        assert self.info_card.card_optional_image_url
        assert len(self.info_card.button_list) > 0
        assert self.button.background_image is not None
        assert self.button.background_image_url is not None


    def test_is_info_card_expired(self):
        streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content",
            info_card_property=self.info_card
        )
        streamlined_comm = StreamlinedCommunicationFactory(
            message=streamlined_message,
            status_code_id=105,
            expiration_option ="Triggered by - Customer Entered Status & Condition",
            expiry_period=2,
            expiry_period_unit="days"
        )

        datetime_now = timezone.localtime(timezone.now())
        customer = CustomerFactory()
        application = ApplicationFactory(customer=customer)
        application.application_status = StatusLookup.objects.get(status_code=105)
        application_history = ApplicationHistoryFactory(
            application_id=application.id,
            status_old=100, status_new=105
        )

        application_history.cdate = datetime_now
        application_history.save()
        assert is_info_card_expired(streamlined_comm, application) is False

        application_history.cdate = datetime_now - timedelta(days=3)
        application_history.save()
        assert is_info_card_expired(streamlined_comm, application) is True

        status_220 = StatusLookup.objects.get(status_code=220)
        loan = LoanFactory(application=application,
                           cdate=datetime_now,
                           loan_status=status_220)
        loan_history = LoanHistoryFactory(
            loan=loan,
            status_old=0,
            status_new=220
        )
        streamlined_comm.status_code_id = 220
        streamlined_comm.save()

        application.application_status = StatusLookup.objects.get(status_code=190)
        application.save()
        assert is_info_card_expired(streamlined_comm, application, loan) is False

        loan_history.cdate = datetime_now - timedelta(days=4)
        loan_history.save()
        assert is_info_card_expired(streamlined_comm, application, loan) is True


class TestCheckingRatingShown(TestCase):
    def setUp(self):
        self.account = AccountFactory(status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active))
        self.application = ApplicationFactory(account=self.account,)
        self.patch_cache()

    def tearDown(self):
        self.redis_patcher.stop()

    @classmethod
    def setUpTestData(cls):
        cls.status_paid = StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        cls.status_not_paid = StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_1DPD)
        cls.status_sell_off = StatusLookupFactory(status_code=PaymentStatusCodes.SELL_OFF)

    def patch_cache(self):
        self.redis_patcher = patch(f'{PACKAGE_NAME}.RedisCache')
        self.mock_redis_cache_class = self.redis_patcher.start()
        self.mock_redis_cache = MagicMock()
        self.mock_redis_cache.get.return_value = None
        self.mock_redis_cache_class.return_value = self.mock_redis_cache

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_ideal_success(self, mock_now):
        mock_now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        AccountPaymentFactory.create_batch(3, account=self.account, status_id=self.status_paid.pk)
        ret_val = checking_rating_shown(self.application)
        self.assertTrue(ret_val)
        self.mock_redis_cache.set.assert_called_once_with('2020-01-01')

    def test_true_for_sell_off_latest(self):
        AccountPaymentFactory.create_batch(1, account=self.account, status_id=self.status_paid.pk)
        AccountPaymentFactory.create_batch(2, account=self.account, status_id=self.status_sell_off.pk)
        ret_val = checking_rating_shown(self.application)
        self.assertTrue(ret_val)

    def test_true_if_account_in_grace(self):
        account = AccountFactory(status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active_in_grace))
        application = ApplicationFactory(account=account)
        AccountPaymentFactory.create_batch(3, account=account, status_id=self.status_paid.pk)
        ret_val = checking_rating_shown(application)
        # self.assertTrue(ret_val)
        self.assertFalse(ret_val)

    def test_false_not_paid(self):
        AccountPaymentFactory.create_batch(1, account=self.account, status_id=self.status_not_paid.pk)
        AccountPaymentFactory.create_batch(2, account=self.account, status_id=self.status_paid.pk)
        ret_val = checking_rating_shown(self.application)
        self.assertFalse(ret_val)
        self.mock_redis_cache.set.assert_not_called()

    def test_false_no_account_payments(self):
        ret_val = checking_rating_shown(self.application)
        self.assertFalse(ret_val)

    def test_false_no_account(self):
        self.application.account = None
        ret_val = checking_rating_shown(self.application)
        self.assertFalse(ret_val)

    def test_false_account_is_not_active(self):
        account = AccountFactory(status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.inactive))
        application = ApplicationFactory(account=account)
        ret_val = checking_rating_shown(application)
        self.assertFalse(ret_val)

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_true_from_cache_same_day(self, mock_now):
        mock_now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        AccountPaymentFactory.create_batch(3, account=self.account, status_id=self.status_paid.pk)
        self.mock_redis_cache.get.return_value = '2020-01-01'

        ret_val = checking_rating_shown(self.application)

        self.assertTrue(ret_val)
        self.mock_redis_cache_class.assert_called_once_with(
            f'streamlined_communication::checking_rating_shown::{self.application.customer_id}',
            days=30,
        )
        self.mock_redis_cache.set.assert_not_called()

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_false_from_cache_diff_day(self, mock_now):
        mock_now.return_value = datetime(2020, 1, 2, tzinfo=timezone.utc)
        AccountPaymentFactory.create_batch(3, account=self.account, status_id=self.status_paid.pk)
        self.mock_redis_cache.get.return_value = '2020-01-01'

        ret_val = checking_rating_shown(self.application)

        self.assertFalse(ret_val)
        self.mock_redis_cache.set.assert_not_called()

    def test_false_is_review_submitted(self):
        customer = CustomerFactory(is_review_submitted=True)
        self.mock_redis_cache.get.return_value = None
        self.application.update_safely(customer=customer)

        ret_val = checking_rating_shown(self.application)
        self.assertFalse(ret_val)
        self.mock_redis_cache.set.assert_not_called()

    @patch(f'{PACKAGE_NAME}.timezone.now')
    def test_false_from_cache_not_active(self, mock_now):
        mock_now.return_value = datetime(2020, 1, 1, tzinfo=timezone.utc)
        account = AccountFactory(status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.inactive))
        application = ApplicationFactory(account=account)
        AccountPaymentFactory.create_batch(3, account=account, status_id=self.status_paid.pk)
        self.mock_redis_cache.get.return_value = '2020-01-01'

        ret_val = checking_rating_shown(application)

        self.assertFalse(ret_val)
        self.mock_redis_cache.set.assert_not_called()

class TestAndroidCheckNotificationValidity(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.action_type = PageType.REFERRAL

    @mock.patch('juloserver.streamlined_communication.services.show_referral_code')
    def test_valid_action(self, mock_show_referral_code):
        mock_show_referral_code.return_value = True
        is_valid, response = validate_action(self.customer, self.action_type)
        self.assertTrue(is_valid)
        self.assertEqual(response, {"isValid": True})

        mock_show_referral_code.return_value = False
        is_valid, response = validate_action(self.customer, self.action_type)
        self.assertFalse(is_valid)
        self.assertEqual(response, {"isValid": False})


class TestValidateAction(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(
            customer=self.account.customer, account=self.account
        )

    @patch('juloserver.loan.services.loan_related.is_product_locked')
    def test_validate_with_julo_shop(self, mock_is_product_locked):
        customer = CustomerFactory()
        account = AccountFactory(status=StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.active),
            customer=customer
        )
        application = ApplicationJ1Factory(customer=customer, account=account)
        master_agreement = DocumentFactory()
        master_agreement.document_source = application.id
        master_agreement.document_type = 'master_agreement'
        master_agreement.save()

        mock_is_product_locked.return_value = False
        ret_val = validate_action(customer, PageType.JULO_SHOP)

        self.assertTrue(ret_val[0])
        self.assertTrue(ret_val[1]['isValid'])

    def test_validate_ovo_deeplink(self):
        customer = CustomerFactory()
        account = AccountFactory(status=StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.scam_victim),
            customer=customer
        )
        ApplicationJ1Factory(customer=customer, account=account)
        ret_val = validate_action(customer, PageType.OVO_TAGIHAN_PAGE)
        self.assertTrue(ret_val[0])
        self.assertFalse(ret_val[1]['isValid'])

        account.update_safely(status_id=420)
        ret_val = validate_action(customer, PageType.OVO_TAGIHAN_PAGE)
        self.assertTrue(ret_val[0])
        self.assertTrue(ret_val[1]['isValid'])

    def test_validate_cashback_deeplink(self):
        customer = CustomerFactory()
        account = AccountFactory(status=StatusLookupFactory(
            status_code=AccountConstant.STATUS_CODE.scam_victim),
            customer=customer
        )
        ApplicationJ1Factory(customer=customer, account=account)
        ret_val = validate_action(customer, PageType.CASHBACK)
        self.assertTrue(ret_val[0])
        self.assertFalse(ret_val[1]['isValid'])

        account.update_safely(status_id=420)
        ret_val = validate_action(customer, PageType.CASHBACK)
        self.assertTrue(ret_val[0])
        self.assertTrue(ret_val[1]['isValid'])

    @mock.patch('juloserver.cfs.services.core_services.get_customer_tier_info')
    def test_validate_ecommerce_deeplink(self, mock_get_customer_tier_info):
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER,
            is_active=False,
            parameters={'customer_ids': [self.customer.id]},
        )
        is_valid, response = validate_action(self.customer, PageType.E_COMMERCE)
        self.assertFalse(is_valid)
        self.assertEqual(response, {'isValid': False})

        cfs_tier = CfsTierFactory(id=1, name='Advanced', point=300, julo_card=True)
        cfs_tier.ecommerce = True
        mock_get_customer_tier_info.return_value = None, cfs_tier
        self.account.status = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account.save()
        self.account_property = AccountPropertyFactory(account=self.account)
        self.account_property.is_entry_level = True
        self.account_property.save()
        self.fs.is_active = True
        self.fs.save()
        # self.fs.refresh_from_db()
        is_valid, response = validate_action(self.customer, PageType.E_COMMERCE)
        self.assertTrue(is_valid)
        self.assertEqual(response, {'isValid': True})

    def test_validate_application_does_not_have_account(self):
        self.application.update_safely(account=None)
        is_valid, response = validate_action(self.customer, PageType.TURBO_SECOND_CHECK_J1_OFFER)
        self.assertTrue(is_valid)
        self.assertEqual(response, {'isValid': True})

    def test_validate_eligible_phone_number_deeplink(self):
        self.application.update_safely(account=None)
        is_valid, response = validate_action(self.customer, PageType.CHANGE_PHONE_NUMBER)
        self.assertTrue(is_valid)
        self.assertEqual(response, {'isValid': True})

    def test_validate_eligible_phone_number_deeplink_with_105_app(self):
        self.new_user_auth = AuthUserFactory()
        self.new_customer = CustomerFactory(user=self.new_user_auth)
        ApplicationJ1Factory(
            customer=self.new_customer, application_status=StatusLookupFactory(status_code=105)
        )
        is_valid, response = validate_action(self.new_customer, PageType.CHANGE_PHONE_NUMBER)
        self.assertTrue(is_valid)
        self.assertEqual(response, {'isValid': True})

    def test_validate_not_eligible_phone_number_deeplink_with_request_account_deletion(self):
        self.new_user_auth = AuthUserFactory()
        self.new_customer = CustomerFactory(user=self.new_user_auth)
        self.new_account = AccountFactory(customer=self.new_customer)
        ApplicationJ1Factory(
            customer=self.new_customer,
            account=self.new_account,
            application_status=StatusLookupFactory(status_code=185),
        )
        is_valid, response = validate_action(self.new_customer, PageType.CHANGE_PHONE_NUMBER)
        self.assertFalse(is_valid)
        self.assertEqual(response, {'isValid': False})

    def test_validate_not_eligible_phone_number_deeplink_with_account_sold_off(self):
        self.new_user_auth = AuthUserFactory()
        self.new_customer = CustomerFactory(user=self.new_user_auth)
        self.new_account = AccountFactory(
            customer=self.new_customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.sold_off),
        )
        ApplicationJ1Factory(customer=self.new_customer, account=self.new_account)
        is_valid, response = validate_action(self.new_customer, PageType.CHANGE_PHONE_NUMBER)
        self.assertFalse(is_valid)
        self.assertEqual(response, {'isValid': False})


class TestIsHoliday(TestCase):
    def setUp(self):
        self.holiday = HolidayFactory(holiday_date=datetime(2022, 4, 28))

    def test_is_holiday_today(self):
        with patch.object(is_holiday, '__defaults__', (datetime(2022, 4, 28),)):
            is_today_holiday = is_holiday()
            self.assertTrue(is_today_holiday)

            self.holiday.holiday_date = datetime(2022, 4, 29)
            self.holiday.save()
            is_today_holiday = is_holiday()
            self.assertFalse(is_today_holiday)

    def test_is_holiday_specific_date(self):
        with patch.object(is_holiday, '__defaults__', (datetime(2022, 4, 28),)):
            is_specified_date_holiday = is_holiday(date=datetime(2022, 4, 29))
            self.assertFalse(is_specified_date_holiday)

    def test_is_holiday_annual_date(self):
        self.holiday.is_annual = True
        self.holiday.save()
        with patch.object(is_holiday, '__defaults__', (datetime(2023, 4, 28),)):
            is_annual_holiday = is_holiday()
            self.assertTrue(is_annual_holiday)

            self.holiday.holiday_date = datetime(2022, 4, 29)
            self.holiday.save()
            is_annual_holiday = is_holiday()
            self.assertFalse(is_annual_holiday)



class TestPushNotificationService(TestCase):
    def setUp(self):
        self.pn_client_mock = MagicMock()
        self.device_repo_mock = MagicMock()

    def test_init(self):
        ret_val = get_push_notification_service()
        self.assertIsInstance(ret_val, PushNotificationService)

    def test_send_pn(self):
        streamlined_comm = StreamlinedCommunicationFactory(
            subject='test subject',
            message=StreamlinedMessageFactory(message_content='test content'),
            template_code='template-code-test',
        )
        extra_data = {"destination_page": 'test-page'}

        self.pn_client_mock.send_downstream_message.return_value = 'Success'
        self.device_repo_mock.get_active_fcm_id.return_value = 'testfcmid'

        pn_service = PushNotificationService(self.pn_client_mock, self.device_repo_mock)
        ret_val = pn_service.send_pn(streamlined_comm, 1234, extra_data)

        self.assertEqual('Success', ret_val)
        self.pn_client_mock.send_downstream_message.assert_called_once_with(
            registration_ids=['testfcmid'],
            data={'title': 'test subject', 'body': 'test content'},
            template_code='template-code-test',
            notification={'destination_page': 'test-page', 'customer_id': 1234},
        )
        self.device_repo_mock.get_active_fcm_id.assert_called_once_with(1234)

    def test_send_pn_no_fcm_id(self):
        streamlined_comm = StreamlinedCommunicationFactory(
            subject='test subject',
            message=StreamlinedMessageFactory(message_content='test content'),
            template_code='template-code-test',
        )

        self.pn_client_mock.send_downstream_message.return_value = 'Success'
        self.device_repo_mock.get_active_fcm_id.return_value = None

        pn_service = PushNotificationService(self.pn_client_mock, self.device_repo_mock)
        with self.assertRaises(StreamlinedCommunicationException) as ex_context:
            ret_val = pn_service.send_pn(streamlined_comm, 1234)

        self.assertEqual(
            "No FCM ID for the registered customer [1234].",
            str(ex_context.exception),
        )
        self.pn_client_mock.send_downstream_message.assert_not_called()


class TestUploadImageAssetsForStreamlinedPn(TestCase):

    def setUp(self):
        self.streamlined_message = StreamlinedMessageFactory(
            message_content="unit test content")
        self.streamlined_comm = StreamlinedCommunicationFactory(
            message=self.streamlined_message
        )

    @mock.patch('juloserver.streamlined_communication.services.os.path.splitext')
    @mock.patch('juloserver.streamlined_communication.services.functions.upload_handle_media')
    @mock.patch('juloserver.streamlined_communication.services.upload_file_to_oss')
    def test_upload_image_for_streamlined_pn(self, mocked_functions, mocked_upload, mocked_os):
        mocked_os.return_value = ('image_name', '.png')
        mocked_functions.return_value = dict(file_name='image_name.png')
        mocked_upload.return_value = dict(file_name='image_name.png')

        class ImageFile(object):
            name = 'image_file_name_unit_test.png'

        image_file = ImageFile()

        result = upload_image_assets_for_streamlined_pn(
            "streamlined-PN", self.streamlined_comm.id, ImageType.STREAMLINED_PN, "streamlined-PN/image",
            image_file
            )
        self.assertEqual(result, True)


class TestIsJuloCardTransactionCompletedAction(TestCase):
    def test_is_julo_card_transaction_completed_action_return_true(self):
        action = '{}/{}'.format(PageType.JULO_CARD_TRANSACTION_COMPLETED, 1234)
        self.assertTrue(is_julo_card_transaction_completed_action(action))

    def test_is_julo_card_transaction_completed_action_return_false_when_invalid_action(self):
        self.assertFalse(is_julo_card_transaction_completed_action('sadwdqw'))


class TestEligibleForDeepLink(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

    def test_invalid_application_status(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.NOT_YET_CREATED
        )
        self.application.save()

        is_eligible = is_eligible_for_deep_link(
            application=self.application, transaction_method=TransactionMethodCode.SELF
        )
        self.assertEquals(is_eligible, False)

    def test_invalid_account_status(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.account.status = StatusLookupFactory(status_code=JuloOneCodes.INACTIVE)
        self.account.save()

        is_eligible = is_eligible_for_deep_link(
            application=self.application, transaction_method=TransactionMethodCode.SELF
        )
        self.assertEquals(is_eligible, False)

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_lock_product(self, mock_is_product_locked):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.account.status = StatusLookupFactory(status_code=JuloOneCodes.INACTIVE)
        self.account.save()
        mock_is_product_locked.return_value = True

        is_eligible = is_eligible_for_deep_link(
            application=self.application, transaction_method=TransactionMethodCode.SELF
        )
        self.assertEquals(is_eligible, False)

    @patch('juloserver.loan.views.views_api_v3.is_product_locked')
    def test_valid_application_and_account_and_product_not_lock(self, mock_is_product_locked):
        self.fs = FeatureSettingFactory(
            feature_name=LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER,
            is_active=False,
            parameters={'customer_ids': []},
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()
        self.account.status = StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        self.account.save()
        mock_is_product_locked.return_value = False
        self.fs.is_active = True
        self.fs.save()
        is_eligible = is_eligible_for_deep_link(
            application=self.application, transaction_method=TransactionMethodCode.SELF
        )
        self.assertEquals(is_eligible, True)

    def test_whitelist_validate_deeplink(self):
        whitelist_setting = MobileFeatureSettingFactory(
            feature_name=MobileFeatureNameConst.TRANSACTION_METHOD_WHITELIST,
            is_active=True,
            parameters={},
        )
        transaction_method = TransactionMethodCode.EDUCATION

        # enable whitelist but empty application_ids
        whitelist_setting.parameters[transaction_method.name] = {"application_ids": []}
        is_eligible = is_eligible_for_deep_link(
            application=self.application, transaction_method=transaction_method
        )
        self.assertEquals(is_eligible, False)

        # enable whitelist and application_ids contains test application
        whitelist_setting.parameters[transaction_method.name]["application_ids"] = [
            self.application.id
        ]
        whitelist_setting.save()
        is_eligible = is_eligible_for_deep_link(
            application=self.application, transaction_method=transaction_method
        )
        self.assertEquals(is_eligible, True)


class TestIPABannerService(TestCase):
    def setUp(self):
        self.experiment_setting = ExperimentSettingFactory(
            code='FDCIPABannerExperiment',
            criteria=dict(
                customer_id=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
                target_version='>=8.9.0'
            ),
            is_active=True,
        )
        self.customer = CustomerFactory()

        self.fdc_inquiry = FDCInquiryFactory(
            customer_id=self.customer.id,
            inquiry_date=self.customer.cdate,
            inquiry_status='success',
        )

        self.fdc_inquiry_loan = FDCInquiryLoanFactory(
            fdc_inquiry_id=self.fdc_inquiry.id,
            no_identitas=self.customer.nik,
            tgl_pelaporan_data=self.customer.cdate,
            tgl_jatuh_tempo_pinjaman=self.customer.cdate - relativedelta(days=2),
        )

        self.app_version = '8.9.0'

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE,)
        self.onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_SHORTENED_ID)
        self.application = ApplicationFactory(
            customer=self.customer,
            onboarding=self.onboarding,
            workflow=self.workflow,
        )
        self.application.application_status_id=ApplicationStatusCodes.FORM_CREATED
        self.application.save()
    
    def test_determine_ipa_banner_experiment(self):
        # criteria is permanent
        self.experiment_setting.is_permanent = True
        self.experiment_setting.save()

        self.assertTrue(determine_ipa_banner_experiment(self.customer, self.app_version))

        # customer_id in criteria and date range
        today = timezone.localtime(timezone.now())
        self.experiment_setting.is_permanent = False
        self.experiment_setting.start_date = today - relativedelta(days=30)
        self.experiment_setting.end_date = today + relativedelta(days=30)
        self.experiment_setting.save()

        self.assertTrue(determine_ipa_banner_experiment(self.customer, self.app_version))

        # customer_id not included in criteria
        self.experiment_setting.criteria = {
            'customer_id': [],
            'target_version': '>=8.9.0',
        }
        self.experiment_setting.save()
        self.assertFalse(determine_ipa_banner_experiment(self.customer, self.app_version))

        # no target version on experiment_setting
        self.experiment_setting.criteria = {
            'customer_id':[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            'target_version': '',
        }
        self.experiment_setting.save()
        self.assertFalse(determine_ipa_banner_experiment(self.customer, self.app_version))

        # version is lower than target_version
        self.experiment_setting.criteria = {
            'customer_id':[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
            'target_version': '>=8.9.0',
        }
        self.experiment_setting.save()
        self.app_version = '8.8.0'
        self.assertFalse(determine_ipa_banner_experiment(self.customer, self.app_version))


    @patch('juloserver.streamlined_communication.services.determine_ipa_banner_experiment', return_value=True)
    def test_show_ipa_banner(self, mock_determine_experiment):
        # case approved
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Lancar (<30 hari)'
        self.fdc_inquiry_loan.save()

        fdc_binary, message = show_ipa_banner(self.customer, self.app_version)
        self.assertTrue(fdc_binary)

        self.fdc_inquiry_loan.kualitas_pinjaman = 'Tidak Lancar (30 sd 90 hari)'
        self.fdc_inquiry_loan.save()

        fdc_binary, message = show_ipa_banner(self.customer, self.app_version)
        self.assertTrue(fdc_binary)

        # case approve
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Macet (>90)'
        self.fdc_inquiry_loan.nilai_pendanaan = 10000
        self.fdc_inquiry_loan.sisa_pinjaman_berjalan = 0
        self.fdc_inquiry_loan.save()

        fdc_binary, message = show_ipa_banner(self.customer, self.app_version)
        self.assertTrue(fdc_binary)

        self.fdc_inquiry_loan.kualitas_pinjaman = 'Macet (>90)'
        self.fdc_inquiry_loan.nilai_pendanaan = 10000
        self.fdc_inquiry_loan.sisa_pinjaman_berjalan = 10000
        self.fdc_inquiry_loan.save()

        fdc_binary, message = show_ipa_banner(self.customer, self.app_version)
        self.assertFalse(fdc_binary)

        # case onboarding id is not 3
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Lancar (<30 hari)'
        self.fdc_inquiry_loan.save()

        self.application.onboarding = OnboardingFactory(id=OnboardingIdConst.LONGFORM_ID)
        self.application.save()

        fdc_binary, message = show_ipa_banner(self.customer, self.app_version)
        self.assertFalse(fdc_binary)

        # case empty onboarding id
        self.fdc_inquiry_loan.kualitas_pinjaman = 'Lancar (<30 hari)'
        self.fdc_inquiry_loan.save()

        self.application.onboarding = None
        self.application.save()

        fdc_binary, message = show_ipa_banner(self.customer, self.app_version)
        self.assertFalse(fdc_binary)

