from __future__ import absolute_import

from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.forms import model_to_dict
from factory import Iterator
from mock import patch

from django.utils import timezone
from django.test.testcases import (
    TestCase,
    override_settings,
)

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountwithApplicationFactory,
    AccountLookupFactory,
    WorkflowFactory,
    ExperimentGroupFactory,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.autodebet.models import AutodebetAccount
from juloserver.autodebet.tests.factories import (
    AutodebetAccountFactory
)
from juloserver.julo.models import (
    Application,
    ProductLine,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.voice import (
    is_last_account_payment_status_notpaid,
    mark_voice_account_payment_reminder,
    retry_send_voice_account_payment_reminder2,
    trigger_account_payment_reminder,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ProductLineFactory,
    ApplicationJ1Factory,
    CustomerFactory,
    PartnerFactory,
    ExperimentSettingFactory,
)
from juloserver.julocore.python2.utils import py2round
from juloserver.julo.services2.voice import (
    excluding_autodebet_account_payment_dpd_minus,
    retry_send_voice_account_payment_reminder1,
    send_voice_account_payment_reminder,
)

from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
)
from juloserver.streamlined_communication.constant import CommunicationPlatform, CardProperty
from juloserver.streamlined_communication.test.factories import StreamlinedCommunicationFactory
from juloserver.dana.tests.factories import DanaCustomerDataFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants

from juloserver.loan.constants import TimeZoneName
from juloserver.loan.services.robocall import get_start_time_and_end_time
from juloserver.julo.constants import AddressPostalCodeConst


