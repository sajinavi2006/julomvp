import os
import math
import mock
import json
import random
import pandas as pd
from unittest import skip
from rest_framework.test import APIClient, APITestCase
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta, date, time
from django.test.testcases import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from django.db.models import Sum
from django.db.models import F, Value, CharField, ExpressionWrapper, IntegerField, Q, Prefetch
from django.db.models.functions import Concat
from juloserver.settings.base import BASE_DIR
from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst, WorkflowConst
from juloserver.minisquad.constants import (
    FeatureNameConst as MiniSquadFeatureNameConst,
    RedisKey,
    IntelixTeam,
    DialerTaskType,
    DialerTaskStatus,
    AiRudder,
    DialerSystemConst,
    AIRudderPDSConstant,
)
from juloserver.julo.models import (
    Application,
    Loan,
    Payment,
    FeatureSetting,
    Skiptrace,
    SkiptraceResultChoice,
    PTP,
    ProductLine
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    LoanFactory,
    ProductLineFactory,
    WorkflowFactory,
    StatusLookupFactory,
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    PartnerFactory,
    ProductLookupFactory,
    CreditMatrixFactory,
    SkiptraceResultChoiceFactory,
    PaymentFactory,
)
from juloserver.minisquad.models import DialerTask, DialerTaskEvent, VendorRecordingDetail
from juloserver.minisquad.tests.factories import DialerTaskFactory, SentToDialerFactory
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.grab.tests.factories import (
    GrabLoanDataFactory,
    GrabIntelixCScoreFactory,
    GrabTempLoanNoCscoreFactory
)
from juloserver.minisquad.tasks2.dialer_system_task_grab import (
    populate_grab_temp_data_for_ai_rudder_dialer,
    process_construct_grab_data_to_ai_rudder,
    process_exclude_for_grab_sent_dialer_per_part_ai_rudder,
    process_grab_populate_temp_data_for_dialer_ai_rudder,
    process_and_send_grab_data_to_ai_rudder,
    populate_grab_temp_data_by_rank_ai_rudder,
    cron_trigger_grab_ai_rudder,
    send_data_to_ai_rudder_with_retries_mechanism_grab,
    grab_process_airudder_store_call_result,
    grab_consume_call_result_system_level,
    grab_process_retroload_call_results,
    delete_grab_paid_payment_from_dialer,
    get_grab_account_id_to_be_deleted_from_airudder,
    delete_grab_paid_payment_from_dialer_bulk,
    grab_write_call_results_subtask_for_manual_upload,
    grab_process_retroload_call_results_sub_task,
    grab_retroload_air_call_result_for_manual_upload,
    grab_retroload_air_call_result_sub_task_for_manual_upload,
    grab_retroload_for_manual_upload_sub_task,
    populate_grab_c_score_data_to_db_for_ai_rudder,
    fetch_sorted_grab_constructed_data,
    populate_grab_temp_data_by_dynamic_rank_ai_rudder,
    clear_grab_temp_loan_no_cscore,
    cron_trigger_sent_to_ai_rudder,
)
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from juloserver.grab.serializers import GrabCollectionDialerTemporarySerializer
from juloserver.grab.models import (
    GrabCollectionDialerTemporaryData,
    GrabConstructedCollectionDialerTemporaryData,
    GrabIntelixCScore,
    GrabLoanData,
    GrabTempAccountData,
    GrabFeatureSetting,
    GrabTempLoanNoCscore,
    GrabTask
)
from juloserver.minisquad.services2.intelix import (
    get_grab_populated_data_for_calling,
    get_starting_and_ending_index_temp_data,
    get_loans_based_on_c_score,
    get_loan_xids_based_on_c_score,
    create_history_dialer_task_event,
    construct_grab_data_for_sent_to_intelix_by_temp_data,
    get_late_fee_amount_intelix_grab,
    construct_additional_data_for_intelix_grab,
    remove_duplicate_data_with_lower_rank,
)
from juloserver.minisquad.services2.airudder import (
    get_grab_active_ptp_account_ids,
    get_not_paid_loan_in_last_2_days_custom,
    get_jumlah_pinjaman_ai_rudder_grab,
    get_angsuran_for_ai_rudder_grab,
    check_grab_customer_bucket_type,
    get_eligible_grab_ai_rudder_payment_for_dialer,
    GrabAIRudderPopulatingService
)
from juloserver.minisquad.services2.ai_rudder_pds import AIRudderPDSServices
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.grab.services.services import add_account_in_temp_table
from juloserver.grab.constants import GrabFeatureNameConst

class TestCronGrabAiRudder(TestCase):
    def setUp(self) -> None:
        self.grab_ai_rudder_call_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL
        )
        self.grab_cscore_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_AI_RUDDER
        )
        date = timezone.localtime(timezone.now() - timedelta(days=1)).strftime("%Y%m%d")
        file_name = 'dax_cscore_{}.csv'.format(date)
        csv_folder = os.path.join(BASE_DIR, 'csv')
        self.file_path = csv_folder + '/grab_cscore/' + file_name
        self.log_action = "populate_grab_c_score_data_to_db_for_ai_rudder"
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.loan = LoanFactory(customer=self.customer, loan_amount=10000000, loan_xid=1000003891)
        self.user1 = AuthUserFactory()
        self.customer1 = CustomerFactory(user=self.user1)
        self.loan1 = LoanFactory(customer=self.customer1, loan_amount=10000000, loan_xid=1000003924)
        self.csv_data = {
            "loan_id": [1000003891, 1000003924],
            "user_id": ['6432621', '6244986'],
            "vehicle_type": ['2W', '2W'],
            "cscore": ['200', '100'],
            "prediction_date": ['2022-12-05', '2022-12-06'],
        }
        self.csv_data1 = {
            "loan_id": [1000003851, 1000003955, 1000003851],
            "user_id": ['6432621', '6244986', '6244986'],
            "vehicle_type": ['2W', '2W', '2W'],
            "cscore": ['200', '100', '50'],
            "prediction_date": ['2022-12-05', '2022-12-06', '2022-12-06'],
        }

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder.delay'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_populate_grab_ai_rudder.delay'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_send_grab_ai_rudder.delay'
    )
    def test_failed_feature_setting_doesnt_active(
        self,
        mock_trigger_send_grab_ai_rudder,
        mock_trigger_populate_grab_ai_rudder,
        mock_trigger_populate_grab_c_score_to_db,
    ):
        self.grab_ai_rudder_call_feature_setting.is_active = False
        self.grab_ai_rudder_call_feature_setting.save()
        self.grab_ai_rudder_call_feature_setting.refresh_from_db()
        cron_trigger_grab_ai_rudder()
        self.assertEqual(mock_trigger_populate_grab_ai_rudder.called, False)
        self.assertEqual(mock_trigger_send_grab_ai_rudder.called, False)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_populate_grab_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_send_grab_ai_rudder.delay')
    def test_failed_feature_setting_doesnt_have_parameters(self, mock_trigger_send_grab_ai_rudder,
                                                           mock_trigger_populate_grab_ai_rudder,
                                                           mock_trigger_populate_grab_c_score_to_db):
        cron_trigger_grab_ai_rudder()
        self.assertEqual(mock_trigger_populate_grab_ai_rudder.called, False)
        self.assertEqual(mock_trigger_send_grab_ai_rudder.called, False)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_populate_grab_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_send_grab_ai_rudder.delay')
    def test_failed_feature_setting_doesnt_have_populate_schedule_parameter(self,
                                                                            mock_trigger_send_grab_ai_rudder,
                                                                            mock_trigger_populate_grab_ai_rudder):
        parameters = {
            "send_schedule": "08:00"
        }
        self.grab_ai_rudder_call_feature_setting.parameters = parameters
        self.grab_ai_rudder_call_feature_setting.save()
        self.grab_ai_rudder_call_feature_setting.refresh_from_db()
        cron_trigger_grab_ai_rudder()
        self.assertEqual(mock_trigger_populate_grab_ai_rudder.called, False)
        self.assertEqual(mock_trigger_send_grab_ai_rudder.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_populate_grab_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_send_grab_ai_rudder.delay')
    def test_failed_feature_setting_doesnt_have_send_schedule_parameter(self,
                                                                        mock_trigger_send_grab_ai_rudder,
                                                                        mock_trigger_populate_grab_ai_rudder,
                                                                        mock_trigger_populate_grab_c_score_to_db):
        parameters = {
            "populate_schedule": "06:00"
        }
        self.grab_ai_rudder_call_feature_setting.parameters = parameters
        self.grab_ai_rudder_call_feature_setting.save()
        self.grab_ai_rudder_call_feature_setting.refresh_from_db()
        cron_trigger_grab_ai_rudder()
        self.assertEqual(mock_trigger_populate_grab_ai_rudder.called, False)
        self.assertEqual(mock_trigger_send_grab_ai_rudder.called, False)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_populate_grab_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_send_grab_ai_rudder.delay')
    def test_failed_feature_setting_doesnt_have_c_score_db_populate_schedule_parameter(
            self, mock_trigger_send_grab_ai_rudder,
            mock_trigger_populate_grab_ai_rudder,
            mock_trigger_populate_grab_c_score_to_db
    ):
        parameters = {
            "populate_schedule": "06:00",
            "send_schedule": "08:00"
        }
        self.grab_ai_rudder_call_feature_setting.parameters = parameters
        self.grab_ai_rudder_call_feature_setting.save()
        self.grab_ai_rudder_call_feature_setting.refresh_from_db()
        cron_trigger_grab_ai_rudder()
        self.assertEqual(mock_trigger_populate_grab_ai_rudder.called, True)
        self.assertEqual(mock_trigger_send_grab_ai_rudder.called, True)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_populate_grab_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_send_grab_ai_rudder.delay')
    def test_failed_feature_setting_with_in_active_grab_c_score_feature_for_intelix(
            self, mock_trigger_send_grab_ai_rudder,
            mock_trigger_populate_grab_ai_rudder,
            mock_trigger_populate_grab_c_score_to_db
    ):
        parameters = {
            "populate_schedule": "06:00",
            "send_schedule": "08:00",
            "c_score_db_populate_schedule": "23:10"
        }
        self.grab_ai_rudder_call_feature_setting.parameters = parameters
        self.grab_ai_rudder_call_feature_setting.save()
        self.grab_ai_rudder_call_feature_setting.refresh_from_db()
        self.grab_cscore_feature_setting.is_active = False
        self.grab_cscore_feature_setting.save()
        self.grab_cscore_feature_setting.refresh_from_db()
        cron_trigger_grab_ai_rudder()
        self.assertEqual(mock_trigger_populate_grab_ai_rudder.called, True)
        self.assertEqual(mock_trigger_send_grab_ai_rudder.called, True)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'cron_trigger_populate_grab_c_score_data_to_db_for_ai_rudder.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_populate_grab_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.cron_trigger_send_grab_ai_rudder.delay')
    def test_success_trigger_populate_and_send_grab_intelix(self, mock_trigger_send_grab_ai_rudder,
                                                            mock_trigger_populate_grab_ai_rudder,
                                                            mock_trigger_populate_grab_c_score_to_db):
        parameters = {
            "populate_schedule": "06:00",
            "send_schedule": "08:00",
            "c_score_db_populate_schedule": "23:10"
        }
        self.grab_ai_rudder_call_feature_setting.parameters = parameters
        self.grab_ai_rudder_call_feature_setting.save()
        self.grab_ai_rudder_call_feature_setting.refresh_from_db()
        cron_trigger_grab_ai_rudder()
        self.assertEqual(mock_trigger_populate_grab_ai_rudder.called, True)
        self.assertEqual(mock_trigger_send_grab_ai_rudder.called, True)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, True)

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.send_grab_failed_deduction_slack.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger.exception')
    def test_populate_grab_c_score_data_to_db_for_ai_rudder_file_not_exist(
        self, mocked_logger, mocked_send_grab_failed_deduction_slack
    ):
        populate_grab_c_score_data_to_db_for_ai_rudder()
        self.assertEqual(mocked_logger.called, True)
        self.assertEqual(mocked_send_grab_failed_deduction_slack.called, True)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.logger.info')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.send_grab_failed_deduction_slack.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.pandas.read_csv')
    def test_populate_grab_c_score_data_to_db_for_ai_rudder(
            self, mocked_csv,  mocked_send_grab_failed_deduction_slack, mocked_logger
    ):
        mocked_csv.return_value = [pd.DataFrame(data=self.csv_data)]
        populate_grab_c_score_data_to_db_for_ai_rudder()
        self.assertEqual(GrabIntelixCScore.objects.count(), 2)
        self.assertEqual(mocked_send_grab_failed_deduction_slack.called, True)

        mocked_csv.return_value = [pd.DataFrame(data=self.csv_data1)]
        populate_grab_c_score_data_to_db_for_ai_rudder()
        self.assertEqual(GrabIntelixCScore.objects.count(), 2)
        self.assertEqual(mocked_send_grab_failed_deduction_slack.called, True)
        mocked_logger.assert_called_with({
            "action": "populate_grab_c_score_data_to_db_for_ai_rudder",
            "message": "successfully finished the task populate_grab_c_score_data_to_db"
        })


