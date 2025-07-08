from __future__ import absolute_import

from unittest.mock import MagicMock

import factory
import pytest
from datetime import datetime
import mock
from mock import patch

from django.test.testcases import TestCase, override_settings

from juloserver.julo.statuses import LoanStatusCodes
from juloserver.payment_point.constants import SepulsaProductType
from .factories import *

from juloserver.julo.exceptions import (
    AutomatedPnNotSent,
    JuloException,
)

from django.contrib.auth.models import User

from juloserver.julo.tasks import (
    calculate_countdown,
    create_accounting_cut_off_date_monthly_entry,
    send_automated_comm_email_for_unsent_moengage,
    send_automated_comm_pn_subtask,
    send_cashback_expired_pn_subtask,
    send_cashback_expired_pn,
    ping_auto_call_122_subtask,
    filter_122_with_nexmo_auto_call,
    filter_138_with_nexmo_auto_call,
    send_email_for_unsent_moengage,
    send_manual_pn_for_unsent_moengage,
    send_manual_pn_for_unsent_moengage_sub_task,
    send_sms_for_unsent_moengage,
)

from juloserver.julo.constants import (
    FeatureNameConst,
)
from ..models import AccountingCutOffDate
from juloserver.julo.tasks2 import (
    scheduled_regenerate_freelance_agent_password,
    send_password_email_for_collection,
    send_password_email_for_operation,
    update_limit_for_good_customers,
)
from juloserver.account.models import CreditLimitGeneration
from juloserver.account.tests.factories import (
    AccountLookupFactory,
    AccountwithApplicationFactory,
    CreditLimitGenerationFactory,
    AccountFactory,
    AccountLimitFactory,
    ExperimentGroupFactory,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    StatusLookupFactory,
    CreditMatrixFactory,
    CreditMatrixProductLineFactory,
    WorkflowFactory,
    ImageFactory,
)
from juloserver.streamlined_communication.test.factories import StreamlinedCommunicationFactory
from juloserver.apiv2.tests.factories import PdCreditModelResultFactory
from juloserver.streamlined_communication.models import StreamlinedMessage, StreamlinedCommunication
from juloserver.streamlined_communication.constant import CommunicationPlatform, ImageType
from juloserver.cashback.tests.factories import CashbackEarnedFactory
from juloserver.collection_vendor.tasks.bucket_5_task import change_ever_entered_b5
from juloserver.julocore.python2.utils import py2round
from juloserver.moengage.constants import (
    INHOUSE,
    UNSENT_MOENGAGE,
)
from juloserver.account_payment.tests.factories import (
    AccountPaymentwithPaymentFactory,
    OldestUnpaidAccountPaymentFactory,
)
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.pn_delivery.tests.factories import (
    PNBlastFactory,
    PNDeliveryFactory,
    PNTracksFactory,
)
from ...account_payment.tests.factories import AccountPaymentFactory
from juloserver.payment_point.tasks.transaction_related import (
    check_transaction_sepulsa,
    reset_transaction_sepulsa_break,
    check_transaction_sepulsa_loan,
)
from juloserver.payment_point.tasks.notification_related import (
    send_slack_notification_sepulsa_balance_reach_minimum_threshold,
    send_slack_notification_sepulsa_remaining_balance,
)
from juloserver.julo.services2.sepulsa import SepulsaService
from juloserver.minisquad.constants import ExperimentConst as MinisqiadExperimentConstant


class TestChangeEverEnteredB5Task(TestCase):
    def setUp(self):
        pass

    @patch('django.db.models.query.QuerySet.select_related')
    def test_change_ever_entered_b5(self, mocked_query):
        application = ApplicationFactory(id=412666, account=None)
        status_220 = StatusLookup.objects.get(status_code=LoanStatusCodes.CURRENT)
        loan = LoanFactory(
            application=application, account=None, id=3112666,
            loan_status=status_220, ever_entered_B5=False)

        today = timezone.localtime(timezone.now()).date()
        due_date_more_91 = today - relativedelta(days=260)

        payment = PaymentFactory(loan=loan, due_date=due_date_more_91, id=6667541)
        mocked_query.return_value.not_paid_active.return_value.filter.return_value = [payment]
        change_ever_entered_b5()

        self.assertTrue(mocked_query.called)
        loan.refresh_from_db()
        self.assertTrue(loan.ever_entered_B5)


class TestCreateAccountingCutOffDateMonthlyEntry(TestCase):
    def setUp(self):
        self.featuresetting = FeatureSettingFactory(
            feature_name=FeatureNameConst.ACCOUNTING_CUT_OFF_DATE,
            parameters={'cut_off_date': 1}
        )
        today = timezone.localtime(timezone.now())
        self.cut_off_date = today.replace(
            day=1).date()

    def test_create_accounting_cut_off_date_monthly_entry(self):
        create_accounting_cut_off_date_monthly_entry()
        assert AccountingCutOffDate.objects.filter(cut_off_date=self.cut_off_date).exists()

    def test_create_accounting_cut_off_date_monthly_entry_no_setting(self):
        self.featuresetting.is_active = False
        self.featuresetting.save()

        create_accounting_cut_off_date_monthly_entry()
        assert not AccountingCutOffDate.objects.filter(cut_off_date=self.cut_off_date).exists()