@patch('juloserver.streamlined_communication.utils.check_payment_reminder_time_limit')
@patch('juloserver.julo.services2.voice.check_payment_reminder_time_limit')
class TestSendVoiceAccountPaymentReminder(TestCase):
    def setUp(self):
        self.streamlined_communication = StreamlinedCommunicationFactory(
            template_code='nexmo_robocall_j1_-3',
            attempts=3,
            call_hours='{11:0,12:1,13:0}',
            communication_platform=CommunicationPlatform.ROBOCALL,
            exclude_risky_customer=True,
            function_name="""
                                {send_voice_account_payment_reminder,retry_send_voice_account_payment_reminder1,
                                retry_send_voice_account_payment_reminder2}
                                """,
            dpd=-3,
            is_active=True,
            is_automated=True,
            time_out_duration=30,
            product='nexmo_j1',
            type='Payment Reminder',
            partner_selection_action='exclude',
            partner_selection_list=['4', '19', '20', '24', '10', '9', '21', '12',
                                    '17', '22', '23', '27', '45', '28', '25', '11',
                                    '26', '41', '42', '29', '30', '31', '32', '33',
                                    '34', '35', '36', '37', '38', '39', '40', '43',
                                    '44', '46', '1', '53', '56', '55', '58', '60',
                                    '61', '62', '63']
        )
        self.product_line_j1 = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.late_fee_experiment = ExperimentSettingFactory(
            is_active=False,
            code=MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            criteria={
                "url": "http://localhost:8000",
                "account_id_tail": {"control": [0, 1, 2, 3, 4], "experiment": [5, 6, 7, 8, 9]}
            },
        )

        for index in range(10):
            if index % 2 == 0:
                kodepos = 97114
            elif index % 3 == 0:
                kodepos = 77111
            else:
                kodepos = 23111

            account_lookup = AccountLookupFactory(workflow=self.workflow)
            account = AccountFactory(account_lookup=account_lookup)
            ApplicationFactory(
                account=account, product_line=self.product_line_j1, address_kodepos=kodepos)

            if index > 6:
                AutodebetAccountFactory(
                    is_use_autodebet=True, account=account)
            else:
                is_use_autodebet = False
                if index > 4:
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet, account=account)
                else:
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet,
                        is_deleted_autodebet=True,
                        account=account)
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet,
                        is_deleted_autodebet=False,
                        account=account)

            AccountPaymentFactory(
                account=account, is_robocall_active=True, due_date='2022-05-11'
            )
            ExperimentGroupFactory(account=account, group='experiment',
                                   experiment_setting=self.late_fee_experiment)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_send_voice_account_payment_reminder_exclude_autodebet_account(
        self, mock_trigger, *args
    ):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ):
            send_voice_account_payment_reminder(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)

            mock_trigger.assert_called()
            self.assertEqual(4, mock_trigger.call_count)

    @patch('juloserver.julo.services2.voice.excluding_autodebet_account_payment_dpd_minus')
    def test_send_voice_account_payment_reminder_bypass_dpd_positive(
        self, mock_exclude_autodebet, *args
    ):
        self.streamlined_communication.dpd = 2
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ):
            send_voice_account_payment_reminder(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            self.assertFalse(mock_exclude_autodebet.called)

    @patch('juloserver.julo.services2.reminders.Reminder.create_j1_reminder_history')
    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_trigger_account_payment_reminder_task(
            self, mock_julo_voice_client, mock_create_reminder_history, *args):
        account_payment = AccountPayment.objects.last()
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ):
            trigger_account_payment_reminder(account_payment.id, self.streamlined_communication.id)
            mock_julo_voice_client.return_value.account_payment_reminder.assert_called()
            self.assertTrue(mock_create_reminder_history.called)
            self.assertTrue(mock_julo_voice_client.called)
            self.assertEqual(1, mock_create_reminder_history.call_count)
            self.assertEqual(1, mock_julo_voice_client.return_value.account_payment_reminder.call_count)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder')
    def test_send_voice_account_payment_reminder_late_fee_experiment_inactive(
        self, mock_trigger, *args
    ):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ):
            self.streamlined_communication.extra_conditions = \
                CardProperty.LATE_FEE_EARLIER_EXPERIMENT
            self.streamlined_communication.save()
            send_voice_account_payment_reminder(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)

            self.assertEqual(0, mock_trigger.call_count)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_send_voice_account_payment_reminder_late_fee_experiment_active(
        self, mock_trigger, *args
    ):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ):
            self.streamlined_communication.extra_conditions = \
                CardProperty.LATE_FEE_EARLIER_EXPERIMENT
            self.streamlined_communication.save()
            self.late_fee_experiment.is_active = True
            self.late_fee_experiment.save()
            send_voice_account_payment_reminder(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)

            mock_trigger.assert_called()
            self.assertEqual(4, mock_trigger.call_count)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder')
    def test_send_voice_account_payment_reminder_late_fee_experiment_active_and_common_nexmo(
        self, mock_trigger, *args
    ):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ):
            self.streamlined_communication.extra_conditions = \
                CardProperty.LATE_FEE_EARLIER_EXPERIMENT
            self.streamlined_communication.save()
            self.late_fee_experiment.is_active = True
            self.late_fee_experiment.save()
            send_voice_account_payment_reminder(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)

            # since all data registred as experiment, and this is common nexmo
            # we will exclude the data
            self.assertEqual(0, mock_trigger.call_count)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_send_voice_account_payment_reminder_late_fee_experiment_active(
        self, mock_trigger, *args
    ):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ):
            self.streamlined_communication.extra_conditions = \
                CardProperty.LATE_FEE_EARLIER_EXPERIMENT
            self.streamlined_communication.save()
            self.late_fee_experiment.is_active = True
            self.late_fee_experiment.save()
            send_voice_account_payment_reminder(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)

            mock_trigger.assert_called()
            self.assertEqual(4, mock_trigger.call_count)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_send_voice_account_payment_reminder_after_6_pm_for_WIT(
        self, mock_trigger, *args
    ):
        self.streamlined_communication.call_hours = '{18:0, 19:0, 18:0}'
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 18, 30, 0)
        ):
            current_time = timezone.localtime(timezone.now())

            start_time, end_time = get_start_time_and_end_time(
                TimeZoneName.WIT, 18, current_time, 18
            )
            send_voice_account_payment_reminder(
                0, 18, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            mock_trigger.assert_called()
            self.assertEqual(mock_trigger._mock_call_args[1]['expires'], end_time)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_send_voice_account_payment_reminder_after_7_pm_for_WITA(
        self, mock_trigger, *args
    ):
        self.streamlined_communication.call_hours = '{18:0, 19:0, 18:0}'
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 19, 30, 0)
        ):
            current_time = timezone.localtime(timezone.now())
            start_time, end_time = get_start_time_and_end_time(
                TimeZoneName.WITA, 19, current_time, 19
            )
            send_voice_account_payment_reminder(
                1, 19, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            mock_trigger.assert_called()
            self.assertEqual(mock_trigger._mock_call_args[1]['expires'], end_time)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_send_voice_account_payment_reminder_after_8_pm_for_WIB(
        self, mock_trigger, *args
    ):
        self.streamlined_communication.call_hours = '{18:0, 19:0, 18:0}'
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 20, 30, 0)
        ):
            current_time = timezone.localtime(timezone.now())
            start_time, end_time = get_start_time_and_end_time(
                TimeZoneName.WIB, 20, current_time, 20
            )
            send_voice_account_payment_reminder(
                2, 20, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            mock_trigger.assert_called()
            self.assertEqual(mock_trigger._mock_call_args[1]['expires'], end_time)


@patch('juloserver.streamlined_communication.utils.check_payment_reminder_time_limit')
@patch('juloserver.julo.services2.voice.check_payment_reminder_time_limit')
class TestRetrySendVoiceAccountPaymentReminder1(TestCase):

    def setUp(self):
        self.streamlined_communication = StreamlinedCommunicationFactory(
            template_code='nexmo_robocall_j1_-3',
            attempts=3,
            call_hours='{11:0,12:1,13:0}',
            communication_platform=CommunicationPlatform.ROBOCALL,
            exclude_risky_customer=True,
            function_name="""
                                    {send_voice_account_payment_reminder,retry_send_voice_account_payment_reminder1,
                                    retry_send_voice_account_payment_reminder2}
                                    """,
            dpd=-3,
            is_active=True,
            is_automated=True,
            time_out_duration=30,
            product='nexmo_j1',
            type='Payment Reminder',
            partner_selection_action='exclude',
            partner_selection_list=['4', '19', '20', '24', '10', '9', '21', '12',
                                    '17', '22', '23', '27', '45', '28', '25', '11',
                                    '26', '41', '42', '29', '30', '31', '32', '33',
                                    '34', '35', '36', '37', '38', '39', '40', '43',
                                    '44', '46', '1', '53', '56', '55', '58', '60',
                                    '61', '62', '63']
        )
        self.product_line_j1 = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)

        for index in range(10):
            if index % 2 == 0:
                kodepos = 97114
            elif index % 3 == 0:
                kodepos = 77111
            else:
                kodepos = 23111

            account_lookup = AccountLookupFactory(workflow=self.workflow)
            account = AccountFactory(account_lookup=account_lookup)
            application = ApplicationFactory(
                account=account, product_line=self.product_line_j1, address_kodepos=kodepos)

            if index > 6:
                AutodebetAccountFactory(
                    is_use_autodebet=True, account=account)
            else:
                is_use_autodebet = False
                if index > 4:
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet, account=account)
                else:
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet,
                        is_deleted_autodebet=True,
                        account=account)
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet,
                        is_deleted_autodebet=False,
                        account=account)

            AccountPaymentFactory(
                account=account, is_robocall_active=True, due_date='2022-05-11'
            )

    @patch('juloserver.julo.services2.reminders.Reminder.create_j1_reminder_history')
    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_retry_send_voice_account_payment_reminder1_exclude_autodebet_account(
        self, mock_julo_voice_client, mock_create_reminder_history, *args
    ):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ) as mock_timezone:
            retry_send_voice_account_payment_reminder1(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            mock_julo_voice_client.return_value.account_payment_reminder.assert_called()
            self.assertTrue(mock_create_reminder_history.called)
            self.assertTrue(mock_julo_voice_client.called)
            self.assertEqual(4, mock_create_reminder_history.call_count)

    @patch('juloserver.julo.services2.voice.excluding_autodebet_account_payment_dpd_minus')
    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_retry_send_voice_account_payment_reminder1_bypass_dpd_positive(
        self, mock_julo_voice_client, mock_exclude_autodebet, *args
    ):
        self.streamlined_communication.dpd = 2
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ) as mock_timezone:
            retry_send_voice_account_payment_reminder1(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            self.assertFalse(mock_exclude_autodebet.called)

    @patch('juloserver.julo.services2.reminders.Reminder.create_j1_reminder_history')
    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_retry_send_voice_account_payment_reminder1_continue_after_error(
        self, mock_julo_voice_client, mock_create_reminder_history, *args
    ):
        mock_create_reminder_history.side_effect = [None, Exception(), None, None]
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ) as mock_timezone:
            retry_send_voice_account_payment_reminder1(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)

            mock_julo_voice_client.return_value.account_payment_reminder.assert_called()
            self.assertTrue(mock_create_reminder_history.called)
            self.assertTrue(mock_julo_voice_client.called)
            self.assertEqual(4, mock_create_reminder_history.call_count)
            self.assertEqual(3, mock_julo_voice_client.return_value.account_payment_reminder.call_count)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_retry_send_voice_account_payment_reminder1_after_6_pm_for_WIT(
        self, mock_trigger, *args
    ):
        self.streamlined_communication.call_hours = '{18:0, 19:0, 18:0}'
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 18, 30, 0)
        ):
            current_time = timezone.localtime(timezone.now())

            start_time, end_time = get_start_time_and_end_time(
                TimeZoneName.WIT, 18, current_time, 18
            )
            send_voice_account_payment_reminder(
                0, 18, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            mock_trigger.assert_called()
            self.assertEqual(mock_trigger._mock_call_args[1]['expires'], end_time)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_retry_send_voice_account_payment_reminder1_after_7_pm_for_WITA(
        self, mock_trigger, *args
    ):
        self.streamlined_communication.call_hours = '{18:0, 19:0, 18:0}'
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 19, 30, 0)
        ):
            current_time = timezone.localtime(timezone.now())
            start_time, end_time = get_start_time_and_end_time(
                TimeZoneName.WITA, 19, current_time, 19
            )
            send_voice_account_payment_reminder(
                1, 19, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            mock_trigger.assert_called()
            self.assertEqual(mock_trigger._mock_call_args[1]['expires'], end_time)

    @patch('juloserver.julo.services2.voice.trigger_account_payment_reminder.apply_async')
    def test_retry_send_voice_account_payment_reminder1_after_8_pm_for_WIB(
        self, mock_trigger, *args
    ):
        self.streamlined_communication.call_hours = '{18:0, 19:0, 18:0}'
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 20, 30, 0)
        ):
            current_time = timezone.localtime(timezone.now())
            start_time, end_time = get_start_time_and_end_time(
                TimeZoneName.WIB, 20, current_time, 20
            )
            send_voice_account_payment_reminder(
                2, 20, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            mock_trigger.assert_called()
            self.assertEqual(mock_trigger._mock_call_args[1]['expires'], end_time)


@patch('juloserver.streamlined_communication.utils.check_payment_reminder_time_limit')
@patch('juloserver.julo.services2.voice.check_payment_reminder_time_limit')
class TestRetrySendVoiceAccountPaymentReminder2(TestCase):

    def setUp(self):
        self.streamlined_communication = StreamlinedCommunicationFactory(
            template_code='nexmo_robocall_j1_-3',
            attempts=3,
            call_hours='{11:0,12:1,13:0}',
            communication_platform=CommunicationPlatform.ROBOCALL,
            exclude_risky_customer=True,
            function_name="""
                                {send_voice_account_payment_reminder,retry_send_voice_account_payment_reminder1,
                                retry_send_voice_account_payment_reminder2}
                                """,
            dpd=-3,
            is_active=True,
            is_automated=True,
            time_out_duration=30,
            product='nexmo_j1',
            type='Payment Reminder',
            partner_selection_action='exclude',
            partner_selection_list=['4', '19', '20', '24', '10', '9', '21', '12',
                                    '17', '22', '23', '27', '45', '28', '25', '11',
                                    '26', '41', '42', '29', '30', '31', '32', '33',
                                    '34', '35', '36', '37', '38', '39', '40', '43',
                                    '44', '46', '1', '53', '56', '55', '58', '60',
                                    '61', '62', '63']
        )
        self.product_line_j1 = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)

        for index in range(10):
            if index % 2 == 0:
                kodepos = 97114
            elif index % 3 == 0:
                kodepos = 77111
            else:
                kodepos = 23111

            account_lookup = AccountLookupFactory(workflow=self.workflow)
            account = AccountFactory(account_lookup=account_lookup)
            application = ApplicationFactory(
                account=account, product_line=self.product_line_j1, address_kodepos=kodepos)

            if index > 6:
                AutodebetAccountFactory(
                    is_use_autodebet=True, account=account)
            else:
                is_use_autodebet = False
                if index > 4:
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet, account=account)
                else:
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet,
                        is_deleted_autodebet=True,
                        account=account)
                    AutodebetAccountFactory(
                        is_use_autodebet=is_use_autodebet,
                        is_deleted_autodebet=False,
                        account=account)

            AccountPaymentFactory(
                account=account, is_robocall_active=True, due_date='2022-05-11'
            )

    @patch('juloserver.julo.services2.reminders.Reminder.create_j1_reminder_history')
    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_retry_send_voice_account_payment_reminder2_exclude_autodebet_account(
        self, mock_julo_voice_client, mock_create_reminder_history, *args
    ):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ) as mock_timezone:
            retry_send_voice_account_payment_reminder2(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            mock_julo_voice_client.return_value.account_payment_reminder.assert_called()
            self.assertTrue(mock_create_reminder_history.called)
            self.assertTrue(mock_julo_voice_client.called)
            self.assertEqual(4, mock_create_reminder_history.call_count)

    @patch('juloserver.julo.services2.voice.excluding_autodebet_account_payment_dpd_minus')
    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_retry_send_voice_account_payment_reminder2_bypass_dpd_positive(
        self, mock_julo_voice_client, mock_exclude_autodebet, *args
    ):
        self.streamlined_communication.dpd = 2
        self.streamlined_communication.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ) as mock_timezone:
            retry_send_voice_account_payment_reminder2(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)
            self.assertFalse(mock_exclude_autodebet.called)

    @patch('juloserver.julo.services2.reminders.Reminder.create_j1_reminder_history')
    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_retry_send_voice_account_payment_reminder2_continue_after_error(
        self, mock_julo_voice_client, mock_create_reminder_history, *args
    ):
        mock_create_reminder_history.side_effect = [None, Exception(), None, None]
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 5, 8, 12, 0, 0)
        ) as mock_timezone:
            retry_send_voice_account_payment_reminder2(
                0, 12, [self.product_line_j1.product_line_code], self.streamlined_communication.pk)

            mock_julo_voice_client.return_value.account_payment_reminder.assert_called()
            self.assertTrue(mock_create_reminder_history.called)
            self.assertTrue(mock_julo_voice_client.called)
            self.assertEqual(4, mock_create_reminder_history.call_count)
            self.assertEqual(3, mock_julo_voice_client.return_value.account_payment_reminder.call_count)


