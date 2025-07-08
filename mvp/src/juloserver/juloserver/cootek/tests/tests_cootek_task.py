from builtins import str
from collections import OrderedDict

import mock
from mock import patch, MagicMock

from datetime import (
    time,
    timedelta,
    datetime,
)

from django.utils import timezone
from django.test.testcases import TestCase

from juloserver.julo.tests.factories import *
from juloserver.loan_refinancing.tests.factories import *
from juloserver.julo.models import CootekRobocall, ExperimentSetting
from juloserver.julo.constants import ExperimentConst
from .factories import *

from juloserver.cootek.tasks import (
    download_cootek_call_report_by_task_id,
    get_tasks_from_db_and_schedule_cootek,
    get_details_of_task_from_cootek,
    process_call_customer_via_cootek,
    task_to_send_data_customer_to_cootek,
    upload_partial_cootek_data_to_intelix,
    upload_partial_cootek_data_to_intelix_t0_00_33,
    upload_partial_cootek_data_to_intelix_t0_34_66,
    upload_partial_cootek_data_to_intelix_t0_67_99,
    upload_partial_cootek_data_to_intelix_tminus1_67_90,
    upload_partial_cootek_data_to_intelix_tminus2_67_99,
    upload_julo_t0_cootek_data_to_intelix,
    upload_julo_t0_cootek_data_to_centerix,
    trigger_experiment_cootek_config,
    upload_jturbo_t0_cootek_data_to_intelix,
)
from juloserver.account.tests.factories import AccountwithApplicationFactory, AccountFactory
from juloserver.account_payment.tests.factories import (
    AccountPaymentwithPaymentFactory,
    AccountPaymentFactory
)
from juloserver.julo.tests.factories import AuthUserFactory, CustomerFactory, CootekRobocallFactory
from juloserver.cootek.constants import CootekAIRobocall
from juloserver.minisquad.constants import DialerTaskStatus, DialerTaskType
from juloserver.minisquad.models import DialerTask, DialerTaskEvent
from juloserver.streamlined_communication.exceptions import PaymentReminderReachTimeLimit
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.account.models import Account
from juloserver.minisquad.constants import FeatureNameConst as MiniSquadFeatureSettingConst
from juloserver.julo.exceptions import JuloException


class TestGetTasksFromDbAndScheduleCootek(TestCase):
    def setUp(self):
        CootekRobotFactory()

    @patch('juloserver.cootek.tasks.get_details_of_task_from_cootek')
    @patch('juloserver.cootek.tasks.task_to_send_data_customer_to_cootek')
    def test_get_tasks_from_db_and_schedule_cootek(
        self, mock_task_to_send_data_customer_to_cootek, mock_get_details_of_task_from_cootek
    ):
        cootek_config_1st = CootekConfigurationFactory(
            task_type='test',
            time_to_start=datetime.strptime("10:00:01", "%H:%M:%S").time()
        )
        cootek_config_2nd = CootekConfigurationFactory(
            task_type='test',
            time_to_start=datetime.strptime("10:00:02", "%H:%M:%S").time()
        )
        cootek_config_bl = CootekConfigurationFactory(
            partner=PartnerFactory(name='bukalapak_paylater'),
            task_type='test2'
        )
        cootek_config_refinancing = CootekConfigurationFactory(
            task_type='test3',
            criteria='Refinancing_Pending',
            dpd_condition=None,
            called_at=None,
            called_to=None
        )
        get_tasks_from_db_and_schedule_cootek()
        cootek_config_1st.refresh_from_db()
        cootek_config_2nd.refresh_from_db()
        cootek_config_bl.refresh_from_db()
        cootek_config_refinancing.refresh_from_db()
        mock_task_to_send_data_customer_to_cootek.apply_async.assert_called()
        mock_get_details_of_task_from_cootek.apply_async.assert_called()
        assert not cootek_config_1st.from_previous_cootek_result
        assert not cootek_config_bl.from_previous_cootek_result
        assert not cootek_config_refinancing.from_previous_cootek_result
        assert cootek_config_2nd.from_previous_cootek_result

    @patch('juloserver.cootek.tasks.is_holiday')
    @patch('juloserver.cootek.tasks.logger')
    @patch('juloserver.cootek.tasks.task_to_send_data_customer_to_cootek.apply_async')
    @patch('juloserver.cootek.tasks.get_details_of_task_from_cootek.apply_async')
    def test_get_tasks_from_db_and_schedule_cootek_is_holiday(
        self, mock_cootek_get_task, mock_cootek_send_task, mock_logger, mock_is_holiday
    ):
        CootekConfigurationFactory(
            task_type='JULO_T0_J1',
            product='J1',
            dpd_condition='Exactly',
            called_at=0,
            called_to=None,
            is_active=True
        )
        mock_is_holiday.return_value = True

        get_tasks_from_db_and_schedule_cootek()
        mock_logger.info.assert_called_once_with({
                'action': 'get_tasks_from_db_and_schedule_cootek',
                'is_holiday': True,
                'message': 'Cootek configuration skipped due to holiday.'
            })
        mock_cootek_send_task.assert_not_called()
        mock_cootek_get_task.assert_not_called()