class TestPopulateDataGrabAiRudder(TestCase):
    def create_populate_feature_settings(self):
        GrabFeatureSetting.objects.get_or_create(
            is_active=True,
            category="grab collection",
            description='grab airudder populating config',
            feature_name=GrabFeatureNameConst.GRAB_POPULATING_CONFIG,
            parameters=[
                {
                    "rank": 1,
                    "score": [{"min": 200, "max": 400}],
                    "dpd": [{"min": 7, "max": 11}, {"min": 30, "max": 40}, {"min": 50, "max": 60}],
                    "category": ["4W"],
                },
                {
                    "rank": 2,
                    "score": [{"min": 400, "max": 800}],
                    "dpd": [{"min": 7, "max": 11}, {"min": 31, "max": 40}, {"min": 50, "max": 60}],
                    "category": ["4W"],
                },
            ],
        )

    def setUp(self):
        self.create_populate_feature_settings()
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)

        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                application=self.application,
                                loan_amount=10000000, loan_xid=1000003456)
        LoanFactory.create_batch(2, loan_amount=10000000, loan_duration=12)
        self.bucket_name = AiRudder.GRAB
        self.redis_data = {}
        self.grab_ai_rudder_call_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL,
            is_active=True,
            parameters={"populate_schedule": "02:00", "send_schedule": "05:00",
                        "grab_send_batch_size": "1000"}
        )

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('juloserver.minisquad.services2.airudder.get_grab_active_ptp_account_ids')
    @mock.patch('juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix')
    def test_failed_no_eligible_grab_payment_data(self, mock_delete_redis_key,
                                                  mock_get_redis_client,
                                                  mock_eligible_grab_payment_data,
                                                  mock_grab_active_ptp_account_ids):
        mock_grab_active_ptp_account_ids.return_value = None
        mock_eligible_grab_payment_data.return_value = [(None, [])]
        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event.status, 'ai_rudder_querying_rank_2_chunk_1')

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_grab_payment_data(self, mock_delete_redis_key,
                                                          mock_get_redis_client,
                                                          mock_eligible_grab_payment_data,
                                                          mock_async_process_sent_dialer_per_part):
        loan_ids = Loan.objects.all().values_list('id', flat=True)
        payments = Payment.objects.select_related('loan').filter(loan_id__in=loan_ids)
        list_account_ids = []
        for payment in payments:
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]
        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event.status, 'ai_rudder_batching_processed_rank_2')
        self.assertEqual(dialer_task_event.data_count, 1)
        # cause there are 1 batches for 2 ranks
        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_grab_payment_data_with_config(self, mock_delete_redis_key,
                                                                      mock_get_redis_client,
                                                                      mock_eligible_grab_payment_data,
                                                                      mock_async_process_sent_dialer_per_part):
        parameters = {
            AiRudder.GRAB: 12
        }
        self.intelix_data_batching_feature_setting = FeatureSetting.objects.create(
            feature_name=MiniSquadFeatureNameConst.AI_RUDDER_SEND_BATCHING_THRESHOLD,
            parameters=parameters,
            is_active=True
        )
        self.grab_cscore_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_AI_RUDDER,
            is_active=False
        )
        loan_ids = Loan.objects.all().values_list('id', flat=True)
        payments = Payment.objects.select_related('loan').filter(loan_id__in=loan_ids)
        list_account_ids = []
        for payment in payments:
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]
        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event.status, 'ai_rudder_batching_processed_rank_2')
        self.assertEqual(dialer_task_event.data_count, 3)
        # cause there are 3 batches for 2 ranks
        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 6)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.logger.info')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_grab_populate_temp_data_for_dialer_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_failed_with_empty_cache_populated_eligible_grab_data(self, mock_get_redis_client,
                                                                  mock_process_temp_data,
                                                                  mocked_logger):
        rank = 1
        page_num = 1
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS
        )
        mocked_logger.return_value = None
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        loan = Loan.objects.first()
        payment_ids = Payment.objects.filter(loan_id=loan.id).all()
        list_account_ids = [payment.loan.account_id for payment in payment_ids]
        account_id_ptp_exist = get_grab_active_ptp_account_ids(list_account_ids)
        process_exclude_for_grab_sent_dialer_per_part_ai_rudder(rank, self.bucket_name, page_num,
                                                                dialer_task.id, account_id_ptp_exist)
        self.assertEqual(mock_process_temp_data.called, False)
        mocked_logger.assert_called()
        redis_key = RedisKey.AI_RUDDER_POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(
            self.bucket_name, rank, page_num)
        mocked_logger.assert_called_with({
            "action": "process_exclude_for_grab_sent_dialer_per_part_ai_rudder",
            "message": "missing redis key - {}".format(redis_key)
        })

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_grab_populate_temp_data_for_dialer_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_success_with_cache_populated_eligible_grab_data(self, mock_get_redis_client,
                                                             mock_process_temp_data):
        loan = Loan.objects.first()
        payment_ids = Payment.objects.filter(loan_id=loan.id).values_list('id', flat=True)
        rank = 1
        page_num = 1
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis( # noqa
            RedisKey.AI_RUDDER_POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(self.bucket_name, rank,
                                                                    page_num),
            payment_ids)
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        loan = Loan.objects.first()
        payment_ids = Payment.objects.filter(loan_id=loan.id).all()
        list_account_ids = [payment.loan.account_id for payment in payment_ids]
        account_id_ptp_exist = get_grab_active_ptp_account_ids(list_account_ids)
        process_exclude_for_grab_sent_dialer_per_part_ai_rudder(rank, self.bucket_name, page_num,
                                                                dialer_task.id, account_id_ptp_exist)
        self.assertEqual(mock_process_temp_data.called, True)

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_failed_construct_data_with_empty_cache(self, mock_get_redis_client):
        rank = 1
        page_num = 1
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        process_grab_populate_temp_data_for_dialer_ai_rudder(rank, self.bucket_name, page_num, dialer_task.id)
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event, None)

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_success_record_to_grab_collection_dialer_temporary_data_table(self,
                                                                           mock_get_redis_client):
        loan = Loan.objects.first()
        payment_ids = Payment.objects.filter(loan_id=loan.id).values_list('id', flat=True)
        rank = 1
        page_num = 1
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis( # noqa
            RedisKey.AI_RUDDER_CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(self.bucket_name, rank,
                                                                                page_num),
            payment_ids)
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        process_grab_populate_temp_data_for_dialer_ai_rudder(rank, self.bucket_name, page_num, dialer_task.id)
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event.status,
                         DialerTaskStatus.GRAB_AI_RUDDER_PROCESSED_POPULATED_GRAB_PAYMENTS.format(
                             self.bucket_name, rank, page_num)
                         )

        grab_coll_dialer_temp_data = GrabCollectionDialerTemporaryData.objects.filter(
            loan_id=loan.id)
        self.assertEqual(len(grab_coll_dialer_temp_data), len(payment_ids))

    def test_create_history_dialer_task_event_success(self):
        dialer_task = DialerTaskFactory()
        error = "ERROR"
        rank = 1
        part = 1
        test_dict = dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.GRAB_AI_RUDDER_FAILURE_RANK_BATCH.format(rank, part),
        )
        error_message = str(error)
        create_history_dialer_task_event(test_dict, error_message)
        dialer_task_event_1 = DialerTaskEvent.objects.filter(
            dialer_task=dialer_task).last()
        self.assertIsNotNone(dialer_task_event_1)
        self.assertEqual(dialer_task_event_1.status, 'ai_rudder_failure_rank_1_part_1')

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.GRAB_AI_RUDDER_PROCESS_POPULATED_GRAB_PAYMENTS.format(
                     self.bucket_name, rank, part)))
        dialer_task_event_2 = DialerTaskEvent.objects.filter(
            dialer_task=dialer_task).last()
        self.assertIsNotNone(dialer_task_event_2)
        self.assertEqual(dialer_task_event_2.status,
                         'ai_rudder_process_populated_grab_payments_{}_rank_1_part_1'.format(AiRudder.GRAB))

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_grab_payment_data_chunked(self, mock_delete_redis_key,
                                                                  mock_get_redis_client,
                                                                  mock_eligible_grab_payment_data,
                                                                  mock_async_process_sent_dialer_per_part):
        loan_ids = Loan.objects.all().values_list('id', flat=True)
        payments = Payment.objects.select_related('loan').filter(loan_id__in=loan_ids)
        list_account_ids = []
        for payment in payments:
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids), (None, [])]
        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, len(payments))

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_1').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_2').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_grab_payment_data_chunked_2(self, mock_delete_redis_key,
                                                                    mock_get_redis_client,
                                                                    mock_eligible_grab_payment_data,
                                                                    mock_async_process_sent_dialer_per_part):
        loan_ids = Loan.objects.all().values_list('id', flat=True)
        payments = Payment.objects.select_related('loan').filter(loan_id__in=loan_ids)
        list_account_ids = []
        for payment in payments:
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(None, []), (payments, list_account_ids)]
        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, len(payments))

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_1').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_2').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_grab_payment_data_chunked_3(self, mock_delete_redis_key,
                                                                    mock_get_redis_client,
                                                                    mock_eligible_grab_payment_data,
                                                                    mock_async_process_sent_dialer_per_part):
        loan_ids = Loan.objects.all().values_list('id', flat=True)
        payments = Payment.objects.select_related('loan').filter(loan_id__in=loan_ids)
        list_account_ids = []
        for payment in payments:
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [
            (Payment.objects.none(), []),
            (payments, list_account_ids)
        ]

        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, len(payments))

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_1').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_2').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_grab_active_ptp_account_ids')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_grab_payment_data_chunked_4(self, mock_delete_redis_key,
                                                                    mock_get_redis_client,
                                                                    mock_eligible_grab_payment_data,
                                                                    mock_async_process_sent_dialer_per_part,
                                                                    mock_get_grab_ptp):
        from juloserver.moengage.utils import chunks
        loan_ids = Loan.objects.all().values_list('id', flat=True)
        mocked_return_value = []
        total_payments = 0
        mock_get_grab_ptp_value = []
        for counter, chunked_loan_ids in enumerate(chunks(loan_ids, 2)):
            payments = Payment.objects.select_related('loan').filter(loan_id__in=chunked_loan_ids)
            total_payments += len(payments)
            list_account_ids = []
            for payment in payments:
                loan = payment.loan
                if loan.account_id:
                    list_account_ids.append(loan.account_id)
            mocked_return_value.append((payments, list_account_ids))
            mock_get_grab_ptp_value.append([counter+1])
        mock_get_grab_ptp.side_effect = mock_get_grab_ptp_value * 2

        mock_eligible_grab_payment_data.return_value = mocked_return_value

        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, total_payments)

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_1').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_2').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)
        positional_args, _ = mock_async_process_sent_dialer_per_part.call_args
        flat_ptp_val_merged = []
        for i in mock_get_grab_ptp_value:
            flat_ptp_val_merged += i
        self.assertEqual(positional_args[-1], flat_ptp_val_merged)

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_grab_active_ptp_account_ids')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'process_exclude_for_grab_sent_dialer_per_part_ai_rudder.delay')
    @mock.patch('juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_grab_payment_data_chunked_7(self, mock_delete_redis_key,
                                                                    mock_get_redis_client,
                                                                    mock_eligible_grab_payment_data,
                                                                    mock_async_process_sent_dialer_per_part,
                                                                    mock_get_grab_ptp):
        from juloserver.moengage.utils import chunks
        loan_ids = Loan.objects.all().values_list('id', flat=True)
        mocked_return_value = []
        total_payments = 0
        mock_get_grab_ptp_value = []
        for counter, chunked_loan_ids in enumerate(chunks(loan_ids, 8)):
            payments = Payment.objects.select_related('loan').filter(loan_id__in=chunked_loan_ids)
            total_payments += len(payments)
            list_account_ids = []
            for payment in payments:
                loan = payment.loan
                if loan.account_id:
                    list_account_ids.append(loan.account_id)
            mocked_return_value.append((payments, list_account_ids))
            mock_get_grab_ptp_value.append([counter+1])
        mock_get_grab_ptp.side_effect = mock_get_grab_ptp_value * 2

        mock_eligible_grab_payment_data.return_value = mocked_return_value

        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, total_payments)

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_1').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='ai_rudder_batching_processed_rank_2').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)
        positional_args, _ = mock_async_process_sent_dialer_per_part.call_args
        flat_ptp_val_merged = []
        for i in mock_get_grab_ptp_value:
            flat_ptp_val_merged += i
        self.assertEqual(positional_args[-1], flat_ptp_val_merged)