class TestExcludingAutodebetAccountPaymentDpdMinus(TestCase):

    def setUp(self):
        self.accounts = AccountFactory.create_batch(10)
        self.application = ApplicationJ1Factory.create_batch(10, account=Iterator(self.accounts))
        self.account_payments = AccountPaymentFactory.create_batch(10, account=Iterator(self.accounts))
        AutodebetAccountFactory.create_batch(2, is_use_autodebet=True, is_deleted_autodebet=False,
                                             account=Iterator(self.accounts[1:3]))
        AutodebetAccountFactory.create_batch(1, is_use_autodebet=True, is_deleted_autodebet=True,
                                             account=Iterator(self.accounts[3:4]))
        AutodebetAccountFactory.create_batch(3, is_use_autodebet=False, is_deleted_autodebet=False,
                                             account=Iterator(self.accounts[4:7]))
        AutodebetAccountFactory.create_batch(3, is_use_autodebet=False, is_deleted_autodebet=True,
                                             account=Iterator(self.accounts[7:]))

        # Create disabled history for account #2
        AutodebetAccountFactory(is_use_autodebet=False, is_deleted_autodebet=True,
                                account=self.accounts[1])
        AutodebetAccountFactory(is_use_autodebet=False, is_deleted_autodebet=False,
                                account=self.accounts[1])
        AutodebetAccountFactory(is_use_autodebet=True, is_deleted_autodebet=True,
                                account=self.accounts[1])

    def test_excluding_autodebet_account_payment_return_data_is_use_autodebet_false(self):
        results = excluding_autodebet_account_payment_dpd_minus(AccountPayment.objects.all())

        # 1x: is_use_autodebet=True and is_deleted_autodebet=True
        # 3x: is_use_autodebet=False and is_deleted_autodebet=False
        # 3x: is_use_autodebet=False and is_deleted_autodebet=True
        # 1x: there is no autodebet_account
        self.assertEqual(8, len(results))
        for result in results:
            autodebet_account = AutodebetAccount.objects.filter(
                account_id=result.account_id,
                is_deleted_autodebet=False).first()

            is_use_autodebet = autodebet_account.is_use_autodebet if autodebet_account else False

            self.assertFalse(is_use_autodebet)

    def test_excluding_autodebet_account_payment_return_argument_when_is_not(self):
        result_none = excluding_autodebet_account_payment_dpd_minus(None)
        result_empty = excluding_autodebet_account_payment_dpd_minus([])

        self.assertEqual(None, result_none)
        self.assertEqual([], result_empty)


