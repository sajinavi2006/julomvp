import ast
import json
from unittest import skip

import mock
import os

from celery.exceptions import Retry
from django.conf import settings
from mock import patch
from datetime import (
    datetime,
    timedelta,
)
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from factory import Iterator
from django.db import connection

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountPropertyFactory,
    ExperimentGroupFactory,
)
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
    AccountPaymentwithPaymentFactory,
)
from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.apiv2.tests.factories import PdCollectionModelResultFactory
from juloserver.julo.tests.factories import (
    LoanFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    ExperimentSettingFactory,
    ApplicationFactory,
    ProductLineFactory,
    AuthUserFactory,
    CustomerFactory,
    SkiptraceResultChoiceFactory,
)
from juloserver.minisquad.constants import (
    FeatureNameConst,
    IntelixTeam,
    DialerTaskType,
    ReasonNotSentToDialer,
    DialerTaskStatus,
    AIRudderPDSConstant,
    DEFAULT_DB,
    RedisKey,
)
from juloserver.minisquad.models import (
    DialerTask,
    CollectionDialerTemporaryData,
    NotSentToDialer,
    CollectionBucketInhouseVendor,
    CollectionDialerTaskSummaryAPI,
)
from juloserver.minisquad.services2.ai_rudder_pds import AiRudderPDSManager
from juloserver.minisquad.services2.dialer_related import \
    update_sort_rank_and_get_final_call_re_experiment_data
