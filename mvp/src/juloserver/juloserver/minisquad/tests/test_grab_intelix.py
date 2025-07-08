import math
from http import HTTPStatus

import mock
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.grab.models import GrabCollectionDialerTemporaryData, GrabSkiptraceHistory, \
    GrabLoanData, GrabIntelixCScore
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst, WorkflowConst
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.minisquad.constants import (FeatureNameConst as MiniSquadFeatureNameConst, RedisKey,
                                            IntelixTeam, DialerTaskType, DialerTaskStatus)
from juloserver.julo.models import Application, Loan, Payment, FeatureSetting, Skiptrace, SkiptraceResultChoice
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes, LoanStatusCodes
from juloserver.julo.tests.factories import FeatureSettingFactory, LoanFactory, ProductLineFactory, \
    WorkflowFactory, StatusLookupFactory, AuthUserFactory, CustomerFactory, ApplicationFactory, \
    PartnerFactory, ProductLookupFactory, CreditMatrixFactory, SkiptraceResultChoiceFactory, \
    PaymentFactory
from juloserver.minisquad.models import DialerTask, DialerTaskEvent, VendorRecordingDetail
from juloserver.minisquad.services2.intelix import get_grab_populated_data_for_calling, \
    construct_grab_data_for_sent_to_intelix_by_temp_data, get_jumlah_pinjaman_intelix_grab, \
    get_angsuran_for_intelix_grab, get_late_fee_amount_intelix_grab, \
    check_grab_customer_bucket_type, \
    construct_additional_data_for_intelix_grab, get_starting_and_ending_index_temp_data, \
    get_loan_xids_based_on_c_score, get_not_paid_loan_in_last_2_days_custom
from juloserver.minisquad.tasks2 import store_system_call_result_in_bulk
from juloserver.minisquad.tasks2.intelix_task2 import (clear_grab_collection_dialer_temp_data,
                                                       cron_trigger_grab_intelix,
                                                       populate_grab_temp_data_by_rank,
                                                       populate_grab_temp_data_for_intelix_dialer, process_construct_grab_data_to_intelix,
                                                       process_exclude_for_grab_sent_dialer_per_part,
                                                       process_grab_populate_temp_data_for_dialer,
                                                       process_and_send_grab_data_to_intelix,
                                                       send_data_to_intelix_with_retries_mechanism_grab,
                                                       get_eligible_grab_payment_for_dialer)
from juloserver.minisquad.tests.factories import DialerTaskFactory
from juloserver.pin.tests.factories import CustomerPinFactory
from juloserver.minisquad.services2.intelix import create_history_dialer_task_event, \
    get_loans_based_on_c_score, get_grab_active_ptp_account_ids
from juloserver.grab.tests.factories import GrabLoanDataFactory, GrabIntelixCScoreFactory
from django.db.models import F, Value, CharField, ExpressionWrapper, IntegerField, Q, Prefetch
from django.db.models.functions import Concat
from juloserver.grab.serializers import GrabCollectionDialerTemporarySerializer
from juloserver.minisquad.tests.test_intelix import JuloAPITestCase
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.minisquad.clients import get_julo_intelix_client


def mock_download_sftp(dialer_task_id, vendor_recording_detail_id):
    return dialer_task_id, vendor_recording_detail_id