class TestSendAutomatedCommPnSubtask(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = PaymentFactory(loan=self.loan)
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

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_automated_comm_pn_subtask(self, mock_get_julo_pn_client):
        send_automated_comm_pn_subtask(
            self.payment.id, 'hi', 'hi', 'hi', 'hi')
        mock_get_julo_pn_client.return_value.automated_payment_reminder.assert_called_once_with(
            self.payment, 'hi', 'hi', 'hi', 'hi' , None
        )

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_automated_comm_pn_subtask_no_payment(self, mock_get_julo_pn_client):
        send_automated_comm_pn_subtask(
            0, 'hi', 'hi', 'hi', 'hi')
        mock_get_julo_pn_client.return_value.automated_payment_reminder.assert_not_called()

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_automated_comm_pn_subtask_with_image(self, mock_get_julo_pn_client):
        send_automated_comm_pn_subtask(
            self.payment.id, 'hi', 'hi', 'hi', 'hi', self.image)
        mock_get_julo_pn_client.return_value.automated_payment_reminder.assert_called_once_with(
            self.payment, 'hi', 'hi', 'hi', 'hi', self.image
        )

class TestCheckTransactionSepulsa(TestCase):
    def setUp(self):
        self.sepulsa = SepulsaTransactionFactory(transaction_status='pending')
        self.sepulsa_2 = SepulsaTransactionFactory(transaction_status='pending')
        self.sepulsa_2.cdate = self.sepulsa_2.cdate - timedelta(minutes=20)
        self.sepulsa_2.save()
        self.sepulsa_3 = SepulsaTransactionFactory(
            transaction_status='pending')
        self.sepulsa_3.cdate = self.sepulsa_3.cdate - timedelta(minutes=20)
        self.sepulsa_3.save()

        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.loan = LoanFactory(account=self.account)
        self.sepulsa_4 = SepulsaTransactionFactory(transaction_status='pending', loan=self.loan)
        self.sepulsa_4.cdate = self.sepulsa_4.cdate - timedelta(minutes=20)
        self.sepulsa_4.save()

    @patch('juloserver.julo.clients.sepulsa.get_julo_sepulsa_client')
    @patch('juloserver.payment_point.tasks.transaction_related.get_julo_sentry_client')
    @patch('juloserver.payment_point.tasks.transaction_related.SepulsaService')
    @patch('juloserver.payment_point.tasks.transaction_related.LineOfCreditPurchaseService')
    @patch('juloserver.payment_point.tasks.transaction_related.action_cashback_sepulsa_transaction')
    def test_check_transaction_sepulsa(
            self, _mock_action_cashback_sepulsa_transaction,
            _mock_LineOfCreditPurchaseService,
            _mock_SepulsaService,
            _mock_get_julo_sentry_client,
            _mock_get_julo_sepulsa_client):
        check_transaction_sepulsa()

    @patch('juloserver.julo.clients.sepulsa.get_julo_sepulsa_client')
    @patch('juloserver.payment_point.tasks.transaction_related.get_julo_sentry_client')
    @patch('juloserver.payment_point.tasks.transaction_related.SepulsaService')
    @patch('juloserver.payment_point.tasks.transaction_related.LineOfCreditPurchaseService')
    @patch('juloserver.payment_point.tasks.transaction_related.action_cashback_sepulsa_transaction')
    def test_check_transaction_sepulsa_with_ewallet_open_payment(
            self, _mock_action_cashback_sepulsa_transaction,
            _mock_LineOfCreditPurchaseService,
            _mock_SepulsaService,
            _mock_get_julo_sentry_client,
            _mock_get_julo_sepulsa_client):
        product = SepulsaProductFactory.ewallet_open_payment()
        sepulsa_5 = SepulsaTransactionFactory(
            transaction_status='pending', loan=None,
            product=product
        )
        sepulsa_5.cdate = sepulsa_5.cdate - timedelta(minutes=20)
        sepulsa_5.save()
        check_transaction_sepulsa()
        _mock_get_julo_sepulsa_client().get_transaction_detail_ewallet_open_payment.assert_called_once_with(
            sepulsa_5
        )

    @patch('juloserver.julo.clients.sepulsa.get_julo_sepulsa_client')
    @patch('juloserver.payment_point.tasks.transaction_related.get_julo_sentry_client')
    @patch('juloserver.payment_point.tasks.transaction_related.SepulsaService')
    @patch('juloserver.payment_point.tasks.transaction_related.LineOfCreditPurchaseService')
    @patch('juloserver.payment_point.tasks.transaction_related.action_cashback_sepulsa_transaction')
    def test_check_transaction_sepulsa_raise_error(
            self, _mock_action_cashback_sepulsa_transaction,
            _mock_LineOfCreditPurchaseService,
            _mock_SepulsaService,
            _mock_get_julo_sentry_client,
            _mock_get_julo_sepulsa_client):
        _mock_SepulsaService.return_value.update_sepulsa_transaction_with_history_accordingly.side_effect = Exception('Boom')
        check_transaction_sepulsa()

    @patch('juloserver.julo.clients.sepulsa.JuloSepulsaClient.get_transaction_detail')
    @patch('juloserver.payment_point.tasks.transaction_related.get_julo_sentry_client')
    @patch('juloserver.payment_point.tasks.transaction_related.action_cashback_sepulsa_transaction')
    def test_check_transaction_sepulsa_loan(
            self,
            _mock_action_cashback_sepulsa_transaction,
            _mock_get_julo_sentry_client,
            _mock_sepulsa_loan_service_get_detail
        ):
        # response_code 26 (new response_code from Sepulsa)
        response = {
            "response_code": "26",
            "transaction_id": "553751807",
            "status": "failed",
            "serial_number": None,
            "token": ""
        }
        _mock_sepulsa_loan_service_get_detail.return_value = response
        check_transaction_sepulsa_loan()
        self.sepulsa_4.refresh_from_db()
        assert self.sepulsa_4.transaction_status == 'failed'

        # raise exception when the response code doesn't exist in the system
        self.sepulsa_4.transaction_status = 'pending'
        self.sepulsa_4.save()
        response['response_code'] = '100'
        _mock_sepulsa_loan_service_get_detail.return_value = response
        services = SepulsaService()
        with self.assertRaises(JuloException) as context:
            services.update_sepulsa_transaction_with_history_accordingly(
                self.sepulsa_4, "update_transaction_via_task", response
            )
        self.assertEqual(
            str(context.exception), 'Sepulsa response code not found (%s)' % (response))

    @patch('juloserver.julo.clients.get_julo_sepulsa_client')
    @patch('juloserver.julo.tasks.warn_sepulsa_balance_low_once_daily_async')
    def test_waning_warn_sepulsa_balance_low_once_daily_async(
            self,
            mock_warn_sepulsa_balance_low_once_daily_async,
            mock_get_julo_sepulsa_client,
    ):
        services = SepulsaService()
        services.julo_sepulsa_client = mock_get_julo_sepulsa_client
        services.julo_sepulsa_client.get_balance_and_check_minimum.return_value = 1000, True
        services.is_balance_enough_for_transaction(5000)
        mock_warn_sepulsa_balance_low_once_daily_async.delay.assert_called_with(1000)


class TestResetTransactionSepulsaBreak(TestCase):
    def setUp(self):
        self.sepulsatransaction = SepulsaTransactionFactory()

    def test_reset_transaction_sepulsa_break(self):
        reset_transaction_sepulsa_break()


class TestPingAutoCall122Subtask(TestCase):

    @patch('juloserver.julo.tasks.datetime')
    @patch('juloserver.julo.tasks.is_app_to_be_called')
    @patch('juloserver.julo.tasks.get_voice_client')
    def test_reset_transaction_sepulsa_break(
            self,
            _mock_get_voice_client,
            _mock_is_app_to_be_called,
            _mock_date):
        _mock_date.now.return_value = datetime.strptime("17:00:00", "%H:%M:%S")
        _mock_date.strptime.side_effect = datetime.strptime
        ping_auto_call_122_subtask(111, 111)


    @patch('juloserver.julo.tasks.datetime')
    @patch('juloserver.julo.tasks.is_app_to_be_called')
    @patch('juloserver.julo.tasks.get_voice_client')
    def test_reset_transaction_sepulsa_break_timeout(
            self,
            _mock_get_voice_client,
            _mock_is_app_to_be_called,
            _mock_date):

        _mock_date.now.return_value = datetime.strptime("15:00:00", "%H:%M:%S")
        _mock_date.strptime.side_effect = datetime.strptime
        ping_auto_call_122_subtask(111, 111)


class TestFilter_122_with_nexmo_auto_call(TestCase):
    def setUp(self):
        self.featuresetting = FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTO_CALL_PING_122,
            is_active=True
        )
        self.application = ApplicationFactory()
        self.application.application_status_id = 122
        self.application.save()

    @patch('juloserver.julo.tasks.filter_due_dates_by_weekend')
    @patch('juloserver.julo.tasks.filter_due_dates_by_pub_holiday')
    def test_filter_122_with_nexmo_auto_call(
            self,
            _mock_filter_due_dates_by_pub_holiday,
            _mock_filter_due_dates_by_weekend):
        filter_122_with_nexmo_auto_call()

    @patch('juloserver.julo.tasks.filter_due_dates_by_weekend')
    @patch('juloserver.julo.tasks.filter_due_dates_by_pub_holiday')
    def test_filter_122_with_nexmo_auto_call_raise_exception(
            self,
            _mock_filter_due_dates_by_pub_holiday,
            _mock_filter_due_dates_by_weekend):
        _mock_filter_due_dates_by_weekend.side_effect = JuloException('boom')
        filter_122_with_nexmo_auto_call()