from juloserver.minisquad.tasks2.intelix_task2 import (
    populate_temp_data_for_dialer,
    process_populate_bucket_3_vendor_distribution_sort1_method,
    process_populate_bucket_3_vendor_distribution_experiment1_method,
    process_exclude_for_sent_dialer_per_part,
)
from juloserver.minisquad.tests.factories import (
    NotSentToDialerFactory,
    SentToDialerFactory,
    CollectionDialerTemporaryDataFactory,
)
from juloserver.account_payment.models import AccountPayment
from juloserver.julo.constants import ExperimentConst
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConst
from juloserver.account.models import ExperimentGroup, Account
from juloserver.minisquad.tests.factories import (
    DialerTaskFactory,
    CollectionBucketInhouseVendorFactory
)
from django.test import TestCase
from juloserver.account_payment.models import AccountPayment
from juloserver.minisquad.constants import DialerSystemConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.minisquad.tasks2.dialer_system_task import (
    clear_dynamic_airudder_config,
    delete_paid_payment_from_dialer,
    process_retrieve_call_recording_data,
    send_airudder_request_data_to_airudder,
    trigger_upload_data_to_dialer,
    sent_alert_data_discrepancies,
    fix_start_ts_skiptrace_history_daily,
    sync_call_result_agent_level,
)
from juloserver.collection_vendor.tests.factories import SkiptraceHistoryFactory
from juloserver.julo.models import SkiptraceHistory


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestPopulateTempDataForDialer(APITestCase):
    def setUp(self):
        self.current_date = timezone.localtime(timezone.now()).date()
        self.status = StatusLookupFactory(status_code=420)
        self.redis_data = {}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_exclude_account_ids_by_ana_above_2_mio')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_eligible_account_payment_for_dialer_and_vendor_qs')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    def test_populate_temp_data_for_dialer(
            self, mock_delete_redis_key, mock_redis_client,
            mock_eligible_account_payment_qs, mock_get_exclude_ana_accounts
    ):
        account = AccountFactory(ever_entered_B5=False, status=self.status)
        account.accountpayment_set.all().delete()
        account_payment_b2 = AccountPaymentFactory(
            account=account,
            due_date=self.current_date - timedelta(days=20),
            is_collection_called=False
        )
        account_payment_b2.account = account
        account_payment_b2.save()
        account_b3 = AccountFactory(
            ever_entered_B5=False, status=self.status)
        account_b3.accountpayment_set.all().delete()
        account_payment_b3 = AccountPaymentFactory(
            account=account_b3,
            due_date=self.current_date - timedelta(days=50),
            is_collection_called=False
        )
        account_payment_b3.account = account_b3
        account_payment_b3.save()
        account_b4 = AccountFactory(
            ever_entered_B5=False, status=self.status)
        account_b4.accountpayment_set.all().delete()
        account_payment_b4 = AccountPaymentFactory(
            account=account_b4,
            due_date=self.current_date - timedelta(days=80),
            is_collection_called=False
        )
        account_payment_b4.account = account_b4
        account_payment_b4.save()
        parameters = {
            IntelixTeam.JULO_B2: 10000,
            IntelixTeam.JULO_B3: 5000,
            IntelixTeam.JULO_B4: 1000
        }
        ApplicationFactory.create_batch(
            3,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            account=Iterator(Account.objects.all()),
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            parameters=parameters)
        mock_eligible_account_payment_qs.return_value.values_list.return_value = [
            account_payment_b2.id, account_payment_b3.id, account_payment_b4.id
        ]
        mock_delete_redis_key.return_value = True
        mock_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_get_exclude_ana_accounts.return_value = []
        populate_temp_data_for_dialer.delay(db_name=DEFAULT_DB)
        dialer_task_b2 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B2)
        ).last()
        dialer_task_b3 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B3)
        ).last()
        dialer_task_b4 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B4)
        ).last()
        self.assertTrue(dialer_task_b2)
        self.assertTrue(dialer_task_b3)
        self.assertTrue(dialer_task_b4)
        self.assertTrue(CollectionDialerTemporaryData.objects.filter(
            account_payment_id__in=[
                account_payment_b3.id,
                account_payment_b2.id,
                account_payment_b4.id]).count() >= 2
        )

    # handling B3 sort1 method
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_exclude_account_ids_by_ana_above_2_mio')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2'
        '.get_eligible_account_payment_for_dialer_and_vendor_qs')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    def test_populate_temp_data_for_dialer_b3_sort1_method(
            self, mock_delete_redis_key, mock_redis_client,
            mock_eligible_account_payment_qs, mock_get_exclude_ana_accounts
    ):
        current_time = timezone.localtime(timezone.now())
        b3_account_payments = []
        pgood_index = [
            0.98, 0.97, 0.96, 0.95, 0.94, 0.93, 0.92, 0.91, 0.90, 0.89, 0.88, 0.87, 0.86,
            0.85, 0.84
        ]
        for i in list(range(0, 15)):
            account = AccountFactory(ever_entered_B5=False, status=self.status)
            AccountPropertyFactory(pgood=pgood_index[i], account=account)
            account.accountpayment_set.all().delete()
            account_payment_b3 = AccountPaymentFactory(
                account=account,
                due_date=self.current_date - timedelta(days=50),
                is_collection_called=False
            )
            account_payment_b3.account = account
            account_payment_b3.save()
            b3_account_payments.append(account_payment_b3.id)
        parameters = {
            IntelixTeam.JULO_B2: 10000,
            IntelixTeam.JULO_B3: 5000,
            IntelixTeam.JULO_B4: 1000
        }
        ApplicationFactory.create_batch(
            15,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            account=Iterator(Account.objects.all()),
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            parameters=parameters)
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = 'block_traffic_intelix'
        feature_setting.is_active = True
        feature_setting.parameters = {
            'toggle': 'sort1',
            'max_ratio_threshold_for_due_amount_differences' : 0.05
        }
        feature_setting.save()
        # set some account payment goes to vendor
        for account_payment_id in b3_account_payments[:3]:
            not_sent_dialer = NotSentToDialerFactory(
                account_payment_id=account_payment_id,
                unsent_reason=ast.literal_eval(
                    ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR'])
            )
            not_sent_dialer.update_safely(cdate=current_time - timedelta(days=1))

        mock_eligible_account_payment_qs.return_value.values_list.return_value = b3_account_payments
        mock_delete_redis_key.return_value = True
        mock_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_get_exclude_ana_accounts.return_value = []
        populate_temp_data_for_dialer.delay(db_name=DEFAULT_DB)
        dialer_task_b3 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B3)
        ).last()
        self.assertTrue(dialer_task_b3)
        self.assertEqual(CollectionDialerTemporaryData.objects.filter(
            team__in=[IntelixTeam.JULO_B3, IntelixTeam.JULO_B3_NC]).count(), 12)
        process_populate_bucket_3_vendor_distribution_sort1_method.apply_async(kwargs={'db_name': DEFAULT_DB})
        # data_goes_to_inhouse = CollectionDialerTemporaryData.objects.filter(
        #     team__in=[IntelixTeam.JULO_B3, IntelixTeam.JULO_B3_NC])
        # self.assertTrue(len(data_goes_to_inhouse) == 6)
        # account_payment_inhouse = data_goes_to_inhouse.first()
        # account_payment_inhouse.account_payment_id = b3_account_payments[2]

    # handling B3 experiment1 method
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_exclude_account_ids_by_ana_above_2_mio')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2'
        '.get_eligible_account_payment_for_dialer_and_vendor_qs')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    def test_populate_temp_data_for_dialer_b3_experiment1_method(
            self, mock_delete_redis_key, mock_redis_client,
            mock_eligible_account_payment_qs, mock_get_exclude_ana_accounts
    ):
        current_time = timezone.localtime(timezone.now())
        accounts = AccountFactory.create_batch(
            15,
            id=Iterator([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]),
            ever_entered_B5=False,
            status=self.status
        )
        account_payments = AccountPaymentFactory.create_batch(
            15,
            account=Iterator(accounts),
            due_date=self.current_date - timedelta(days=50),
            is_collection_called=False
        )
        account_payment_ids = AccountPayment.objects.all().values_list('pk', flat=True)
        parameters = {
            IntelixTeam.JULO_B2: 10000,
            IntelixTeam.JULO_B3: 5000,
            IntelixTeam.JULO_B4: 1000
        }
        exp_setting = ExperimentSettingFactory(
            code = ExperimentConst.B3_DISTRIBUTION_EXPERIMENT,
            is_active=True,
            is_permanent=False,
            criteria={"account_id_tail_to_inhouse": [0, 1, 2, 3, 4]}
        )
        ApplicationFactory.create_batch(
            15,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            account=Iterator(accounts),
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            parameters=parameters)
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = 'block_traffic_intelix'
        feature_setting.is_active = True
        feature_setting.parameters = {
            'toggle': 'sort1'
        }
        feature_setting.save()
        # set some account payment goes to vendor
        b3_vendors = list(AccountPayment.objects.filter(
            account__in=[1, 4, 6]
        ).values_list('pk', flat=True))
        for account_payment_id in b3_vendors:
            not_sent_dialer = NotSentToDialerFactory(
                account_payment_id=account_payment_id,
                unsent_reason=ast.literal_eval(
                    ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR'])
            )
            not_sent_dialer.update_safely(cdate=current_time - timedelta(days=1))

        # set some account payment goes to inhouse
        b3_inhouses = list(AccountPayment.objects.filter(
            account__in=[2, 8]
        ).values_list('pk', flat=True))
        for account_payment_id in b3_inhouses:
            sent_to_dialer = SentToDialerFactory(
                account_payment_id=account_payment_id,
                cdate=current_time - timedelta(days=1),
                bucket=IntelixTeam.JULO_B3
            )
            sent_to_dialer.update_safely(cdate=current_time - timedelta(days=1))

        mock_eligible_account_payment_qs.return_value.values_list.return_value = account_payment_ids
        mock_delete_redis_key.return_value = True
        mock_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_get_exclude_ana_accounts.return_value = []
        populate_temp_data_for_dialer.delay(db_name=DEFAULT_DB)
        dialer_task_b3 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B3)
        ).last()
        # self.assertTrue(dialer_task_b3)
        # self.assertEqual(CollectionDialerTemporaryData.objects.filter(
        #     team__in=[IntelixTeam.JULO_B3, IntelixTeam.JULO_B3_NC]).count(), 12)
        # process_populate_bucket_3_vendor_distribution_experiment1_method.apply_async(
        #     kwargs={'db_name': DEFAULT_DB})
        # self.assertEqual(CollectionDialerTemporaryData.objects.filter(
        #     team__in=[IntelixTeam.JULO_B3, IntelixTeam.JULO_B3_NC]).count(), 8)
        # self.assertEqual(NotSentToDialer.objects.filter(
        #     unsent_reason=ast.literal_eval(
        #         ReasonNotSentToDialer.UNSENT_REASON['SENDING_B3_TO_VENDOR'])
        # ).distinct('account_payment').count(), 7)
        # # fresh data
        # self.assertEqual(ExperimentGroup.objects.filter(
        #     experiment_setting=exp_setting,
        #     group="b3 vendor group",
        #     account_payment_id__in=account_payment_ids).count(), 4)
        # self.assertEqual(ExperimentGroup.objects.filter(
        #     experiment_setting=exp_setting,
        #     group="b3 inhouse group",
        #     account_payment_id__in=account_payment_ids).count(), 6)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    def test_delete_tmp_inhouse_vendor_on_process_exclude_for_sent_dialer_per_part_goes_to_b4(
            self, mock_redis_client):
        account = AccountFactory(ever_entered_B5=False, status=self.status)
        account.accountpayment_set.all().delete()
        account_payment = AccountPaymentFactory(
            account=account,
            due_date=self.current_date - timedelta(days=75),
            is_collection_called=False
        )
        collection_inhouse_vendor = CollectionBucketInhouseVendorFactory(
            account_payment=account_payment,
            bucket=IntelixTeam.JULO_B3,
            vendor=False
        )
        self.redis_data = {
            'populate_eligible_call_account_payment_ids_JULO_B4_part_1': [account_payment.id]
        }
        bucket_name = IntelixTeam.JULO_B4
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.BATCHING_PROCESSED.format(bucket_name, '1')
        )
        mock_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_redis_client.return_value.get_list.side_effect = self.get_redis
        process_exclude_for_sent_dialer_per_part.delay(bucket_name, 1, dialer_task.id)
        result = CollectionBucketInhouseVendor.objects.get_or_none(account_payment=account_payment.id)
        self.assertIsNone(result)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2'
        '.get_exclude_account_ids_by_intelix_blacklist_improved')
    def test_delete_tmp_inhouse_vendor_on_process_exclude_for_sent_dialer_per_part_blacklist(
            self, mock_intelix_blacklist, mock_redis_client):
        account = AccountFactory(ever_entered_B5=False, status=self.status)
        account.accountpayment_set.all().delete()
        account_payment = AccountPaymentFactory(
            account=account,
            due_date=self.current_date - timedelta(days=60),
            is_collection_called=False
        )
        collection_inhouse_vendor = CollectionBucketInhouseVendorFactory(
            account_payment=account_payment,
            bucket=IntelixTeam.JULO_B3,
            vendor=False
        )
        self.redis_data = {
            'populate_eligible_call_account_payment_ids_JULO_B3_part_1': [account_payment.id]
        }
        bucket_name = IntelixTeam.JULO_B3
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.BATCHING_PROCESSED.format(bucket_name, '1')
        )
        mock_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_intelix_blacklist.return_value = [account.id]
        process_exclude_for_sent_dialer_per_part.delay(bucket_name, 1, dialer_task.id)
        result = CollectionBucketInhouseVendor.objects.get_or_none(account_payment=account_payment.id)
        self.assertIsNone(result)

    # experiment
    def test_final_call_re_experiment(self):
        finalcall_experiment_setting = ExperimentSettingFactory(
            code=MinisquadExperimentConst.FINAL_CALL_REEXPERIMENT,
            name="Final Call ReExperiment",
            type="collection",
            criteria={
                "experiment_group_name": "experiment",
                "control_group_name": "control",
            },
            is_active=True,
            is_permanent=False,
        )
        temp_data = []
        for i in range(20):
            account_payment = AccountPaymentwithPaymentFactory()
            data = CollectionDialerTemporaryDataFactory(
                team=IntelixTeam.JULO_B1, account_payment=account_payment, sort_order=None)
            temp_data.append(data)
        group = ['control', 'experiment']
        reversed_temp_data = temp_data[:10][::-1]
        for i in range(10):
            index = i + 1
            selected_group = group[index % 2]
            PdCollectionModelResultFactory(
                account_payment=reversed_temp_data[i].account_payment, sort_rank=index,
                experiment_group=selected_group, prediction_date=self.current_date)
        populated_dialer_call_data, experiment_data = \
            update_sort_rank_and_get_final_call_re_experiment_data(
                finalcall_experiment_setting, IntelixTeam.JULO_B1,
                IntelixTeam.BUCKET_1_EXPERIMENT)
        self.assertTrue(len(populated_dialer_call_data) == 10)
        self.assertTrue(len(experiment_data) == 10)
        self.assertTrue(populated_dialer_call_data[0].account_payment_id == reversed_temp_data[1].account_payment_id)
        self.assertTrue(experiment_data[0].account_payment_id == reversed_temp_data[0].account_payment_id)

        # end of experiment

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_omnichannel_comms_block_active')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_omnichannel_account_payment_ids')
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.get_exclude_account_ids_by_ana_above_2_mio'
    )
    @mock.patch(
        'juloserver.minisquad.tasks2.intelix_task2.get_eligible_account_payment_for_dialer_and_vendor_qs'
    )
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.delete_redis_key_list_with_prefix')
    def test_populate_temp_data_for_dialer_exclude_omnichannel(
        self,
        mock_delete_redis_key,
        mock_redis_client,
        mock_eligible_account_payment_qs,
        mock_get_exclude_ana_accounts,
        mock_get_omnichannel_account_payment_ids,
        mock_get_omnichannel_comms_block_active,
    ):
        account = AccountFactory(ever_entered_B5=False, status=self.status)
        account.accountpayment_set.all().delete()
        account_payment_b2 = AccountPaymentFactory(
            account=account,
            due_date=self.current_date - timedelta(days=20),
            is_collection_called=False,
        )
        account_payment_b2.account = account
        account_payment_b2.save()
        account_b3 = AccountFactory(ever_entered_B5=False, status=self.status)
        account_b3.accountpayment_set.all().delete()
        account_payment_b3 = AccountPaymentFactory(
            account=account_b3,
            due_date=self.current_date - timedelta(days=50),
            is_collection_called=False,
        )
        account_payment_b3.account = account_b3
        account_payment_b3.save()
        account_b4 = AccountFactory(ever_entered_B5=False, status=self.status)
        account_b4.accountpayment_set.all().delete()
        account_payment_b4 = AccountPaymentFactory(
            account=account_b4,
            due_date=self.current_date - timedelta(days=80),
            is_collection_called=False,
        )
        account_payment_b4.account = account_b4
        account_payment_b4.save()
        mock_get_omnichannel_account_payment_ids.return_value = [
            account_payment_b4.id,
        ]
        parameters = {
            IntelixTeam.JULO_B2: 10000,
            IntelixTeam.JULO_B3: 5000,
            IntelixTeam.JULO_B4: 1000,
        }
        ApplicationFactory.create_batch(
            3,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
            account=Iterator(Account.objects.all()),
        )
        FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            parameters=parameters,
        )
        mock_eligible_account_payment_qs.return_value.values_list.return_value = [
            account_payment_b2.id,
            account_payment_b3.id,
            account_payment_b4.id,
        ]
        mock_delete_redis_key.return_value = True
        mock_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_redis_client.return_value.get_list.side_effect = self.get_redis
        mock_get_exclude_ana_accounts.return_value = []
        mock_get_omnichannel_comms_block_active.return_value = mock.Mock(is_excluded=True)
        populate_temp_data_for_dialer.delay(db_name=DEFAULT_DB)
        dialer_task_b2 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B2)
        ).last()
        dialer_task_b3 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B3)
        ).last()
        dialer_task_b4 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B4)
        ).last()
        self.assertTrue(dialer_task_b2)
        self.assertTrue(dialer_task_b3)
        self.assertTrue(dialer_task_b4)
        self.assertTrue(
            CollectionDialerTemporaryData.objects.filter(
                account_payment_id__in=[
                    account_payment_b3.id,
                    account_payment_b2.id,
                ]
            ).count()
            >= 2
        )
        self.assertIsNone(
            CollectionDialerTemporaryData.objects.filter(
                account_payment_id=account_payment_b4.id
            ).first()
        )