class TestIsLastAccountPaymentStatusNotPaid(TestCase):
    def setUp(self):
        self.account = AccountFactory()

    def test_no_prev_account_payment(self):
        account_payments = AccountPaymentFactory.create_batch(
            2,
            due_date=Iterator(['2022-03-01', '2022-04-01']),
            status_id=Iterator([310, 310]),
            account=self.account
        )
        ret_val = is_last_account_payment_status_notpaid(account_payments[0])
        self.assertFalse(ret_val)

    def test_prev_paid(self):
        account_payments = AccountPaymentFactory.create_batch(
            4,
            due_date=Iterator(['2022-01-01', '2022-02-01', '2022-03-01', '2022-04-01']),
            status_id=Iterator([330, 330, 310, 310]),
            account=self.account
        )
        ret_val = is_last_account_payment_status_notpaid(account_payments[2])
        self.assertFalse(ret_val)

    def test_prev_paid_wrong_order_id(self):
        account_payments = AccountPaymentFactory.create_batch(
            4,
            due_date=Iterator(['2022-01-01', '2022-02-01', '2022-04-01', '2022-03-01']),
            status_id=Iterator([330, 330, 310, 310]),
            account=self.account
        )
        ret_val = is_last_account_payment_status_notpaid(account_payments[3])
        self.assertFalse(ret_val)

    def test_prev_unpaid(self):
        account_payments = AccountPaymentFactory.create_batch(
            4,
            due_date=Iterator(['2022-01-01', '2022-02-01', '2022-03-01', '2022-04-01']),
            status_id=Iterator([330, 330, 310, 310]),
            account=self.account
        )
        ret_val = is_last_account_payment_status_notpaid(account_payments[3])
        self.assertTrue(ret_val)

    def test_prev_paid_restructured(self):
        account_payments = AccountPaymentFactory.create_batch(
            4,
            due_date=Iterator(['2022-01-01', '2022-02-01', '2022-03-01', '2022-04-01']),
            status_id=Iterator([330, 330, 310, 310]),
            is_restructured=Iterator([False, False, True, False]),
            account=self.account
        )
        ret_val = is_last_account_payment_status_notpaid(account_payments[3])
        self.assertFalse(ret_val)

    def test_prev_unpaid_restructured(self):
        account_payments = AccountPaymentFactory.create_batch(
            4,
            due_date=Iterator(['2022-01-01', '2022-02-01', '2022-03-01', '2022-04-01']),
            status_id=Iterator([330, 310, 330, 310]),
            is_restructured=Iterator([False, False, True, False]),
            account=self.account
        )
        ret_val = is_last_account_payment_status_notpaid(account_payments[3])
        self.assertTrue(ret_val)