class TestCootekTasks(TestCase):

    def mock_get_list(self, param):
        if param == 'minisquad:oldest_payment_ids':
            return [self.payment.id]
        return []

    def setUp(self):
        self.today = datetime.now()
        self.loan = LoanFactory(is_ignore_calls=False)
        self.loan.loan_status_id = 230
        self.loan.save()
        self.payment = PaymentFactory(
            loan=self.loan,
            is_collection_called=False,
            ptp_date=None,
            is_whatsapp=False,
        )
        self.payment.payment_status_id = 320
        self.payment.save()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountwithApplicationFactory(customer=self.customer)
        self.account_payment = AccountPaymentwithPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.user = self.loan.customer.user
        self.application = self.loan.application
        self.loan_refinancing_request = LoanRefinancingRequestFactory(
            loan=self.loan, status='Approved')
        self.loan_refinancing_offer = LoanRefinancingOfferFactory(
            loan_refinancing_request=self.loan_refinancing_request,
            is_accepted=True,
            offer_accepted_ts=(timezone.localtime(timezone.now()) - timedelta(4))
        )
        CootekRobotFactory()
        self.cootek_config_1st = CootekConfigurationFactory(
            task_type='test',
            time_to_start=datetime.strptime("10:00:01", "%H:%M:%S").time(),
            time_to_end=datetime.strptime("12:00:01", "%H:%M:%S").time()
        )

        self.cootek_config_2nd = CootekConfigurationFactory(
            task_type='test',
            time_to_start=datetime.strptime("10:00:02", "%H:%M:%S").time(),
            time_to_end=datetime.strptime("12:00:02", "%H:%M:%S").time()
        )

        self.cootek_config_bl = CootekConfigurationFactory(
            partner=PartnerFactory(name='bukalapak_paylater'),
            task_type='test2')

        self.cootek_config_refinancing = CootekConfigurationFactory(
            task_type='test3',
            criteria='Refinancing_Pending',
            dpd_condition=None,
            called_at=None,
            called_to=None)
        self.cootek_config_j1 = CootekConfigurationFactory(
            task_type='test4',
            product='J1',
            dpd_condition=None,
            called_at=None,
            called_to=None)
        self.statement = StatementFactory(
            statement_due_date=timezone.localtime(timezone.now()) - timedelta(5))
        self.statement.statement_status_id = 100
        self.statement.save()

    @patch('juloserver.cootek.services.filtering_cashback_new_scheme_experiment_for_cootek')
    @patch('juloserver.streamlined_communication.utils.check_payment_reminder_time_limit')
    @patch('juloserver.cootek.services.check_payment_is_blocked_comms')
    @patch('juloserver.cootek.services.get_julo_cootek_client')
    @patch('juloserver.cootek.services.get_redis_client')
    @patch('juloserver.cootek.services.check_cootek_experiment')
    def test_task_to_send_data_customer_to_cootek_payment(
            self, mock_check_cootek_experiment,
            mock_get_redis_client,
            mock_get_julo_cootek_client, mock_check_payment_is_blocked_comms, mock_cashback_experiment, *args):
        self.payment.due_date = timezone.localtime(timezone.now()) - timedelta(5)
        self.payment.save()

        mock_get_redis_client.return_value.get_list.side_effect = self.mock_get_list
        mock_get_julo_cootek_client.return_value.create_task.return_value = 5
        mock_get_julo_cootek_client.return_value.get_task_details.return_value = {
            'TaskID': 5,
            'Status': 'pending',
            'detail': [{
                'Comments': self.payment.id,
                'RingType': 'test',
                'Intention': 'test',
                'HangupType': 'test',
                'CallEndTime': '2020-01-17 16:00:00',
                'CallStartTime': '2020-01-17 16:30:00',
                'Status': 'pending',
                'RobotID': '3f53ac78e7fea695a164f55a6ff4de21',
                'Multi_intention': '{}',
            }]
        }
        mock_cashback_experiment.return_value = None
        self.cootek_config_1st.exclude_risky_customer = True
        self.cootek_config_1st.product = 'stl'
        self.cootek_config_1st.save()

        self.application.update_safely(
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.STL1)
        )
        cootek_experiment = MagicMock()
        cootek_experiment.criteria = {
            'dpd': [1, 0, -1, 5],
            "loan_id": "#last:1:0,1,2,3,4,5,6,7,8,9"}
        mock_check_cootek_experiment.return_value = cootek_experiment
        now = timezone.localtime(timezone.now())
        start_time = self.cootek_config_1st.time_to_start
        start_time = str(start_time)
        start_time = str(now.date()) + ' ' + start_time
        start_time = datetime.strptime(start_time, "%Y-%m-%d %X")
        end_time = datetime.strptime(
            str(now.date()) + ' ' + str(self.cootek_config_1st.time_to_end), "%Y-%m-%d %X")
        mock_check_payment_is_blocked_comms.return_value = False
        task_to_send_data_customer_to_cootek(
            self.cootek_config_1st.id, start_time, end_time=end_time)
        assert CootekRobocall.objects.get(task_id=5, task_type='test')
        get_details_of_task_from_cootek(
            **{'cootek_record_id': self.cootek_config_1st.id, 'start_time': start_time})

    @patch('juloserver.streamlined_communication.utils.check_payment_reminder_time_limit')
    @patch('juloserver.cootek.services.get_julo_cootek_client')
    @patch('juloserver.cootek.services.check_cootek_experiment')
    def test_task_to_send_data_customer_to_cootek_case_loan_refinancing(
            self, mock_check_cootek_experiment,
            mock_get_julo_cootek_client, *args):
        mock_get_julo_cootek_client.return_value.create_task.return_value = 6
        mock_get_julo_cootek_client.return_value.get_task_details.return_value = {
            'TaskID': 6,
            'Status': 'pending',
            'detail': [{
                'Comments': self.loan_refinancing_offer.id,
                'RingType': 'test',
                'Intention': 'test',
                'HangupType': 'test',
                'CallEndTime': '2020-01-17 16:00:00',
                'CallStartTime': '2020-01-17 16:30:00',
                'Status': 'pending'
            }]
        }

        cootek_experiment = MagicMock()
        cootek_experiment.criteria = {
            'dpd': [1, 0, -1, 5],
            "loan_id": "#last:1:0,1,2,3,4,5,6,7,8,9"}
        mock_check_cootek_experiment.return_value = cootek_experiment
        now = timezone.localtime(timezone.now())
        start_time = self.cootek_config_refinancing.time_to_start
        start_time = str(start_time)
        start_time = str(now.date()) + ' ' + start_time
        start_time = datetime.strptime(start_time, "%Y-%m-%d %X")
        task_to_send_data_customer_to_cootek(self.cootek_config_refinancing.id, start_time)
        assert CootekRobocall.objects.get(task_id=6, task_type='test3')
        get_details_of_task_from_cootek(
            **{'cootek_record_id': self.cootek_config_1st.id, 'start_time': start_time})

    @patch('juloserver.streamlined_communication.utils.check_payment_reminder_time_limit')
    @patch('juloserver.cootek.services.get_julo_cootek_client')
    @patch('juloserver.cootek.services.get_redis_client')
    @patch('juloserver.cootek.services.check_cootek_experiment')
    def test_task_to_send_data_customer_to_cootek_bl(
            self, mock_check_cootek_experiment,
            mock_get_redis_client,
            mock_get_julo_cootek_client, *args):
        self.payment.due_date = timezone.localtime(timezone.now()) - timedelta(5)
        self.payment.save()

        mock_get_redis_client.return_value.get_list.side_effect = self.mock_get_list
        mock_get_julo_cootek_client.return_value.create_task.return_value = 7
        mock_get_julo_cootek_client.return_value.get_task_details.return_value = {
            'TaskID': 7,
            'Status': 'pending',
            'detail': [{
                'Comments': self.statement.id,
                'RingType': 'test',
                'Intention': 'test',
                'HangupType': 'test',
                'CallEndTime': '2020-01-17 16:00:00',
                'CallStartTime': '2020-01-17 16:30:00',
                'Status': 'pending'
            }]
        }
        cootek_experiment = MagicMock()
        cootek_experiment.criteria = {
            'dpd': [1, 0, -1, 7],
            "loan_id": "#last:1:0,1,2,3,4,5,6,7,8,9"}
        mock_check_cootek_experiment.return_value = cootek_experiment
        now = timezone.localtime(timezone.now())
        start_time = self.cootek_config_bl.time_to_start
        start_time = str(start_time)
        start_time = str(now.date()) + ' ' + start_time
        start_time = datetime.strptime(start_time, "%Y-%m-%d %X")
        task_to_send_data_customer_to_cootek(self.cootek_config_bl.id, start_time)
        assert CootekRobocall.objects.get(task_id=7, task_type=self.cootek_config_bl.task_type)
        get_details_of_task_from_cootek(
            **{'cootek_record_id': self.cootek_config_1st.id, 'start_time': start_time})

    @patch('juloserver.cootek.tasks.create_history_dialer_task_event')
    def test_upload_partial_cootek_data_to_intelix_no_setting(
            self, mock_create_history_dialer_task_event):

        upload_partial_cootek_data_to_intelix(0, 'abc', [])
        assert not mock_create_history_dialer_task_event.called

    @patch('juloserver.cootek.tasks.record_intelix_log')
    @patch('juloserver.cootek.tasks.get_julo_intelix_client')
    @patch('juloserver.cootek.tasks.construct_data_for_intelix')
    @patch('juloserver.cootek.tasks.create_history_dialer_task_event')
    def test_upload_partial_cootek_data_to_intelix(
            self,
            mock_get_julo_intelix_client,
            mock_construct_data_for_intelix,
            mock_create_history_dialer_task_event,
            mock_record_intelix_log):
        today = datetime.now().date()
        ExperimentSetting.objects.create(
            code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
            is_active=True,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            criteria=''
        )

        mock_get_julo_intelix_client.return_value.upload_to_queue.return_value = {
            'result': 'success',
            'rec_num': 1
        }

        upload_partial_cootek_data_to_intelix(0, 'abc', [1])
        assert mock_create_history_dialer_task_event.called
        assert mock_construct_data_for_intelix.called
        assert not mock_record_intelix_log.called


    @patch('juloserver.cootek.tasks.record_intelix_log')
    @patch('juloserver.cootek.tasks.get_julo_intelix_client')
    @patch('juloserver.cootek.tasks.construct_data_for_intelix')
    @patch('juloserver.cootek.tasks.create_history_dialer_task_event')
    def test_upload_partial_cootek_data_to_intelix_dpd0(
            self, mock_create_history_dialer_task_event,
            mock_construct_data_for_intelix,
            mock_get_julo_intelix_client,
            mock_record_intelix_log):
        today = datetime.now().date()
        ExperimentSetting.objects.create(
            code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
            is_active=True,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            criteria=''
        )
        mock_get_julo_intelix_client.return_value.upload_to_queue.return_value = {
            'result': 'success',
            'rec_num': 1
        }

        upload_partial_cootek_data_to_intelix(0, 'L34-L66', [1])
        assert mock_create_history_dialer_task_event.called
        assert mock_construct_data_for_intelix.called
        assert mock_record_intelix_log.called

    def test_trigger_experiment_cootek_config_enable(self):
        cootek_normal = CootekConfigurationFactory(
            task_type='enable_test2',
            product='mtl'
        )
        cootek_experiment = CootekConfigurationFactory(
            task_type='enable_test3',
            product='mtl',
            strategy_name='EXPERIMENT_test2'
        )
        cootek_special = CootekConfigurationFactory(
            task_type='enable_test2_L34-L66',
            product='mtl',
            strategy_name='EXPERIMENT_test2',
            called_at=0,
        )
        trigger_experiment_cootek_config(disable=False)
        cootek_normal.refresh_from_db()
        cootek_experiment.refresh_from_db()
        cootek_special.refresh_from_db()
        assert not cootek_normal.is_active
        assert cootek_experiment.is_active
        assert not cootek_special.is_active

    def test_trigger_experiment_cootek_config_disable(self):
        cootek_normal = CootekConfigurationFactory(
            task_type='disable_test2',
            product='mtl'
        )
        cootek_experiment = CootekConfigurationFactory(
            task_type='disable_test3',
            product='mtl',
            strategy_name='EXPERIMENT_test2'
        )
        cootek_special = CootekConfigurationFactory(
            task_type='disable_test2_L34-L66',
            product='mtl',
            strategy_name='EXPERIMENT_test2',
            called_at=0,
        )
        trigger_experiment_cootek_config(disable=True)
        cootek_normal.refresh_from_db()
        cootek_experiment.refresh_from_db()
        cootek_special.refresh_from_db()
        assert cootek_normal.is_active
        assert not cootek_experiment.is_active
        assert not cootek_special.is_active

    @patch('juloserver.streamlined_communication.utils.check_payment_reminder_time_limit')
    @patch('juloserver.cootek.services.check_account_payment_is_blocked_comms')
    @patch('juloserver.cootek.services.get_julo_cootek_client')
    @patch('juloserver.cootek.services.get_redis_client')
    @patch('juloserver.cootek.services.check_cootek_experiment')
    def test_task_to_send_data_customer_to_cootek_j1(
        self,
        mock_check_cootek_experiment,
        mock_get_redis_client,
        mock_get_julo_cootek_client,
        mock_check_account_payment_is_blocked_comms,
        *args
    ):
        self.account_payment.due_date = timezone.localtime(timezone.now()) - timedelta(8)
        self.account_payment.save()

        mock_get_redis_client.return_value.get_list.side_effect = self.mock_get_list
        mock_get_julo_cootek_client.return_value.create_task.return_value = 8
        mock_get_julo_cootek_client.return_value.get_task_details.return_value = {
            'TaskID': 8,
            'Status': 'pending',
            'detail': [{
                'Comments': self.account_payment.id,
                'RingType': 'test',
                'Intention': 'test',
                'HangupType': 'test',
                'CallEndTime': '2020-01-17 16:00:00',
                'CallStartTime': '2020-01-17 16:30:00',
                'Status': 'pending'
            }]
        }
        self.cootek_config_j1.exclude_risky_customer = False
        self.cootek_config_j1.from_previous_cootek_result = False
        self.cootek_config_j1.save()
        cootek_experiment = MagicMock()
        cootek_experiment.criteria = {
            'dpd': [1, 0, -1, 8],
            "loan_id": "#last:1:0,1,2,3,4,5,6,7,8,9"}
        mock_check_cootek_experiment.return_value = cootek_experiment
        now = timezone.localtime(timezone.now())
        start_time = self.cootek_config_j1.time_to_start
        start_time = str(start_time)
        start_time = str(now.date()) + ' ' + start_time
        start_time = datetime.strptime(start_time, "%Y-%m-%d %X")
        mock_check_account_payment_is_blocked_comms.return_value = False
        task_to_send_data_customer_to_cootek(self.cootek_config_j1.id, start_time)
        get_details_of_task_from_cootek(
            **{'cootek_record_id': self.cootek_config_1st.id, 'start_time': start_time})

    @patch('juloserver.cootek.tasks.get_payment_details_cootek_for_intelix')
    @patch('juloserver.cootek.tasks.record_intelix_log')
    @patch('juloserver.cootek.tasks.get_julo_intelix_client')
    @patch('juloserver.cootek.tasks.construct_data_for_intelix')
    @patch('juloserver.cootek.tasks.create_history_dialer_task_event')
    def test_upload_partial_cootek_data_to_intelix_t0_00_33(
            self,
            mock_get_julo_intelix_client,
            mock_construct_data_for_intelix,
            mock_create_history_dialer_task_event,
            mock_record_intelix_log,
            mock_payments):
        today = datetime.now().date()
        ExperimentSetting.objects.create(
            code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
            is_active=True,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            criteria=''
        )

        mock_get_julo_intelix_client.return_value.upload_to_queue.return_value = {
            'result': 'success',
            'rec_num': 1
        }
        mock_payments.return_value = [1]

        upload_partial_cootek_data_to_intelix_t0_00_33()
        assert mock_create_history_dialer_task_event.called
        assert mock_construct_data_for_intelix.called
        assert not mock_record_intelix_log.called

    @patch('juloserver.cootek.tasks.get_payment_details_for_intelix')
    @patch('juloserver.cootek.tasks.record_intelix_log')
    @patch('juloserver.cootek.tasks.get_julo_intelix_client')
    @patch('juloserver.cootek.tasks.construct_data_for_intelix')
    @patch('juloserver.cootek.tasks.create_history_dialer_task_event')
    def test_upload_partial_cootek_data_to_intelix_t0_34_66(
            self,
            mock_get_julo_intelix_client,
            mock_construct_data_for_intelix,
            mock_create_history_dialer_task_event,
            mock_record_intelix_log,
            mock_payments):
        today = datetime.now().date()
        ExperimentSetting.objects.create(
            code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
            is_active=True,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            criteria=''
        )

        mock_get_julo_intelix_client.return_value.upload_to_queue.return_value = {
            'result': 'success',
            'rec_num': 1
        }
        mock_payments.return_value = [1]

        upload_partial_cootek_data_to_intelix_t0_34_66()
        assert mock_create_history_dialer_task_event.called
        assert mock_construct_data_for_intelix.called
        assert not mock_record_intelix_log.called

    @patch('juloserver.cootek.tasks.get_payment_details_cootek_for_intelix')
    @patch('juloserver.cootek.tasks.record_intelix_log')
    @patch('juloserver.cootek.tasks.get_julo_intelix_client')
    @patch('juloserver.cootek.tasks.construct_data_for_intelix')
    @patch('juloserver.cootek.tasks.create_history_dialer_task_event')
    def test_upload_partial_cootek_data_to_intelix_t0_67_99(
            self,
            mock_get_julo_intelix_client,
            mock_construct_data_for_intelix,
            mock_create_history_dialer_task_event,
            mock_record_intelix_log,
            mock_payments):
        today = datetime.now().date()
        ExperimentSetting.objects.create(
            code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
            is_active=True,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            criteria=''
        )

        mock_get_julo_intelix_client.return_value.upload_to_queue.return_value = {
            'result': 'success',
            'rec_num': 1
        }
        mock_payments.return_value = [1]

        upload_partial_cootek_data_to_intelix_t0_67_99()
        assert mock_create_history_dialer_task_event.called
        assert mock_construct_data_for_intelix.called
        assert not mock_record_intelix_log.called

    @patch('juloserver.cootek.tasks.get_payment_details_cootek_for_intelix')
    @patch('juloserver.cootek.tasks.record_intelix_log')
    @patch('juloserver.cootek.tasks.get_julo_intelix_client')
    @patch('juloserver.cootek.tasks.construct_data_for_intelix')
    @patch('juloserver.cootek.tasks.create_history_dialer_task_event')
    def test_upload_partial_cootek_data_to_intelix_tminus1_67_90(
            self,
            mock_get_julo_intelix_client,
            mock_construct_data_for_intelix,
            mock_create_history_dialer_task_event,
            mock_record_intelix_log,
            mock_payments):
        today = datetime.now().date()
        ExperimentSetting.objects.create(
            code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
            is_active=True,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            criteria=''
        )

        mock_get_julo_intelix_client.return_value.upload_to_queue.return_value = {
            'result': 'success',
            'rec_num': 1
        }
        mock_payments.return_value = [1]

        upload_partial_cootek_data_to_intelix_tminus1_67_90()
        assert mock_create_history_dialer_task_event.called
        assert mock_construct_data_for_intelix.called
        assert not mock_record_intelix_log.called

    @patch('juloserver.cootek.tasks.get_payment_details_cootek_for_intelix')
    @patch('juloserver.cootek.tasks.record_intelix_log')
    @patch('juloserver.cootek.tasks.get_julo_intelix_client')
    @patch('juloserver.cootek.tasks.construct_data_for_intelix')
    @patch('juloserver.cootek.tasks.create_history_dialer_task_event')
    def test_upload_partial_cootek_data_to_intelix_tminus2_67_99(
            self,
            mock_get_julo_intelix_client,
            mock_construct_data_for_intelix,
            mock_create_history_dialer_task_event,
            mock_record_intelix_log,
            mock_payments):
        today = datetime.now().date()
        ExperimentSetting.objects.create(
            code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
            is_active=True,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            criteria=''
        )

        mock_get_julo_intelix_client.return_value.upload_to_queue.return_value = {
            'result': 'success',
            'rec_num': 1
        }
        mock_payments.return_value = [1]

        upload_partial_cootek_data_to_intelix_tminus2_67_99()
        assert mock_create_history_dialer_task_event.called
        assert mock_construct_data_for_intelix.called
        assert not mock_record_intelix_log.called

    @mock.patch('juloserver.cootek.services.construct_data_for_intelix')
    @mock.patch('juloserver.cootek.services.set_redis_data_temp_table')
    @mock.patch('juloserver.cootek.services.record_not_sent_to_intelix_task')
    @mock.patch('juloserver.cootek.services.set_redis_data_temp_table')
    @mock.patch('juloserver.cootek.services.send_data_to_intelix_with_retries_mechanism')
    def test_upload_julo_t0_cootek_data_to_intelix(
        self, mock_send_data, mock_set_redis, mock_record_not_sent, mock_set_redis2, mock_construct
    ):
        today = timezone.localtime(timezone.now())
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts)
        )
        account_autodebet = Account.objects.get_or_none(id=accounts[0].id)
        ApplicationFactory(account=account_autodebet)
        AutodebetAccountFactory(
            account = account_autodebet,
            vendor = "BCA",
            is_use_autodebet = True,
            is_deleted_autodebet = False
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
            parameters={
                "dpd_zero": True,
            },
            is_active=True
        )
        FeatureSettingFactory(
            feature_name=MiniSquadFeatureSettingConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            parameters={
                "JULO_T0": 2,
            },
            is_active=True
        )
        CootekRobocallFactory.create_batch(
            10,
            called_at=0,
            cdate=today,
            account_payment=Iterator(account_payments),
            intention=Iterator(['B', 'E', 'F', 'G', 'H', 'I']),
            call_status='finished'
        )
        mock_construct.return_value = True
        mock_set_redis.return_value = True
        mock_record_not_sent.return_value = None
        mock_set_redis2.return_value = True
        upload_julo_t0_cootek_data_to_intelix.delay()
        mock_send_data.si.assert_called()
        dialer_task = DialerTask.objects.filter(status=DialerTaskStatus.STORED)
        split_count = DialerTaskEvent.objects.get(status=DialerTaskStatus.BATCHING_PROCESSED)
        self.assertEqual(len(dialer_task), 1)
        self.assertEqual(split_count.data_count, 5)

    @mock.patch('juloserver.cootek.services.construct_data_for_intelix')
    @mock.patch('juloserver.cootek.services.set_redis_data_temp_table')
    @mock.patch('juloserver.cootek.services.record_not_sent_to_intelix_task')
    @mock.patch('juloserver.cootek.services.set_redis_data_temp_table')
    @mock.patch('juloserver.cootek.services.send_data_to_intelix_with_retries_mechanism')
    def test_upload_jturbo_t0_cootek_data_to_intelix(
        self, mock_send_data, mock_set_redis, mock_record_not_sent, mock_set_redis2, mock_construct
    ):
        today = timezone.localtime(timezone.now())
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts)
        )
        account_autodebet = Account.objects.get_or_none(id=accounts[0].id)
        ApplicationFactory(account=account_autodebet)
        AutodebetAccountFactory(
            account = account_autodebet,
            vendor = "BCA",
            is_use_autodebet = True,
            is_deleted_autodebet = False
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
            parameters={
                "dpd_zero": True,
            },
            is_active=True
        )
        FeatureSettingFactory(
            feature_name=MiniSquadFeatureSettingConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            parameters={
                'JTURBO_T0': 2,
            },
            is_active=True
        )
        CootekRobocallFactory.create_batch(
            10,
            called_at=0,
            cdate=today,
            account_payment=Iterator(account_payments),
            intention=Iterator(['B', 'E', 'F', 'G', 'H', 'I']),
            call_status='finished'
        )
        mock_construct.return_value = True
        mock_set_redis.return_value = True
        mock_record_not_sent.return_value = None
        mock_set_redis2.return_value = True
        upload_jturbo_t0_cootek_data_to_intelix.delay()
        mock_send_data.si.assert_called()
        dialer_task = DialerTask.objects.filter(status=DialerTaskStatus.STORED)
        split_count = DialerTaskEvent.objects.get(status=DialerTaskStatus.BATCHING_PROCESSED)
        self.assertEqual(len(dialer_task), 1)
        self.assertEqual(split_count.data_count, 5)

    @patch('juloserver.cootek.tasks.upload_partial_cootek_data_to_intelix_t0_34_66')
    @patch('juloserver.cootek.tasks.get_payment_details_cootek_for_intelix')
    def test_upload_partial_cootek_data_to_intelix_t0_00_33_case_1(
            self,
            mock_payments,
            mock_task):
        mock_payments.return_value = []

        upload_partial_cootek_data_to_intelix_t0_00_33()
        assert not mock_task.called

    @patch('juloserver.cootek.tasks.upload_partial_cootek_data_to_intelix_t0_67_99')
    @patch('juloserver.cootek.tasks.get_payment_details_for_intelix')
    def test_upload_partial_cootek_data_to_intelix_t0_34_66_case_1(
            self,
            mock_payments,
            mock_task):
        mock_payments.return_value = []

        upload_partial_cootek_data_to_intelix_t0_34_66()
        assert not mock_task.called

    @patch('juloserver.cootek.tasks.upload_partial_cootek_data_to_intelix_t0_67_99')
    @patch('juloserver.cootek.tasks.get_payment_details_cootek_for_intelix')
    def test_upload_partial_cootek_data_to_intelix_t0_67_99_case_1(
            self,
            mock_payments,
            mock_task):
        mock_payments.return_value = []

        upload_partial_cootek_data_to_intelix_t0_67_99()
        assert not mock_task.called

    @patch('juloserver.cootek.tasks.upload_partial_cootek_data_to_intelix_t0_67_99')
    @patch('juloserver.cootek.tasks.get_payment_details_cootek_for_intelix')
    def test_upload_partial_cootek_data_to_intelix_tminus1_67_90_case_1(
            self,
            mock_payments,
            mock_task):
        mock_payments.return_value = []

        upload_partial_cootek_data_to_intelix_tminus1_67_90()
        assert not mock_task.called

    @patch('juloserver.cootek.tasks.upload_payment_details')
    @patch('juloserver.cootek.tasks.get_payment_details_cootek_for_centerix')
    def test_upload_julo_t0_cootek_data_to_centerix(
            self,
            mock_payments,
            mock_upload_payment_details):
        mock_payments.return_value = [1]

        upload_julo_t0_cootek_data_to_centerix()
        assert mock_upload_payment_details.called

    @mock.patch('juloserver.cootek.tasks.construct_data_for_intelix')
    @mock.patch('juloserver.cootek.tasks.get_payment_details_cootek_for_intelix')
    @mock.patch('juloserver.cootek.tasks.get_julo_intelix_client')
    def test_upload_julo_t0_cootek_data_to_intelix_case_1(self, mock_intelix_client, mocked_payment, mock_data):
        mocked_payment.return_value = [1], []
        today = datetime.now().date()
        ExperimentSetting.objects.create(
            code=ExperimentConst.COOTEK_REVERSE_EXPERIMENT,
            is_active=True,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=1),
            criteria=''
        )
        mock_data.return_value = {'payment_id': 123445}
        mock_intelix_client.return_value.upload_to_queue.return_value = 200
        upload_julo_t0_cootek_data_to_intelix.delay()
        assert not mocked_payment.called