class TestSendPopulatedGrabDataAiRudder(TestCase):
    def create_populate_feature_settings(self):
        GrabFeatureSetting.objects.get_or_create(
            is_active=True,
            category="grab collection",
            description='grab airudder populating config',
            feature_name=GrabFeatureNameConst.GRAB_POPULATING_CONFIG,
            parameters=[
                {
                    "rank": 1,
                    "score": [{"min": 200, "max": 400}],
                    "dpd": [{"min": 7, "max": 11}, {"min": 30, "max": 40}, {"min": 50, "max": 60}],
                    "category": ["4W"],
                },
                {
                    "rank": 2,
                    "score": [{"min": 400, "max": 800}],
                    "dpd": [{"min": 7, "max": 11}, {"min": 31, "max": 40}, {"min": 50, "max": 60}],
                    "category": ["4W"],
                },
            ],
        )

    def setUp(self) -> None:
        self.create_populate_feature_settings()

        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        GrabTempAccountData.objects.create(account_id=self.account.id)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email@gmail.com',
            account=self.account
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user, latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90))
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED)

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)

        self.loan = LoanFactory(account=self.account, customer=self.customer,
                                application=self.application,
                                loan_amount=10000000, loan_xid=1000003456)
        self.bucket_name = AiRudder.GRAB
        self.redis_data = {}
        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )
        self.customer_2 = CustomerFactory()
        self.account_2 = AccountFactory(
            customer=self.customer_2,
            account_lookup=self.account_lookup
        )
        self.application_2 = ApplicationFactory(
            customer=self.customer_2,
            account=self.account_2,
            application_status=StatusLookupFactory(status_code=190)
        )
        self.loan_2 = LoanFactory(
            loan_purpose='Grab_loan_creation', loan_amount=500000, loan_duration=180,
            account=self.account_2, customer=self.customer_2,
            loan_status=StatusLookupFactory(status_code=231)
        )
        self.grab_loan_data_2 = GrabLoanDataFactory(loan=self.loan_2)
        loan_payments = Payment.objects.filter(loan=self.loan_2).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=20))
        for idx, payment in enumerate(loan_payments):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.save()
        self.first_payment = loan_payments[0]

        self.loan_3 = LoanFactory(
            loan_purpose='Grab_loan_creation', loan_amount=500000, loan_duration=180,
            account=self.account_2, customer=self.customer_2,
            loan_status=StatusLookupFactory(status_code=231)
        )
        self.grab_loan_data_3 = GrabLoanDataFactory(loan=self.loan_3)
        loan_payments_3 = Payment.objects.filter(loan=self.loan_2).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=10))
        for idx, payment in enumerate(loan_payments):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 30000
            payment.save()
        self.grab_ai_rudder_call_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL,
            is_active=True,
            parameters={"populate_schedule": "02:00", "send_schedule": "05:00",
                        "grab_send_batch_size": "1000", "c_score_db_populate_schedule": "23:10"}
        )
        self.grab_cscore_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_AI_RUDDER,
            is_active=True
        )
        self.grab_ai_rudder_delete_phone_number = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_DELETE_PHONE_NUMBER,
            is_active=True
        )

        ranks = list(range(1, 9))
        for rank in ranks:
            grab_payments = self.get_eligible_grab_payment_for_dialer_initialize(rank)
            current_date = timezone.localtime(timezone.now()).date()
            grouped_payments = Payment.objects.filter(
                id__in=grab_payments).annotate(
                alamat=Concat(
                    F('loan__account__application__address_street_num'), Value(' '),
                    F('loan__account__application__address_provinsi'), Value(' '),
                    F('loan__account__application__address_kabupaten'), Value(' '),
                    F('loan__account__application__address_kecamatan'), Value(' '),
                    F('loan__account__application__address_kelurahan'), Value(' '),
                    F('loan__account__application__address_kodepos'),
                    output_field=CharField()
                ),
                team=Value('GRAB', output_field=CharField()),
                dpd_field=ExpressionWrapper(
                    current_date - F('due_date'),
                    output_field=IntegerField()),
                sort_order=Value(1, IntegerField())
            ).values(
                'loan__account__customer_id',  # customer_id
                'loan__account__application__id',  # application_id
                'loan__account__application__fullname',  # nama_customer
                'loan__account__application__company_name',  # nama_perusahaan
                'loan__account__application__position_employees',  # posisi_karyawan
                'loan__account__application__spouse_name',  # nama_pasangan
                'loan__account__application__kin_name',  # nama_kerabat
                'loan__account__application__kin_relationship',  # hubungan_kerabat
                'loan__account__application__gender',  # jenis_kelamin
                'loan__account__application__dob',  # tgl_lahir
                'loan__account__application__payday',  # tgl_gajian
                'loan__account__application__loan_purpose',  # tujuan_pinjaman
                'due_date',  # tanggal_jatuh_tempo
                'alamat',  # alamat
                'loan__account__application__address_kabupaten',  # kota
                'loan__account__application__product_line__product_line_type',  # tipe_produk
                'loan__account__application__partner__name',  # partner_name
                'team',  # bucket_name
                'id',  # payment id,
                'dpd_field',
                'loan_id',
                'sort_order'
            )
            serialize_data = GrabCollectionDialerTemporarySerializer(
                data=list(grouped_payments), many=True)
            serialize_data.is_valid(raise_exception=True)
            serialized_data = serialize_data.validated_data
            serialized_data_objects = [
                GrabCollectionDialerTemporaryData(**vals) for vals in serialized_data]
            GrabCollectionDialerTemporaryData.objects.bulk_create(serialized_data_objects)

    def insert_data_to_grab_constructed_collection_dailer(self):
        grab_collection_dialer_temp_datas = GrabCollectionDialerTemporaryData.objects.order_by('id')[:3]
        constructed_calling_data_obj = []
        today = timezone.localtime(timezone.now()).date()
        today_str = datetime.strftime(today, "%Y-%m-%d")
        outstanding_amount = 50000
        dpd = 60
        sort_order = 3
        for grab_collection_dialer_temp_data in grab_collection_dialer_temp_datas:
            payment = (
                Payment.objects.select_related('loan').filter(pk=grab_collection_dialer_temp_data.payment_id).last()
            )
            if not payment:
                continue
            loan = payment.loan
            if loan.status not in set(LoanStatusCodes.grab_current_until_180_dpd()):
                continue
            account = loan.account
            application = account.last_application
            if not application:
                continue
            zip_code = application.address_kodepos
            denda = 0
            grab_constructed = GrabConstructedCollectionDialerTemporaryData(
                application_id=grab_collection_dialer_temp_data.application_id,
                customer_id=grab_collection_dialer_temp_data.customer_id,
                nama_customer=grab_collection_dialer_temp_data.nama_customer,
                nama_perusahaan=grab_collection_dialer_temp_data.nama_perusahaan,
                posisi_karyawan=grab_collection_dialer_temp_data.posisi_karyawan,
                nama_pasangan=grab_collection_dialer_temp_data.nama_pasangan,
                nama_kerabat=grab_collection_dialer_temp_data.nama_kerabat,
                hubungan_kerabat=grab_collection_dialer_temp_data.hubungan_kerabat,
                jenis_kelamin=grab_collection_dialer_temp_data.jenis_kelamin,
                tgl_lahir=grab_collection_dialer_temp_data.tgl_lahir,
                tgl_gajian=grab_collection_dialer_temp_data.tgl_gajian,
                tujuan_pinjaman=grab_collection_dialer_temp_data.tujuan_pinjaman,
                tanggal_jatuh_tempo=grab_collection_dialer_temp_data.tanggal_jatuh_tempo,
                alamat=grab_collection_dialer_temp_data.alamat,
                kota=grab_collection_dialer_temp_data.kota,
                tipe_produk=grab_collection_dialer_temp_data.tipe_produk,
                partner_name=grab_collection_dialer_temp_data.partner_name,
                account_payment_id=grab_collection_dialer_temp_data.account_payment_id,
                dpd=dpd,
                team=grab_collection_dialer_temp_data.team,
                loan_id=None,
                payment_id=None,
                mobile_phone_1='0837347373',
                mobile_phone_2='0837347373',
                telp_perusahaan='0837347373',
                denda=denda,
                outstanding=outstanding_amount,
                angsuran_ke='',
                no_telp_pasangan='0837347373',
                no_telp_kerabat='0837347373',
                tgl_upload=today_str,
                va_bca='',
                va_permata='',
                va_maybank='',
                va_alfamart='',
                va_indomaret='',
                campaign="JULO",
                jumlah_pinjaman=1700000,
                tenor=None,
                last_agent='',
                last_call_status='',
                customer_bucket_type="Fresh",
                zip_code=zip_code,
                disbursement_period='',
                repeat_or_first_time='',
                account_id=payment.loan.account_id,
                is_j1=False,
                Autodebit="Tidak Aktif",
                refinancing_status='',
                activation_amount='',
                program_expiry_date='',
                promo_untuk_customer='',
                last_pay_date='',
                last_pay_amount=0,
                status_tagihan={"1_status_tagihan": "26 Jan 2018; 327; 1885000"},
                sort_order=sort_order
            )
            constructed_calling_data_obj.append(grab_constructed)
            outstanding_amount = outstanding_amount + 10000
            dpd = dpd - 10
            sort_order = sort_order - 1

        GrabConstructedCollectionDialerTemporaryData.objects.bulk_create(
            constructed_calling_data_obj
        )

    def insert_date_to_dialer_task(self):
        current_time = timezone.localtime(timezone.now())
        today_min = datetime.combine(current_time, time.min)
        today_max = datetime.combine(current_time, time.max)
        upload_dialer_task = DialerTask.objects.create(
            type=DialerTaskType.GRAB_AI_RUDDER_UPLOAD_GRAB,
            vendor=DialerSystemConst.AI_RUDDER_PDS
        )
        return upload_dialer_task

    def get_eligible_grab_payment_for_dialer_initialize(
            self, rank, restructured_loan_ids_list=None, loan_xids_based_on_c_score_list=None):
        if loan_xids_based_on_c_score_list is None:
            loan_xids_based_on_c_score_list = []
        if restructured_loan_ids_list is None:
            restructured_loan_ids_list = []
        DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID = 2
        MINIMUM_DPD_VALUE = 2
        use_outstanding = False
        is_below_700k = False
        is_restructured = False
        is_loan_below_91 = True
        is_include_restructure_and_normal = False
        exclusion_filter = Q()
        inclusion_filter = {
            'loan__loan_status_id__in': LoanStatusCodes.grab_current_until_90_dpd(),
            'payment_status_id__in': {
                PaymentStatusCodes.PAYMENT_DUE_TODAY,
                PaymentStatusCodes.PAYMENT_1DPD,
                PaymentStatusCodes.PAYMENT_5DPD,
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_60DPD,
                PaymentStatusCodes.PAYMENT_90DPD
            },
            'is_restructured': False,
            'loan__account__account_lookup__workflow__name': WorkflowConst.GRAB
        }
        is_above_100k = False

        if rank == 1:
            # high risk without restructure loan
            use_outstanding = True
            is_above_100k = True
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 2:
            # high risk only restructure loan
            is_restructured = True
            use_outstanding = True
            is_above_100k = True
            restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
                restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
            ) if restructured_loan_ids_list else []
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 3:
            # medium risk without restructure loan
            use_outstanding = True
            is_above_100k = True
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 4:
            # medium risk only restructure loan
            is_restructured = True
            use_outstanding = True
            is_above_100k = True
            restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
                restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
            ) if restructured_loan_ids_list else []
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 5:
            # low risk without restructure loan
            use_outstanding = True
            is_above_100k = True
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 6:
            # low risk only restructure loan
            is_restructured = True
            use_outstanding = True
            is_above_100k = True
            restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
                restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
            ) if restructured_loan_ids_list else []
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 7:
            use_outstanding = True
            is_above_100k = True
            exclusion_filter = exclusion_filter | Q(loan__loan_xid__in=GrabIntelixCScore.objects.filter(
                cscore__range=(200, 800)).values_list('loan_xid', flat=True))
        elif rank == 8:
            is_restructured = True
            restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
                restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
            ) if restructured_loan_ids_list else []
            exclusion_filter = exclusion_filter | Q(loan__loan_xid__in=GrabIntelixCScore.objects.filter(
                cscore__range=(200, 800)).values_list('loan_xid', flat=True))
        else:
            raise Exception("INVALID RANK FOR GRAB AI_RUDDER RANK({})".format(rank))

        """
        check if both data should be included
        if not then check it is should be restructured only data or normal data only
        """
        if not is_include_restructure_and_normal:
            if not is_restructured:
                exclusion_filter = exclusion_filter | (Q(loan_id__in=restructured_loan_ids_list))
            else:
                inclusion_filter.update({'loan_id__in': restructured_loan_ids_list})

        grab_loan_data_set = GrabLoanData.objects.only(
            'loan_halt_date', 'loan_resume_date', 'id', 'loan_id', 'is_repayment_capped')
        prefetch_grab_loan_data = Prefetch(
            'loan__grabloandata_set', to_attr='grab_loan_data_set', queryset=grab_loan_data_set)

        oldest_unpaid_payments_queryset = Payment.objects.only(
            'id', 'loan_id', 'due_date', 'payment_status_id'
        ).not_paid_active().order_by('due_date')
        prefetch_oldest_unpaid_payments = Prefetch(
            'loan__payment_set', to_attr="grab_oldest_unpaid_payments",
            queryset=oldest_unpaid_payments_queryset)

        prefetch_join_tables = [
            prefetch_oldest_unpaid_payments,
            prefetch_grab_loan_data
        ]

        oldest_payment_qs = Payment.objects.select_related('loan').prefetch_related(
            *prefetch_join_tables
        ).filter(
            **inclusion_filter
        ).exclude(
            exclusion_filter
        )
        total_oldest_payment_qs = oldest_payment_qs.count()
        split_threshold = 5000
        grouped_by_loan_customer_and_max_dpd = []
        for iterator in list(range(0, total_oldest_payment_qs, split_threshold)):
            oldest_payment_qs_sliced = Payment.objects.select_related('loan').prefetch_related(
                *prefetch_join_tables
            ).filter(
                **inclusion_filter
            ).exclude(
                exclusion_filter
            )[iterator:iterator + split_threshold]

            """
            group the data by loan_id and max_dpd
            e.g:
            [
                {'loan_id': 3000009060, 'loan__customer_id': 10001, 'max_dpd': 487},
                {'loan_id': 3000009075, 'loan__customer_id': 10001, 'max_dpd': 695},
                {'loan_id': 3000009083, 'loan__customer_id': 10003, 'max_dpd': 695}
            ]
            """
            for payment in oldest_payment_qs_sliced:
                if not any(
                        d['loan_id'] == payment.loan.id and d['customer_id'] == payment.loan.customer.id
                        for
                        d in grouped_by_loan_customer_and_max_dpd):
                    max_dpd = payment.loan.grab_oldest_unpaid_payments[0].get_grab_dpd
                    if max_dpd < MINIMUM_DPD_VALUE:
                        continue
                    temp_grouped_dict = {
                        'loan_id': payment.loan.id,
                        'customer_id': payment.loan.customer.id,
                        'max_dpd': max_dpd
                    }
                    grouped_by_loan_customer_and_max_dpd.append(temp_grouped_dict)

        loan_customer_and_dpd = {}
        for item in grouped_by_loan_customer_and_max_dpd:
            loan_customer_and_dpd[item.get("loan_id")] = item
        # get all data with correct dpd required
        loan_ids_with_correct_dpd = []
        for data in loan_customer_and_dpd.values():
            loan_id = data.get('loan_id')
            max_dpd = data.get('max_dpd')
            is_loan_max_dpd_around_2_and_90_high_risk = 2 <= max_dpd <= 90 and rank in {1, 2}
            is_loan_max_dpd_around_7_and_90 = 7 <= max_dpd <= 90 and rank in {3, 4}
            is_loan_max_dpd_around_14_and_90 = 14 <= max_dpd <= 90 and rank in {5, 6}
            is_loan_max_dpd_around_2_and_90 = 2 <= max_dpd <= 90 and rank > 6
            is_loan_max_dpd_above_90 = max_dpd > 90
            if (is_loan_below_91 and is_loan_max_dpd_around_2_and_90) or (
                    not is_loan_below_91 and is_loan_max_dpd_above_90) or (
                    is_loan_below_91 and is_loan_max_dpd_around_2_and_90_high_risk) or (
                    is_loan_below_91 and is_loan_max_dpd_around_7_and_90) or (
                    is_loan_below_91 and is_loan_max_dpd_around_14_and_90):
                loan_ids_with_correct_dpd.append(loan_id)

        filtered_data_by_dpd = oldest_payment_qs.filter(loan_id__in=loan_ids_with_correct_dpd)

        if use_outstanding:
            loan_ids_with_correct_outstanding = []
            for payment in filtered_data_by_dpd.iterator():
                loan = payment.loan
                outstanding_amount = loan.payment_set.not_paid_active().aggregate(
                    Sum('due_amount'))['due_amount__sum'] or 0
                if is_above_100k and outstanding_amount > 100000:
                    loan_ids_with_correct_outstanding.append(loan.id)

            data = filtered_data_by_dpd.filter(loan_id__in=loan_ids_with_correct_outstanding)
        else:
            data = filtered_data_by_dpd

        return data

    def get_data_from_raw_query(
            self, rank, loan_xids_based_on_c_score_list=None, restructured_loan_ids_list=None):
        if loan_xids_based_on_c_score_list is None:
            loan_xids_based_on_c_score_list = []
        if restructured_loan_ids_list is None:
            restructured_loan_ids_list = []

        DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID = 2
        MINIMUM_DPD_VALUE = 2
        use_outstanding = False
        is_below_700k = False
        is_restructured = False
        is_loan_below_91 = True
        is_include_restructure_and_normal = False
        exclusion_filter = Q()
        inclusion_filter = {
            'loan__loan_status_id__in': LoanStatusCodes.grab_current_until_90_dpd(),
            'payment_status_id__in': {
                PaymentStatusCodes.PAYMENT_DUE_TODAY,
                PaymentStatusCodes.PAYMENT_1DPD,
                PaymentStatusCodes.PAYMENT_5DPD,
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_60DPD,
                PaymentStatusCodes.PAYMENT_90DPD
            },
            'is_restructured': False,
            'loan__account__account_lookup__workflow__name': WorkflowConst.GRAB
        }
        is_above_100k = False

        if rank == 1:
            # high risk without restructure loan
            use_outstanding = True
            is_above_100k = True
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 2:
            # high risk only restructure loan
            is_restructured = True
            use_outstanding = True
            is_above_100k = True
            restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
                restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
            ) if restructured_loan_ids_list else []
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 3:
            # medium risk without restructure loan
            use_outstanding = True
            is_above_100k = True
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 4:
            # medium risk only restructure loan
            is_restructured = True
            use_outstanding = True
            is_above_100k = True
            restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
                restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
            ) if restructured_loan_ids_list else []
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 5:
            # low risk without restructure loan
            use_outstanding = True
            is_above_100k = True
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 6:
            # low risk only restructure loan
            is_restructured = True
            use_outstanding = True
            is_above_100k = True
            restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
                restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
            ) if restructured_loan_ids_list else []
            inclusion_filter.update({'loan__loan_xid__in': loan_xids_based_on_c_score_list})

        elif rank == 7:
            use_outstanding = True
            is_above_100k = True
            exclusion_filter = exclusion_filter | Q(loan__loan_xid__in=GrabIntelixCScore.objects.filter(
                cscore__range=(200, 800)).values_list('loan_xid', flat=True))
        elif rank == 8:
            is_restructured = True
            restructured_loan_ids_list = get_not_paid_loan_in_last_2_days_custom(
                restructured_loan_ids_list, DURATION_IN_DAYS_FOR_RESTRUCTURED_UNPAID
            ) if restructured_loan_ids_list else []
            exclusion_filter = exclusion_filter | Q(loan__loan_xid__in=GrabIntelixCScore.objects.filter(
                cscore__range=(200, 800)).values_list('loan_xid', flat=True))
        else:
            raise Exception("INVALID RANK FOR GRAB AI_RUDDER RANK({})".format(rank))

        """
        check if both data should be included
        if not then check it is should be restructured only data or normal data only
        """
        if not is_include_restructure_and_normal:
            if not is_restructured:
                exclusion_filter = exclusion_filter | (Q(loan_id__in=restructured_loan_ids_list))
            else:
                inclusion_filter.update({'loan_id__in': restructured_loan_ids_list})

        grab_loan_data_set = GrabLoanData.objects.only(
            'loan_halt_date', 'loan_resume_date', 'id', 'loan_id', 'is_repayment_capped')
        prefetch_grab_loan_data = Prefetch(
            'loan__grabloandata_set', to_attr='grab_loan_data_set', queryset=grab_loan_data_set)

        oldest_unpaid_payments_queryset = Payment.objects.only(
            'id', 'loan_id', 'due_date', 'payment_status_id'
        ).not_paid_active().order_by('due_date')
        prefetch_oldest_unpaid_payments = Prefetch(
            'loan__payment_set', to_attr="grab_oldest_unpaid_payments",
            queryset=oldest_unpaid_payments_queryset)

        prefetch_join_tables = [
            prefetch_oldest_unpaid_payments,
            prefetch_grab_loan_data
        ]

        oldest_payment_qs = Payment.objects.select_related('loan').prefetch_related(
            *prefetch_join_tables
        ).filter(
            **inclusion_filter
        ).exclude(
            exclusion_filter
        )
        total_oldest_payment_qs = oldest_payment_qs.count()
        split_threshold = 5000
        grouped_by_loan_customer_and_max_dpd = []
        final_list = list()
        for iterator in list(range(0, total_oldest_payment_qs, split_threshold)):
            oldest_payment_qs_sliced = Payment.objects.select_related('loan').prefetch_related(
                *prefetch_join_tables
            ).filter(
                **inclusion_filter
            ).exclude(
                exclusion_filter
            )[iterator:iterator + split_threshold]

            """
            group the data by loan_id and max_dpd
            e.g:
            [
                {'loan_id': 3000009060, 'loan__customer_id': 10001, 'max_dpd': 487},
                {'loan_id': 3000009075, 'loan__customer_id': 10001, 'max_dpd': 695},
                {'loan_id': 3000009083, 'loan__customer_id': 10003, 'max_dpd': 695}
            ]
            """
            for payment in oldest_payment_qs_sliced:
                if not any(
                        d['loan_id'] == payment.loan.id and d['customer_id'] == payment.loan.customer.id
                        for d in grouped_by_loan_customer_and_max_dpd):
                    max_dpd = payment.loan.grab_oldest_unpaid_payments[0].get_grab_dpd
                    if max_dpd < MINIMUM_DPD_VALUE:
                        continue
                    temp_grouped_dict = {
                        'loan_id': payment.loan.id,
                        'payment_id': payment.id,
                        'due_date': payment.loan.grab_oldest_unpaid_payments[0].due_date,
                        'customer_id': payment.loan.customer.id
                    }
                    grouped_by_loan_customer_and_max_dpd.append(temp_grouped_dict)
            for i in grouped_by_loan_customer_and_max_dpd:
                final_list.append([i['loan_id'], i['payment_id'], i['due_date']])
        return final_list

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    def side_effect_get_redis_data_temp_table(redis_key):
        first_loan = Loan.objects.first()
        payments_from_first_loan = Payment.objects.filter(loan_id=first_loan.id)
        payment_ids_from_first_loan = [payment.id for payment in payments_from_first_loan]
        if redis_key == 'ai_rudder_grab_temp_data_coll_ids|GRAB|batch_1':
            return payment_ids_from_first_loan

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    def test_cron_trigger_sent_to_ai_rudder_with_no_data(self, mocked_logger):
        cron_trigger_sent_to_ai_rudder()
        mocked_logger.info.assert_called_with({
            "action": "cron_trigger_sent_to_ai_rudder",
            "message": "No constructed data in GrabConstructedCollectionDialerTemporaryData table"
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    def test_cron_trigger_sent_to_ai_rudder_with_no_dialer_task_data(self, mocked_logger):
        self.insert_data_to_grab_constructed_collection_dailer()
        cron_trigger_sent_to_ai_rudder()
        mocked_logger.info.assert_called_with({
            "action": "cron_trigger_sent_to_ai_rudder",
            "message": "No grab upload dialer task"
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    def test_cron_trigger_sent_to_ai_rudder_with_dialer_task_event_data(self, mocked_logger):
        self.insert_data_to_grab_constructed_collection_dailer()
        upload_dialer_task = self.insert_date_to_dialer_task()
        DialerTaskEvent.objects.create(
            dialer_task=upload_dialer_task,
            status=DialerTaskStatus.GRAB_AI_RUDDER_TRIGGER_SENT_BATCH
        )
        cron_trigger_sent_to_ai_rudder()
        mocked_logger.info.assert_called_with({
            "action": "cron_trigger_sent_to_ai_rudder",
            "message": "already triggered the sent data"
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    def test_cron_trigger_sent_to_ai_rudder_with_no_dialer_task_event_data(self, mocked_logger):
        self.insert_data_to_grab_constructed_collection_dailer()
        self.insert_date_to_dialer_task()
        cron_trigger_sent_to_ai_rudder()
        mocked_logger.info.assert_called_with({
            "action": "cron_trigger_sent_to_ai_rudder",
            "message": "No batch data has been constructed"
        })

    def test_fetch_sorted_grab_constructed_data(self):
        current_time = timezone.localtime(timezone.now())
        today_min = datetime.combine(current_time, time.min)
        today_max = datetime.combine(current_time, time.max)
        self.insert_data_to_grab_constructed_collection_dailer()
        grab_constructed_data = fetch_sorted_grab_constructed_data(today_min, today_max)
        if grab_constructed_data:
            self.assertEqual(len(grab_constructed_data), 3)
            self.assertEqual(grab_constructed_data[0]['sort_order'], 1)
            self.assertEqual(grab_constructed_data[0]['outstanding'], 70000)
            self.assertEqual(grab_constructed_data[0]['dpd'], 40)

            self.assertEqual(grab_constructed_data[1]['sort_order'], 2)
            self.assertEqual(grab_constructed_data[1]['outstanding'], 60000)
            self.assertEqual(grab_constructed_data[1]['dpd'], 50)

            self.assertEqual(grab_constructed_data[2]['sort_order'], 3)
            self.assertEqual(grab_constructed_data[2]['outstanding'], 50000)
            self.assertEqual(grab_constructed_data[2]['dpd'], 60)

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.send_grab_failed_deduction_slack.delay')
    def test_cron_trigger_sent_to_ai_rudder_success(self, mocked_send_grab_failed_deduction_slack,
                                                    mock_get_redis_client, mock_set_temp):
        self.insert_data_to_grab_constructed_collection_dailer()
        upload_dialer_task = self.insert_date_to_dialer_task()
        batch_num = 1
        GrabTask.objects.create(
            task_id='111111',
            task_type='grab_ai_rudder_constructed_batch_1',
            status='SUCCESS'
        )
        create_history_dialer_task_event(dict(
            dialer_task=upload_dialer_task,
            status=DialerTaskStatus.GRAB_AI_RUDDER_BEFORE_PROCESS_CONSTRUCT_BATCH.format(batch_num)
        ))
        mocked_redis = mock.MagicMock()
        mocked_redis.delete_key.return_value = None
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_set_temp.return_value = True
        cron_trigger_sent_to_ai_rudder()
        self.assertEqual(mocked_send_grab_failed_deduction_slack.called, True)

    def test_fetch_sorted_grab_constructed_data_for_duplicate(self):
        current_time = timezone.localtime(timezone.now())
        today_min = datetime.combine(current_time, time.min)
        today_max = datetime.combine(current_time, time.max)
        self.insert_data_to_grab_constructed_collection_dailer()
        today = timezone.localtime(timezone.now()).date()
        today_str = datetime.strftime(today, "%Y-%m-%d")
        outstanding_amount = 50000
        dpd = 60
        sort_order = 3

        grab_collection_dialer_temp_datas = GrabCollectionDialerTemporaryData.objects.order_by('id')[:1]
        for grab_collection_dialer_temp_data in grab_collection_dialer_temp_datas:
            payment = (
                Payment.objects.select_related('loan').filter(pk=grab_collection_dialer_temp_data.payment_id).last()
            )
            if not payment:
                continue
            loan = payment.loan
            if loan.status not in set(LoanStatusCodes.grab_current_until_180_dpd()):
                continue
            account = loan.account
            application = account.last_application
            if not application:
                continue
            zip_code = application.address_kodepos
            denda = 0
            GrabConstructedCollectionDialerTemporaryData.objects.create(
                application_id=grab_collection_dialer_temp_data.application_id,
                customer_id=grab_collection_dialer_temp_data.customer_id,
                nama_customer=grab_collection_dialer_temp_data.nama_customer,
                nama_perusahaan=grab_collection_dialer_temp_data.nama_perusahaan,
                posisi_karyawan=grab_collection_dialer_temp_data.posisi_karyawan,
                nama_pasangan=grab_collection_dialer_temp_data.nama_pasangan,
                nama_kerabat=grab_collection_dialer_temp_data.nama_kerabat,
                hubungan_kerabat=grab_collection_dialer_temp_data.hubungan_kerabat,
                jenis_kelamin=grab_collection_dialer_temp_data.jenis_kelamin,
                tgl_lahir=grab_collection_dialer_temp_data.tgl_lahir,
                tgl_gajian=grab_collection_dialer_temp_data.tgl_gajian,
                tujuan_pinjaman=grab_collection_dialer_temp_data.tujuan_pinjaman,
                tanggal_jatuh_tempo=grab_collection_dialer_temp_data.tanggal_jatuh_tempo,
                alamat=grab_collection_dialer_temp_data.alamat,
                kota=grab_collection_dialer_temp_data.kota,
                tipe_produk=grab_collection_dialer_temp_data.tipe_produk,
                partner_name=grab_collection_dialer_temp_data.partner_name,
                account_payment_id=grab_collection_dialer_temp_data.account_payment_id,
                dpd=dpd,
                team=grab_collection_dialer_temp_data.team,
                loan_id=None,
                payment_id=None,
                mobile_phone_1='0837347373',
                mobile_phone_2='0837347373',
                telp_perusahaan='0837347373',
                denda=denda,
                outstanding=outstanding_amount,
                angsuran_ke='',
                no_telp_pasangan='0837347373',
                no_telp_kerabat='0837347373',
                tgl_upload=today_str,
                va_bca='',
                va_permata='',
                va_maybank='',
                va_alfamart='',
                va_indomaret='',
                campaign="JULO",
                jumlah_pinjaman=1700000,
                tenor=None,
                last_agent='',
                last_call_status='',
                customer_bucket_type="Fresh",
                zip_code=zip_code,
                disbursement_period='',
                repeat_or_first_time='',
                account_id=payment.loan.account_id,
                is_j1=False,
                Autodebit="Tidak Aktif",
                refinancing_status='',
                activation_amount='',
                program_expiry_date='',
                promo_untuk_customer='',
                last_pay_date='',
                last_pay_amount=0,
                status_tagihan={"1_status_tagihan": "26 Jan 2018; 327; 1885000"},
                sort_order=sort_order
            )
        grab_constructed_data = fetch_sorted_grab_constructed_data(today_min, today_max)
        self.assertEqual(len(grab_constructed_data), 3)

    @mock.patch(
        'juloserver.minisquad.tasks2.'
        'dialer_system_task_grab.process_construct_grab_data_to_ai_rudder')
    def test_failed_without_populated_dialer_task_data(self, mock_construct_dialer_data):
        with self.assertRaises(Exception) as context:
            process_and_send_grab_data_to_ai_rudder()
        self.assertTrue("data to ai rudder still not populated" in str(context.exception))
        mock_construct_dialer_data.assert_not_called()

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.process_construct_grab_data_to_ai_rudder')
    def test_failed_no_batching_dialer_task_event(self, mock_construct_dialer_data):
        rank = 1
        populated_dialer_task = DialerTask.objects.create(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name),
            vendor=DialerSystemConst.AI_RUDDER_PDS
        )

        create_history_dialer_task_event(
            dict(dialer_task=populated_dialer_task,
                 status=DialerTaskStatus.GRAB_AI_RUDDER_QUERIED_RANK.format(rank)
                 )
        )
        with self.assertRaises(Exception) as context:
            process_and_send_grab_data_to_ai_rudder()

        self.assertTrue("doesn't have ai rudder batching log" in str(context.exception))
        mock_construct_dialer_data.assert_not_called()

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_eligible_grab_ai_rudder_payment_for_dialer')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.process_construct_grab_data_to_ai_rudder'
    )
    def test_failed_no_processed_dialer_task_event(
        self,
        mock_construct_dialer_data,
        mock_delete_redis_key,
        mock_get_redis_client,
        mock_eligible_grab_payment_data,
    ):
        loan = Loan.objects.first()
        payments = Payment.objects.filter(loan_id=loan.id)
        list_account_ids = []
        for payment in payments:
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]
        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()
        with self.assertRaises(Exception) as context:
            process_and_send_grab_data_to_ai_rudder()
            self.assertTrue("doesn't have ai rudder processed log" in str(context.exception))
        mock_construct_dialer_data.assert_not_called()

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'send_data_to_ai_rudder_with_retries_mechanism_grab.delay'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.get_eligible_grab_ai_rudder_payment_for_dialer'
    )
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix'
    )
    def test_failed_with_empty_temporary_data(
        self,
        mock_delete_redis_key,
        mock_get_redis_client,
        mock_eligible_grab_payment_data,
        mock_send_data_to_ai_rudder,
    ):
        loan = Loan.objects.first()
        rank = 1
        page_num = 1
        payments = Payment.objects.filter(loan_id=loan.id)
        payment_ids = []
        list_account_ids = []
        for payment in payments:
            payment_ids.append(payment.id)
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]
        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()

        populate_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name
            )
        ).first()

        restructured_loan_ids_list = []
        loan_xids_based_on_c_score_list = []

        for rank in range(1, 9):
            populate_grab_temp_data_by_rank_ai_rudder(
                rank,
                populate_dialer_task,
                self.bucket_name,
                restructured_loan_ids_list,
                loan_xids_based_on_c_score_list,
            )

            mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(  # noqa
                RedisKey.AI_RUDDER_CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                    self.bucket_name, rank, page_num
                ),
                payment_ids,
            )

            process_grab_populate_temp_data_for_dialer_ai_rudder(
                rank, self.bucket_name, page_num, populate_dialer_task.id
            )

        GrabCollectionDialerTemporaryData.objects.all().delete()
        process_and_send_grab_data_to_ai_rudder()
        upload_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_UPLOAD_GRAB
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=upload_dialer_task).last()
        self.assertEqual(dialer_task_event.status, DialerTaskStatus.FAILURE)
        mock_send_data_to_ai_rudder.assert_not_called()

    def test_get_loans_based_on_c_score_success(self):
        ranks = list(range(1, 7))
        grab_intelix_cscore = GrabIntelixCScoreFactory(
            loan_xid=self.loan.loan_xid,
            grab_user_id=123,
            vehicle_type='type1',
            cscore=250,
            customer_id=self.customer.id,
        )
        cscore = 0
        for rank in ranks:
            if rank % 2 == 1:
                cscore += 250
            grab_intelix_cscore.cscore = cscore
            grab_intelix_cscore.save()
            return_value = get_loans_based_on_c_score(rank)
            self.assertEqual(self.loan.loan_xid, return_value[0])

    def test_get_loans_based_on_c_score_failure(self):
        return_value = get_loans_based_on_c_score(10)
        self.assertIsNone(return_value)

    def test_get_jumlah_pinjaman_intelix_grab_success(self):
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name
        )
        fetch_temp_ids = grab_collection_temp_data_list_ids[0:total_count]
        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        grab_temp = grab_payments.filter(payment_id=self.first_payment.id).last()
        first_payment = Payment.objects.get(pk=grab_temp.payment_id)
        self.grab_loan_data_2.is_repayment_capped = False

        total_loan_amount = 1000000
        return_value = get_jumlah_pinjaman_ai_rudder_grab(first_payment)
        self.assertEqual(total_loan_amount, return_value)

    def test_get_angsuran_for_intelix_grab_success(self):
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name
        )
        fetch_temp_ids = grab_collection_temp_data_list_ids[0:total_count]
        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        grab_temp = grab_payments.filter(payment_id=self.first_payment.id).last()
        first_payment = Payment.objects.get(pk=grab_temp.payment_id)
        total_installment_amount = self.loan_2.installment_amount + self.loan_3.installment_amount
        return_value = get_angsuran_for_ai_rudder_grab(first_payment)
        self.assertEqual(return_value, total_installment_amount)

    def test_get_angsuran_for_intelix_grab_failure(self):
        total_installment_amount = 0
        return_value = get_angsuran_for_ai_rudder_grab(None)
        self.assertEqual(return_value, total_installment_amount)

    def test_check_grab_customer_bucket_type(self):
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name
        )
        fetch_temp_ids = grab_collection_temp_data_list_ids[0:total_count]
        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        grab_temp = grab_payments.filter(payment_id=self.first_payment.id).last()
        first_payment = Payment.objects.get(pk=grab_temp.payment_id)
        return_value = check_grab_customer_bucket_type(first_payment)
        self.assertEqual(return_value, 'Fresh')

    @mock.patch('juloserver.minisquad.services2.airudder.get_grab_active_ptp_account_ids')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'send_data_to_ai_rudder_with_retries_mechanism_grab.delay'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.get_eligible_grab_ai_rudder_payment_for_dialer'
    )
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix'
    )
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_redis_data_temp_table')
    def test_success_send_temporary_data_to_ai_rudder(
        self,
        mock_get_data_temp,
        mock_delete_redis_key,
        mock_get_redis_client,
        mock_eligible_grab_payment_data,
        mock_send_data_to_ai_rudder,
        mocked_redis_delete,
        mock_active_ptp,
    ):
        loan = Loan.objects.first()
        page_num = 1
        payments = Payment.objects.filter(loan_id=loan.id)
        payment_ids = [payment.id for payment in payments]
        list_account_ids = []
        for payment in payments:
            payment_ids.append(payment.id)
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)

        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]
        mock_delete_redis_key.return_value = True
        mocked_redis = mock.MagicMock()
        mocked_redis.delete_key.return_value = None
        mocked_redis_delete.return_value = mocked_redis
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        mocked_active_ptp_value = [[i] for i in range(1, 11)]
        mock_active_ptp.side_effect = mocked_active_ptp_value

        today = timezone.localtime(timezone.now()).date()
        grab_collection_dialer_temp_data_list = (
            GrabCollectionDialerTemporaryData.objects.filter(
                team=self.bucket_name, cdate__date=today
            )
            .order_by('sort_order')
            .values_list('id', flat=True)
        )

        def custom_side_effect_get_redis_data_temp_table(redis_key):
            if redis_key == 'ai_rudder_grab_temp_data_coll_ids|GRAB|batch_1':
                return grab_collection_dialer_temp_data_list
            return payment_ids

        populate_grab_temp_data_for_ai_rudder_dialer()

        populate_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name
            )
        ).first()

        mock_get_data_temp.side_effect = custom_side_effect_get_redis_data_temp_table

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd(),
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()
        loan_xids_based_on_c_score_list = []
        for rank in range(1, 9):
            if grab_intellix_cscore_obj and rank not in (7, 8):
                loan_xids_based_on_c_score_list = get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            populate_grab_temp_data_by_rank_ai_rudder(
                rank,
                populate_dialer_task,
                self.bucket_name,
                restructured_loan_ids_list,
                loan_xids_based_on_c_score_list,
            )

            process_grab_populate_temp_data_for_dialer_ai_rudder(
                rank, self.bucket_name, page_num, populate_dialer_task.id
            )

        def custom_side_effect_get_grab_populated_data_for_calling(bucket_name, temporary_id_list):
            from django.db.models import Prefetch

            filter_dict = dict(team=bucket_name, cdate__date=today, id__in=temporary_id_list)
            populated_call_dialer_data = GrabCollectionDialerTemporaryData.objects.filter(
                **filter_dict
            )
            return populated_call_dialer_data

        process_and_send_grab_data_to_ai_rudder()

        upload_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_UPLOAD_GRAB
        ).first()
        process_construct_grab_data_to_ai_rudder(
            bucket_name=self.bucket_name, batch_num=1, dialer_task_id=upload_dialer_task.id
        )
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=upload_dialer_task).last()
        self.assertEqual(
            dialer_task_event.status, DialerTaskStatus.GRAB_AI_RUDDER_STORED_BATCH.format(1)
        )

    def test_construct_grab_data_for_sent_to_ai_rudder_by_temp_data_success(self):
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name
        )
        fetch_temp_ids = grab_collection_temp_data_list_ids[0:total_count]
        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        populated_temp_data = grab_payments[0]
        first_payment = Payment.objects.get(pk=populated_temp_data.payment_id)
        application = Application.objects.get(pk=populated_temp_data.application_id)

        phone_numbers = {
            'company_phone_number': '',
            'kin_mobile_phone': self.application.kin_mobile_phone,
            'spouse_mobile_phone': self.application.spouse_mobile_phone,
            'mobile_phone_1': self.application.mobile_phone_1,
            'mobile_phone_2': '',
        }
        others, last_pay_details, outstanding_amount = construct_additional_data_for_intelix_grab(
            first_payment
        )

        zip_code = application.address_kodepos
        last_agent = ''
        last_call_status = ''
        repeat_or_first_time = ''
        disbursement_period = ''
        partner_name = ''
        autodebet_status = "Tidak Aktif"
        today = timezone.localtime(timezone.now()).date()
        today_str = datetime.strftime(today, "%Y-%m-%d")
        params = {
            "loan_id": None,
            "payment_id": None,
            "mobile_phone_1": phone_numbers['mobile_phone_1'],
            "mobile_phone_2": phone_numbers['mobile_phone_2'],
            "telp_perusahaan": phone_numbers['company_phone_number'],
            "angsuran/bulan": get_angsuran_for_ai_rudder_grab(first_payment),
            "denda": get_late_fee_amount_intelix_grab(first_payment),
            "outstanding": outstanding_amount,
            "angsuran_ke": '',
            "no_telp_pasangan": phone_numbers['spouse_mobile_phone'],
            "no_telp_kerabat": phone_numbers['kin_mobile_phone'],
            "tgl_upload": today_str,
            "va_bca": "",
            "va_permata": "",
            "va_maybank": "",
            "va_alfamart": "",
            "va_indomaret": "",
            "campaign": "JULO",
            "jumlah_pinjaman": get_jumlah_pinjaman_ai_rudder_grab(first_payment),
            "tenor": None,
            "partner_name": partner_name,
            "last_agent": last_agent,
            "last_call_status": last_call_status,
            "customer_bucket_type": check_grab_customer_bucket_type(first_payment),
            "zip_code": zip_code,
            'disbursement_period': disbursement_period,
            'repeat_or_first_time': repeat_or_first_time,
            'account_id': first_payment.loan.account_id,
            'is_j1': False,
            'Autodebit': autodebet_status,
            'refinancing_status': '',
            'activation_amount': '',
            'program_expiry_date': '',
            'promo_untuk_customer': '',
        }

        expected_output = {
            'application_id': populated_temp_data.application_id,
            'customer_id': populated_temp_data.customer_id,
            'nama_customer': populated_temp_data.nama_customer,
            'nama_perusahaan': populated_temp_data.nama_perusahaan,
            'posisi_karyawan': populated_temp_data.posisi_karyawan,
            'nama_pasangan': populated_temp_data.nama_pasangan,
            'nama_kerabat': populated_temp_data.nama_kerabat,
            'hubungan_kerabat': populated_temp_data.hubungan_kerabat,
            'jenis_kelamin': populated_temp_data.jenis_kelamin,
            'tgl_lahir': populated_temp_data.tgl_lahir,
            'tgl_gajian': populated_temp_data.tgl_gajian,
            'tujuan_pinjaman': populated_temp_data.tujuan_pinjaman,
            'tanggal_jatuh_tempo': populated_temp_data.tanggal_jatuh_tempo,
            'alamat': populated_temp_data.alamat,
            'kota': populated_temp_data.kota,
            'tipe_produk': populated_temp_data.tipe_produk,
            'partner_name': populated_temp_data.partner_name,
            'account_payment_id': populated_temp_data.account_payment_id,
            'dpd': populated_temp_data.dpd,
            'team': populated_temp_data.team,
            'loan_id': populated_temp_data.loan_id,
            'payment_id': populated_temp_data.payment_id,
        }
        expected_output.update(params)
        expected_output.update(others)
        expected_output.update(last_pay_details)
        constructed_data = construct_grab_data_for_sent_to_intelix_by_temp_data(grab_payments)
        self.assertDictEqual(expected_output, constructed_data[0])

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'send_data_to_ai_rudder_with_retries_mechanism_grab.delay'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.get_eligible_grab_ai_rudder_payment_for_dialer'
    )
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix'
    )
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_redis_data_temp_table')
    def test_success_split_process_and_send_grab_data_to_ai_rudder(
        self,
        mock_get_data_temp,
        mock_delete_redis_key,
        mock_get_redis_client,
        mock_eligible_grab_payment_data,
        mock_send_data_to_ai_rudder,
        mocked_redis_delete,
    ):
        loan = Loan.objects.first()
        rank = 1
        page_num = 1
        payments = Payment.objects.filter(loan_id=loan.id)
        payment_ids = []
        list_account_ids = []
        for payment in payments:
            payment_ids.append(payment.id)
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]
        mock_delete_redis_key.return_value = True
        mocked_redis = mock.MagicMock()
        mocked_redis.delete_key.return_value = None
        mocked_redis_delete.return_value = mocked_redis
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis

        today = timezone.localtime(timezone.now()).date()
        grab_collection_dialer_temp_data_list = GrabCollectionDialerTemporaryData.objects.filter(
            team=self.bucket_name, cdate__date=today
        ).order_by('sort_order').values_list('id', flat=True)

        def custom_side_effect_get_redis_data_temp_table(redis_key):
            if 'grab_temp_data_coll_ids' in redis_key:
                return grab_collection_dialer_temp_data_list[0:2]
            return payment_ids

        populate_grab_temp_data_for_ai_rudder_dialer()

        populate_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name)
        ).first()

        mock_get_data_temp.side_effect = custom_side_effect_get_redis_data_temp_table

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()
        loan_xids_based_on_c_score_list = []

        for rank in range(1, 9):
            if grab_intellix_cscore_obj and rank not in (7, 8):
                loan_xids_based_on_c_score_list = get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            populate_grab_temp_data_by_rank_ai_rudder(
                rank,
                populate_dialer_task,
                self.bucket_name,
                restructured_loan_ids_list,
                loan_xids_based_on_c_score_list,
            )

            process_grab_populate_temp_data_for_dialer_ai_rudder(
                rank, self.bucket_name, page_num, populate_dialer_task.id
            )

        # update send batch size to 2
        self.grab_ai_rudder_call_feature_setting.update_safely(
            parameters={
                'populate_schedule': '02:00',
                'send_schedule': '05:00',
                'grab_construct_batch_size': '2',
            }
        )
        self.grab_ai_rudder_call_feature_setting.refresh_from_db()
        process_and_send_grab_data_to_ai_rudder()
        upload_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_UPLOAD_GRAB
        ).first()
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name
        )
        fetching_data_batch_size = math.ceil(
            total_count
            / int(
                self.grab_ai_rudder_call_feature_setting.parameters.get('grab_construct_batch_size')
            )
        )
        dialer_task_event = DialerTaskEvent.objects.filter(
            dialer_task=upload_dialer_task, status__icontains='stored'
        )
        self.assertEqual(dialer_task_event.count(), fetching_data_batch_size)

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger.exception')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'send_data_to_ai_rudder_with_retries_mechanism_grab.delay'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'get_eligible_grab_ai_rudder_payment_for_dialer'
    )
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.delete_redis_key_list_with_prefix'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.get_starting_and_ending_index_temp_data'
    )
    def test_failed_split_process_and_send_grab_data_to_ai_rudder(
        self,
        mock_get_index_temp_data,
        mock_delete_redis_key,
        mock_get_redis_client,
        mock_eligible_grab_payment_data,
        mock_send_data_to_airudder,
        mocked_redis_delete,
        mocked_logger,
    ):
        loan = Loan.objects.first()
        page_num = 1
        payments = Payment.objects.filter(loan_id=loan.id)
        payment_ids = []
        list_account_ids = []
        for payment in payments:
            payment_ids.append(payment.id)
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]
        mock_delete_redis_key.return_value = True
        mocked_redis = mock.MagicMock()
        mocked_redis.delete_key.return_value = None
        mocked_redis_delete.return_value = mocked_redis
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_ai_rudder_dialer()

        populate_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name
            )
        ).first()

        restructured_loan_ids_list = []
        loan_xids_based_on_c_score_list = []

        for rank in range(1, 9):
            populate_grab_temp_data_by_rank_ai_rudder(
                rank,
                populate_dialer_task,
                self.bucket_name,
                restructured_loan_ids_list,
                loan_xids_based_on_c_score_list,
            )

            mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(  # noqa
                RedisKey.AI_RUDDER_CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                    self.bucket_name, rank, page_num
                ),
                payment_ids,
            )

            create_history_dialer_task_event(
                dict(
                    dialer_task=populate_dialer_task,
                    status=DialerTaskStatus.GRAB_AI_RUDDER_PROCESSED_POPULATED_GRAB_PAYMENTS.format(
                        self.bucket_name, rank, page_num
                    ),
                )
            )

        mock_get_index_temp_data.return_value = 0, None

        process_and_send_grab_data_to_ai_rudder()
        upload_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.GRAB_AI_RUDDER_UPLOAD_GRAB
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=upload_dialer_task).last()
        self.assertEqual(dialer_task_event.status, DialerTaskStatus.FAILURE)
        mock_send_data_to_airudder.assert_not_called()
        mocked_logger.assert_called_with(
            {
                "action": "process_and_send_grab_data_to_ai_rudder",
                'error': "Temporary Table(grab) is empty.",
            }
        )

    def test_remove_duplicate_data_with_lower_rank(self):
        GrabCollectionDialerTemporaryData.objects.all().delete()
        GrabCollectionDialerTemporaryData.objects.create(
            dpd=3, sort_order=1, customer_id=self.customer.id
        )
        GrabCollectionDialerTemporaryData.objects.create(
            dpd=4, sort_order=1, customer_id=self.customer.id
        )
        remove_duplicate_data_with_lower_rank()
        grab_collection_dialer_temporary_data = GrabCollectionDialerTemporaryData.objects.all()
        self.assertTrue(
            grab_collection_dialer_temporary_data.filter(
                dpd=4, customer_id=self.customer.id
            ).exists()
        )
        self.assertEqual(1, grab_collection_dialer_temporary_data.count())

    def test_grab_account_id_to_be_deleted_from_airudder_with_in_active_setting(self):

        self.grab_ai_rudder_delete_phone_number.is_active = False
        self.grab_ai_rudder_delete_phone_number.save()

        self.assertFalse(get_grab_account_id_to_be_deleted_from_airudder())

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.delete_grab_paid_payment_from_dialer_bulk'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.get_eligible_grab_ai_rudder_payment_for_dialer'
    )
    def test_grab_account_id_to_be_deleted_from_airudder_with_air_delete_call_not_called(
        self, mock_eligible_grab_payment_data, mock_delete_grab_paid_payment
    ):
        loan = Loan.objects.first()
        payments = Payment.objects.filter(loan_id=loan.id)[:2]
        payment_ids = []
        list_account_ids = []
        for payment in payments:
            payment_ids.append(payment.id)
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]
        get_grab_account_id_to_be_deleted_from_airudder()
        mock_delete_grab_paid_payment.delay.assert_not_called()

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.delete_grab_paid_payment_from_dialer_bulk'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.get_eligible_grab_ai_rudder_payment_for_dialer'
    )
    def test_grab_account_id_to_be_deleted_from_airudder_with_air_delete_call_called(
        self, mock_eligible_grab_payment_data, mock_delete_grab_paid_payment
    ):
        GrabTempAccountData.objects.create(account_id=12123)
        loan = Loan.objects.first()
        payments = Payment.objects.filter(loan_id=loan.id)[:2]
        payment_ids = []
        list_account_ids = []
        for payment in payments:
            payment_ids.append(payment.id)
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)
        mock_eligible_grab_payment_data.return_value = [(payments, list_account_ids)]

        get_grab_account_id_to_be_deleted_from_airudder()
        self.assertEqual(1, GrabTempAccountData.objects.count())
        mock_delete_grab_paid_payment.delay.assert_called()

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.delete_grab_paid_payment_from_dialer'
    )
    def test_delete_grab_paid_payment_from_dialer_bulk(
        self, mock_delete_grab_paid_payment_from_dialer
    ):

        loan = Loan.objects.first()
        payments = Payment.objects.filter(loan_id=loan.id)[:2]
        payment_ids = []
        list_account_ids = []
        for payment in payments:
            payment_ids.append(payment.id)
            loan = payment.loan
            if loan.account_id:
                list_account_ids.append(loan.account_id)

        delete_grab_paid_payment_from_dialer_bulk(list_account_ids)
        mock_delete_grab_paid_payment_from_dialer.assert_called()

    def test_add_account_in_temp_table_failure(self):
        loan = Loan.objects.first()
        self.grab_ai_rudder_delete_phone_number.is_active = False
        self.grab_ai_rudder_delete_phone_number.save()
        self.assertFalse(add_account_in_temp_table(loan))

    def test_add_account_in_temp_table_failure_with_already_account(self):
        loan = Loan.objects.first()
        self.assertFalse(add_account_in_temp_table(loan))

    def test_add_account_in_temp_table_success(self):
        loan = Loan.objects.first()
        GrabTempAccountData.objects.filter(account_id=self.account.id).delete()
        self.assertTrue(add_account_in_temp_table(loan))

    def clear_grab_temp_account_data(self):
        self.assertEqual(0, GrabTempAccountData.objects.count())