class TestFilter138WithNexmoAutoCall(TestCase):
    def setUp(self):
        pass

    @patch('juloserver.julo.tasks.filter_due_dates_by_weekend')
    @patch('juloserver.julo.tasks.filter_due_dates_by_pub_holiday')
    def test_filter_138_with_nexmo_auto_call(
            self,
            mock_filter_due_dates_by_pub_holiday,
            mock_filter_due_dates_by_weekend):
        filter_138_with_nexmo_auto_call()


def slack_message_mock(message, channel):
    return message, channel


class TestSlackCurrentBalanceSepulsaDeposit(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.NOTIFICATION_MINIMUM_PARTNER_DEPOSIT_BALANCE,
            parameters={
                'balance_threshold': 10000,
                'users': ["unittest1", "unittest2"]
            }
        )

    @mock.patch('juloserver.payment_point.tasks.notification_related.send_message_normal_format',
                side_effect=slack_message_mock)
    @mock.patch('juloserver.payment_point.tasks.notification_related.get_julo_sepulsa_client')
    @mock.patch('juloserver.payment_point.tasks.notification_related.get_julo_sepulsa_loan_client')
    def test_sepulsa_remaining_balance_notification(
            self, sepulsa_loan_client_mock, sepulsa_client_mock, slack_mock):
        sepulsa_loan_client_mock.return_value.get_balance.return_value = 100000
        sepulsa_client_mock.return_value.get_balance.return_value = 100000
        send_slack_notification_sepulsa_remaining_balance()
        assert '#partner_balance' == slack_mock.mock_calls[0][2]['channel']
        assert len(slack_mock.mock_calls[0][1][0]) > 0

    @mock.patch('juloserver.payment_point.tasks.notification_related.send_message_normal_format_to_users',
                side_effect=slack_message_mock)
    @mock.patch('juloserver.payment_point.tasks.notification_related.send_message_normal_format',
                side_effect=slack_message_mock)
    @mock.patch('juloserver.payment_point.tasks.notification_related.get_julo_sepulsa_client')
    @mock.patch('juloserver.payment_point.tasks.notification_related.get_julo_sepulsa_loan_client')
    def test_sepulsa_balance_reach_minimum_threshold_notification(
            self, sepulsa_loan_client_mock, sepulsa_client_mock,
            slack_channel_mock, slack_personal_mock):
        sepulsa_loan_client_mock.return_value.get_balance.return_value = 10000
        sepulsa_client_mock.return_value.get_balance.return_value = 10000
        send_slack_notification_sepulsa_balance_reach_minimum_threshold()
        assert '#partner_balance' == slack_channel_mock.mock_calls[0][2]['channel']
        assert len(slack_channel_mock.mock_calls[0][1][0]) > 0
        assert 'unittest1' in slack_personal_mock.mock_calls[0][1][1]


class TestUpdateLimitAdjustmentTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.application = ApplicationFactory(customer=self.customer,
                                              account=self.account,
                                              workflow=self.workflow)
        self.application.application_status = StatusLookupFactory(status_code=150)
        self.application.save()
        self.account_limit = AccountLimitFactory(
            account=self.account,
            max_limit=1000,
            set_limit=1000,
            available_limit=1000
        )
        self.pd_credit_model = PdCreditModelResultFactory(
            pgood=0.95, application_id=self.application.id,
            customer_id=self.customer.id
        )
        self.credit_matrix = CreditMatrixFactory()
        self.credit_matrix_product_line = CreditMatrixProductLineFactory(
            credit_matrix=self.credit_matrix,
            max_loan_amount=10000000
        )
        self.customer_limit_generation = CreditLimitGenerationFactory(
            account=self.account,
            application=self.application,
            credit_matrix=self.credit_matrix,
            max_limit=40000,
            set_limit=40000,
            log='{"simple_limit": 0, "max_limit (pre-matrix)": 0, "set_limit (pre-matrix)": 0, '
                '"limit_adjustment_factor": 0.8, "reduced_limit": 0}'
        )

    @mock.patch('juloserver.account.services.credit_limit.get_credit_matrix_parameters')
    @mock.patch('juloserver.account.services.credit_limit.get_credit_matrix')
    def test_update_limit_adjustment(self, mocked_credit_matrix, mocked_parameters):
        mocked_credit_matrix.return_value = self.credit_matrix
        mocked_parameters.return_value = {
            'min_threshold__lte': 1.0,
            'max_threshold__gte': 1.0,
            'credit_matrix_type': 'julo1',
            'is_salaried': True,
            'is_premium_area': True}
        update_limit_for_good_customers(self.application.id, None, 0.9)

        credit_limit = CreditLimitGeneration.objects.filter(
            account=self.account,
            log__contains='"limit_adjustment_factor": 0.9'
        ).count()
        assert credit_limit == 1