@patch('juloserver.cootek.tasks.download_cootek_call_report_by_task_id')
@patch('juloserver.cootek.tasks.get_julo_cootek_client')
class TestProcessCallCustomerViaCootek(TestCase):
    def setUp(self):
        self.mock_cootek_client = MagicMock()
        self.product_line = ProductLineFactory(
            product_line_code="123456",
            product_line_type="TProduct",
        )
        self.customer = CustomerFactory(
            fullname='customer fullname',
            gender='Pria',
            phone="085212345678",
            product_line=self.product_line,
        )
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationJ1Factory(account=self.account, customer=self.customer)
        self.account_payment = AccountPaymentwithPaymentFactory(
            account=self.account, due_amount=123000, due_date="2024-02-01"
        )
        self.loan = self.account_payment.payment_set.order_by('cdate').last().loan
        self.request_data = OrderedDict(
            [
                (
                    "customers",
                    [
                        OrderedDict(
                            [
                                ("customer_id", str(self.customer.id)),
                                ("current_account_payment_id", str(self.account_payment.id)),
                            ]
                        ),
                    ],
                ),
                (
                    "campaign_data",
                    OrderedDict([("campaign_name", "test campaign"), ("campaign_id", "12345")]),
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
                            ("intention_list", []),
                            ("is_group_method", False),
                        ]
                    ),
                ),
            ]
        )

    @patch.object(timezone, 'now')
    @patch('juloserver.cootek.tasks.secrets')
    def test_success_no_intention(
        self,
        mock_secrets,
        mock_now,
        mock_get_cootek_client,
        mock_download_cootek_call_report_by_task_id,
    ):
        mock_secrets.token_hex.return_value = "secret-token"
        mock_now.return_value = datetime(2024, 2, 1, 9, 00)
        mock_get_cootek_client.return_value = self.mock_cootek_client
        mock_download_cootek_call_report_by_task_id.apply_async.return_value = MagicMock(id=10)
        self.mock_cootek_client.create_task.return_value = 321
        ret_val = process_call_customer_via_cootek("test", self.request_data)
        self.assertEqual(ret_val, 321)

        cootek_robot = CootekRobot.objects.filter(robot_identifier="54321").first()
        self.mock_cootek_client.create_task.assert_called_once_with(
            task_name="dev|test|12345|secret-token|test-task",
            start_time=timezone.localtime(datetime(2024, 2, 1, 13, 11)),
            end_time=timezone.localtime(datetime(2024, 2, 1, 15, 13)),
            robot=cootek_robot,
            attempts=3,
            task_details=[
                {
                    'Debtor': "customer fullname",
                    'Mobile': "+6285212345678",
                    'DueDate': "2024-02-01",
                    'LoanDate': self.loan.cdate.strftime("%Y-%m-%d"),
                    'LoanAmount': self.loan.loan_amount,
                    'Arrears': 123000,
                    'Unit': CootekAIRobocall.UNIT_RUPIAH,
                    'Platform': CootekAIRobocall.PLATFORM_JULO,
                    'Comments': str(self.account_payment.id),
                    'Gender': "male",
                    'ExtraA': 0,
                }
            ],
        )
        cootek_robocall = CootekRobocall.objects.filter(
            account_payment_id=self.account_payment.id
        ).last()
        self.assertIsNotNone(cootek_robocall)
        self.assertEqual("TProduct", cootek_robocall.product)
        self.assertEqual(123000, cootek_robocall.arrears)
        self.assertEqual(cootek_robot.id, cootek_robocall.cootek_robot_id)
        self.assertEqual(
            "dev|test|12345|secret-token|test-task", cootek_robocall.campaign_or_strategy
        )
        self.assertEqual("test-task", cootek_robocall.task_type)
        self.assertEqual("test", cootek_robocall.cootek_event_type)
        mock_download_cootek_call_report_by_task_id.apply_async.assert_called_once_with(
            (321, "dev|test|12345|secret-token|test-task"), countdown=22980.0
        )

    @patch.object(timezone, 'now')
    @patch('juloserver.cootek.tasks.secrets')
    def test_no_customer(
        self,
        mock_secrets,
        mock_now,
        mock_get_cootek_client,
        mock_download_cootek_call_report_by_task_id,
    ):
        mock_now.return_value = datetime(2024, 2, 1, 9, 00)
        mock_get_cootek_client.return_value = self.mock_cootek_client
        mock_download_cootek_call_report_by_task_id.apply_async.return_value = MagicMock(id=10)
        self.mock_cootek_client.create_task.return_value = 321

        self.request_data['data']['intention_list'] = ["A"]
        ret_val = process_call_customer_via_cootek("test", self.request_data)

        self.assertIsNone(ret_val)
        self.mock_cootek_client.create_task.has_no_call()
        mock_download_cootek_call_report_by_task_id.apply_async.has_no_call()

    @patch.object(timezone, 'now')
    @patch('juloserver.cootek.tasks.secrets')
    def test_success_with_intention(
        self,
        mock_secrets,
        mock_now,
        mock_get_cootek_client,
        mock_download_cootek_call_report_by_task_id,
    ):
        mock_secrets.token_hex.return_value = "secret-token"
        mock_now.return_value = datetime(2024, 2, 1, 9, 00)
        mock_get_cootek_client.return_value = self.mock_cootek_client
        mock_download_cootek_call_report_by_task_id.apply_async.return_value = MagicMock(id=10)
        self.mock_cootek_client.create_task.return_value = 321

        # Intention setup
        customer = CustomerFactory(
            fullname='customer fullname intention',
            gender='Wanita',
            phone="0852123456789",
        )
        account = AccountFactory(customer=customer)
        application = ApplicationJ1Factory(account=account, customer=customer)
        account_payment = AccountPaymentwithPaymentFactory(
            account=account, due_amount=234000, due_date="2024-03-10"
        )
        loan = account_payment.payment_set.order_by('cdate').last().loan
        CootekRobocallFactory(
            account_payment=account_payment,
            task_type='test-task',
            product='J1',
            call_status='finished',
            intention="A",
        )
        self.request_data['customers'].append(
            OrderedDict(
                [
                    ("customer_id", str(customer.id)),
                    ("current_account_payment_id", str(account_payment.id)),
                ]
            )
        )
        self.request_data['data']['intention_list'] = ["A"]

        ret_val = process_call_customer_via_cootek("test", self.request_data)

        self.assertEqual(ret_val, 321)

        cootek_robot = CootekRobot.objects.filter(robot_identifier="54321").first()
        self.mock_cootek_client.create_task.assert_called_once_with(
            task_name="dev|test|12345|secret-token|test-task",
            start_time=timezone.localtime(datetime(2024, 2, 1, 13, 11)),
            end_time=timezone.localtime(datetime(2024, 2, 1, 15, 13)),
            robot=cootek_robot,
            attempts=3,
            task_details=[
                {
                    'Debtor': "customer fullname intention",
                    'Mobile': "+62852123456789",
                    'DueDate': "2024-03-10",
                    'LoanDate': loan.cdate.strftime("%Y-%m-%d"),
                    'LoanAmount': loan.loan_amount,
                    'Arrears': 234000,
                    'Unit': CootekAIRobocall.UNIT_RUPIAH,
                    'Platform': CootekAIRobocall.PLATFORM_JULO,
                    'Comments': str(account_payment.id),
                    'Gender': "female",
                    'ExtraA': 0,
                }
            ],
        )
        mock_download_cootek_call_report_by_task_id.apply_async.assert_called_once_with(
            (321, "dev|test|12345|secret-token|test-task"), countdown=22980.0
        )

    @patch.object(timezone, 'now')
    @patch('juloserver.cootek.tasks.secrets')
    def test_success_with_custom_attributes(
        self,
        mock_secrets,
        mock_now,
        mock_get_cootek_client,
        mock_download_cootek_call_report_by_task_id,
    ):
        mock_secrets.token_hex.return_value = "secret-token"
        mock_now.return_value = datetime(2024, 2, 1, 9, 00)
        mock_get_cootek_client.return_value = self.mock_cootek_client
        mock_download_cootek_call_report_by_task_id.apply_async.return_value = MagicMock(id=10)
        self.mock_cootek_client.create_task.return_value = 321
        request_data = self.request_data
        request_data['customers'][0].update(
            due_amount=321000,
            due_date='2024-10-10',
            loan_amount=300000,
            loan_date="2024-04-21",
            extraA="100",
        )
        ret_val = process_call_customer_via_cootek("test", request_data)

        self.assertEqual(ret_val, 321)

        cootek_robot = CootekRobot.objects.filter(robot_identifier="54321").first()
        self.mock_cootek_client.create_task.assert_called_once_with(
            task_name="dev|test|12345|secret-token|test-task",
            start_time=timezone.localtime(datetime(2024, 2, 1, 13, 11)),
            end_time=timezone.localtime(datetime(2024, 2, 1, 15, 13)),
            robot=cootek_robot,
            attempts=3,
            task_details=[
                {
                    'Debtor': "customer fullname",
                    'Mobile': "+6285212345678",
                    'DueDate': "2024-10-10",
                    'LoanDate': "2024-04-21",
                    'LoanAmount': 300000,
                    'Arrears': 321000,
                    'Unit': CootekAIRobocall.UNIT_RUPIAH,
                    'Platform': CootekAIRobocall.PLATFORM_JULO,
                    'Comments': str(self.account_payment.id),
                    'Gender': "male",
                    'ExtraA': "100",
                }
            ],
        )
        mock_download_cootek_call_report_by_task_id.apply_async.assert_called_once_with(
            (321, "dev|test|12345|secret-token|test-task"), countdown=22980.0
        )

    def test_success_cootek_robot_has_created(
        self,
        mock_get_cootek_client,
        mock_download_cootek_call_report_by_task_id,
    ):
        CootekRobotFactory(robot_identifier="54321", is_group_method=False)
        mock_get_cootek_client.return_value = self.mock_cootek_client
        mock_download_cootek_call_report_by_task_id.apply_async.return_value = MagicMock(id=10)
        self.mock_cootek_client.create_task.return_value = 321
        ret_val = process_call_customer_via_cootek("test", self.request_data)

        self.assertEqual(ret_val, 321)
        self.assertEqual(1, CootekRobot.objects.count())

    def test_success_duplicate_cootek_robot(
        self,
        mock_get_cootek_client,
        mock_download_cootek_call_report_by_task_id,
    ):
        cootek_robot = CootekRobotFactory(robot_identifier="54321", is_group_method=False)
        CootekRobotFactory(robot_identifier="54321", is_group_method=False)
        mock_get_cootek_client.return_value = self.mock_cootek_client
        mock_download_cootek_call_report_by_task_id.apply_async.return_value = MagicMock(id=10)
        self.mock_cootek_client.create_task.return_value = 321
        ret_val = process_call_customer_via_cootek("test", self.request_data)

        self.assertEqual(ret_val, 321)
        self.assertEqual(2, CootekRobot.objects.count())
        self.mock_cootek_client.create_task.assert_called_once_with(
            task_name=mock.ANY,
            start_time=mock.ANY,
            end_time=mock.ANY,
            robot=cootek_robot,
            attempts=mock.ANY,
            task_details=mock.ANY,
        )