class TestSendVoiceAccountPaymentReminderDana(TestCase):

    def setUp(self):
        self.streamlined_communication_dana = StreamlinedCommunicationFactory(
            template_code='nexmo_robocall_dana_-2',
            attempts=3,
            call_hours='{8:0,10:0,12:0}',
            function_name="""
                                                {send_voice_account_payment_reminder,retry_send_voice_account_payment_reminder1,
                                                retry_send_voice_account_payment_reminder2}
                                                """,
            communication_platform=CommunicationPlatform.ROBOCALL,
            time_out_duration=30,
            product='nexmo_dana',
            type='Payment Reminder',
            dpd=-3,
            is_active=True,
            is_automated=True,

        )
        self.product_line_dana = ProductLineFactory(
            product_line_code=700, product_line_type='DANA'
        )

        account_dana = AccountFactory()
        ApplicationFactory(
            account=account_dana, product_line=self.product_line_dana, address_kodepos=97711
        )
        AccountPaymentFactory(
            account=account_dana, is_robocall_active=True, due_date='2023-01-11'
        )
        customer = CustomerFactory()
        partner = PartnerFactory()
        DanaCustomerDataFactory(
            dana_customer_identifier="Dana_customer303", account=account_dana,
            customer=customer, partner=partner
        )

    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_send_voice_account_payment_remainder_for_nexmo_dana(self, mock_julo_voice_client):

        with patch.object(
                timezone, 'now', return_value=datetime(2023, 1, 8, 12, 0, 0)
        ) as mock_timezone:
            send_voice_account_payment_reminder(
                0, 12, [self.product_line_dana.product_line_code],
                self.streamlined_communication_dana.pk
            )

            mock_julo_voice_client.return_value.account_payment_reminder.assert_called()
            self.assertTrue(mock_julo_voice_client.called)

    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_retry_send_voice_account_payment_reminder1_for_dana(
        self, mock_julo_voice_client):
        with patch.object(
            timezone, 'now', return_value=datetime(2023, 1, 8, 12, 0, 0)
        ) as mock_timezone:
            retry_send_voice_account_payment_reminder1(
                0, 12, [self.product_line_dana.product_line_code], self.streamlined_communication_dana.pk)

            mock_julo_voice_client.return_value.account_payment_reminder.assert_called()
            self.assertTrue(mock_julo_voice_client.called)

    @patch('juloserver.julo.clients.voice_v2.JuloVoiceClientV2')
    def test_retry_send_voice_account_payment_reminder2_for_dana(
        self, mock_julo_voice_client):
        with patch.object(
            timezone, 'now', return_value=datetime(2023, 1, 8, 12, 0, 0)
        ) as mock_timezone:
            retry_send_voice_account_payment_reminder2(
                0, 12, [self.product_line_dana.product_line_code], self.streamlined_communication_dana.pk)

            mock_julo_voice_client.return_value.account_payment_reminder.assert_called()
            self.assertTrue(mock_julo_voice_client.called)