class TestSendCashbackExpiredPN(TestCase):
    def setUp(self):
        message_pn_with_action_buttons = StreamlinedMessage.objects.create(
            message_content="Test PN with Action Buttons")
        self.streamlined_communication = StreamlinedCommunication.objects.create(
            type='Payment Reminder',
            communication_platform=CommunicationPlatform.PN,
            template_code='MTL_T0',
            message=message_pn_with_action_buttons,
            product='mtl',
            dpd=5)
        self.customer = CustomerFactory(
            can_notify=True
        )
        today = timezone.localtime(timezone.now())
        self.device = DeviceFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer,
                                              device=self.device)
        self.cashback_earned = CashbackEarnedFactory(
            current_balance=10000,
            expired_on_date=today + timedelta(days=5)
        )
        self.customer_wallet_history = CustomerWalletHistoryFactory(
            customer=self.customer,
            change_reason='cashback_earned',
            wallet_balance_available=self.cashback_earned.current_balance,
            cashback_earned=self.cashback_earned,
        )

    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_send_cashback_expired_pn_subtask(self, mock_get_julo_pn_client):
        send_cashback_expired_pn_subtask(
            self.customer.id, 'hi', 'template_code')
        assert mock_get_julo_pn_client.return_value.cashback_expire_reminder.called

    @patch('juloserver.julo.tasks.send_automated_comm_pn_subtask')
    def test_send_automated_comm_pn(self, mock_send_automated_comm_pn_subtask):
        response = send_cashback_expired_pn(self.streamlined_communication.id)
        assert response is None


class TestSendEmailForUnsentMoengage(TestCase):
    def setUp(self):
        self.streamlined_comms = StreamlinedCommunicationFactory(
                moengage_template_code='some_moengage_template_code',
                communication_platform=CommunicationPlatform.EMAIL,
                time_sent='18:0',
                is_automated=True,
                extra_conditions=UNSENT_MOENGAGE,
                dpd=-4
        )

    @patch('juloserver.julo.tasks.send_automated_comm_email_for_unsent_moengage.apply_async')
    def test_send_automated_comm_email_applied_when_streamlined_comm_exist(
            self, mock_send_automated_comm_email):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 4, 28, 16, 0, 0)
        ) as mock_timezone:
            send_email_for_unsent_moengage()
            time = self.streamlined_comms.time_sent.split(':')
            args = mock_send_automated_comm_email.call_args_list

            self.assertTrue(mock_send_automated_comm_email.called)
            self.assertEqual(4, mock_send_automated_comm_email.call_count)

            for attempt in range(4):
                expected_result = calculate_countdown(
                    hour=int(time[0]), minute=int(time[1])) + 1800 * attempt

                self.assertEqual((self.streamlined_comms.id,), args[attempt][0][0])
                self.assertEqual(expected_result, args[attempt][1]['countdown'])

    @patch('juloserver.julo.tasks.send_automated_comm_email_for_unsent_moengage.apply_async')
    def test_send_automated_comm_email_call_count_6_when_sent_time_5pm(
            self, mock_send_automated_comm_email):
        self.streamlined_comms.time_sent = '17:0'
        self.streamlined_comms.save()

        with patch.object(
            timezone, 'now', return_value=datetime(2022, 4, 28, 16, 0, 0)
        ) as mock_timezone:
            send_email_for_unsent_moengage()
            self.assertEqual(6, mock_send_automated_comm_email.call_count)

    @patch('juloserver.julo.tasks.send_automated_comm_email_for_unsent_moengage.apply_async')
    def test_send_automated_comm_email_fail_when_streamlined_comm_none(
            self, mock_send_automated_comm_email):
        self.streamlined_comms.delete()
        send_email_for_unsent_moengage()
        self.assertFalse(mock_send_automated_comm_email.called)

    @patch('juloserver.julo.tasks.send_automated_comm_email_for_unsent_moengage.apply_async')
    def test_send_automated_comm_email_partial_fail_when_base_countdown_less_than_zero(
            self, mock_send_automated_comm_email):
        with patch.object(
            timezone, 'now', return_value=datetime(2022, 4, 28, 18, 1, 0)
        ) as mock_timezone:
            send_email_for_unsent_moengage()
            self.assertEqual(3, mock_send_automated_comm_email.call_count)

    @patch('juloserver.julo.tasks.send_automated_comm_email_for_unsent_moengage.apply_async')
    def test_send_automated_comm_email_fail_when_sent_time_8pm(
            self, mock_send_automated_comm_email):
        self.streamlined_comms.time_sent = '20:0'
        self.streamlined_comms.save()

        send_email_for_unsent_moengage()
        self.assertFalse(mock_send_automated_comm_email.called)