@patch('juloserver.cootek.tasks.update_cootek_data')
@patch('juloserver.cootek.tasks.get_julo_cootek_client')
class TestDownloadCootekCallReportByTaskId(TestCase):
    def setUp(self):
        self.default_task_details = {
            "TaskID": 123,
            "Status": "finished",
            "detail": [
                {
                    "Comments": "123",
                    "RingType": "test",
                    "Intention": "test",
                    "HangupType": "test",
                    "CallEndTime": "2024-02-01 15:13:00",
                    "CallStartTime": "2024-02-01 13:11:00",
                    "Status": "finished",
                }
            ],
        }
        self.mock_cootek_client = MagicMock()
        self.mock_cootek_client.get_task_details.return_value = self.default_task_details

    def test_success(self, mock_get_cootek_client, mock_update_cootek_data):
        mock_get_cootek_client.return_value = self.mock_cootek_client
        download_cootek_call_report_by_task_id(123, task_name="test")

        self.mock_cootek_client.get_task_details.assert_called_once_with(
            123,
            retries_times=0,
            mock_url=None,
        )
        mock_update_cootek_data.assert_called_once_with(
            self.default_task_details,
            None,
            is_julo_one_product=True,
        )

    @patch('juloserver.cootek.tasks.send_message_normal_format')
    def test_retry(self, mock_send_message_normal_format, mock_get_cootek_client, *args):
        mock_get_cootek_client.return_value = self.mock_cootek_client
        self.mock_cootek_client.get_task_details.side_effect = JuloException("something wrong")

        with self.assertRaises(JuloException):
            download_cootek_call_report_by_task_id(123, task_name="test")

        self.assertEqual(1, self.mock_cootek_client.get_task_details.call_count)