class TestDownloadAirCallResults(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB, handler='GrabWorkflowHandler')
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name='GRAB', payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990067,
            partner=partner,
            product_line=self.product_line,
            email='testing1_email@gmail.com',
            account=self.account
        )
        self.data1 = {
            "type": "TaskStatus",
            "body": {}
        }
        self.data2 = {
            "type": "AgentStatus",
            "body": ""
        }

        self.data3 = {
              "type": "AgentStatus",
              "body": {
                "agentName": "Julodemo1001",
                "registerState": "Registered",
                "State": "HANGUP",
                "callType": "",
                "taskId": "0eb6512129694be4a31440321ee7ee9f",
                "taskName": "STAGING-special_cohort_JTURBO_B3-20230919-0915-1",
                "groupName": "demoTeam1",
                "phoneNumber": "+6281288893327",
                "callid": "ec72fb62040142b4a84c2c4abf5da542",
                "contactName": "",
                "address": "",
                "info1": "",
                "info2": "",
                "info3": "",
                "remark": "",
                "privateData": "",
                "timestamp": "1695091377922",
                "talkResultLabel": "WA",
                "talkremarks": "feagagatrqt52513414fdvadfgafdfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgg",
                "mainNumber": "+6281288893327",
                "phoneTag": "",
                "curDayCallCount": {
                  "auto": 6,
                  "manual": 0
                },
                "curDayCallDuration": {
                  "auto": 1549,
                  "manual": 0
                },
                "curDayTalkResults": [
                  {
                    "talkResult": "Connected",
                    "count": 2
                  },
                  {
                    "talkResult": "NotConnected",
                    "count": 3
                  },
                  {
                    "talkResult": "WA",
                    "count": 1
                  },
                  {
                    "talkResult": "RPC",
                    "count": 0
                  },
                  {
                    "talkResult": "WPC",
                    "count": 1
                  },
                  {
                    "talkResult": "ShortCall",
                    "count": 1
                  },
                  {
                    "talkResult": "AnsweringMachine",
                    "count": 2
                  },
                  {
                    "talkResult": "BusyTone",
                    "count": 1
                  },
                  {
                    "talkResult": "Ringing",
                    "count": 0
                  },
                  {
                    "talkResult": "DeadCall",
                    "count": 0
                  },
                  {
                    "talkResult": "WAText",
                    "count": 1
                  },
                  {
                    "talkResult": "RPC-Regular",
                    "count": 0
                  },
                  {
                    "talkResult": "RPC-PTP",
                    "count": 0
                  },
                  {
                    "talkResult": "RPC-HTP",
                    "count": 0
                  },
                  {
                    "talkResult": "RPC-BrokenPromise",
                    "count": 0
                  },
                  {
                    "talkResult": "RPC-CallBack",
                    "count": 0
                  },
                  {
                    "talkResult": "WPC-Regular",
                    "count": 1
                  },
                  {
                    "talkResult": "WPC-LeftMessage",
                    "count": 0
                  },
                  {
                    "talkResult": "Child",
                    "count": 0
                  },
                  {
                    "talkResult": "CoWorker",
                    "count": 1
                  },
                  {
                    "talkResult": "Friend",
                    "count": 0
                  },
                  {
                    "talkResult": "Other",
                    "count": 0
                  },
                  {
                    "talkResult": "Parent",
                    "count": 0
                  },
                  {
                    "talkResult": "Sibling",
                    "count": 1
                  },
                  {
                    "talkResult": "Spouse",
                    "count": 0
                  },
                  {
                    "talkResult": "User",
                    "count": 0
                  },
                  {
                    "talkResult": "Banyak_cicilan/pinjaman_dari_tempat_lain",
                    "count": 0
                  },
                  {
                    "talkResult": "Bencana_Alam",
                    "count": 0
                  },
                  {
                    "talkResult": "Dana_terpakai_untuk_kebutuhan_mendesak",
                    "count": 0
                  },
                  {
                    "talkResult": "Indikasi_fraud",
                    "count": 0
                  },
                  {
                    "talkResult": "Jobless/Bangkrut",
                    "count": 0
                  },
                  {
                    "talkResult": "Kontak_tidak_bisa_dihubungi",
                    "count": 0
                  },
                  {
                    "talkResult": "Lupa_Tanggal_Pembayaran",
                    "count": 2
                  },
                  {
                    "talkResult": "Pembayaran_Gagal",
                    "count": 0
                  },
                  {
                    "talkResult": "Peminjam_digunakan_untuk_orang_lain",
                    "count": 0
                  },
                  {
                    "talkResult": "Peminjam_sedang_perjalanan_keluar_kota",
                    "count": 0
                  },
                  {
                    "talkResult": "Peminjam/orang_terdekat_terkena_musibah/kecelakaan",
                    "count": 0
                  },
                  {
                    "talkResult": "Pengajuan_Keringanan",
                    "count": 0
                  },
                  {
                    "talkResult": "Penghasilan_pekerjaan/bisnis_sedang_menurun",
                    "count": 0
                  },
                  {
                    "talkResult": "Perubahan_status_pekerjaan-perubahan_tanggal_gajian",
                    "count": 0
                  },
                  {
                    "talkResult": "Sakit_Kronis-Peminjam_Mengalami_Sakit_Kronis",
                    "count": 0
                  },
                  {
                    "talkResult": "Tidak_Bisa_Membuka_Aplikasi_JULO",
                    "count": 0
                  },
                  {
                    "talkResult": "Nasabah_meninggal",
                    "count": 0
                  },
                  {
                    "talkResult": "Tidak_mau_membayar",
                    "count": 0
                  },
                  {
                    "talkResult": "Others",
                    "count": 0
                  }
                ],
                "displayTalkResult": "",
                "isConcealCallee": "",
                "curDayOnlineDuration": 34397,
                "curDayRestDuration": 0,
                "curWaitingCallCount": 2,
                "groupUnallocatedCall": 0,
                "earliestCallWaitTime": 0,
                "threewayState": "",
                "threewayAccount": "",
                "customizeResults": {
                  "Level1": "WA",
                  "Level2": "WAText",
                  "Level3": "",
                  "PTP Amount": "",
                  "PTP Date": "",
                  "Spokewith": "",
                  "nopaymentreason": ""
                },
                "customerInfo": {
                  "account_id": "104184",
                  "account_payment_id": "260665",
                  "activation_amount": "31023",
                  "alamat": "shdhk Daerah Khusus Ibukota Jakarta Kota Jakarta Pusat Kecamatan Gambir Gambir 10110",
                  "angsuran_ke": "None",
                  "customer_bucket_type": "Fresh",
                  "customer_id": "1000244103",
                  "dpd": "60",
                  "hubungan_kerabat": "Orang tua",
                  "jenis_kelamin": "Pria",
                  "kota": "Kota Jakarta Pusat",
                  "last_pay_amount": "0",
                  "nama_customer": "prod only",
                  "nama_kerabat": "usiw",
                  "nama_perusahaan": "PT. Pgas Telekomunikasi Nusantara",
                  "no_telp_kerabat": "+62873942784",
                  "program_expiry_date": "2023-09-09",
                  "tanggal_jatuh_tempo": "2023-07-21",
                  "tgl_gajian": "1",
                  "tgl_lahir": "1997-05-24",
                  "tgl_upload": "2023-09-19",
                  "tipe_produk": "J-STARTER",
                  "total_denda": "134200",
                  "total_due_amount": "378223",
                  "total_outstanding": "378223",
                  "va_alfamart": "319320872896323",
                  "va_bca": "109940872896323",
                  "va_indomaret": "3193210872896323",
                  "va_mandiri": "8830822000284458",
                  "va_maybank": "78218220738052",
                  "va_permata": "85159820738052",
                  "zip_code": "10110"
                },
                "waitingDialNumber": 2,
                "totalNumber": 404,
                "holdTimestamp": 0,
                "holdDuration": {
                  "auto": 0,
                  "manual": 0
                }
              }
            }
        self.api = '/api/minisquad/grab/airudder/webhooks/'
        self.redis_data = {}
        self.bucket = DialerSystemConst.GRAB
        self.grab_ai_rudder_call_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_AI_RUDDER_CALL
        )
        self.grab_manual_upload_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_MANUAL_UPLOAD_FEATURE_FOR_AI_RUDDER
        )

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    def test_call_back_with_incorrect_callback_type(self):
        response = self.client.post(self.api, data=self.data1, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response_data['status'], 'skipped')

    def test_call_back_with_empty_callback_body(self):
        response = self.client.post(self.api, data=self.data2, format='json')
        response_data = response.json()
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertEqual(response_data['status'], 'failed')

    @mock.patch('juloserver.minisquad.views.grab_process_airudder_store_call_result.delay')
    def test_call_back_with_success(self, mock_grab_process_airudder_store_call_result):
        response = self.client.post(self.api, data=self.data3, format='json')
        response_data = response.json()
        self.assertEqual(mock_grab_process_airudder_store_call_result.called, True)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response_data['status'], 'success')

    def test_grab_failed_process_airudder_store_call_result(self):
        with self.assertRaises(Exception) as context:
            grab_process_airudder_store_call_result(self.data3, "test")
        self.assertTrue("Failed process store call result agent." in str(context.exception))

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.grab_store_call_result_agent')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_success_process_airudder_store_call_result(self, mock_air_service,
                                                             mock_grab_store_call_result_agent1,
                                                             mock_logger):

        with self.assertRaises(Exception) as context:
            grab_process_airudder_store_call_result(self.data3, "test")
        self.assertTrue("Failed process store call result agent." in str(context.exception))

        mock_logger.info.assert_called_once_with({
            'function_name': 'process_airudder_store_call_result',
            'message': 'Start running process_airudder_store_call_result',
            'data': self.data3,
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'grab_process_retroload_call_results.delay')
    def test_grab_consume_call_result_system_level_with_inactive_feature_setting(
            self, mock_grab_process_retroload_call_results,
            mock_logger):
        self.grab_ai_rudder_call_feature_setting.is_active = False
        self.grab_ai_rudder_call_feature_setting.save()
        self.grab_ai_rudder_call_feature_setting.refresh_from_db()
        grab_consume_call_result_system_level()

        mock_logger.info.assert_called_with({
            'action': 'grab_consume_call_result_system_level',
            'message': "Feature setting not found / inactive"
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'grab_process_retroload_call_results.delay')
    def test_grab_consume_call_result_system_level(self, mock_grab_process_retroload_call_results,
                                                   mock_logger):
        grab_consume_call_result_system_level()
        mock_logger.info.assert_called_with({
            'action': 'grab_consume_call_result_system_level',
            'message': 'sent to async task'
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    def test_grab_write_call_results_subtask_for_manual_upload_failure_with_incorrect_third_party(
            self,
            mock_logger):
        now = timezone.localtime(timezone.now())
        # example this task run at 09.15 AM
        # so we pull data in range 08.00 -08.59 AM
        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)
        with self.assertRaises(Exception) as context:
            grab_write_call_results_subtask_for_manual_upload(self.data, {}, start_time, 12344, '')
            self.assertTrue("Dialer system : selected third party is not handled yet")

    @mock.patch('juloserver.minisquad.services2.airudder.get_grab_task_ids_from_sent_to_dialer')
    @mock.patch('juloserver.minisquad.services2.airudder.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    def test_grab_process_retroload_call_results_with_empty_task(self,
                                                                 mock_logger,
                                                                 mock_airservice,
                                                                 mock_get_redis_client,
                                                                 mock_get_grab_task_ids_from_sent_to_dialer):
        now = timezone.localtime(timezone.now())
        # example this task run at 09.15 AM
        # so we pull data in range 08.00 -08.59 AM
        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(  # noqa
            RedisKey.AI_RUDDER_GRAB_DAILY_TASK_ID_FROM_DIALER,
            [], timedelta(hours=12)
        )
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_get_grab_task_ids_from_sent_to_dialer.return_value = None
        grab_process_retroload_call_results(start_time=start_time, end_time=end_time)

        mock_logger.info.assert_called_with({
            'action': 'grab_process_retroload_call_results',
            'message': 'tasks ids for date {} - {} is null'.format(
                str(start_time), str(end_time)
            ),
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_grab_task_ids_from_sent_to_dialer')
    @mock.patch('juloserver.minisquad.services2.airudder.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_process_retroload_call_results_with_task_empty_task(self,
                                                                      mock_airservice,
                                                                      mock_get_redis_client,
                                                                      mock_get_grab_task_ids_from_sent_to_dialer,
                                                                      mock_logger):
        now = timezone.localtime(timezone.now())
        # example this task run at 09.15 AM
        # so we pull data in range 08.00 -08.59 AM
        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)
        mock_get_grab_task_ids_from_sent_to_dialer.return_value = ['57bf2049f77e4285b1db2e1fc9391267']
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(  # noqa
            RedisKey.AI_RUDDER_GRAB_DAILY_TASK_ID_FROM_DIALER,
            mock_get_grab_task_ids_from_sent_to_dialer, timedelta(hours=12)
        )
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis

        mock_airservice.return_value.get_grab_call_results_data_by_task_id \
            .return_value = 0

        grab_process_retroload_call_results(start_time=start_time, end_time=end_time)

        mock_logger.info.assert_called_with({
            'action': 'grab_process_retroload_call_results',
            'message': 'all data in range {} - {} sent to async task'.format(start_time, end_time),
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.'
                'grab_process_retroload_call_results_sub_task.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.get_grab_task_ids_from_sent_to_dialer')
    @mock.patch('juloserver.minisquad.services2.airudder.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_process_retroload_call_results_with_task(self,
                                                           mock_airservice,
                                                           mock_get_redis_client,
                                                           mock_get_grab_task_ids_from_sent_to_dialer,
                                                           mock_logger,
                                                           mock_grab_process_retroload_call_results_sub_task
                                                           ):
        now = timezone.localtime(timezone.now())
        # example this task run at 09.15 AM
        # so we pull data in range 08.00 -08.59 AM
        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)
        mock_get_grab_task_ids_from_sent_to_dialer.return_value = ['57bf2049f77e4285b1db2e1fc9391267']
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(  # noqa
            RedisKey.AI_RUDDER_GRAB_DAILY_TASK_ID_FROM_DIALER,
            mock_get_grab_task_ids_from_sent_to_dialer, timedelta(hours=12)
        )
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis

        mock_airservice.return_value.get_grab_call_results_data_by_task_id \
            .return_value = [
            {
                "talkDuration": 0,
                "seScore": 0,
                "holdDuration": 0,
                "hangupReason": 3,
                "nthCall": 2,
                "taskId": "57bf2049f77e4285b1db2e1fc9391267",
                "taskName": "STAGING-GRAB-20231109-1645-1",
                "callid": "194bcf580650401bb8637ebff48b65f9",
                "phoneNumber": "+628989785585",
                "calltime": "2023-11-09T10:44:03Z",
                "ringtime": "2023-11-09T10:44:09Z",
                "answertime": "",
                "talktime": "",
                "endtime": "2023-11-09T10:44:19Z",
                "biztype": "demoTeam1",
                "agentName": "",
                "OrgName": "AICC_JULO_PDS_DEMO",
                "TaskStartTime": "2023-11-09T10:30:02Z",
                "talkResult": "",
                "remark": "",
                "talkremarks": "",
                "customerName": "",
                "callResultType": "NoAnswered",
                "callType": "auto",
                "mainNumber": "+628989785585",
                "phoneTag": "",
                "waitingDuration": 0,
                "talkedTime": 0,
                "seText": "No Survey Results",
                "adminAct": [],
                "reclink": "",
                "wfContactId": "",
                "transferReason": "",
                "customizeResults": [
                    {
                        "title": "Level1",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Level2",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Level3",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Spokewith",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "nopaymentreason",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "PTP Date",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "PTP Amount",
                        "groupName": "",
                        "value": ""
                    }
                ],
                "qaInfo": []
            }
        ]
        grab_process_retroload_call_results(start_time=start_time, end_time=end_time)
        mock_grab_process_retroload_call_results_sub_task.assert_called()
        mock_logger.info.assert_called_with({
            'action': 'grab_process_retroload_call_results',
            'message': 'all data in range {} - {} sent to async task'.format(start_time, end_time),
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.'
                'grab_construct_call_results.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_process_retroload_call_results_sub_task(self,
                                                           mock_airservice,
                                                           mock_logger,
                                                           mock_grab_construct_call_results
                                                           ):
        now = timezone.localtime(timezone.now())
        # example this task run at 09.15 AM
        # so we pull data in range 08.00 -08.59 AM
        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)

        mock_airservice.return_value.get_grab_call_results_data_by_task_id \
            .return_value = [
            {
                "talkDuration": 0,
                "seScore": 0,
                "holdDuration": 0,
                "hangupReason": 3,
                "nthCall": 2,
                "taskId": "57bf2049f77e4285b1db2e1fc9391267",
                "taskName": "STAGING-GRAB-20231109-1645-1",
                "callid": "194bcf580650401bb8637ebff48b65f9",
                "phoneNumber": "+628989785585",
                "calltime": "2023-11-09T10:44:03Z",
                "ringtime": "2023-11-09T10:44:09Z",
                "answertime": "",
                "talktime": "",
                "endtime": "2023-11-09T10:44:19Z",
                "biztype": "demoTeam1",
                "agentName": "",
                "OrgName": "AICC_JULO_PDS_DEMO",
                "TaskStartTime": "2023-11-09T10:30:02Z",
                "talkResult": "",
                "remark": "",
                "talkremarks": "",
                "customerName": "",
                "callResultType": "NoAnswered",
                "callType": "auto",
                "mainNumber": "+628989785585",
                "phoneTag": "",
                "waitingDuration": 0,
                "talkedTime": 0,
                "seText": "No Survey Results",
                "adminAct": [],
                "reclink": "",
                "wfContactId": "",
                "transferReason": "",
                "customizeResults": [
                    {
                        "title": "Level1",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Level2",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Level3",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Spokewith",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "nopaymentreason",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "PTP Date",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "PTP Amount",
                        "groupName": "",
                        "value": ""
                    }
                ],
                "qaInfo": []
            }
        ]
        task_id = '57bf2049f77e4285b1db2e1fc9391267'
        grab_process_retroload_call_results_sub_task(task_id=task_id, start_time=start_time, end_time=end_time)
        mock_grab_construct_call_results.assert_called()
        mock_logger.info.assert_called_with({
            'action': 'grab_process_retroload_call_results_sub_task',
            'task_id': task_id,
            'message': 'all data sent to async task'
        })


    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'grab_process_retroload_call_results.delay')
    def test_grab_retroload_air_call_result_for_manual_upload_with_inactive_feature_setting(
            self, mock_grab_process_retroload_call_results,
            mock_logger):
        self.grab_manual_upload_feature_setting.is_active = False
        self.grab_manual_upload_feature_setting.save()
        self.grab_manual_upload_feature_setting.refresh_from_db()
        grab_retroload_air_call_result_for_manual_upload()

        mock_logger.info.assert_called_with({
            'action': 'grab_retroload_air_call_result_for_manual_upload',
            'message': "Manual upload Ai rudder Feature setting not found / inactive"
        })


    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'grab_retroload_air_call_result_sub_task_for_manual_upload.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_retroload_air_call_result_for_manual_upload(
            self,
            mock_airservice,
            mock_grab_retroload_air_call_result_sub_task_for_manual_upload,
            mock_logger
    ):
        mock_airservice.return_value.get_group_name_by_bucket \
            .return_value = 'test'
        grab_retroload_air_call_result_for_manual_upload()
        self.assertEqual(mock_grab_retroload_air_call_result_sub_task_for_manual_upload.call_count, 2)
        mock_logger.info.assert_called_with({
            'action': 'grab_retroload_air_call_result_for_manual_upload',
            'message': 'sent to async task'
        })

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'grab_retroload_air_call_result_sub_task_for_manual_upload.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_retroload_air_call_result_for_manual_upload_with_invalid_group_name(
            self,
            mock_airservice,
            mock_grab_retroload_air_call_result_sub_task_for_manual_upload
    ):
        mock_airservice.return_value.get_group_name_by_bucket \
            .return_value = None
        grab_retroload_air_call_result_for_manual_upload()
        mock_grab_retroload_air_call_result_sub_task_for_manual_upload.assert_not_called()


    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_retroload_air_call_result_sub_task_for_manual_upload_failure_with_no_task(
            self,
            mock_airservice,
            mock_logger
    ):
        now = timezone.localtime(timezone.now())
        # example this task run at 09.15 AM
        # so we pull data in range 08.00 -08.59 AM
        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)
        mock_airservice.return_value.get_list_of_task_id_with_date_range_and_group \
            .return_value = []

        grab_retroload_air_call_result_sub_task_for_manual_upload(group_name='test',
                                                                  start_time=start_time,
                                                                  end_time=end_time)
        mock_logger.info.assert_called_with({
            'action': 'grab_retroload_air_call_result_sub_task_for_manual_upload',
                        'message': 'tasks ids for date {} - {} is null'.format(
                        str(start_time), str(end_time)
                    ),
        })

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.'
                'grab_retroload_for_manual_upload_sub_task.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_retroload_air_call_result_sub_task_for_manual_upload_success(
        self,
        mock_airservice,
        mock_logger,
        mock_grab_retroload_for_manual_upload_sub_task
    ):
        now = timezone.localtime(timezone.now())
        # example this task run at 09.15 AM
        # so we pull data in range 08.00 -08.59 AM
        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)
        group_name = 'test'
        mock_airservice.return_value.get_list_of_task_id_with_date_range_and_group \
            .return_value = ['57bf2049f77e4285b1db2e1fc9391267@@test@@web@@STAGING-GRAB-20231109-1645-1']

        grab_retroload_air_call_result_sub_task_for_manual_upload(group_name='test',
                                                                  start_time=start_time,
                                                                  end_time=end_time)
        mock_grab_retroload_for_manual_upload_sub_task.assert_called()
        mock_logger.info.assert_called_with({
            'action': 'grab_retroload_air_call_result_sub_task_for_manual_upload',
            'message': 'all data in range {} - {} sent to async task'.format(start_time, end_time),
        })


    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.'
        'grab_construct_call_results_for_manual_upload.delay')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.logger')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task_grab.AIRudderPDSServices')
    def test_grab_retroload_air_call_result_sub_task_for_manual_upload_success(
        self,
        mock_airservice,
        mock_logger,
        mock_grab_construct_call_results_for_manual_upload
    ):
        now = timezone.localtime(timezone.now())
        # example this task run at 09.15 AM
        # so we pull data in range 08.00 -08.59 AM
        start_time = now.replace(hour=now.hour - 1, minute=0, second=0)
        end_time = start_time.replace(minute=59, second=59)
        task_detail= '57bf2049f77e4285b1db2e1fc9391267@@test@@web@@STAGING-GRAB-20231109-1645-1'

        grab_retroload_for_manual_upload_sub_task(
            task_id='57bf2049f77e4285b1db2e1fc9391267',
            task_name='STAGING-GRAB-20231109-1645-1',
            start_time=start_time, end_time=end_time,
            dialer_third_party_service=DialerSystemConst.AI_RUDDER_PDS,
            task_detail=task_detail
        )
        mock_airservice.return_value.get_grab_call_results_data_by_task_id \
            .return_value = [
            {
                "talkDuration": 0,
                "seScore": 0,
                "holdDuration": 0,
                "hangupReason": 3,
                "nthCall": 2,
                "taskId": "57bf2049f77e4285b1db2e1fc9391267",
                "taskName": "STAGING-GRAB-20231109-1645-1",
                "callid": "194bcf580650401bb8637ebff48b65f9",
                "phoneNumber": "+628989785585",
                "calltime": "2023-11-09T10:44:03Z",
                "ringtime": "2023-11-09T10:44:09Z",
                "answertime": "",
                "talktime": "",
                "endtime": "2023-11-09T10:44:19Z",
                "biztype": "demoTeam1",
                "agentName": "",
                "OrgName": "AICC_JULO_PDS_DEMO",
                "TaskStartTime": "2023-11-09T10:30:02Z",
                "talkResult": "",
                "remark": "",
                "talkremarks": "",
                "customerName": "",
                "callResultType": "NoAnswered",
                "callType": "auto",
                "mainNumber": "+628989785585",
                "phoneTag": "",
                "waitingDuration": 0,
                "talkedTime": 0,
                "seText": "No Survey Results",
                "adminAct": [],
                "reclink": "",
                "wfContactId": "",
                "transferReason": "",
                "customizeResults": [
                    {
                        "title": "Level1",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Level2",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Level3",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "Spokewith",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "nopaymentreason",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "PTP Date",
                        "groupName": "",
                        "value": ""
                    },
                    {
                        "title": "PTP Amount",
                        "groupName": "",
                        "value": ""
                    }
                ],
                "qaInfo": []
            }
        ]
        mock_grab_construct_call_results_for_manual_upload.assert_called()

    @mock.patch("juloserver.minisquad.views.process_airudder_store_call_result.delay")
    @mock.patch('juloserver.minisquad.views.grab_process_airudder_store_call_result.delay')
    def test_jturbo_callback(
        self,
        mock_grab_process_airudder_store_call_result,
        mock_process_airudder_store_call_result
    ):
        api = '/api/minisquad/airudder/webhooks/'
        response = self.client.post(api, data=self.data3, format='json')
        response_data = response.json()
        self.assertEqual(mock_grab_process_airudder_store_call_result.called, False)
        self.assertEqual(mock_process_airudder_store_call_result.called, True)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response_data['status'], 'success')

    @mock.patch("juloserver.minisquad.views.process_airudder_store_call_result.delay")
    @mock.patch('juloserver.minisquad.views.grab_process_airudder_store_call_result.delay')
    def test_jturbo_callback_with_grab_task(
        self,
        mock_grab_process_airudder_store_call_result,
        mock_process_airudder_store_call_result
    ):
        api = '/api/minisquad/airudder/webhooks/'
        self.data3["body"].update({"taskName": "STAGING-GRAB-20231109-1645-1"})
        response = self.client.post(api, data=self.data3, format='json')
        response_data = response.json()
        self.assertEqual(mock_grab_process_airudder_store_call_result.called, True)
        self.assertEqual(mock_process_airudder_store_call_result.called, False)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response_data['status'], 'success')