@patch('juloserver.julo.tasks.get_redis_client')
class TestSendAutomatedCommEmailForUnsentMoengage(TestCase):
    def setUp(self):
        self.workflow = WorkflowFactory(name='JuloOneWorkflow')
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)
        self.customer = CustomerFactory()
        self.account = AccountwithApplicationFactory(
            account_lookup=self.account_lookup,
            customer=self.customer,
        )
        self.account_payment = AccountPaymentwithPaymentFactory(account=self.account)
        self.oldest_unpaid_account_payment = OldestUnpaidAccountPaymentFactory(
            dpd=-2,
            account_payment=self.account_payment
        )
        self.streamlined_comm = StreamlinedCommunicationFactory(
            dpd=-2,
            template_code='j1_email_dpd_-2',
            moengage_template_code='j1_email_reminder_-2',
            extra_conditions=UNSENT_MOENGAGE,
            product='j1'
        )
        self.streamlined_comm_autodebet = StreamlinedCommunicationFactory(
            template_code='j1_email_autodebet_dpd_-2',
            communication_platform=CommunicationPlatform.EMAIL,
            time_sent='18:0',
            is_automated=True,
            extra_conditions=UNSENT_MOENGAGE,
            dpd=-2
        )
        self.application = Application.objects.get(account_id=self.account.pk)
        self.email_history = EmailHistoryFactory(
            application=self.application,
            customer=self.customer,
            lender=None,
            payment=None,
            account_payment=self.account_payment,
            template_code=self.streamlined_comm.moengage_template_code,
            source='MOENGAGE'
        )
        self.cashback_exp = ExperimentSettingFactory(
            is_active=False,
            code=MinisqiadExperimentConstant.CASHBACK_NEW_SCHEME,
            is_permanent=False,
            criteria={
                "account_id_tail": {
                    "control": [0, 1, 2, 3, 4],
                    "experiment": [5, 6, 7, 8, 9]
                }
            }
        )

    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    def test_send_email_payment_reminder_unsent_account_payment(
            self, mock_send_email_payment_reminder, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        self.email_history.delete()
        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.id)
        mock_send_email_payment_reminder.assert_called_once_with(
            self.account_payment.id,
            self.streamlined_comm.id,
            'send_automated_comm_email_for_unsent_moengage'
        )

    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    @patch('juloserver.julo.tasks.logger')
    def test_send_email_payment_reminder_ignore_sent_streamlined_account_payment(
        self, mock_logger, mock_send_email_payment_reminder, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None
        self.email_history.source = INHOUSE
        self.email_history.save()
        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.id)
        mock_send_email_payment_reminder.assert_not_called()
        mock_logger.info.assert_called_once_with({
            'action': 'send_automated_comm_email_for_unsent_moengage',
            'message': 'all data is sent successfully',
            'template_code': ('j1_email_dpd_-2', 'j1_email_reminder_-2',
                              'j1_email_autodebet_dpd_-2'),
            'date': str(timezone.localtime(timezone.now()).date())
        })

    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    @patch('juloserver.julo.tasks.logger')
    def test_send_email_payment_reminder_ignore_sent_moengage_account_payment(
        self, mock_logger, mock_send_email_payment_reminder, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None
        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.id)
        mock_send_email_payment_reminder.assert_not_called()
        mock_logger.info.assert_called_once_with({
            'action': 'send_automated_comm_email_for_unsent_moengage',
            'message': 'all data is sent successfully',
            'template_code': ('j1_email_dpd_-2', 'j1_email_reminder_-2',
                              'j1_email_autodebet_dpd_-2'),
            'date': str(timezone.localtime(timezone.now()).date())
        })

    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    def test_send_email_payment_reminder_with_autodebet_account_when_streamlined_dpd_minus_2(
            self, mock_send_email_payment_reminder, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        self.email_history.delete()
        AutodebetAccountFactory(
            account=self.account,
            is_use_autodebet=True,
            is_deleted_autodebet=False
        )
        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.pk)
        mock_send_email_payment_reminder.assert_called_once_with(
            self.account_payment.id,
            self.streamlined_comm_autodebet.id,
            'send_automated_comm_email_for_unsent_moengage'
        )

    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    def test_send_email_payment_reminder_with_autodebet_account_unsent(
        self, mock_send_email_payment_reminder, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        self.email_history.delete()
        AutodebetAccountFactory(
            account=self.account,
            is_use_autodebet=True,
            is_deleted_autodebet=False
        )
        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.pk)
        mock_send_email_payment_reminder.assert_called_once_with(
            self.account_payment.id,
            self.streamlined_comm_autodebet.id,
            'send_automated_comm_email_for_unsent_moengage'
        )

    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    @patch('juloserver.julo.tasks.logger')
    def test_send_email_payment_reminder_with_autodebet_account_dont_send_not_unsent(
        self, mock_logger, mock_send_email_payment_reminder, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None

        AutodebetAccountFactory(
            account=self.account,
            is_use_autodebet=True,
            is_deleted_autodebet=False)
        self.email_history.source = INHOUSE
        self.email_history.template_code = self.streamlined_comm_autodebet.template_code
        self.email_history.save()
        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.id)
        mock_send_email_payment_reminder.assert_not_called()
        mock_logger.info.assert_called_once_with({
            'action': 'send_automated_comm_email_for_unsent_moengage',
            'message': 'all data is sent successfully',
            'template_code': ('j1_email_dpd_-2', 'j1_email_reminder_-2',
                              'j1_email_autodebet_dpd_-2'),
            'date': str(timezone.localtime(timezone.now()).date())
        })

    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    def test_send_email_payment_reminder_with_autodebet_account_dont_send_dpd_not_minus_2(
        self, mock_send_email_payment_reminder, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None

        self.email_history.delete()
        AutodebetAccountFactory(
            account=self.account,
            is_use_autodebet=True,
            is_deleted_autodebet=False)
        self.streamlined_comm.dpd = -3
        self.streamlined_comm.save()
        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.pk)
        mock_send_email_payment_reminder.assert_not_called()

    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    def test_send_email_payment_reminder_with_email_history_no_account_payment_id_dont_send(
        self, mock_send_email_payment_reminder, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None

        self.email_history.account_payment = None
        self.email_history.save()
        EmailHistoryFactory(
            application=self.application,
            customer=self.customer,
            lender=None,
            payment=None,
            account_payment=None,
            template_code=self.streamlined_comm.moengage_template_code,
            source='MOENGAGE'
        )
        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.id)
        mock_send_email_payment_reminder.assert_not_called()

    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.email_delivery.tasks.send_email_payment_reminder_for_unsent_moengage.delay')
    def test_send_email_payment_reminder_with_email_history_no_account_payment_id_send_others(
        self, mock_send_email_payment_reminder, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_redis_client.return_value.set.return_value = None

        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')
        account_unsent = AccountwithApplicationFactory(
            account_lookup=self.account_lookup,
        )
        account_payment_unsent = AccountPaymentwithPaymentFactory(account=account_unsent)
        OldestUnpaidAccountPaymentFactory(
            dpd=-2,
            account_payment=account_payment_unsent
        )

        send_automated_comm_email_for_unsent_moengage(self.streamlined_comm.id)
        mock_send_email_payment_reminder.assert_called_once_with(
            account_payment_unsent.id,
            self.streamlined_comm.id,
            'send_automated_comm_email_for_unsent_moengage'
        )


class TestSmsForUnsentMoengage(TestCase):
    def setUp(self):
        self.streamlined_comms = StreamlinedCommunicationFactory(
                communication_platform=CommunicationPlatform.SMS,
                time_sent='18:0',
                is_automated=True,
                extra_conditions=UNSENT_MOENGAGE,
                dpd=-4
        )

    @patch('juloserver.julo.tasks.send_automated_comm_sms_for_unsent_moengage.apply_async')
    @patch('juloserver.julo.tasks.calculate_countdown', return_value=21600)
    def test_send_automated_comm_sms_applied_when_streamlined_comm_exist(
            self, mock_countdown, mock_send_automated_comm_sms):
        send_sms_for_unsent_moengage()

        args, kwargs = mock_send_automated_comm_sms.call_args
        expected_result = mock_countdown.return_value

        self.assertTrue(mock_send_automated_comm_sms.called)
        self.assertEqual(1, mock_send_automated_comm_sms.call_count)
        self.assertEqual((self.streamlined_comms.id,), args[0])
        self.assertEqual(expected_result, kwargs['countdown'])

    @patch('juloserver.julo.tasks.send_automated_comm_sms_for_unsent_moengage.apply_async')
    def test_send_automated_comm_sms_fail_when_streamlined_comm_none(
            self, mock_send_automated_comm_sms):
        self.streamlined_comms.delete()
        send_sms_for_unsent_moengage()
        self.assertFalse(mock_send_automated_comm_sms.called)

    @patch('juloserver.julo.tasks.send_automated_comm_sms_for_unsent_moengage.apply_async')
    @patch('juloserver.julo.tasks.calculate_countdown', return_value=-1)
    def test_send_automated_comm_sms_fail_when_countdown_less_than_zero(
            self, mock_countdown, mock_send_automated_comm_sms
    ):
        send_sms_for_unsent_moengage()
        self.assertFalse(mock_send_automated_comm_sms.call_args_list)
        self.assertFalse(mock_send_automated_comm_sms.called)


class TestPnForUnsentMoengage(TestCase):
    def setUp(self):
        self.streamlined_communication = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.PN,
            template_code='j1_pn_T-2_backup',
            moengage_template_code='j1_pn_T-2',
            extra_conditions=UNSENT_MOENGAGE,
            time_sent='16:0',
            is_automated=True,
            is_active=True,
            dpd=-2,
            product='j1'
        )
        self.streamlined_communication_autodebet = StreamlinedCommunicationFactory(
            communication_platform=CommunicationPlatform.PN,
            template_code='j1_pn_autodebet_T-2_backup',
            moengage_template_code='j1_pn_autodebet_T-2',
            is_automated=True,
            is_active=True,
            extra_conditions=UNSENT_MOENGAGE,
            time_sent='16:0',
            dpd=-2,
            product='j1'
        )
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow', handler='JuloOneWorkflowHandler'
        )
        self.julo_turbo_workflow = WorkflowFactory(
            name='JuloStarterWorkflow', handler='JuloStarterWorkflowHandler'
        )
        self.account_lookup = AccountLookupFactory(
            workflow=self.julo_one_workflow,
            name='JULO1'
        )
        self.account_lookup_jturbo = AccountLookupFactory(
            workflow=self.julo_turbo_workflow,
            name='JULOTURBO'
        )
        self.account, self.account_payment, self.oldest_unpaid_account_payment = (
            self._prepare_account_payment(dpd=-2)
        )
        self.autodebet_account = AutodebetAccountFactory(
            account=self.account, is_use_autodebet=True)
        self.cashback_exp = ExperimentSettingFactory(
            is_active=False,
            code=MinisqiadExperimentConstant.CASHBACK_NEW_SCHEME,
            is_permanent=False,
            criteria={
                "account_id_tail": {
                    "control": [0, 1, 2, 3, 4],
                    "experiment": [5, 6, 7, 8, 9]
                }
            }
        )

    def _prepare_account_payment(self, dpd: int, product: str = 'j1'):
        if product == 'jturbo':
            account = AccountwithApplicationFactory(account_lookup=self.account_lookup_jturbo)
        else:
            account = AccountwithApplicationFactory(account_lookup=self.account_lookup)
        account_payment = AccountPaymentwithPaymentFactory(account=account)
        DeviceFactory(gcm_reg_id='1234567890', customer=account.customer)
        oldest_unpaid_account_payment = OldestUnpaidAccountPaymentFactory(
            dpd=dpd, account_payment=account_payment)
        return account, account_payment, oldest_unpaid_account_payment

    @patch('juloserver.julo.tasks.send_manual_pn_for_unsent_moengage_sub_task.apply_async')
    def test_send_manual_pn_for_unsent_moengage_queue_time_match(
        self, mock_send_manual_pn
    ):
        with patch.object(timezone, 'now',
                          return_value=datetime(2022, 5, 13, 15, 0, 0)) as mock_timezone:
            send_manual_pn_for_unsent_moengage()

            mock_arguments = mock_send_manual_pn.call_args_list
            self.assertTrue(mock_send_manual_pn.called)
            self.assertEqual(6, mock_send_manual_pn.call_count)

            iterate_index = 0
            time_sent = self.streamlined_communication.time_sent.split(':')
            for streamlined_count in range(2):
                for attempt in range(3):
                    expected_result = calculate_countdown(
                        hour=int(time_sent[0]), minute=int(time_sent[1])) + 4200 * attempt
                    self.assertEqual(expected_result, mock_arguments[iterate_index][1]['countdown'])

                    iterate_index += 1

    @patch('juloserver.julo.tasks.send_manual_pn_for_unsent_moengage_sub_task.apply_async')
    def test_send_manual_pn_for_unsent_moengage_dont_send_after_comm_limit(
        self, mock_send_manual_pn
    ):
        with patch.object(timezone, 'now',
                          return_value=datetime(2022, 5, 13, 19, 31, 0)) as mock_timezone:
            send_manual_pn_for_unsent_moengage()

            self.assertFalse(mock_send_manual_pn.called)

        mock_send_manual_pn.reset_mock()
        with patch.object(timezone, 'now',
                          return_value=datetime(2022, 5, 13, 18, 0, 0)) as mock_timezone:
            self.streamlined_communication.time_sent = '21:00'
            self.streamlined_communication_autodebet.time_sent = '21:00'
            self.streamlined_communication.save()
            self.streamlined_communication_autodebet.save()

            send_manual_pn_for_unsent_moengage()
            self.assertFalse(mock_send_manual_pn.called)

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_send_for_unsent_normal(
        self, mock_manual_blast, mock_get_autodebet, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        mock_get_autodebet.return_value = None

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        mock_manual_blast.return_value.manual_blast_pn.assert_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_send_for_unsent_autodebet_check(
        self, mock_manual_blast, mock_get_autodebet, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        # is_use_autodebet = True & is_deleted_autodebet = False
        mock_get_autodebet.return_value = self.autodebet_account

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)

        mock_arguments = mock_manual_blast.return_value.manual_blast_pn.call_args
        mock_manual_blast.return_value.manual_blast_pn.assert_called()
        self.assertEqual(mock_arguments[0][2], self.streamlined_communication_autodebet)

        # is_use_autodebet = False & is_deleted_autodebet = False
        mock_manual_blast.reset_mock()
        self.autodebet_account.is_use_autodebet = False
        self.autodebet_account.save()
        mock_get_autodebet.return_value = self.autodebet_account

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)

        mock_arguments = mock_manual_blast.return_value.manual_blast_pn.call_args
        mock_manual_blast.return_value.manual_blast_pn.assert_called()
        self.assertEqual(mock_arguments[0][2], self.streamlined_communication)

        # is_use_autodebet = True & is_deleted_autodebet = True
        mock_manual_blast.reset_mock()
        self.autodebet_account.is_use_autodebet = True
        self.autodebet_account.is_deleted_autodebet = True
        self.autodebet_account.save()
        mock_get_autodebet.return_value = self.autodebet_account

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)

        mock_arguments = mock_manual_blast.return_value.manual_blast_pn.call_args
        mock_manual_blast.return_value.manual_blast_pn.assert_called()
        self.assertEqual(mock_arguments[0][2], self.streamlined_communication)

        # no autodebet_account
        mock_manual_blast.reset_mock()
        self.autodebet_account.delete()
        mock_get_autodebet.return_value = None

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)

        mock_arguments = mock_manual_blast.return_value.manual_blast_pn.call_args
        mock_manual_blast.return_value.manual_blast_pn.assert_called()
        self.assertEqual(mock_arguments[0][2], self.streamlined_communication)

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_send_normal_for_unsent_autodebet_exclude_dpd(
        self, mock_manual_blast, mock_get_autodebet, mock_experiment_group, mock_redis_client
    ):
        self.streamlined_communication.dpd = -6
        self.oldest_unpaid_account_payment.dpd = -6
        self.streamlined_communication.save()
        self.oldest_unpaid_account_payment.save()
        mock_get_autodebet.return_value = self.autodebet_account

        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)

        mock_arguments = mock_manual_blast.return_value.manual_blast_pn.call_args
        mock_manual_blast.return_value.manual_blast_pn.assert_called()
        self.assertEqual(mock_arguments[0][2], self.streamlined_communication)

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_dont_send_for_sent_moengage(
        self, mock_manual_blast, mock_get_autodebet, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        mock_get_autodebet.return_value = None
        pn_blast = PNBlastFactory(name=self.streamlined_communication.moengage_template_code)
        pn_delivery = PNDeliveryFactory(
            pn_blast=pn_blast, account_payment_id=self.account_payment.pk)
        PNTracksFactory(account_payment_id=self.account_payment.pk, pn_id=pn_delivery)

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        mock_manual_blast.return_value.manual_blast_pn.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_dont_send_for_autodebet_sent_moengage(
        self, mock_manual_blast, mock_get_autodebet, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        mock_get_autodebet.return_value = self.autodebet_account
        pn_blast = PNBlastFactory(name=self.streamlined_communication.moengage_template_code)
        pn_delivery = PNDeliveryFactory(
            pn_blast=pn_blast, account_payment_id=self.account_payment.pk)
        PNTracksFactory(account_payment_id=self.account_payment.pk, pn_id=pn_delivery)

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        mock_manual_blast.return_value.manual_blast_pn.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_dont_send_for_sent_inhouse(
        self, mock_manual_blast, mock_get_autodebet, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        mock_get_autodebet.return_value = None
        pn_blast = PNBlastFactory(name=self.streamlined_communication.template_code)
        pn_delivery = PNDeliveryFactory(
            pn_blast=pn_blast, account_payment_id=self.account_payment.pk)
        PNTracksFactory(account_payment_id=self.account_payment.pk, pn_id=pn_delivery)

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        mock_manual_blast.return_value.manual_blast_pn.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_dont_send_for_account_not_account_product(
        self, mock_manual_blast, mock_get_autodebet, mock_experiment_group, mock_redis_client
    ):
        random_account_lookup = AccountLookupFactory()
        self.account.account_lookup = random_account_lookup
        self.account.save()

        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        mock_manual_blast.return_value.manual_blast_pn.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_dont_send_for_unsent_paid(
        self, mock_manual_blast, mock_get_autodebet, mock_experiment_group, mock_redis_client
    ):
        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        self.mock_get_autodebet = None

        status_lookup = StatusLookupFactory(status_code=PaymentStatusCodes.PAID_ON_TIME)
        self.account_payment.status = status_lookup
        self.account_payment.save()

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        mock_manual_blast.return_value.manual_blast_pn.assert_not_called()

    @patch('juloserver.autodebet.services.account_services.get_existing_autodebet_account')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_dont_send_for_autodebet_template_dont_exist(
        self, mock_manual_blast, mock_get_autodebet
    ):
        mock_get_autodebet.return_value = self.autodebet_account
        self.streamlined_communication.template_code = 'j1_pn_autodebet_T-3_backup'
        self.streamlined_communication_autodebet.dpd = -3
        self.streamlined_communication.save()

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        mock_manual_blast.return_value.manual_blast_pn.assert_not_called()

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.tasks.get_julo_pn_client')
    def test_partial_error_backup_pn(self, mock_get_julo_pn_client, mock_experiment_group, mock_redis_client):
        for i in range(4):
            self._prepare_account_payment(dpd=-2)

        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        mock_julo_pn_client = MagicMock()
        mock_get_julo_pn_client.return_value = mock_julo_pn_client
        mock_julo_pn_client.manual_blast_pn.side_effect = [Exception(), None, None, None, None]

        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)

        self.assertEquals(5, mock_julo_pn_client.manual_blast_pn.call_count)

    @patch('juloserver.streamlined_communication.services.get_redis_client')
    @patch('juloserver.julo.tasks.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.julo.clients.pn.JuloPNClient')
    def test_send_manual_pn_for_unsent_moengage_sub_task_different_product(
        self, mock_manual_blast, mock_experiment_group, mock_redis_client
    ):
        for i in range(3):
            self._prepare_account_payment(dpd=-2, product='j1')
        for i in range(2):
            self._prepare_account_payment(dpd=-2, product='jturbo')

        mock_redis_client.return_value.get.return_value = None
        mock_experiment_group.return_value = ExperimentGroupFactory(
            experiment_setting=self.cashback_exp,
            account_id=self.account.id,
            group='experiment')

        # Expected result is 1+3 because of initial dataset in setUp()
        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        self.assertEquals(4, mock_manual_blast.return_value.manual_blast_pn.call_count)
        mock_manual_blast.reset_mock()

        self.streamlined_communication.update_safely(
            template_code='jturbo_pn_T-2_backup',
            moengage_template_code='jturbo_pn_T-2',
            product='jturbo',
        )
        send_manual_pn_for_unsent_moengage_sub_task(self.streamlined_communication.id)
        self.assertEquals(2, mock_manual_blast.return_value.manual_blast_pn.call_count)


class TestCalculateCountdown(TestCase):
    def test_countdown_result_accurate(self):
        result = calculate_countdown(
                18, 0, 0,
                timezone.localtime(timezone.now()).replace(
                        hour=12, minute=0, second=0))

        self.assertEqual(21600, result)

    def test_countdown_result_accurate_when_now_is_none(self):
        with patch.object(timezone, 'now', return_value=datetime(2022, 4, 28, 12, 0, 0)) as mock_now:
            result = calculate_countdown(18, 0, 0)
            expected_later = timezone.localtime(mock_now.return_value).replace(
                hour=18, minute=0)
            expected_now = timezone.localtime(mock_now.return_value)
            expected_result = int(py2round((expected_later - expected_now).total_seconds()))

            self.assertEqual(expected_result, result)


class TestScheduledRegenerateFreelanceAgentPassword(TestCase):
    @patch('juloserver.julo.tasks2.agent_tasks.get_julo_email_client')
    def setUp(self, mock_julo_email_client):
        mock_julo_email_client.return_value.send_email.return_value = (
            202, '', {'X-Message-Id': '14c5d75ce93.dfd.64b469.unittest0001.16648.5515E0B88.0'})

        self.agent = AuthUserFactory(email='test@julofinance.com', pk=9999)
        freelance_group = GroupFactory(name='freelance')
        self.agent.groups.add(freelance_group)

    @patch('juloserver.julo.tasks2.agent_tasks.send_password_email_for_collection.delay')
    @patch('juloserver.julo.tasks2.agent_tasks.send_password_email_for_operation.delay')
    def test_scheduled_regenerate_freelance_agent_password(self, mock_send_operation, mock_send_collection):
        scheduled_regenerate_freelance_agent_password()

        mock_send_collection.return_value = None
        mock_send_operation.return_value = None

        self.assertEqual(1, mock_send_collection.call_count)
        self.assertEqual(1, mock_send_operation.call_count)
        self.assertEqual([9999], list(mock_send_collection.call_args_list[0][0][0]))
        self.assertEqual([9999], list(mock_send_operation.call_args_list[0][0][0]))


class TestSendPasswordEmailForCollection(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.RECIPIENTS_BACKUP_PASSWORD,
            is_active=True,
            parameters={
                'collection': ['collection-lead@julofinance.com'],
                'operation': ['operation-lead@julofinance.com']
            }
        )

    @patch('juloserver.julo.tasks2.agent_tasks.generate_agent_password')
    @patch('juloserver.julo.tasks2.agent_tasks.get_julo_email_client')
    def test_agent_user_exist(self, mock_julo_email_client, mock_generate_agent_password):
        mock_generate_agent_password.return_value = 'password123'
        mock_julo_email_client.return_value.send_email.return_value = (
        202, '', {'X-Message-Id': '14c5d75ce93.dfd.64b469.unittest0001.16648.5515E0B88.0'})

        agent = AuthUserFactory(email='test@julofinance.com')
        freelance_group = GroupFactory(name='freelance')
        collection_group = GroupFactory(name='collection')
        agent.groups.add(freelance_group)
        agent.groups.add(collection_group)
        # Resetting call count due to signal adding to count when adding user to freelance group
        mock_julo_email_client.return_value.send_email.call_count = 0

        freelance_user_ids = [agent.pk]
        send_password_email_for_collection(freelance_user_ids)
        self.assertEqual(2, mock_julo_email_client.return_value.send_email.call_count)

    @patch('juloserver.julo.tasks2.agent_tasks.generate_agent_password')
    @patch('juloserver.julo.tasks2.agent_tasks.get_julo_email_client')
    def test_multiple_lead_user_exist(self, mock_julo_email_client, mock_generate_agent_password):
        mock_generate_agent_password.return_value = 'password123'
        mock_julo_email_client.return_value.send_email.return_value = (
            202, '', {'X-Message-Id': '14c5d75ce93.dfd.64b469.unittest0001.16648.5515E0B88.0'})
        self.feature_setting.parameters['collection'] = ['collection-lead@julofinance.com',
                                                         'collection-lead-two@julofinance.com']
        self.feature_setting.save()

        agent = AuthUserFactory(email='test@julofinance.com')
        freelance_group = GroupFactory(name='freelance')
        collection_group = GroupFactory(name='collection')
        agent.groups.add(freelance_group)
        agent.groups.add(collection_group)
        # Resetting call count due to signal adding to count when adding user to freelance group
        mock_julo_email_client.return_value.send_email.call_count = 0

        freelance_user_ids = [agent.pk]

        send_password_email_for_collection(freelance_user_ids)
        self.assertEqual(3, mock_julo_email_client.return_value.send_email.call_count)


class TestSendPasswordEmailForOperation(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.RECIPIENTS_BACKUP_PASSWORD,
            is_active=True,
            parameters={
                'collection': ['collection-lead@julofinance.com'],
                'operation': ['operation-lead@julofinance.com']
            }
        )

    @patch('juloserver.julo.tasks2.agent_tasks.generate_agent_password')
    @patch('juloserver.julo.tasks2.agent_tasks.get_julo_email_client')
    def test_agent_user_exist(self, mock_julo_email_client, mock_generate_agent_password):
        mock_generate_agent_password.return_value = 'password123'
        mock_julo_email_client.return_value.send_email.return_value = (
        202, '', {'X-Message-Id': '14c5d75ce93.dfd.64b469.unittest0001.16648.5515E0B88.0'})

        agent = AuthUserFactory(email='test@julofinance.com')
        freelance_group = GroupFactory(name='freelance')
        operation_group = GroupFactory(name='operation')
        agent.groups.add(freelance_group)
        agent.groups.add(operation_group)
        # Resetting call count due to signal adding to count when adding user to freelance group
        mock_julo_email_client.return_value.send_email.call_count = 0

        freelance_user_ids = [agent.pk]
        send_password_email_for_operation(freelance_user_ids)
        self.assertEqual(2, mock_julo_email_client.return_value.send_email.call_count)

    @patch('juloserver.julo.tasks2.agent_tasks.generate_agent_password')
    @patch('juloserver.julo.tasks2.agent_tasks.get_julo_email_client')
    def test_multiple_lead_user_exist(self, mock_julo_email_client, mock_generate_agent_password):
        mock_generate_agent_password.return_value = 'password123'
        mock_julo_email_client.return_value.send_email.return_value = (
            202, '', {'X-Message-Id': '14c5d75ce93.dfd.64b469.unittest0001.16648.5515E0B88.0'})
        self.feature_setting.parameters['operation'] = ['operation-lead@julofinance.com',
                                                         'operation-lead-two@julofinance.com']
        self.feature_setting.save()

        agent = AuthUserFactory(email='test@julofinance.com')
        freelance_group = GroupFactory(name='freelance')
        operation_group = GroupFactory(name='operation')
        agent.groups.add(freelance_group)
        agent.groups.add(operation_group)
        # Resetting call count due to signal adding to count when adding user to freelance group
        mock_julo_email_client.return_value.send_email.call_count = 0

        freelance_user_ids = [agent.pk]
        send_password_email_for_operation(freelance_user_ids)
        self.assertEqual(3, mock_julo_email_client.return_value.send_email.call_count)