def flush_temp_data_inhouse_vendor():
    # this function only for test purpose, so can test retroload several times
    cursor = connection.cursor()
    cursor.execute("TRUNCATE TABLE ops.collection_bucket_inhouse_vendor")
    cursor.close()


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class DeletePaidPaymentFromDialerTestCase(TestCase):

    def setUp(self):
        self.account = AccountFactory(ever_entered_B5=False)
        self.application = ApplicationFactory(
            account=self.account, mobile_phone_1='08123456789')
        self.account_payment = AccountPaymentFactory(account=self.account,)
        self.sent_to_dialer = SentToDialerFactory(
            account_payment=self.account_payment, task_id='unit_test_task_id')
        self.sent_to_dialer.cdate = datetime(
            2023, 5, 15, 15, 30, 0)
        self.sent_to_dialer.save()
        self.redis_data = {}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('juloserver.minisquad.services2.ai_rudder_pds.get_redis_client')
    @mock.patch('django.utils.timezone.localtime')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.get_list_of_task_id_today'
    )
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient.refresh_token')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.AIRudderPDSClient._make_request')
    def test_delete_paid_payment_from_dialer(
        self,
        mock_cancel_phone_call_by_phone_numbers,
        mock_token,
        mock_task_list,
        mock_redis,
        mock_time,
        mock_redis_service,
    ):
        mock_time.return_value = datetime(2023, 5, 15, 15, 30, 0)
        mock_response = mock.Mock()
        responses = {
            "code": 0, "message": AIRudderPDSConstant.SUCCESS_MESSAGE_RESPONSE, "body": ['+6281232413101']
        }
        self.redis_data[RedisKey.DAILY_TASK_IDS_FOR_CANCEL_CALL] = []
        mock_redis_service.return_value.set_list.side_effect = self.set_redis
        mock_redis_service.return_value.get_list.side_effect = self.get_redis
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis

        mock_response.text = json.dumps(responses)
        mock_response.status_code = 200
        mock_cancel_phone_call_by_phone_numbers.return_value = mock_response
        mock_token.return_value = 'token_unittest'
        mock_task_list.return_value = ['task_unittest_id']

        result = delete_paid_payment_from_dialer.delay(
            self.account_payment.id, DialerSystemConst.AI_RUDDER_PDS)
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
            delete_paid_payment_from_dialer.delay(
                self.account_payment.id, DialerSystemConst.AI_RUDDER_PDS)
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
            delete_paid_payment_from_dialer(
                self.account_payment.id, DialerSystemConst.AI_RUDDER_PDS)