class MarkVoiceAccountPaymentReminder(TestCase):
    def setUp(self):
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.DANA,
            product_line_type='DANA'
        )
        self.customer = CustomerFactory()
        self.account = AccountwithApplicationFactory(
            customer=self.customer,
            create_application__product_line=self.product_line,
            create_application__customer=self.customer
        )
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            is_restructured=False,
            is_robocall_active=False,
            due_date=datetime(2023, 1, 11)
        )

    def test_mark_voice_account_payment_reminder(self):
        with patch.object(
            timezone, 'now', return_value=datetime(2023, 1, 8, 12, 0, 0)
        ):
            mark_voice_account_payment_reminder([-3])

        self.account_payment.refresh_from_db()
        self.assertEqual(self.account_payment.is_robocall_active, True)

    def test_mark_voice_account_payment_reminder_unpaid_not_in_dpd(self):
        with patch.object(
            timezone, 'now', return_value=datetime(2023, 1, 8, 12, 0, 0)
        ):
            mark_voice_account_payment_reminder([-5])

        self.account_payment.refresh_from_db()
        self.assertEqual(self.account_payment.is_robocall_active, None)

    def test_mark_voice_account_payment_reminder_product_not_included(self):
        application = Application.objects.get(customer=self.customer)
        application.product_line = ProductLineFactory(
            product_line_code=999,
            product_line_type='FakeProduct'
        )
        application.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2023, 1, 8, 12, 0, 0)
        ):
            mark_voice_account_payment_reminder([-3])

        self.account_payment.refresh_from_db()
        self.assertEqual(self.account_payment.is_robocall_active, None)