class TestAIRudderPDSServices(TestCase):
    def setUp(self):
        self.data = {
            "type": "AgentStatus",
            "body": {
                "agentName": "Julodemo1001",
                "registerState": "Registered",
                "State": "HANGUP",
                "callType": "",
                "taskId": "0eb6512129694be4a31440321ee7ee9f",
                "taskName": "STAGING-special_cohort_JTURBO_B3-20230919-0915-1",
                "groupName": "demoTeam1",
                "phoneNumber": "",
                "callid": "ec72fb62040142b4a84c2c4abf5da542",
                "contactName": "",
                "address": "",
                "info1": "",
                "info2": "",
                "info3": "",
                "remark": "",
                "privateData": "",
                "timestamp": "1695091377922",
                "talkResultLabel": "WA",
                "talkremarks": "feagagatrqt52513414fdvadfgafdfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgfeagagatrqt52513414fdvadfgafdgg",
                "mainNumber": "+6281288893327",
                "phoneTag": "",
                "curDayCallCount": {
                    "auto": 6,
                    "manual": 0
                },
                "curDayCallDuration": {
                    "auto": 1549,
                    "manual": 0
                },
                "curDayTalkResults": [
                    {
                        "talkResult": "Connected",
                        "count": 2
                    },
                    {
                        "talkResult": "NotConnected",
                        "count": 3
                    },
                    {
                        "talkResult": "WA",
                        "count": 1
                    },
                    {
                        "talkResult": "RPC",
                        "count": 0
                    },
                    {
                        "talkResult": "WPC",
                        "count": 1
                    },
                    {
                        "talkResult": "ShortCall",
                        "count": 1
                    },
                    {
                        "talkResult": "AnsweringMachine",
                        "count": 2
                    },
                    {
                        "talkResult": "BusyTone",
                        "count": 1
                    },
                    {
                        "talkResult": "Ringing",
                        "count": 0
                    },
                    {
                        "talkResult": "DeadCall",
                        "count": 0
                    },
                    {
                        "talkResult": "WAText",
                        "count": 1
                    },
                    {
                        "talkResult": "RPC-Regular",
                        "count": 0
                    },
                    {
                        "talkResult": "RPC-PTP",
                        "count": 0
                    },
                    {
                        "talkResult": "RPC-HTP",
                        "count": 0
                    },
                    {
                        "talkResult": "RPC-BrokenPromise",
                        "count": 0
                    },
                    {
                        "talkResult": "RPC-CallBack",
                        "count": 0
                    },
                    {
                        "talkResult": "WPC-Regular",
                        "count": 1
                    },
                    {
                        "talkResult": "WPC-LeftMessage",
                        "count": 0
                    },
                    {
                        "talkResult": "Child",
                        "count": 0
                    },
                    {
                        "talkResult": "CoWorker",
                        "count": 1
                    },
                    {
                        "talkResult": "Friend",
                        "count": 0
                    },
                    {
                        "talkResult": "Other",
                        "count": 0
                    },
                    {
                        "talkResult": "Parent",
                        "count": 0
                    },
                    {
                        "talkResult": "Sibling",
                        "count": 1
                    },
                    {
                        "talkResult": "Spouse",
                        "count": 0
                    },
                    {
                        "talkResult": "User",
                        "count": 0
                    },
                    {
                        "talkResult": "Banyak_cicilan/pinjaman_dari_tempat_lain",
                        "count": 0
                    },
                    {
                        "talkResult": "Bencana_Alam",
                        "count": 0
                    },
                    {
                        "talkResult": "Dana_terpakai_untuk_kebutuhan_mendesak",
                        "count": 0
                    },
                    {
                        "talkResult": "Indikasi_fraud",
                        "count": 0
                    },
                    {
                        "talkResult": "Jobless/Bangkrut",
                        "count": 0
                    },
                    {
                        "talkResult": "Kontak_tidak_bisa_dihubungi",
                        "count": 0
                    },
                    {
                        "talkResult": "Lupa_Tanggal_Pembayaran",
                        "count": 2
                    },
                    {
                        "talkResult": "Pembayaran_Gagal",
                        "count": 0
                    },
                    {
                        "talkResult": "Peminjam_digunakan_untuk_orang_lain",
                        "count": 0
                    },
                    {
                        "talkResult": "Peminjam_sedang_perjalanan_keluar_kota",
                        "count": 0
                    },
                    {
                        "talkResult": "Peminjam/orang_terdekat_terkena_musibah/kecelakaan",
                        "count": 0
                    },
                    {
                        "talkResult": "Pengajuan_Keringanan",
                        "count": 0
                    },
                    {
                        "talkResult": "Penghasilan_pekerjaan/bisnis_sedang_menurun",
                        "count": 0
                    },
                    {
                        "talkResult": "Perubahan_status_pekerjaan-perubahan_tanggal_gajian",
                        "count": 0
                    },
                    {
                        "talkResult": "Sakit_Kronis-Peminjam_Mengalami_Sakit_Kronis",
                        "count": 0
                    },
                    {
                        "talkResult": "Tidak_Bisa_Membuka_Aplikasi_JULO",
                        "count": 0
                    },
                    {
                        "talkResult": "Nasabah_meninggal",
                        "count": 0
                    },
                    {
                        "talkResult": "Tidak_mau_membayar",
                        "count": 0
                    },
                    {
                        "talkResult": "Others",
                        "count": 0
                    }
                ],
                "displayTalkResult": "",
                "isConcealCallee": "",
                "curDayOnlineDuration": 34397,
                "curDayRestDuration": 0,
                "curWaitingCallCount": 2,
                "groupUnallocatedCall": 0,
                "earliestCallWaitTime": 0,
                "threewayState": "",
                "threewayAccount": "",
                "customizeResults": {
                    "Level1": "WA",
                    "Level2": "WAText",
                    "Level3": "",
                    "PTP Amount": "10000",
                    "PTP Date": "2022-09-13",
                    "Spokewith": "",
                    "nopaymentreason": ""
                },
                "customerInfo": {
                    "account_id": "104184",
                    "account_payment_id": "260665",
                    "activation_amount": "31023",
                    "alamat": "shdhk Daerah Khusus Ibukota Jakarta Kota Jakarta Pusat Kecamatan Gambir Gambir 10110",
                    "angsuran_ke": "None",
                    "customer_bucket_type": "Fresh",
                    "customer_id": "1000244103",
                    "dpd": "60",
                    "hubungan_kerabat": "Orang tua",
                    "jenis_kelamin": "Pria",
                    "kota": "Kota Jakarta Pusat",
                    "last_pay_amount": "0",
                    "nama_customer": "prod only",
                    "nama_kerabat": "usiw",
                    "nama_perusahaan": "PT. Pgas Telekomunikasi Nusantara",
                    "no_telp_kerabat": "+62873942784",
                    "program_expiry_date": "2023-09-09",
                    "tanggal_jatuh_tempo": "2023-07-21",
                    "tgl_gajian": "1",
                    "tgl_lahir": "1997-05-24",
                    "tgl_upload": "2023-09-19",
                    "tipe_produk": "J-STARTER",
                    "total_denda": "134200",
                    "total_due_amount": "378223",
                    "total_outstanding": "378223",
                    "va_alfamart": "319320872896323",
                    "va_bca": "109940872896323",
                    "va_indomaret": "3193210872896323",
                    "va_mandiri": "8830822000284458",
                    "va_maybank": "78218220738052",
                    "va_permata": "85159820738052",
                    "zip_code": "10110"
                },
                "waitingDialNumber": 2,
                "totalNumber": 404,
                "holdTimestamp": 0,
                "holdDuration": {
                    "auto": 0,
                    "manual": 0
                }
            }
        }
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990080,
            partner=partner,
            product_line=self.product_line,
            email='testing_email11@gmail.com',
            account=self.account
        )
        code = StatusLookupFactory(status_code=220)
        loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=code, application=self.application)

        self.payment = PaymentFactory(loan=loan, installment_principal=10000000)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.payment.account_payment = self.account_payment
        self.payment.save()

        self.data1 = {
            "customizeResults":
                {
                    "PTP Amount": "20000",
                    "ptp_date": "2023-10-11"
                }
        }
        self.data2 = {
            "customizeResults":
                {
                    "PTP Amount": "",
                    "ptp_date": ""
                }
        }

    @mock.patch('juloserver.minisquad.services2.ai_rudder_pds.get_julo_ai_rudder_pds_client')
    def test_construct_skiptrace_history_data_with_ptp(self, mock_get_julo_ai_rudder_pds_client):
        self.air_service = AIRudderPDSServices()
        is_success_construct_skiptrace, msg, data = self.air_service.construct_skiptrace_history_data(
            self.data
        )
        self.assertEqual(is_success_construct_skiptrace, False)
        self.assertEqual(msg, "Phone number not valid, please provide valid phone number!")

        data_body = self.data['body']
        data_body['phoneNumber'] = '+6281288893327'
        is_success_construct_skiptrace, msg, data = self.air_service.construct_skiptrace_history_data(
            self.data
        )
        self.assertEqual(is_success_construct_skiptrace, False)
        self.assertEqual(msg, "Agent name not valid, please provide valid agent name")

        self.user.username = 'Julodemo1001'
        self.user.save()

        is_success_construct_skiptrace, msg, data = self.air_service.construct_skiptrace_history_data(
            self.data
        )
        self.assertEqual(is_success_construct_skiptrace, False)
        self.assertEqual(msg, "account_id is not valid")
        body_customer_info = self.data['body']['customerInfo']
        body_customer_info['account_id'] = self.account.id
        body_customer_info['account_payment_id'] = self.account_payment.id
        is_success_construct_skiptrace, msg, data = self.air_service.construct_skiptrace_history_data(
            self.data
        )
        self.account_payment = (self.account.accountpayment_set.not_paid_active().
                                order_by('-id').filter(id=self.account_payment.id).last())
        self.payment = Payment.objects.filter(account_payment=self.account_payment).first()
        self.assertEqual(self.account_payment.ptp_amount, 10000)
        self.assertEqual(self.payment.ptp_amount, 10000)

        is_exists = PTP.objects.filter(account_payment=self.account_payment).exists()
        self.assertTrue(is_exists)

    @mock.patch('juloserver.minisquad.services2.ai_rudder_pds.logger.info')
    @mock.patch('juloserver.minisquad.services2.ai_rudder_pds.get_julo_ai_rudder_pds_client')
    def test_update_grab_ptp_details(self, mock_get_julo_ai_rudder_pds_client,
                                     mocked_logger):
        self.air_service = AIRudderPDSServices()
        self.user.username = 'Julodemo1001'
        self.user.save()
        ptp_notes = self.air_service.update_grab_ptp_details(
            self.data1,
            self.account_payment,
            self.user,
            None
        )

        self.payment = Payment.objects.filter(account_payment=self.account_payment).first()
        self.assertEqual(self.account_payment.ptp_amount, 20000)
        self.assertEqual(self.payment.ptp_amount, 20000)
        self.assertEqual(ptp_notes, "Promise to Pay %s -- %s " % (
            self.account_payment.ptp_amount,
            self.account_payment.ptp_date))
        customize_res = self.data1.get('customizeResults', {})
        mocked_logger.assert_called_with({
            "action": "ptp_create_v2",
            "account_payment_id": self.account_payment.id,
            "ptp_date": customize_res.get('ptp_date', ''),
            "ptp_amount": customize_res.get('PTP Amount', ''),
            "agent_user": self.user.id,
            "function": 'update_grab_ptp_details',
            "source": "Grab Consume",
        })

        ptp_notes = self.air_service.update_grab_ptp_details(
            self.data1,
            self.account_payment,
            self.user,
            None
        )
        self.assertEqual(ptp_notes, '')


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class DeleteGrabPaidPaymentFromDialerTestCase(TestCase):

    def setUp(self):
        self.account = AccountFactory()
        self.application = ApplicationFactory(
            account=self.account, mobile_phone_1='08123456779')
        self.sent_to_dialer = SentToDialerFactory(
            account=self.account, task_id='unit_test_task_id', bucket=AiRudder.GRAB)
        self.sent_to_dialer.cdate = datetime(
            2023, 5, 15, 15, 30, 0)
        self.sent_to_dialer.save()
        self.redis_data = {}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('django.utils.timezone.localtime')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.get_list_of_task_id_today')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient.refresh_token')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient._make_request')
    def test_delete_paid_payment_from_dialer(
            self, mock_cancel_phone_call_by_phone_numbers, mock_token, mock_task_list, mock_redis,
            mock_time
    ):
        mock_time.return_value = datetime(2023, 5, 15, 15, 30, 0)
        mock_response = mock.Mock()
        responses = {
            "code": 0, "message": AIRudderPDSConstant.SUCCESS_MESSAGE_RESPONSE, "body": ['+6281232413101']
        }
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        mock_response.text = json.dumps(responses)
        mock_response.status_code = 200
        mock_cancel_phone_call_by_phone_numbers.return_value = mock_response
        mock_token.return_value = 'token_unittest'
        mock_task_list.return_value = ['task_unittest_id']

        result = delete_grab_paid_payment_from_dialer.delay(
            self.account.id, DialerSystemConst.AI_RUDDER_PDS)
        self.assertTrue(result)

    @mock.patch('django.utils.timezone.localtime')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.get_list_of_task_id_today')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient.refresh_token')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient._make_request')
    def test_delete_paid_payment_from_dialer_with_no_mobile_phone_1(
            self, mock_cancel_phone_call_by_phone_numbers, mock_token, mock_task_list, mock_redis,
            mock_time
    ):
        mock_time.return_value = datetime(2023, 5, 15, 15, 30, 0)
        mock_response = mock.Mock()
        responses = {
            "code": 0, "message": AIRudderPDSConstant.SUCCESS_MESSAGE_RESPONSE,
            "body": ['+6281232413101']
        }
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        mock_response.text = json.dumps(responses)
        mock_response.status_code = 200
        mock_cancel_phone_call_by_phone_numbers.return_value = mock_response
        mock_token.return_value = 'token_unittest'
        mock_task_list.return_value = ['task_unittest_id']
        self.application.mobile_phone_1 = None
        self.application.save()
        with self.assertRaises(Exception):
            delete_grab_paid_payment_from_dialer.delay(
                self.account.id, DialerSystemConst.AI_RUDDER_PDS)
        mock_cancel_phone_call_by_phone_numbers.assert_not_called()

    @mock.patch('django.utils.timezone.localtime')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.get_list_of_task_id_today')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient.refresh_token')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient._make_request')
    def test_delete_paid_payment_from_dialer_with_cancel_failure(
            self, mock_cancel_phone_call_by_phone_numbers, mock_token, mock_task_list, mock_redis,
            mock_time):
        mock_time.return_value = datetime(2023, 5, 15, 15, 30, 0)
        mock_response = mock.Mock()
        responses = {'message': 'error', 'code': 0}
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        mock_response.text = json.dumps(responses)
        mock_response.status_code = 200
        mock_cancel_phone_call_by_phone_numbers.return_value = mock_response
        mock_token.return_value = 'token_unittest'
        mock_task_list.return_value = ['task_unittest_id']
        with self.assertRaises(Exception):
            delete_grab_paid_payment_from_dialer(
                self.account.id, DialerSystemConst.AI_RUDDER_PDS)

    @mock.patch('juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.'
                'do_delete_phone_numbers_from_call_queue')
    @mock.patch('django.utils.timezone.localtime')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.get_redis_client')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient.refresh_token')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient._make_request')
    def test_grab_delete_single_call_from_calling_queue(
            self, mock_req, mock_token,  mock_redis,
            mock_time, mock_delete_number):
        airudder_services = AIRudderPDSServices()
        mock_time.return_value = datetime(2023, 5, 15, 15, 30, 0)
        mock_response = mock.Mock()
        responses = {'message': 'error', 'code': 0}
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        mock_response.text = json.dumps(responses)
        mock_response.status_code = 200
        mock_req.return_value = mock_response
        mock_token.return_value = 'token_unittest'

        self.account1 = AccountFactory()
        self.assertEqual(airudder_services.grab_delete_single_call_from_calling_queue(self.account1), False)
        self.sent_to_dialer.task_id = None
        self.sent_to_dialer.save()
        with self.assertRaises(Exception) as e:
            airudder_services.grab_delete_single_call_from_calling_queue(self.account)
        self.assertTrue(str(e), "AI Rudder task_id is empty in sent_to_dialer")

        self.sent_to_dialer.task_id = 'unit_test_task_id'
        self.sent_to_dialer.save()
        mock_delete_number.return_value = True, None
        self.assertEqual(airudder_services.grab_delete_single_call_from_calling_queue(self.account), True)