class TestProcessRetrieveCallRecordingData(TestCase):
    def setUp(self):
        pass

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task'
        '.get_download_link_by_call_id')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task.AIRudderPDSServices')
    def test_retrive_data(
        self, mock_airudder, mock_download):
        mock_airudder.return_value.get_list_of_task_id_with_date_range\
            .return_value = ['task_12345']
        return_mock = []
        for i in range(0, 25):
            # create some case have null task id list and task detail
            if i in [2, 5, 9]:
                return_mock.append(0)
            elif i in [10, 14]:
                return_mock.append(1)
                return_mock.append([])
            elif i in [17, 18]:
                # create cas when total reach 50k data
                return_mock.append(50000)
            else:
                return_mock.append(1)
                return_mock.append([{'taskName': 'test', 'callid': 'call_123{}'.format(i)}])
        mock_airudder.return_value.get_call_results_data_by_task_id\
            .side_effect = return_mock
        process_retrieve_call_recording_data.delay()
        self.assertEqual(mock_download.si.call_count, 18)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestSendDataToDialer(TestCase):
    def setUp(self):
        self.feature_setting_full_rollout = FeatureSettingFactory(
            is_active=True,
            parameters={'eligible_bucket_number': [3], 'eligible_jturbo_bucket_number': [3]},
            feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT)

    @patch('juloserver.minisquad.tasks2.dialer_system_task.batch_data_per_bucket_for_send_to_dialer')
    def test_trigger_upload_data_to_dialer(self, mock_delay):
        # Call the task function
        trigger_upload_data_to_dialer()
        self.assertTrue(mock_delay.delay.call_count > 0)