class TestCronGrabIntelix(TestCase):
    def setUp(self) -> None:
        self.grab_intelix_call_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_INTELIX_CALL
        )
        self.grab_cscore_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_INTELIX
        )

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_c_score_to_db.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_intelix.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.cron_trigger_send_grab_intelix.delay')
    def test_failed_feature_setting_doesnt_active(self, mock_trigger_send_grab_intelix,
                                                  mock_trigger_populate_grab_intelix,
                                                  mock_trigger_populate_grab_c_score_to_db):
        self.grab_intelix_call_feature_setting.is_active = False
        self.grab_intelix_call_feature_setting.save()
        self.grab_intelix_call_feature_setting.refresh_from_db()
        cron_trigger_grab_intelix()
        self.assertEqual(mock_trigger_populate_grab_intelix.called, False)
        self.assertEqual(mock_trigger_send_grab_intelix.called, False)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_c_score_to_db.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_intelix.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.cron_trigger_send_grab_intelix.delay')
    def test_failed_feature_setting_doesnt_have_parameters(self, mock_trigger_send_grab_intelix,
                                                           mock_trigger_populate_grab_intelix,
                                                           mock_trigger_populate_grab_c_score_to_db):
        cron_trigger_grab_intelix()
        self.assertEqual(mock_trigger_populate_grab_intelix.called, False)
        self.assertEqual(mock_trigger_send_grab_intelix.called, False)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_intelix.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.cron_trigger_send_grab_intelix.delay')
    def test_failed_feature_setting_doesnt_have_populate_schedule_parameter(self,
                                                                            mock_trigger_send_grab_intelix,
                                                                            mock_trigger_populate_grab_intelix):
        parameters = {
            "send_schedule": "08:00"
        }
        self.grab_intelix_call_feature_setting.parameters = parameters
        self.grab_intelix_call_feature_setting.save()
        self.grab_intelix_call_feature_setting.refresh_from_db()
        cron_trigger_grab_intelix()
        self.assertEqual(mock_trigger_populate_grab_intelix.called, False)
        self.assertEqual(mock_trigger_send_grab_intelix.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_intelix.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.cron_trigger_send_grab_intelix.delay')
    def test_failed_feature_setting_doesnt_have_send_schedule_parameter(self,
                                                                        mock_trigger_send_grab_intelix,
                                                                        mock_trigger_populate_grab_intelix):
        parameters = {
            "populate_schedule": "06:00"
        }
        self.grab_intelix_call_feature_setting.parameters = parameters
        self.grab_intelix_call_feature_setting.save()
        self.grab_intelix_call_feature_setting.refresh_from_db()
        cron_trigger_grab_intelix()
        self.assertEqual(mock_trigger_populate_grab_intelix.called, False)
        self.assertEqual(mock_trigger_send_grab_intelix.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_c_score_to_db.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_intelix.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.cron_trigger_send_grab_intelix.delay')
    def test_failed_feature_setting_doesnt_have_c_score_db_populate_schedule_parameter(
            self, mock_trigger_send_grab_intelix,
            mock_trigger_populate_grab_intelix,
            mock_trigger_populate_grab_c_score_to_db):
        parameters = {
            "populate_schedule": "06:00",
            "send_schedule": "08:00"
        }
        self.grab_intelix_call_feature_setting.parameters = parameters
        self.grab_intelix_call_feature_setting.save()
        self.grab_intelix_call_feature_setting.refresh_from_db()
        cron_trigger_grab_intelix()
        self.assertEqual(mock_trigger_populate_grab_intelix.called, True)
        self.assertEqual(mock_trigger_send_grab_intelix.called, True)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_c_score_to_db.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_intelix.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.cron_trigger_send_grab_intelix.delay')
    def test_failed_feature_setting_with_in_active_grab_c_score_feature_for_intelix(
            self, mock_trigger_send_grab_intelix,
            mock_trigger_populate_grab_intelix,
            mock_trigger_populate_grab_c_score_to_db
    ):
        parameters = {
            "populate_schedule": "06:00",
            "send_schedule": "08:00",
            "c_score_db_populate_schedule": "23:10"
        }
        self.grab_intelix_call_feature_setting.parameters = parameters
        self.grab_intelix_call_feature_setting.save()
        self.grab_intelix_call_feature_setting.refresh_from_db()
        self.grab_cscore_feature_setting.is_active = False
        self.grab_cscore_feature_setting.save()
        self.grab_cscore_feature_setting.refresh_from_db()
        cron_trigger_grab_intelix()
        self.assertEqual(mock_trigger_populate_grab_intelix.called, True)
        self.assertEqual(mock_trigger_send_grab_intelix.called, True)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, False)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_c_score_to_db.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.cron_trigger_populate_grab_intelix.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.cron_trigger_send_grab_intelix.delay')
    def test_success_trigger_populate_and_send_grab_intelix(self, mock_trigger_send_grab_intelix,
                                                            mock_trigger_populate_grab_intelix,
                                                            mock_trigger_populate_grab_c_score_to_db):
        parameters = {
            "populate_schedule": "06:00",
            "send_schedule": "08:00",
            "c_score_db_populate_schedule": "23:10"
        }
        self.grab_intelix_call_feature_setting.parameters = parameters
        self.grab_intelix_call_feature_setting.save()
        self.grab_intelix_call_feature_setting.refresh_from_db()
        cron_trigger_grab_intelix()
        self.assertEqual(mock_trigger_populate_grab_intelix.called, True)
        self.assertEqual(mock_trigger_send_grab_intelix.called, True)
        self.assertEqual(mock_trigger_populate_grab_c_score_to_db.called, True)


class TestPopulateDataGrabIntelix(TestCase):
    def setUp(self):
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
        self.bucket_name = IntelixTeam.GRAB
        self.redis_data = {}
        self.grab_intelix_call_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_INTELIX_CALL,
            is_active=True,
            parameters={"populate_schedule": "02:00", "send_schedule": "05:00",
                        "grab_send_batch_size": "1000"}
        )

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]


    @mock.patch('juloserver.minisquad.services2.intelix.get_grab_active_ptp_account_ids')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    def test_failed_no_eligible_grab_payment_data(self, mock_delete_redis_key,
                                                  mock_get_redis_client,
                                                  mock_eligible_grab_payment_data,
                                                  mock_grab_active_ptp_account_ids):
        mock_grab_active_ptp_account_ids.return_value = None
        mock_eligible_grab_payment_data.return_value = [(None, [])]
        mock_delete_redis_key.return_value = True
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        populate_grab_temp_data_for_intelix_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event.status, 'querying_rank_8_chunk_1')

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_exclude_for_grab_sent_dialer_per_part.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
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
        populate_grab_temp_data_for_intelix_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event.status, 'batching_processed_rank_8')
        self.assertEqual(dialer_task_event.data_count, 1)
        # cause there are 1 batches for 2 ranks
        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)

    @mock.patch(
    'juloserver.minisquad.tasks2.intelix_task2.process_exclude_for_grab_sent_dialer_per_part.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
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
        populate_grab_temp_data_for_intelix_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, len(payments))

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='batching_processed_rank_7').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='batching_processed_rank_8').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_exclude_for_grab_sent_dialer_per_part.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
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
        populate_grab_temp_data_for_intelix_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, len(payments))

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='batching_processed_rank_7').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='batching_processed_rank_8').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_exclude_for_grab_sent_dialer_per_part.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
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
        populate_grab_temp_data_for_intelix_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, len(payments))

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='batching_processed_rank_7').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='batching_processed_rank_8').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_grab_active_ptp_account_ids')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_exclude_for_grab_sent_dialer_per_part.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
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
        populate_grab_temp_data_for_intelix_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        )

        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task)
        for task_event in dialer_task_event:
            if 'queried' in task_event.status:
                self.assertEqual(task_event.data_count, total_payments)

        # check the batching, should be exists for rank 7 and 8
        self.assertTrue(dialer_task_event.filter(
            status__contains='batching_processed_rank_7').exists())
        self.assertTrue(dialer_task_event.filter(
            status__contains='batching_processed_rank_8').exists())

        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 2)
        positional_args, _ = mock_async_process_sent_dialer_per_part.call_args
        flat_ptp_val_merged = []
        for i in mock_get_grab_ptp_value:
            flat_ptp_val_merged += i
        self.assertEqual(positional_args[-1], flat_ptp_val_merged)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_exclude_for_grab_sent_dialer_per_part.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_grab_payment_data_with_config(self, mock_delete_redis_key,
                                                                      mock_get_redis_client,
                                                                      mock_eligible_grab_payment_data,
                                                                      mock_async_process_sent_dialer_per_part):
        parameters = {
            "GRAB": 12
        }
        self.intelix_data_batching_feature_setting = FeatureSetting.objects.create(
            feature_name=MiniSquadFeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            parameters=parameters,
            is_active=True
        )
        self.grab_cscore_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_INTELIX,
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
        populate_grab_temp_data_for_intelix_dialer()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(
                self.bucket_name)
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event.status, 'batching_processed_rank_8')
        self.assertEqual(dialer_task_event.data_count, 3)
        # cause there are 3 batches for 2 ranks
        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 6)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.logger.info')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_grab_populate_temp_data_for_dialer.delay')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_failed_with_empty_cache_populated_eligible_grab_data(self, mock_get_redis_client,
                                                                  mock_process_temp_data,
                                                                  mocked_logger):
        rank = 1
        page_num = 1
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name)
        )
        mocked_logger.return_value = None
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        loan = Loan.objects.first()
        payment_ids = Payment.objects.filter(loan_id=loan.id).all()
        list_account_ids = [payment.loan.account_id for payment in payment_ids]
        account_id_ptp_exist = get_grab_active_ptp_account_ids(list_account_ids)
        process_exclude_for_grab_sent_dialer_per_part(rank, self.bucket_name, page_num,
                                                      dialer_task.id, account_id_ptp_exist)
        self.assertEqual(mock_process_temp_data.called, False)
        mocked_logger.assert_called()
        redis_key = RedisKey.POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(
            self.bucket_name, rank, page_num)
        mocked_logger.assert_called_with({
            "action": "process_exclude_for_grab_sent_dialer_per_part",
            "message": "missing redis key - {}".format(redis_key)
        })

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_grab_populate_temp_data_for_dialer.delay')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_success_with_cache_populated_eligible_grab_data(self, mock_get_redis_client,
                                                             mock_process_temp_data):
        loan = Loan.objects.first()
        payment_ids = Payment.objects.filter(loan_id=loan.id).values_list('id', flat=True)
        rank = 1
        page_num = 1
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name)
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis( # noqa
            RedisKey.POPULATE_ELIGIBLE_CALL_GRAB_PAYMENT_IDS.format(self.bucket_name, rank,
                                                                    page_num),
            payment_ids)
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        loan = Loan.objects.first()
        payment_ids = Payment.objects.filter(loan_id=loan.id).all()
        list_account_ids = [payment.loan.account_id for payment in payment_ids]
        account_id_ptp_exist = get_grab_active_ptp_account_ids(list_account_ids)
        process_exclude_for_grab_sent_dialer_per_part(rank, self.bucket_name, page_num,
                                                      dialer_task.id, account_id_ptp_exist)
        self.assertEqual(mock_process_temp_data.called, True)

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_failed_construct_data_with_empty_cache(self, mock_get_redis_client):
        rank = 1
        page_num = 1
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name)
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        process_grab_populate_temp_data_for_dialer(rank, self.bucket_name, page_num, dialer_task.id)
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
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name)
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis( # noqa
            RedisKey.CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(self.bucket_name, rank,
                                                                      page_num),
            payment_ids)
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        process_grab_populate_temp_data_for_dialer(rank, self.bucket_name, page_num, dialer_task.id)
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertEqual(dialer_task_event.status,
                         DialerTaskStatus.PROCESSED_POPULATED_GRAB_PAYMENTS.format(
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
            status=DialerTaskStatus.FAILURE_RANK_BATCH.format(rank, part),
        )
        error_message = str(error)
        create_history_dialer_task_event(test_dict, error_message)
        dialer_task_event_1 = DialerTaskEvent.objects.filter(
            dialer_task=dialer_task).last()
        self.assertIsNotNone(dialer_task_event_1)
        self.assertEqual(dialer_task_event_1.status, 'failure_rank_1_part_1')

        create_history_dialer_task_event(
            dict(dialer_task=dialer_task,
                 status=DialerTaskStatus.PROCESS_POPULATED_GRAB_PAYMENTS.format(
                     self.bucket_name, rank, part)))
        dialer_task_event_2 = DialerTaskEvent.objects.filter(
            dialer_task=dialer_task).last()
        self.assertIsNotNone(dialer_task_event_2)
        self.assertEqual(dialer_task_event_2.status,
                         'process_populated_grab_payments_GRAB_rank_1_part_1')


class TestSendPopulatedGrabDataIntelix(TestCase):
    def setUp(self) -> None:
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
        self.bucket_name = IntelixTeam.GRAB
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
        self.grab_intelix_call_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_INTELIX_CALL,
            is_active=True,
            parameters={"populate_schedule": "02:00", "send_schedule": "05:00",
                        "grab_send_batch_size": "1000", "c_score_db_populate_schedule": "23:10"}
        )
        self.grab_cscore_feature_setting = FeatureSettingFactory(
            feature_name=JuloFeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_INTELIX,
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
            raise Exception("INVALID RANK FOR GRAB INTELIX RANK({})".format(rank))
        # -----------------------------------------------------------
        # -------------- DEPRICATED CODE ----------------------------
        # -----------------------------------------------------------
        # elif rank == 9:
        #     use_outstanding = True
        #     is_below_700k = True
        #     restructured_loan = restructured_loan.filter(
        #         loan__loan_status_id__in=LoanStatusCodes.grab_current_until_180_dpd()
        #     )
        # elif rank == 10:
        #     is_include_restructure_and_normal = True
        #     is_loan_below_91 = False
        #     restructured_loan = restructured_loan.filter(
        #         loan__loan_status_id__in=LoanStatusCodes.grab_current_until_180_dpd()
        #     )

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

        # get the highest dpd from loan which have same customer_id
        unique_loan_customer_and_dpd = {}
        for item in grouped_by_loan_customer_and_max_dpd:
            final_dpd = item.get('max_dpd')
            if item.get('customer_id') not in unique_loan_customer_and_dpd:
                unique_loan_customer_and_dpd[item.get("customer_id")] = item
            elif item.get('customer_id') in unique_loan_customer_and_dpd and \
                    unique_loan_customer_and_dpd[item.get('customer_id')].get(
                        'max_dpd') < final_dpd:
                unique_loan_customer_and_dpd[item.get("customer_id")] = item

        # get all data with correct dpd required
        loan_ids_with_correct_dpd = []
        for data in unique_loan_customer_and_dpd.values():
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

            data = filtered_data_by_dpd.filter(loan_id__in=loan_ids_with_correct_outstanding).order_by(
                'loan__customer', 'id').distinct('loan__customer')
        else:
            data = filtered_data_by_dpd.order_by('loan__customer', 'id').distinct('loan__customer')

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
            raise Exception("INVALID RANK FOR GRAB INTELIX RANK({})".format(rank))
        # -----------------------------------------------------------
        # -------------- DEPRICATED CODE ----------------------------
        # -----------------------------------------------------------
        # elif rank == 9:
        #     use_outstanding = True
        #     is_below_700k = True
        #     restructured_loan = restructured_loan.filter(
        #         loan__loan_status_id__in=LoanStatusCodes.grab_current_until_180_dpd()
        #     )
        # elif rank == 10:
        #     is_include_restructure_and_normal = True
        #     is_loan_below_91 = False
        #     restructured_loan = restructured_loan.filter(
        #         loan__loan_status_id__in=LoanStatusCodes.grab_current_until_180_dpd()
        #     )

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
        if redis_key == 'grab_temp_data_coll_ids|GRAB|batch_1':
            return payment_ids_from_first_loan

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_construct_grab_data_to_intelix')
    def test_failed_without_populated_dialer_task_data(self, mock_construct_dialer_data):
        with self.assertRaises(Exception) as context:
            process_and_send_grab_data_to_intelix()

        self.assertTrue("data still not populated" in str(context.exception))
        mock_construct_dialer_data.assert_not_called()

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_construct_grab_data_to_intelix')
    def test_failed_no_batching_dialer_task_event(self, mock_construct_dialer_data):
        rank = 1
        populated_dialer_task = DialerTask.objects.create(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name)
        )

        create_history_dialer_task_event(
            dict(dialer_task=populated_dialer_task,
                 status=DialerTaskStatus.QUERIED_RANK.format(rank)
                 )
        )
        with self.assertRaises(Exception) as context:
            process_and_send_grab_data_to_intelix()

        self.assertTrue("doesn't have batching log" in str(context.exception))
        mock_construct_dialer_data.assert_not_called()

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.process_construct_grab_data_to_intelix')
    def test_failed_no_processed_dialer_task_event(self, mock_construct_dialer_data,
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

        populate_grab_temp_data_for_intelix_dialer()

        with self.assertRaises(Exception) as context:
            process_and_send_grab_data_to_intelix()
            self.assertTrue("doesn't have processed log" in str(context.exception))

        mock_construct_dialer_data.assert_not_called()

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.send_data_to_intelix_with_retries_mechanism_grab.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    def test_failed_with_empty_temporary_data(self,
                                              mock_delete_redis_key,
                                              mock_get_redis_client,
                                              mock_eligible_grab_payment_data,
                                              mock_send_data_to_intelix
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
        populate_grab_temp_data_for_intelix_dialer()

        populate_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name)
        ).first()

        restructured_loan_ids_list = []
        loan_xids_based_on_c_score_list = []

        for rank in range(1, 9):
            populate_grab_temp_data_by_rank(rank, populate_dialer_task, self.bucket_name,
                                            restructured_loan_ids_list,
                                            loan_xids_based_on_c_score_list)

            mock_get_redis_client.return_value.set_list.side_effect = self.set_redis( # noqa
                RedisKey.CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                    self.bucket_name, rank, page_num), payment_ids
            )

            process_grab_populate_temp_data_for_dialer(
                rank, self.bucket_name, page_num, populate_dialer_task.id)

        GrabCollectionDialerTemporaryData.objects.all().delete()
        process_and_send_grab_data_to_intelix()
        upload_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.UPLOAD_GRAB
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=upload_dialer_task).last()
        self.assertEqual(dialer_task_event.status, DialerTaskStatus.FAILURE)
        mock_send_data_to_intelix.assert_not_called()

    def test_get_loans_based_on_c_score_success(self):
        ranks = list(range(1, 7))
        grab_intelix_cscore = GrabIntelixCScoreFactory(
            loan_xid=self.loan.loan_xid,
            grab_user_id=123,
            vehicle_type='type1', cscore=250, customer_id=self.customer.id
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
            self.bucket_name)
        fetch_temp_ids = grab_collection_temp_data_list_ids[0: total_count]
        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        grab_temp = grab_payments.filter(payment_id=self.first_payment.id).last()
        first_payment = Payment.objects.get(pk=grab_temp.payment_id)
        self.grab_loan_data_2.is_repayment_capped = False

        total_loan_amount = 1000000
        return_value = get_jumlah_pinjaman_intelix_grab(first_payment)
        self.assertEqual(total_loan_amount, return_value)

    def test_get_angsuran_for_intelix_grab_success(self):
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name)
        fetch_temp_ids = grab_collection_temp_data_list_ids[0: total_count]
        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        grab_temp = grab_payments.filter(payment_id=self.first_payment.id).last()
        first_payment = Payment.objects.get(pk=grab_temp.payment_id)
        total_installment_amount = self.loan_2.installment_amount + self.loan_3.installment_amount
        return_value = get_angsuran_for_intelix_grab(first_payment)
        self.assertEqual(return_value, total_installment_amount)

    def test_get_angsuran_for_intelix_grab_failure(self):
        total_installment_amount = 0
        return_value = get_angsuran_for_intelix_grab(None)
        self.assertEqual(return_value, total_installment_amount)

    def test_check_grab_customer_bucket_type(self):
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name)
        fetch_temp_ids = grab_collection_temp_data_list_ids[0: total_count]
        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        grab_temp = grab_payments.filter(payment_id=self.first_payment.id).last()
        first_payment = Payment.objects.get(pk=grab_temp.payment_id)
        return_value = check_grab_customer_bucket_type(first_payment)
        self.assertEqual(return_value, 'Fresh')

    def test_get_late_fee_amount_intelix_grab_success(self):
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name)
        fetch_temp_ids = grab_collection_temp_data_list_ids[0: total_count]

        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        first_temp = grab_payments.filter(payment_id=self.first_payment.id).last()
        first_payment = Payment.objects.get(pk=first_temp.payment_id)
        late_fee_amount = get_late_fee_amount_intelix_grab(first_payment)
        self.assertEqual(late_fee_amount, 10000)

    def test_get_late_fee_amount_intelix_grab_failure(self):
        late_fee_amount = get_late_fee_amount_intelix_grab(None)
        self.assertEqual(0, late_fee_amount)

    def test_construct_grab_data_for_sent_to_intelix_by_temp_data_success(self):
        total_count, grab_collection_temp_data_list_ids = get_starting_and_ending_index_temp_data(
            self.bucket_name)
        fetch_temp_ids = grab_collection_temp_data_list_ids[0: total_count]
        grab_payments = get_grab_populated_data_for_calling(self.bucket_name, fetch_temp_ids)
        populated_temp_data = grab_payments[0]
        first_payment = Payment.objects.get(pk=populated_temp_data.payment_id)
        application = first_payment.loan.account.last_application

        phone_numbers = {
            'company_phone_number': '',
            'kin_mobile_phone': self.application.kin_mobile_phone,
            'spouse_mobile_phone': self.application.spouse_mobile_phone,
            'mobile_phone_1': self.application.mobile_phone_1,
            'mobile_phone_2': ''
        }
        others, last_pay_details, outstanding_amount = construct_additional_data_for_intelix_grab(
            first_payment)

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
            "angsuran/bulan": get_angsuran_for_intelix_grab(first_payment),
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
            "jumlah_pinjaman": get_jumlah_pinjaman_intelix_grab(first_payment),
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
            'promo_untuk_customer': ''
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
            'payment_id': populated_temp_data.payment_id
        }
        expected_output.update(params)
        expected_output.update(others)
        expected_output.update(last_pay_details)
        constructed_data = construct_grab_data_for_sent_to_intelix_by_temp_data(grab_payments)
        self.assertDictEqual(expected_output, constructed_data[0])

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.logger.exception')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.send_data_to_intelix_with_retries_mechanism_grab.delay')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_grab_payment_for_dialer')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_starting_and_ending_index_temp_data')
    def test_failed_split_process_and_send_grab_data_to_intelix(self,
                                                                mock_get_index_temp_data,
                                                                mock_delete_redis_key,
                                                                mock_get_redis_client,
                                                                mock_eligible_grab_payment_data,
                                                                mock_send_data_to_intelix,
                                                                mocked_redis_delete,
                                                                mocked_logger):
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
        populate_grab_temp_data_for_intelix_dialer()

        populate_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(self.bucket_name)
        ).first()

        restructured_loan_ids_list = []
        loan_xids_based_on_c_score_list = []

        for rank in range(1, 9):
            populate_grab_temp_data_by_rank(rank, populate_dialer_task, self.bucket_name,
                                            restructured_loan_ids_list,
                                            loan_xids_based_on_c_score_list)

            mock_get_redis_client.return_value.set_list.side_effect = self.set_redis( # noqa
            RedisKey.CLEAN_GRAB_PAYMENT_IDS_FOR_DIALER_RELATED.format(self.bucket_name, rank,
                                                                      page_num),
            payment_ids)

            create_history_dialer_task_event(
                dict(dialer_task=populate_dialer_task,
                    status=DialerTaskStatus.PROCESSED_POPULATED_GRAB_PAYMENTS.format(self.bucket_name,
                                                                                    rank,
                                                                                    page_num)
                    )
            )

        mock_get_index_temp_data.return_value = 0, None

        process_and_send_grab_data_to_intelix()
        upload_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.UPLOAD_GRAB
        ).first()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=upload_dialer_task).last()
        self.assertEqual(dialer_task_event.status, DialerTaskStatus.FAILURE)
        mock_send_data_to_intelix.assert_not_called()
        mocked_logger.assert_called_with({
            "action": "process_and_send_grab_data_to_intelix",
            'error': "Temporary Table(grab) is empty."
        })

    @mock.patch('juloserver.minisquad.services2.intelix.connection')
    def test_get_eligible_grab_payment_for_dialer_rank_1(self, mocked_connection):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer,
            account_lookup=self.account_lookup
        )

        loan_rank = LoanFactory(
            loan_purpose='Grab_loan_creation',
            loan_amount=3000000,
            loan_duration=180,
            account=account,
            customer=customer,
            loan_status=StatusLookupFactory(status_code=231),
            loan_xid=1000006485
        )
        grab_loan_data_rank = GrabLoanDataFactory(
            loan=loan_rank,
            is_repayment_capped=False
        )
        loan_payments_rank = Payment.objects.filter(
            loan=loan_rank).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=4))

        grab_intelix_cscore = GrabIntelixCScoreFactory(
            loan_xid=loan_rank.loan_xid,
            grab_user_id=123,
            vehicle_type='type1',
            cscore=250,
            customer=customer
        )
        grab_intelix_cscore.save()

        for idx, payment in enumerate(loan_payments_rank):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 90000
            payment.save()

        grab_intelix_cscore.cscore = 250
        grab_intelix_cscore.save()

        grab_loan_data_rank.is_repayment_capped = False
        grab_loan_data_rank.save()

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

        mocked_connection_magic_mock = mock.MagicMock()
        mocked_connection_magic_mock.execute.return_value = None
        mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
            1, restructured_loan_ids_list=restructured_loan_ids_list,
            loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(grab_intellix_cscore_obj, 1))
        mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
        grab_payments = None
        for result in get_eligible_grab_payment_for_dialer(
            1,
            restructured_loan_ids_list,
            get_loan_xids_based_on_c_score(
            grab_intellix_cscore_obj, 1)):
            grab_payments, list_account_ids = result[0], result[1]
            self.assertTrue(grab_payments.filter(loan__customer=loan_rank.customer).exists())
            self.assertTrue(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
            self.assertEqual(1, grab_payments.count())
            mocked_connection.cursor.return_value.__enter__.assert_called()
        mocked_connection.reset_mock()

        for rank in range(2, 9):
            mocked_connection_magic_mock = mock.MagicMock()
            mocked_connection_magic_mock.execute.return_value = None
            mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
                rank,
                restructured_loan_ids_list=restructured_loan_ids_list,
                loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            )
            mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
            grab_payments = None
            result_count = 0
            for result in get_eligible_grab_payment_for_dialer(
                rank,
                restructured_loan_ids_list,
                get_loan_xids_based_on_c_score(
                grab_intellix_cscore_obj, rank)):
                result_count += 1
                grab_payments = result[0]
                self.assertFalse(grab_payments.filter(loan__customer=loan_rank.customer).exists())
                self.assertFalse(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
                mocked_connection.reset_mock()

            if rank not in [7,8]:
                self.assertEqual(result_count, 0)

    @mock.patch('juloserver.minisquad.services2.intelix.connection')
    def test_get_eligible_grab_payment_for_dialer_rank_2(self, mocked_connection):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer,
            account_lookup=self.account_lookup
        )
        loan_rank = LoanFactory(
            loan_purpose='Grab_loan_creation',
            loan_amount=3000000,
            loan_duration=180,
            account=account,
            customer=customer,
            loan_status=StatusLookupFactory(status_code=231),
            loan_xid=1000006486
        )
        grab_loan_data_rank = GrabLoanDataFactory(
            loan=loan_rank,
            is_repayment_capped=False
        )
        loan_payments_rank = Payment.objects.filter(
            loan=loan_rank).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=4))

        grab_intelix_cscore = GrabIntelixCScoreFactory(
            loan_xid=loan_rank.loan_xid,
            grab_user_id=123,
            vehicle_type='type1',
            cscore=250,
            customer_id=customer.id
        )
        yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
        grab_intelix_cscore.cdate = yesterday
        grab_intelix_cscore.save()

        for idx, payment in enumerate(loan_payments_rank):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 90000
            payment.save()

        grab_intelix_cscore.cscore = 250
        grab_intelix_cscore.save()

        grab_loan_data_rank.is_repayment_capped = True
        grab_loan_data_rank.save()

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

        test_for_rank = 2
        for result in get_eligible_grab_payment_for_dialer(
            test_for_rank,
            restructured_loan_ids_list,
            get_loan_xids_based_on_c_score(
            grab_intellix_cscore_obj, test_for_rank)):
            grab_payments, list_account_ids = result[0], result[1]

            self.assertTrue(grab_payments.filter(loan__customer=loan_rank.customer).exists())
            self.assertTrue(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
            self.assertEqual(1, grab_payments.count())
            mocked_connection.cursor.return_value.__enter__.assert_called()
        mocked_connection.reset_mock()

        for rank in range(1, 9):
            if rank == test_for_rank:
                continue
            mocked_connection_magic_mock = mock.MagicMock()
            mocked_connection_magic_mock.execute.return_value = None
            mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
                rank,
                restructured_loan_ids_list=restructured_loan_ids_list,
                loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            )
            mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
            grab_payments = None
            result_count = 0
            for result in get_eligible_grab_payment_for_dialer(
                rank,
                restructured_loan_ids_list,
                get_loan_xids_based_on_c_score(
                grab_intellix_cscore_obj, rank)):
                result_count += 1
                grab_payments = result[0]
                self.assertFalse(grab_payments.filter(loan__customer=loan_rank.customer).exists())
                self.assertFalse(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
                mocked_connection.reset_mock()

            if rank not in [7,8]:
                self.assertEqual(result_count, 0)

    @mock.patch('juloserver.minisquad.services2.intelix.connection')
    def test_get_eligible_grab_payment_for_dialer_rank_3(self, mocked_connection):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer,
            account_lookup=self.account_lookup
        )
        loan_rank = LoanFactory(
            loan_purpose='Grab_loan_creation',
            loan_amount=3000000,
            loan_duration=180,
            account=account,
            customer=customer,
            loan_status=StatusLookupFactory(status_code=231),
            loan_xid=1000006487
        )
        grab_loan_data_rank = GrabLoanDataFactory(
            loan=loan_rank,
            is_repayment_capped=False
        )
        loan_payments_rank = Payment.objects.filter(
            loan=loan_rank).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=10))

        grab_intelix_cscore = GrabIntelixCScoreFactory(
            loan_xid=loan_rank.loan_xid,
            grab_user_id=123,
            vehicle_type='type1',
            cscore=250,
            customer_id=customer.id
        )
        yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
        grab_intelix_cscore.cdate = yesterday
        grab_intelix_cscore.save()

        for idx, payment in enumerate(loan_payments_rank):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 90000
            payment.save()

        grab_intelix_cscore.cscore = 500
        grab_intelix_cscore.save()

        grab_loan_data_rank.is_repayment_capped = False
        grab_loan_data_rank.save()

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

        test_for_rank = 3
        for result in get_eligible_grab_payment_for_dialer(
            test_for_rank,
            restructured_loan_ids_list,
            get_loan_xids_based_on_c_score(
            grab_intellix_cscore_obj, test_for_rank)):
            grab_payments, list_account_ids = result[0], result[1]

            self.assertTrue(grab_payments.filter(loan__customer=loan_rank.customer).exists())
            self.assertTrue(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
            self.assertEqual(1, grab_payments.count())
            mocked_connection.cursor.return_value.__enter__.assert_called()
        mocked_connection.reset_mock()

        for rank in range(1, 9):
            if rank == test_for_rank:
                continue
            mocked_connection_magic_mock = mock.MagicMock()
            mocked_connection_magic_mock.execute.return_value = None
            mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
                rank,
                restructured_loan_ids_list=restructured_loan_ids_list,
                loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            )
            mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
            grab_payments = None
            result_count = 0
            for result in get_eligible_grab_payment_for_dialer(
                rank,
                restructured_loan_ids_list,
                get_loan_xids_based_on_c_score(
                grab_intellix_cscore_obj, rank)):
                result_count += 1
                grab_payments = result[0]
                self.assertFalse(grab_payments.filter(loan__customer=loan_rank.customer).exists())
                self.assertFalse(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
                mocked_connection.reset_mock()

            if rank not in [7,8]:
                self.assertEqual(result_count, 0)

    @mock.patch('juloserver.minisquad.services2.intelix.connection')
    def test_get_eligible_grab_payment_for_dialer_rank_4(self, mocked_connection):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer,
            account_lookup=self.account_lookup
        )
        loan_rank = LoanFactory(
            loan_purpose='Grab_loan_creation',
            loan_amount=3000000,
            loan_duration=180,
            account=account,
            customer=customer,
            loan_status=StatusLookupFactory(status_code=231),
            loan_xid=1000006488
        )
        grab_loan_data_rank = GrabLoanDataFactory(
            loan=loan_rank,
            is_repayment_capped=False
        )
        loan_payments_rank = Payment.objects.filter(
            loan=loan_rank).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=10))

        grab_intelix_cscore = GrabIntelixCScoreFactory(
            loan_xid=loan_rank.loan_xid,
            grab_user_id=123,
            vehicle_type='type1',
            cscore=250,
            customer_id=customer.id
        )
        yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
        grab_intelix_cscore.cdate = yesterday
        grab_intelix_cscore.save()

        for idx, payment in enumerate(loan_payments_rank):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 90000
            payment.save()

        grab_intelix_cscore.cscore = 500
        grab_intelix_cscore.save()

        grab_loan_data_rank.is_repayment_capped = True
        grab_loan_data_rank.save()

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

        test_for_rank = 4
        for result in get_eligible_grab_payment_for_dialer(
            test_for_rank,
            restructured_loan_ids_list,
            get_loan_xids_based_on_c_score(
            grab_intellix_cscore_obj, test_for_rank)):
            grab_payments, list_account_ids = result[0], result[1]

            self.assertTrue(grab_payments.filter(loan__customer=loan_rank.customer).exists())
            self.assertTrue(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
            self.assertEqual(1, grab_payments.count())
            mocked_connection.cursor.return_value.__enter__.assert_called()
        mocked_connection.reset_mock()

        for rank in range(1, 9):
            if rank == test_for_rank:
                continue
            mocked_connection_magic_mock = mock.MagicMock()
            mocked_connection_magic_mock.execute.return_value = None
            mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
                rank,
                restructured_loan_ids_list=restructured_loan_ids_list,
                loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            )
            mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
            grab_payments = None
            result_count = 0
            for result in get_eligible_grab_payment_for_dialer(
                rank,
                restructured_loan_ids_list,
                get_loan_xids_based_on_c_score(
                grab_intellix_cscore_obj, rank)):
                result_count += 1
                grab_payments = result[0]
                self.assertFalse(grab_payments.filter(loan__customer=loan_rank.customer).exists())
                self.assertFalse(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
                mocked_connection.reset_mock()

            if rank not in [7,8]:
                self.assertEqual(result_count, 0)

    @mock.patch('juloserver.minisquad.services2.intelix.connection')
    def test_get_eligible_grab_payment_for_dialer_rank_5(self, mocked_connection):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer,
            account_lookup=self.account_lookup
        )
        loan_rank = LoanFactory(
            loan_purpose='Grab_loan_creation',
            loan_amount=3000000,
            loan_duration=180,
            account=account,
            customer=customer,
            loan_status=StatusLookupFactory(status_code=231),
            loan_xid=1000006489
        )
        grab_loan_data_rank = GrabLoanDataFactory(
            loan=loan_rank,
            is_repayment_capped=False
        )
        loan_payments_rank = Payment.objects.filter(
            loan=loan_rank).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=20))

        grab_intelix_cscore = GrabIntelixCScoreFactory(
            loan_xid=loan_rank.loan_xid,
            grab_user_id=123,
            vehicle_type='type1',
            cscore=250,
            customer_id=customer.id
        )
        yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
        grab_intelix_cscore.cdate = yesterday
        grab_intelix_cscore.save()

        for idx, payment in enumerate(loan_payments_rank):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 90000
            payment.save()

        grab_intelix_cscore.cscore = 700
        grab_intelix_cscore.save()

        grab_loan_data_rank.is_repayment_capped = False
        grab_loan_data_rank.save()

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

        test_for_rank = 5
        for result in get_eligible_grab_payment_for_dialer(
            test_for_rank,
            restructured_loan_ids_list,
            get_loan_xids_based_on_c_score(
            grab_intellix_cscore_obj, test_for_rank)):
            grab_payments, list_account_ids = result[0], result[1]

            self.assertTrue(grab_payments.filter(loan__customer=loan_rank.customer).exists())
            self.assertTrue(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
            self.assertEqual(1, grab_payments.count())
            mocked_connection.cursor.return_value.__enter__.assert_called()
        mocked_connection.reset_mock()

        for rank in range(1, 9):
            if rank == test_for_rank:
                continue
            mocked_connection_magic_mock = mock.MagicMock()
            mocked_connection_magic_mock.execute.return_value = None
            mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
                rank,
                restructured_loan_ids_list=restructured_loan_ids_list,
                loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            )
            mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
            grab_payments = None
            result_count = 0
            for result in get_eligible_grab_payment_for_dialer(
                rank,
                restructured_loan_ids_list,
                get_loan_xids_based_on_c_score(
                grab_intellix_cscore_obj, rank)):
                result_count += 1
                grab_payments = result[0]
                self.assertFalse(grab_payments.filter(loan__customer=loan_rank.customer).exists())
                self.assertFalse(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
                mocked_connection.reset_mock()

            if rank not in [7,8]:
                self.assertEqual(result_count, 0)

    @mock.patch('juloserver.minisquad.services2.intelix.connection')
    def test_get_eligible_grab_payment_for_dialer_rank_6(self, mocked_connection):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer,
            account_lookup=self.account_lookup
        )
        loan_rank = LoanFactory(
            loan_purpose='Grab_loan_creation',
            loan_amount=3000000,
            loan_duration=180,
            account=account,
            customer=customer,
            loan_status=StatusLookupFactory(status_code=231),
            loan_xid=1000006490
        )
        grab_loan_data_rank = GrabLoanDataFactory(
            loan=loan_rank,
            is_repayment_capped=False
        )
        loan_payments_rank = Payment.objects.filter(
            loan=loan_rank).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=20))

        grab_intelix_cscore = GrabIntelixCScoreFactory(
            loan_xid=loan_rank.loan_xid,
            grab_user_id=123,
            vehicle_type='type1',
            cscore=250,
            customer_id=customer.id
        )
        yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
        grab_intelix_cscore.cdate = yesterday
        grab_intelix_cscore.save()

        for idx, payment in enumerate(loan_payments_rank):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 90000
            payment.save()

        grab_intelix_cscore.cscore = 700
        grab_intelix_cscore.save()

        grab_loan_data_rank.is_repayment_capped = True
        grab_loan_data_rank.save()

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

        test_for_rank = 6
        for result in get_eligible_grab_payment_for_dialer(
            test_for_rank,
            restructured_loan_ids_list,
            get_loan_xids_based_on_c_score(
            grab_intellix_cscore_obj, test_for_rank)):
            grab_payments, list_account_ids = result[0], result[1]

            self.assertTrue(grab_payments.filter(loan__customer=loan_rank.customer).exists())
            self.assertTrue(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
            self.assertEqual(1, grab_payments.count())
            mocked_connection.cursor.return_value.__enter__.assert_called()
        mocked_connection.reset_mock()

        for rank in range(1, 9):
            if rank == test_for_rank:
                continue
            mocked_connection_magic_mock = mock.MagicMock()
            mocked_connection_magic_mock.execute.return_value = None
            mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
                rank,
                restructured_loan_ids_list=restructured_loan_ids_list,
                loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            )
            mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
            grab_payments = None
            result_count = 0
            for result in get_eligible_grab_payment_for_dialer(
                rank,
                restructured_loan_ids_list,
                get_loan_xids_based_on_c_score(
                grab_intellix_cscore_obj, rank)):
                result_count += 1
                grab_payments = result[0]
                self.assertFalse(grab_payments.filter(loan__customer=loan_rank.customer).exists())
                self.assertFalse(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
                mocked_connection.reset_mock()

            if rank not in [7,8]:
                self.assertEqual(result_count, 0)

    @mock.patch('juloserver.minisquad.services2.intelix.connection')
    def test_get_eligible_grab_payment_for_dialer_rank_7(self, mocked_connection):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer,
            account_lookup=self.account_lookup
        )
        loan_rank = LoanFactory(
            loan_purpose='Grab_loan_creation',
            loan_amount=3000000,
            loan_duration=180,
            account=account,
            customer=customer,
            loan_status=StatusLookupFactory(status_code=231),
            loan_xid=1000006491
        )
        grab_loan_data_rank = GrabLoanDataFactory(
            loan=loan_rank,
            is_repayment_capped=False
        )
        loan_payments_rank = Payment.objects.filter(
            loan=loan_rank).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=4))

        for idx, payment in enumerate(loan_payments_rank):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 90000
            payment.save()

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

        test_for_rank = 7
        for result in get_eligible_grab_payment_for_dialer(
            test_for_rank,
            restructured_loan_ids_list,
            get_loan_xids_based_on_c_score(
            grab_intellix_cscore_obj, test_for_rank)):
            grab_payments, list_account_ids = result[0], result[1]

            self.assertTrue(grab_payments.filter(loan__customer=loan_rank.customer).exists())
            self.assertTrue(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
            self.assertEqual(1, grab_payments.count())
            mocked_connection.cursor.return_value.__enter__.assert_called()
        mocked_connection.reset_mock()

        for rank in range(1, 9):
            if rank == test_for_rank:
                continue
            mocked_connection_magic_mock = mock.MagicMock()
            mocked_connection_magic_mock.execute.return_value = None
            mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
                rank,
                restructured_loan_ids_list=restructured_loan_ids_list,
                loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            )
            mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
            grab_payments = None
            result_count = 0
            for result in get_eligible_grab_payment_for_dialer(
                rank,
                restructured_loan_ids_list,
                get_loan_xids_based_on_c_score(
                grab_intellix_cscore_obj, rank)):
                result_count += 1
                grab_payments = result[0]
                self.assertFalse(grab_payments.filter(loan__customer=loan_rank.customer).exists())
                self.assertFalse(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
                mocked_connection.reset_mock()

            if rank not in [7,8]:
                self.assertEqual(result_count, 0)

    @mock.patch('juloserver.minisquad.services2.intelix.connection')
    def test_get_eligible_grab_payment_for_dialer_rank_8(self, mocked_connection):
        customer = CustomerFactory()
        account = AccountFactory(
            customer=customer,
            account_lookup=self.account_lookup
        )
        loan_rank = LoanFactory(
            loan_purpose='Grab_loan_creation',
            loan_amount=3000000,
            loan_duration=180,
            account=account,
            customer=customer,
            loan_status=StatusLookupFactory(status_code=231),
            loan_xid=1000006492
        )
        grab_loan_data_rank = GrabLoanDataFactory(
            loan=loan_rank,
            is_repayment_capped=True
        )
        loan_payments_rank = Payment.objects.filter(
            loan=loan_rank).order_by('id')
        start_date = timezone.localtime(timezone.now() - relativedelta(days=4))

        for idx, payment in enumerate(loan_payments_rank):
            payment.due_date = start_date + relativedelta(days=idx)
            payment.is_restructured = False
            payment.payment_status = StatusLookupFactory(status_code=320)
            payment.late_fee_amount = 10000
            payment.due_amount = 90000
            payment.save()

        restructured_loan_ids_list = GrabLoanData.objects.filter(
            loan_id__isnull=False,
            is_repayment_capped=True,
            loan__loan_status_id__in=LoanStatusCodes.grab_current_until_90_dpd()
        ).values_list('loan_id', flat=True)
        grab_intellix_cscore_obj = GrabIntelixCScore.objects.all()

        test_for_rank = 8
        for result in get_eligible_grab_payment_for_dialer(
            test_for_rank,
            restructured_loan_ids_list,
            get_loan_xids_based_on_c_score(
            grab_intellix_cscore_obj, test_for_rank)):
            grab_payments, list_account_ids = result[0], result[1]

            self.assertTrue(grab_payments.filter(loan__customer=loan_rank.customer).exists())
            self.assertTrue(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
            self.assertEqual(1, grab_payments.count())
            mocked_connection.cursor.return_value.__enter__.assert_called()
        mocked_connection.reset_mock()

        for rank in range(1, 9):
            if rank == test_for_rank:
                continue
            mocked_connection_magic_mock = mock.MagicMock()
            mocked_connection_magic_mock.execute.return_value = None
            mocked_connection_magic_mock.fetchall.return_value = self.get_data_from_raw_query(
                rank,
                restructured_loan_ids_list=restructured_loan_ids_list,
                loan_xids_based_on_c_score_list=get_loan_xids_based_on_c_score(
                    grab_intellix_cscore_obj, rank
                )
            )
            mocked_connection.cursor.return_value.__enter__.return_value = mocked_connection_magic_mock
            grab_payments = None
            result_count = 0
            for result in get_eligible_grab_payment_for_dialer(
                rank,
                restructured_loan_ids_list,
                get_loan_xids_based_on_c_score(
                grab_intellix_cscore_obj, rank)):
                result_count += 1
                grab_payments = result[0]
                self.assertFalse(grab_payments.filter(loan__customer=loan_rank.customer).exists())
                self.assertFalse(grab_payments.filter(loan__loan_xid=loan_rank.loan_xid).exists())
                mocked_connection.reset_mock()

            if rank not in [7,8]:
                self.assertEqual(result_count, 0)


class TestIntelixCallback(JuloAPITestCase):
    def setUp(self) -> None:
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        self.product_lookup = ProductLookupFactory()

        self.user = AuthUserFactory(username='agenttest')
        self.workflow = WorkflowFactory(
            name=WorkflowConst.GRAB,
            handler='GrabWorkflowHandler'
        )
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow,
            name='GRAB',
            payment_frequency='daily'
        )
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            account_lookup=self.account_lookup
        )
        self.skiptrace_result_choice = SkiptraceResultChoiceFactory(name='RPC - Regular')
        SkiptraceResultChoice.objects.create(
            name='RPC - PTP', weight=-20, customer_reliability_score=10
        )
        self.skiptrace_choice_tidak_diangkat = SkiptraceResultChoiceFactory(name='Tidak Diangkat')
        self.skiptrace_choice_busy = SkiptraceResultChoiceFactory(name='Busy')
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account,
            application_status=StatusLookupFactory(status_code=190)
        )
        self.loan = LoanFactory(
            loan_purpose='Grab_loan_creation', loan_amount=1000000, loan_duration=180,
            account=self.account, customer=self.customer,
            loan_status=StatusLookupFactory(status_code=231)
        )
        for payment in self.loan.payment_set.all():
            account_payment = AccountPaymentFactory(
                account=self.account,
                due_date=payment.due_date,
                due_amount=payment.due_amount
            )
            account_payment.save()
            payment.account_payment = account_payment
            payment.save()

        self.callback_data = {
            "CALLBACK_TIME": "12:00:00",
            "START_TS": "2022-11-16 19:01:06",
            "END_TS": "2022-11-16 19:01:06",
            "NON_PAYMENT_REASON": "Other",
            "SPOKE_WITH": "User",
            "CALL_STATUS": "RPC - Regular",
            "AGENT_NAME": "agenttest",
            "NOTES": "dpd 12",
            "PHONE_NUMBER": "6286620960079",
            "CALL_ID": "neverspoke7",
            "ACCOUNT_ID": str(self.account.id)
        }

    def test_grab_intellix_callback_agent_missing(self):
        self.callback_data['AGENT_NAME'] = 'missing_agent'
        response = self.client.realtime_agent_level_call_result(self.callback_data)
        self.assertEqual(400, response.status_code)

    def test_grab_intellix_callback_skiptrace_missing(self):
        self.callback_data['CALL_STATUS'] = 'invalid'
        response = self.client.realtime_agent_level_call_result(self.callback_data)
        self.assertEqual(400, response.status_code)

    def test_grab_intellix_callback_success(self):
        self.callback_data['CALL_STATUS'] = 'RPC - Regular'
        self.callback_data['AGENT_NAME'] = 'agenttest'
        response = self.client.realtime_agent_level_call_result(self.callback_data)
        self.assertEqual(200, response.status_code)
        self.assertTrue(GrabSkiptraceHistory.objects.filter(
            account_id=self.account.id,
            source='Intelix',
            agent_name='agenttest'
        ).exists())

    def test_grab_intellix_callback_missing_account(self):
        self.callback_data['CALL_STATUS'] = 'RPC - Regular'
        self.callback_data['AGENT_NAME'] = 'agenttest'
        self.callback_data.pop('ACCOUNT_ID')
        response = self.client.realtime_agent_level_call_result(self.callback_data)
        self.assertEqual(400, response.status_code)

    @mock.patch('juloserver.minisquad.views.ptp_create_v2')
    def test_grab_intellix_callback_ptp_success(self, mocked_ptp_create):
        self.callback_data['CALL_STATUS'] = 'RPC - Regular'
        self.callback_data['AGENT_NAME'] = 'agenttest'
        self.callback_data['PTP_AMOUNT'] = '10000'
        self.callback_data['PTP_DATE'] = '2022-12-12'
        mocked_ptp_create.return_value = True
        response = self.client.realtime_agent_level_call_result(self.callback_data)
        self.assertEqual(200, response.status_code)
        self.assertTrue(GrabSkiptraceHistory.objects.filter(
            account_id=self.account.id,
            source='Intelix',
            agent_name='agenttest'
        ).exists())
        mocked_ptp_create.assert_called()
        mocked_ptp_create.assert_called_with(
            mock.ANY, '2022-12-12', '10000', mock.ANY, mock.ANY, True)

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task.create_failed_call_results.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task.trigger_insert_col_history.delay')
    def test_failed_store_system_call_result_account_not_found(self,
                                                               mock_trigger_insert_col_history,
                                                               mock_create_failed_call):
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.SKIPTRACE_HISTORY_SYSTEM_LEVEL
        )
        skiptrace_result_choices = SkiptraceResultChoice.objects.all().values_list('id', 'name')

        call_results = [{
            "CALLBACK_TIME": "12:00:00",
            "START_TS": "2022-11-16 19:01:06",
            "END_TS": "2022-11-16 19:01:06",
            "NON_PAYMENT_REASON": "Other",
            "SPOKE_WITH": "User",
            "CALL_STATUS": "Busy",
            "AGENT_NAME": "agenttest",
            "NOTES": "dpd 12",
            "PHONE_NUMBER": "6286620960079",
            "CALL_ID": "neverspoke7",
            "ACCOUNT_ID": 12345
        }]
        store_system_call_result_in_bulk(call_results, dialer_task.id, skiptrace_result_choices)
        self.assertTrue(mock_create_failed_call.called)
        mock_trigger_insert_col_history.assert_not_called()

        grab_skiptrace_history = GrabSkiptraceHistory.objects.all()
        self.assertEqual(len(grab_skiptrace_history), 0)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.logger.exception')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task.create_failed_call_results.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task.trigger_insert_col_history.delay')
    def test_failed_store_system_call_result_grab_skiptrace_exist(self,
                                                                  mock_trigger_insert_col_history,
                                                                  mock_create_failed_call,
                                                                  mocked_logger):
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.SKIPTRACE_HISTORY_SYSTEM_LEVEL
        )
        skiptrace_result_choices = SkiptraceResultChoice.objects.all().values_list('id', 'name')

        call_results = [{
            "CALLBACK_TIME": "12:00:00",
            "START_TS": "2022-11-16 19:01:06",
            "END_TS": "2022-11-16 19:01:06",
            "NON_PAYMENT_REASON": "Other",
            "SPOKE_WITH": "User",
            "CALL_STATUS": "Busy",
            "AGENT_NAME": "agenttest",
            "NOTES": "dpd 12",
            "PHONE_NUMBER": "6286620960079",
            "CALL_ID": "neverspoke7",
            "ACCOUNT_ID": str(self.account.id)
        }]

        start_ts = datetime.strptime(call_results[0].get('START_TS'), '%Y-%m-%d %H:%M:%S')
        end_ts = datetime.strptime(call_results[0].get('END_TS'), '%Y-%m-%d %H:%M:%S')
        call_status = call_results[0].get('CALL_STATUS')
        phone = call_results[0].get('PHONE_NUMBER')

        skiptrace = Skiptrace.objects.create(
            phone_number=format_e164_indo_phone_number(phone),
            customer=self.customer,
            application=self.application
        )

        skip_result_choice_id = skiptrace_result_choices[2][0]

        GrabSkiptraceHistory.objects.create(
            account=self.account,
            skiptrace_id=skiptrace.id,
            start_ts=start_ts,
            end_ts=end_ts,
            dialer_task_id=dialer_task.id,
            status=call_status,
            call_result_id=skip_result_choice_id,
            source='Intelix'
        )
        store_system_call_result_in_bulk(call_results, dialer_task.id, skiptrace_result_choices)
        mock_create_failed_call.assert_not_called()
        mock_trigger_insert_col_history.assert_not_called()
        mocked_logger.assert_called_with({
            "action_view": "store_system_call_result",
            "error": "skip trace history already exists",
            "account_type": "GRAB",
        })

    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task.create_failed_call_results.delay')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task.trigger_insert_col_history.delay')
    def test_success_store_system_call_result(self, mock_trigger_insert_col_history,
                                              mock_create_failed_call):
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.SKIPTRACE_HISTORY_SYSTEM_LEVEL
        )
        skiptrace_result_choices = SkiptraceResultChoice.objects.all().values_list('id', 'name')

        call_results = [{
            "CALLBACK_TIME": "12:00:00",
            "START_TS": "2022-11-16 19:01:06",
            "END_TS": "2022-11-16 19:01:06",
            "NON_PAYMENT_REASON": "Other",
            "SPOKE_WITH": "User",
            "CALL_STATUS": "call rejected",
            "AGENT_NAME": "agenttest",
            "NOTES": "dpd 12",
            "PHONE_NUMBER": "6286620960079",
            "CALL_ID": "neverspoke7",
            "ACCOUNT_ID": str(self.account.id)
        }]
        store_system_call_result_in_bulk(call_results, dialer_task.id, skiptrace_result_choices)
        mock_create_failed_call.assert_not_called()
        self.assertTrue(mock_trigger_insert_col_history.called)

        grab_skiptrace_history = GrabSkiptraceHistory.objects.all()
        self.assertEqual(len(grab_skiptrace_history), 1)

    @mock.patch('juloserver.minisquad.views.download_call_recording_via_sftp',
                side_effect=mock_download_sftp)
    def test_success_store_recording_detail(self, mocked):
        # for grab bucket data sending loan_id, payment_id, account_payment_id as empty string
        data = {
            'ACCOUNT_ID': self.account.id,
            'LOAN_ID': "",
            'PAYMENT_ID': "",
            'START_TS': '2023-08-29 09:50:29',
            'END_TS': '2023-08-29 10:00:29',
            'BUCKET': IntelixTeam.GRAB,
            'CALL_TO': '6281111111111',
            'VOICE_PATH': '/files/recording2/2023/08/29/29080030-4024-ce6f78190d.wav',
            'CALL_ID': '672776_64ed4315c1f32',
            'AGENT_NAME': self.user.username,
            'CALL_STATUS': 'RPC - PTP',
        }
        response = self.client.storing_recording_file_call_result(data)

        storing_recording_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.STORING_RECORDING_INTELIX
        ).last()

        vendor_recording_detail = VendorRecordingDetail.objects.filter(
            unique_call_id=data.get('CALL_ID')).last()
        self.assertEqual(storing_recording_dialer_task.status, DialerTaskStatus.SUCCESS)
        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertIsNotNone(vendor_recording_detail)

    @mock.patch('juloserver.minisquad.views.download_call_recording_via_sftp',
                side_effect=mock_download_sftp)
    def test_failed_store_recording_detail(self, mocked):
        data = {
            'ACCOUNT_ID': self.account.id,
            'LOAN_ID': "",
            'PAYMENT_ID': "",
            'START_TS': "",
            'END_TS': '2023-08-29 10:00:29',
            'BUCKET': IntelixTeam.GRAB,
            'CALL_TO': '6281111111111',
            'VOICE_PATH': '/files/recording2/2023/08/29/29080030-4024-ce6f78190d.wav',
            'CALL_ID': '672776_64ed4315c1f32',
            'AGENT_NAME': "",
            'CALL_STATUS': 'RPC - PTP',
        }
        response = self.client.storing_recording_file_call_result(data)

        storing_recording_dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.STORING_RECORDING_INTELIX
        ).last()

        vendor_recording_detail = VendorRecordingDetail.objects.filter(
            unique_call_id=data.get('CALL_ID')).last()
        self.assertEqual(storing_recording_dialer_task.status, DialerTaskStatus.FAILURE)
        self.assertEqual(response.status_code, HTTPStatus.BAD_REQUEST)
        self.assertIsNone(vendor_recording_detail)


class TestIntelixTimeout(TestCase):
    def test_intelix_timeout(self):
        intelix_client = get_julo_intelix_client()
        self.assertEqual(intelix_client.INTELIX_READ_TIMEOUT, 120)
        self.assertEqual(intelix_client.INTELIX_CONNECT_TIMEOUT, 120)