class TestGrabAIRudderPopulatingService(TestCase):
    def setUp(self):
        ProductLookupFactory()

        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.status_lookup = StatusLookupFactory()
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )

        payment_status_lookup = StatusLookupFactory(status_code=PaymentStatusCodes.PAYMENT_90DPD)
        loan_status = StatusLookupFactory(status_code=LoanStatusCodes.LOAN_90DPD)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)

        self.loans_xid = set()
        self.loans_id = set()
        self.payment_list = set()
        self.intelix_cscore_ids = []
        for counter in range(5):
            base = 1000003890
            user = AuthUserFactory()
            customer = CustomerFactory(user=user)
            account = AccountFactory(
                customer=customer,
                status=self.status_lookup,
                account_lookup=self.account_lookup,
                cycle_day=1
            )
            AccountPaymentFactory(account=account)
            partner = PartnerFactory(user=user, is_active=True)
            application = ApplicationFactory(
                customer=customer,
                workflow=self.workflow,
                application_xid=base+counter+10,
                partner=partner,
                product_line=product_line,
                email='testing_email{}@gmail.com'.format(counter),
                account=account
            )
            loan = LoanFactory(
                account=account,
                customer=customer,
                loan_amount=10000000,
                loan_xid=base+counter,
                is_restructured=False,
                loan_status=loan_status,
                application_id2=application.id
            )
            loan.application_id2 = application.id
            loan.save()
            GrabLoanDataFactory(loan=loan, account_halt_info=json.dumps([{
                "account_halt_date": "2024-01-01",
                "account_resume_date": "2024-02-01"
            }]))
            self.loans_id.add(loan.id)
            self.loans_xid.add(loan.loan_xid)

            intelix_cscore = GrabIntelixCScoreFactory(
                cscore=random.randint(200, 800),
                loan_xid=loan.loan_xid,
                customer_id=customer.id
            )
            self.intelix_cscore_ids.append(intelix_cscore.id)

            payment = PaymentFactory(loan=loan, installment_principal=10000000)
            self.payment_list.add(payment.id)
            account_payment = AccountPaymentFactory(account=account)
            payment.account_payment = account_payment
            payment.payment_status = payment_status_lookup
            payment.due_date = timezone.localtime(timezone.now()) - timedelta(
                days=random.randint(2, 90)
            )
            payment.save()

    @mock.patch("juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.update_dpd_on_cscore_table")
    @mock.patch("juloserver.minisquad.services2.airudder.GrabAIRudderPopulatingService.process_loans_xid")
    def test_prepare_data(self, mock_process_loans_xid, mock_update_dpd_on_cscore_table):
        mock_process_loans_xid.return_value = {}, Q()
        service = GrabAIRudderPopulatingService()
        service.prepare_loan_with_csore_data()
        mock_process_loans_xid.assert_called()
        mock_update_dpd_on_cscore_table.assert_called()

    def test_get_loans_id_from_payment(self):
        service = GrabAIRudderPopulatingService()
        loans_xid = self.loans_xid
        loans_id = service.get_loans_id_from_payment(loans_xid=loans_xid)
        self.assertEqual(len(loans_xid), len(loans_id))

    def test_get_oldest_not_paid_active_payment(self):
        service = GrabAIRudderPopulatingService()
        oldest_not_paid_payment = service.get_oldest_unpaid_active_payment(
            loans_id=list(self.loans_id)
        )
        self.assertEqual(
            self.loans_id,
            oldest_not_paid_payment.get('loan_oldest_payment_loan_list')
        )
        self.assertEqual(
            self.payment_list,
            oldest_not_paid_payment.get('loan_oldest_payment_list')
        )

        for loan_id in self.loans_id:
            self.assertTrue(loan_id in oldest_not_paid_payment['loan_oldest_payment_mapping'])

    def test_get_payment_data(self):
        grab_loan_data_set = GrabLoanData.objects.only(
            'loan_halt_date', 'loan_resume_date', 'account_halt_info',
            'id', 'loan_id', 'is_repayment_capped')

        prefetch_grab_loan_data = Prefetch(
            'loan__grabloandata_set',
            to_attr='grab_loan_data_set',
            queryset=grab_loan_data_set
        )

        service = GrabAIRudderPopulatingService()
        payment_queryset = service.get_payment_data(
            payments_id=self.payment_list,
            prefetch_join_tables=[prefetch_grab_loan_data]
        )
        self.assertEqual(payment_queryset.count(), len(self.payment_list))

    def test_update_dpd(self):
        service = GrabAIRudderPopulatingService()
        service.prepare_loan_with_csore_data()
        cscore_qs = GrabIntelixCScore.objects.filter(loan_xid__in=self.loans_xid)
        for i in cscore_qs:
            self.assertNotEqual(i.dpd, 0)
            self.assertTrue(i.dpd is not None)
            self.assertNotEqual(i.outstanding_amount, None)
            self.assertEqual(i.outstanding_amount, 0)
        self.assertEqual(cscore_qs.count(), len(self.loans_xid))

    def test_build_query_grab_intelix_cscore(self):
        service = GrabAIRudderPopulatingService()
        grab_intelix_cscore = GrabIntelixCScore.objects.all()

        param = {
            "score": [{"min": 200, "max": 250}],
            "dpd": [{"min": 2, "max": 70}]
        }
        grab_intelix_cscore.update(cscore=200, dpd=2)
        qs_based_on_cscore = service.build_query_grab_intelix_csore(param)

        self.assertEqual(grab_intelix_cscore.count(), qs_based_on_cscore.count())

    def test_build_query_grab_intelix_cscore_with_duplicate_data(self):
        service = GrabAIRudderPopulatingService()
        grab_intelix_cscore = GrabIntelixCScore.objects.filter(id__in=self.intelix_cscore_ids)

        param = {
            "score": [{"min": 200, "max": 250}],
            "dpd": [{"min": 2, "max": 70}]
        }
        grab_intelix_cscore.update(cscore=200, dpd=2, customer_id=123)
        qs_based_on_cscore = service.build_query_grab_intelix_csore(param)

        self.assertEqual(grab_intelix_cscore.count(), qs_based_on_cscore.count())

    def test_build_query_grab_intelix_cscore_no_valid_cscore(self):
        service = GrabAIRudderPopulatingService()
        grab_intelix_cscore = GrabIntelixCScore.objects.filter(id__in=self.intelix_cscore_ids)

        param = {
            "score": [{"min": 200, "max": 250}],
            "dpd": [{"min": 2, "max": 70}]
        }

        grab_intelix_cscore.update(cscore=250, dpd=2)
        qs_based_on_cscore = service.build_query_grab_intelix_csore(param)
        self.assertEqual(qs_based_on_cscore.count(), 0)

    def test_build_query_grab_intelix_cscore_no_valid_dpd(self):
        service = GrabAIRudderPopulatingService()
        grab_intelix_cscore = GrabIntelixCScore.objects.filter(id__in=self.intelix_cscore_ids)

        param = {
            "score": [{"min": 200, "max": 250}],
            "dpd": [{"min": 2, "max": 70}]
        }

        grab_intelix_cscore.update(cscore=200, dpd=71)
        qs_based_on_cscore = service.build_query_grab_intelix_csore(param)
        self.assertEqual(qs_based_on_cscore.count(), 0)

    def test_build_query_grab_intelix_cscore_with_category(self):
        service = GrabAIRudderPopulatingService()
        grab_intelix_cscore = GrabIntelixCScore.objects.filter(id__in=self.intelix_cscore_ids)

        param = {
            "score": [{"min": 200, "max": 250}],
            "dpd": [{"min": 2, "max": 70}],
            "category": ["4W"]
        }
        grab_intelix_cscore.update(cscore=200, dpd=2, vehicle_type="4W")
        qs_based_on_cscore = service.build_query_grab_intelix_csore(param)
        self.assertEqual(grab_intelix_cscore.count(), qs_based_on_cscore.count())

    def test_build_query_grab_intelix_cscore_no_valid_vehicle_type(self):
        service = GrabAIRudderPopulatingService()
        grab_intelix_cscore = GrabIntelixCScore.objects.filter(id__in=self.intelix_cscore_ids)

        param = {
            "score": [{"min": 200, "max": 250}],
            "dpd": [{"min": 2, "max": 70}],
            "category": ["4W"]
        }
        grab_intelix_cscore.update(cscore=200, dpd=2, vehicle_type="2W")
        qs_based_on_cscore = service.build_query_grab_intelix_csore(param)
        self.assertEqual(qs_based_on_cscore.count(), 0)

    def test_get_dynamic_eligible_grab_ai_rudder_payment_for_dialer(self):
        service = GrabAIRudderPopulatingService()
        service.prepare_loan_with_csore_data()

        param = {
            "score": [{"min": 200, "max": 800}],
            "dpd": [{"min": 2, "max": 90}]
        }
        for payment_qs, account_list in service.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer(param):
            self.assertEqual(payment_qs.count(), len(account_list))

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.process_exclude_for_grab_sent_dialer_per_part_ai_rudder')
    @mock.patch("juloserver.minisquad.services2.intelix.get_redis_client")
    def test_populate_grab_temp_data_by_dynamic_rank_ai_rudder(self, mock_get_redis_client, mock_process_exclude):
        mock_get_redis_client.return_value = None
        service = GrabAIRudderPopulatingService()
        service.prepare_loan_with_csore_data()

        param = {
            "rank": "1",
            "score": [{"min": 200, "max": 800}],
            "dpd": [{"min": 2, "max": 90}]
        }

        bucket_name = AiRudder.GRAB
        dialer_task = DialerTask.objects.create(
            vendor=DialerSystemConst.AI_RUDDER_PDS,
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name)
        )

        populate_grab_temp_data_by_dynamic_rank_ai_rudder(param, dialer_task, bucket_name)
        mock_process_exclude.delay.assert_called()

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task_grab.process_exclude_for_grab_sent_dialer_per_part_ai_rudder')
    @mock.patch("juloserver.minisquad.services2.intelix.get_redis_client")
    def test_populate_grab_temp_data_by_dynamic_rank_ai_rudder_multiple_rank(self, mock_redis_client, mock_process_exclude):
        mock_redis_client.return_value = None
        service = GrabAIRudderPopulatingService()
        service.prepare_loan_with_csore_data()

        params = [
            {
                "rank": "1",
                "score": [{"min": 200, "max": 400}],
                "dpd": [{"min": 2, "max": 90}]
            },
            {
                "rank": "2",
                "score": [{"min": 400, "max": 800}],
                "dpd": [{"min": 2, "max": 90}]
            },
        ]

        cscore = GrabIntelixCScore.objects.filter(loan_xid__in=self.loans_xid)
        cscore_rank1 = cscore[:(cscore.count()/2)+1].values_list('id', flat=True)
        GrabIntelixCScore.objects.filter(id__in=cscore_rank1).update(cscore=300, dpd=20)
        cscore_rank2 = cscore[(cscore.count()/2)+1:].values_list('id', flat=True)
        GrabIntelixCScore.objects.filter(id__in=cscore_rank2).update(cscore=500, dpd=20)

        bucket_name = AiRudder.GRAB
        dialer_task = DialerTask.objects.create(
            vendor=DialerSystemConst.AI_RUDDER_PDS,
            type=DialerTaskType.GRAB_AI_RUDDER_POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name)
        )

        for param in params:
            populate_grab_temp_data_by_dynamic_rank_ai_rudder(param, dialer_task, bucket_name)

        self.assertEqual(mock_process_exclude.delay.call_count, 2)

    def test_get_feature_settings(self):
        GrabFeatureSetting.objects.get_or_create(
            is_active=True,
            category="grab collection",
            description='grab airudder populating config',
            feature_name=GrabFeatureNameConst.GRAB_POPULATING_CONFIG,
            parameters=[
                {
                    "rank": 1,
                    "score": [{"min": 200, "max": 400}],
                    "dpd": [{"min": 7, "max": 11}, {"min": 30, "max": 40}, {"min": 50, "max": 60}],
                    "category": ["4W"],
                },
                {
                    "rank": 2,
                    "score": [{"min": 400, "max": 800}],
                    "dpd": [{"min": 7, "max": 11}, {"min": 31, "max": 40}, {"min": 50, "max": 60}],
                    "category": ["4W"],
                },
            ],
        )

        service = GrabAIRudderPopulatingService()
        parameters = service.get_feature_settings()
        self.assertNotEqual(parameters, None)
        self.assertNotEqual(parameters, [])
        field = ["rank", "score", "dpd", "category"]
        for param in parameters:
            for i in field:
                self.assertTrue(i in param)

    def test_get_feature_settings_inactive(self):
        feature_setting = GrabFeatureSetting.objects.get_or_create(
            is_active=True,
            category="grab collection",
            description='grab airudder populating config',
            feature_name=GrabFeatureNameConst.GRAB_POPULATING_CONFIG,
            parameters=[
                {
                    "rank": 1,
                    "score": [{"min": 200, "max": 400}],
                    "dpd": [{"min": 7, "max": 11}, {"min": 30, "max": 40}, {"min": 50, "max": 60}],
                    "category": ["4W"],
                },
                {
                    "rank": 2,
                    "score": [{"min": 400, "max": 800}],
                    "dpd": [{"min": 7, "max": 11}, {"min": 31, "max": 40}, {"min": 50, "max": 60}],
                    "category": ["4W"],
                },
            ],
        )

        feature_setting[0].is_active = False
        feature_setting[0].save()
        feature_setting[0].refresh_from_db()

        service = GrabAIRudderPopulatingService()
        parameters = service.get_feature_settings()
        self.assertNotEqual(parameters, None)
        self.assertEqual(parameters, [])

    def test_get_loans_id_without_cscore(self):
        service = GrabAIRudderPopulatingService()
        for loans_id in service.get_loans_id_without_cscore(chunk_size=100):
            self.assertNotEqual(len(loans_id), 0)

    def test_insert_loans_no_cscore_to_temp_table(self):
        self.assertFalse(GrabTempLoanNoCscore.objects.all().exists())
        service = GrabAIRudderPopulatingService()
        service.insert_loans_no_cscore_to_temp_table(self.loans_id)
        self.assertTrue(GrabTempLoanNoCscore.objects.all().exists())

        before_duplicate_count = GrabTempLoanNoCscore.objects.all().count()
        service.insert_loans_no_cscore_to_temp_table(self.loans_id)
        after_duplicate_count = GrabTempLoanNoCscore.objects.all().count()

        self.assertEqual(before_duplicate_count, after_duplicate_count)

    def exclude_loan_have_cscore_from_temp_table(self):
        service = GrabAIRudderPopulatingService()

        self.assertFalse(GrabTempLoanNoCscore.objects.all().exists())

        service.insert_loans_no_cscore_to_temp_table(self.loans_id)
        self.assertTrue(GrabTempLoanNoCscore.objects.all().exists())

        service.exclude_loan_have_cscore_from_temp_table(chunk_size=100)
        self.assertFalse(GrabTempLoanNoCscore.objects.all().exists())

    @mock.patch('juloserver.minisquad.services2.airudder.bulk_update')
    def test_prepare_loan_without_cscore_data_no_data_in_cscore_table(self, mock_bulk_update):
        service = GrabAIRudderPopulatingService()

        GrabIntelixCScore.objects.all().delete()

        service.prepare_loan_without_cscore_data()
        mock_bulk_update.assert_called()

    def test_get_dynamic_eligible_grab_ai_rudder_payment_for_dialer_no_cscore(self):
        service = GrabAIRudderPopulatingService()

        self.assertFalse(GrabTempLoanNoCscore.objects.all().exists())
        GrabIntelixCScore.objects.all().delete()

        service.prepare_loan_without_cscore_data()

        param = [{"dpd": {"min": 2, "max": 90}}]
        for payment_qs, account_list in service.get_dynamic_eligible_grab_ai_rudder_payment_for_dialer(param):
            self.assertEqual(payment_qs.count(), len(account_list))

    @skip(reason="causing db lock")
    def test_clear_grab_temp_loan_no_cscore(self):
        for _ in range(5):
            GrabTempLoanNoCscoreFactory()

        self.assertTrue(GrabTempLoanNoCscore.objects.all().exists())
        clear_grab_temp_loan_no_cscore()
        self.assertFalse(GrabTempLoanNoCscore.objects.all().exists())

    def test_get_max_dpd_ai_rudder_on_loan_level_halted_loan(self):
        payment = Payment.objects.get(id=list(self.payment_list)[0])
        payment.loan.loan_status = StatusLookupFactory(status_code=LoanStatusCodes.HALT)
        payment.loan.save()
        svc = GrabAIRudderPopulatingService()
        dpd_calculation, _ = svc.process_loans_id([payment.loan.id])
        for key, value in dpd_calculation.items():
            self.assertEqual(value['dpd'], 0)