@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestSentAlertDiscrepanciesData(TestCase):
    def setUp(self):
        self.feature_setting_full_rollout = FeatureSettingFactory(
            is_active=True,
            parameters={'discrepancies_threshold': 0.1},
            feature_name=FeatureNameConst.DIALER_DISCREPANCIES)
        self.redis_data = {}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.j1_get_task_ids_dialer')
    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.get_call_results_data_by_task_id_with_retry_mechasm'
    )
    @mock.patch('juloserver.julo.models.SkiptraceHistory.objects.filter')
    @mock.patch('juloserver.monitors.notifications.notify_dialer_discrepancies')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.get_redis_client')
    def test_not_sent_alert_discrepancies_data(self, mock_redis, mock_sent_slack, mock_skiptrace, mock_total, mock_task):
        mock_task.return_value = [
            {
                'task_name': 'julo_task_b1',
                'task_id': 'taskxxxx001'
            }
        ]
        mock_total.return_value = 125000
        mock_skiptrace.return_value.count.return_value = 124000
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        sent_alert_data_discrepancies.delay()
        mock_sent_slack.assert_not_called()
        self.assertEqual(1, CollectionDialerTaskSummaryAPI.objects.all().count())

    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.j1_get_task_ids_dialer')
    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.get_call_results_data_by_task_id_with_retry_mechasm'
    )
    @mock.patch('juloserver.julo.models.SkiptraceHistory.objects.filter')
    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task.notify_dialer_discrepancies')
    @mock.patch('juloserver.minisquad.clients.airudder_pds.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task.autorecon_discrepancies_data')
    def test_sent_alert_discrepancies_data(
        self, mock_autorecon ,mock_redis, mock_sent_slack, mock_skiptrace, mock_total, mock_task):
        mock_task.return_value = [
            {
                'task_name': 'julo_task_b1',
                'task_id': 'taskxxxx001'
            }
        ]
        mock_total.return_value = 125000
        mock_skiptrace.return_value.count.return_value = 90000
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        sent_alert_data_discrepancies.delay()
        mock_sent_slack.assert_called_once()
        mock_autorecon.delay.assert_called_once()
        self.assertEqual(1, CollectionDialerTaskSummaryAPI.objects.all().count())


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestFixStartTSSkiptraceHistoryDaily(TestCase):
    def setUp(self):
        start_ts = datetime(1970, 1, 1, 0, 0, 0)
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        for i in range(3):
            SkiptraceHistoryFactory(
                account=self.account,
                start_ts=start_ts,
                source='AiRudder',
                external_task_identifier='task_1',
                external_unique_identifier='call_{}'.format(str(i)),
            )

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('juloserver.minisquad.clients.airudder_pds.get_redis_client')
    @mock.patch(
        'juloserver.minisquad.services2.ai_rudder_pds.AIRudderPDSServices.get_call_results_data_by_task_id'
    )
    def test_fix_start_ts_data(self, mock_api, mock_redis):
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        mock_api.side_effect = [
            [{'calltime': '2024-04-18T04:03:06Z'}],
            [{'calltime': '2024-04-18T04:01:06Z'}],
            [{'calltime': '2024-04-18T04:02:06Z'}],
        ]
        fix_start_ts_skiptrace_history_daily.delay()
        self.assertEqual(
            0,
            SkiptraceHistory.objects.filter(
                source='AiRudder',
                external_task_identifier__isnull=False,
                start_ts__lt='2000-01-01 00:00:00+0700',
            ).count(),
        )


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestSyncCallResultAgentLevel(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        skiptrace_result_choices = SkiptraceResultChoiceFactory.create_batch(
            3, name=Iterator(['RPC - PTP', 'NULL', 'ACW - Interrupt'])
        )
        self.current_date = timezone.localtime(timezone.now()).replace(hour=10, minute=0, second=0)
        for i in range(3):
            SkiptraceHistoryFactory(
                cdate=self.current_date,
                source='AiRudder',
                external_task_identifier='task_1',
                external_unique_identifier='call_{}'.format(str(i)),
                call_result=skiptrace_result_choices[i],
                agent=self.user_auth,
                agent_name='agent_name_test',
            )

    @mock.patch(
        'juloserver.minisquad.tasks2.dialer_system_task.sync_call_result_agent_level_subtask'
    )
    def test_sync_call_result_agent_level(self, mock_subtask):
        sync_call_result_agent_level.delay()
        self.assertEquals(2, mock_subtask.delay.call_count)


@mock.patch('juloserver.minisquad.tasks2.dialer_system_task.store_dynamic_airudder_config')
@mock.patch('juloserver.minisquad.tasks2.dialer_system_task.AiRudderPDSSender')
@mock.patch('juloserver.minisquad.tasks2.dialer_system_task.AiRudderPDSManager')
@mock.patch(
    'juloserver.minisquad.tasks2.dialer_system_task.get_airudder_request_temp_data_from_cache'
)
class TestSendAirudderRequestDataToAirudder(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dialer_task = DialerTaskFactory()
        cls.req_data = {
            "bucket_name": "JULO_B3",
            "airudder_config": {},
            "batch_number": 2,
            "customers": [],
        }

    def test_success(
        self,
        mock_get_from_cache,
        mock_airudder_pds_manager,
        mock_airudder_pds_sender,
        mock_store_dynamic_airudder_config,
    ):
        mock_get_from_cache.return_value = self.req_data
        mock_airudder_pds_manager.return_value.create_task.return_value = 'task_id'

        task_id = send_airudder_request_data_to_airudder(self.dialer_task.id, "redis-key")

        self.assertEqual('task_id', task_id)
        mock_airudder_pds_sender.assert_called_once_with(
            bucket_name=self.req_data['bucket_name'],
            customer_list=self.req_data['customers'],
            strategy_config=self.req_data['airudder_config'],
            callback_url="{}/api/minisquad/airudder/webhooks".format(settings.BASE_URL),
            batch_number=self.req_data['batch_number'],
            source="OMNICHANNEL",
        )
        mock_airudder_pds_manager.assert_called_once_with(
            dialer_task=self.dialer_task,
            airudder_sender=mock_airudder_pds_sender.return_value,
        )
        mock_store_dynamic_airudder_config.assert_called_once_with(
            self.req_data['bucket_name'],
            self.req_data['airudder_config'],
        )

    def test_retry(
        self,
        mock_get_from_cache,
        mock_airudder_pds_manager,
        *args,
    ):
        mock_get_from_cache.return_value = self.req_data
        mock_airudder_pds_manager.NeedRetryException = AiRudderPDSManager.NeedRetryException
        mock_airudder_pds_manager.return_value.create_task.side_effect = (
            AiRudderPDSManager.NeedRetryException("exception")
        )

        with self.assertRaises(AiRudderPDSManager.NeedRetryException):
            send_airudder_request_data_to_airudder(self.dialer_task.id, "redis-key")


@mock.patch('juloserver.minisquad.tasks2.dialer_system_task.AiRudderPDSSettingManager')
@mock.patch('juloserver.minisquad.tasks2.dialer_system_task.get_redis_client')
class TestClearDynamicAiRudderConfig(TestCase):
    def test_success_delete(self, mock_get_redis, mock_setting_manager):
        mock_get_redis.return_value.get_list.return_value = ["bucket 1", "bucket 2"]

        clear_dynamic_airudder_config.delay()

        mock_setting_manager.has_calls(
            [
                mock.call('bucket 1'),
                mock.call('bucket 2'),
            ]
        )
        self.assertEqual(2, mock_setting_manager.return_value.remove_config_from_setting.call_count)

        mock_get_redis.return_value.get_list.assert_called_once_with(
            RedisKey.DYNAMIC_AIRUDDER_CONFIG,
        )
        mock_get_redis.return_value.delete_key.assert_called_once_with(
            RedisKey.DYNAMIC_AIRUDDER_CONFIG,
        )
