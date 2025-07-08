from builtins import range
from builtins import object
import json

import mock
import requests
from django.conf import settings
from django.test.testcases import TestCase
from django.test.utils import override_settings
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from datetime import datetime, timedelta
from django.utils import timezone
from mock import patch

from datetime import date
from factory import Iterator

from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.tests.factories import DanaCustomerDataFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import Agent, SkiptraceResultChoice, SkiptraceHistory, StatusLookup
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import sort_payment_and_account_payment_by_collection_model
from juloserver.julo.tasks import send_automated_comm_sms
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             LoanFactory,
                                             PaymentMethodFactory,
                                             PTPFactory,
                                             StatusLookupFactory, PaymentFactory,
                                             ApplicationFactory, SkiptraceFactory, WorkflowFactory,
                                             CustomerFactory, FeatureSettingFactory,
                                             PartnerFactory, ExperimentSettingFactory)
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory
from juloserver.minisquad.clients.intelix import JuloIntelixClient
from juloserver.minisquad.constants import DialerTaskStatus, DialerTaskType, ExperimentConst, DEFAULT_DB
from juloserver.minisquad.models import (
    CollectionSquad,
    FailedCallResult,
    DialerTask,
    NotSentToDialer,
    CollectionDialerTemporaryData,
    CollectionBucketInhouseVendor,
    VendorQualityExperiment,
)
from juloserver.minisquad.services2.intelix import (
    create_history_dialer_task_event,
    update_intelix_callback,
    construct_data_for_intelix, construct_status_and_status_group,
    construct_parameter_for_intelix_upload,
    get_phone_numbers_filter_by_intelix_blacklist
)
from juloserver.minisquad.tasks2.intelix_task import (
    # trigger_system_call_result_every_hours,
    store_agent_productivity_from_intelix_every_hours,
    # trigger_system_call_result_every_hours_last_attempt,
    store_agent_productivity_from_intelix_every_hours_last_attempt,
    construct_julo_b1_data_to_intelix,
    construct_julo_b2_data_to_intelix,
    construct_julo_b3_data_to_intelix,
    construct_julo_b1_non_contacted_data_to_intelix,
    construct_julo_b2_non_contacted_data_to_intelix,
    construct_julo_b3_non_contacted_data_to_intelix,
    upload_julo_b4_data_to_intelix,
    upload_julo_b4_non_contacted_data_to_intelix,
    trigger_slack_empty_bucket_sent_to_dialer_daily, upload_j1_jturbo_t_minus_to_intelix,
    set_time_retry_mechanism_and_send_alert_for_unsent_intelix_issue,
    retry_mechanism_and_send_alert_for_unsent_intelix_issue,
    construct_jturbo_b1_data_to_intelix,
    construct_jturbo_b1_nc_data_to_intelix,
    construct_jturbo_b2_data_to_intelix,
    construct_jturbo_b2_nc_data_to_intelix,
    construct_jturbo_b3_data_to_intelix,
    construct_jturbo_b3_nc_data_to_intelix,
    construct_jturbo_b4_data_to_intelix,
    construct_jturbo_b4_nc_data_to_intelix
)
from django.contrib.auth.models import User, Group
from juloserver.minisquad.constants import IntelixTeam
from juloserver.julo.models import Payment
from juloserver.minisquad.services import (
    get_payment_details_for_calling,
    exclude_ptp_payment_loan_ids,
    get_exclude_account_ids_by_intelix_blacklist
)
from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.minisquad.tasks2.intelix_task import create_failed_call_results
from juloserver.minisquad.tests.factories import (
    SentToDialerFactory,
    DialerTaskSentFactory,
    DialerTaskFactory,
    DialerTaskEventFactory,
    CollectionDialerTemporaryDataFactory,
    TemporaryStorageDialerFactory
)
from juloserver.minisquad.tests.factories import intelixBlacklistFactory
from juloserver.minisquad.constants import RedisKey
from juloserver.collection_vendor.tests.factories import (
    CollectionVendorRatioFactory,
    CollectionVendorFactory,
    SubBucketFactory)
from juloserver.minisquad.services2.intelix import get_redis_data_temp_table, set_redis_data_temp_table
from juloserver.minisquad.models import TemporaryStorageDialer
from juloserver.account.models import ExperimentGroup
from juloserver.apiv2.tests.factories import PdCollectionModelResultFactory
from juloserver.account.models import Account
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from juloserver.julo.models import FeatureNameConst
from unittest import skip


INTELIX_CALL_RESULTS_RESPONSE = [
    {
        "SKIPTRACE_HISTORY_ID": "",
        "AGENT_ID": "",
        "AGENT_NAME": "unittest",
        "APPLICATION_ID": 0,
        "APPLICATION_STATUS": "",
        "CALLBACK_TIME": "",
        "CDATE": "",
        "END_TS": "2020-06-16 08:00:29",
        "EXCLUDED_FROM_BUCKET": "",
        "LOAN_ID": 99,
        "LOAN_STATUS": "",
        "NON_PAYMENT_REASON": "",
        "NOTES": "",
        "OLD_APPLICATION_STATUS": "",
        "PAYMENT_ID": 991,
        "PAYMENT_STATUS": "",
        "SKIPTRACE_ID": "",
        "SKIPTRACE_RESULT_CHOICE_ID": "",
        "SPOKE_WITH": "",
        "START_TS": "2020-06-16 08:00:15",
        "UDATE": "0000-00-00 00:00:00",
        "PTP_DATE": "",
        "PTP_AMOUNT": "0",
        "CALL_STATUS": "Congestion (circuits busy)"
    }
]

INTELIX_AGENT_PRODUCTIVITY_RESULTS_RESPONSE = [
    {"INTERVAL": "08:00-09:00", "AGENT_NAME": "unittest", "SUMMARY_DATE": "2020-06-16",
     "INBOUND_CALLS_OFFERED": "0", "INBOUND_CALLS_ANSWERED": "0", "INBOUND_CALLS_NOT_ANSWERED": "0",
     "OUTBOUND_CALLS_INITIATED": "8", "OUTBOUND_CALLS_CONNECTED": "3", "OUTBOUND_CALLS_NOT_CONNECTED": "5",
     "OUTBOUND_CALLS_OFFERED": "8", "OUTBOUND_CALLS_ANSWERED": "8", "OUTBOUND_CALLS_NOT_ANSWERED": "5",
     "MANUAL_IN_CALLS_OFFERED": "0", "MANUAL_IN_CALLS_ANSWERED": "0", "MANUAL_IN_CALLS_NOT_ANSWERED": "0",
     "MANUAL_OUT_CALLS_INITIATED": "0", "MANUAL_OUT_CALLS_CONNECTED": "0", "MANUAL_OUT_CALLS_NOT_CONNECTED": "0",
     "INTERNAL_IN_CALLS_OFFERED": "0", "INTERNAL_IN_CALLS_ANSWERED": "0", "INTERNAL_IN_CALLS_NOT_ANSWERED": "0",
     "INTERNAL_OUT_CALLS_INITIATED": "0", "INTERNAL_OUT_CALLS_CONNECTED": "0", "INTERNAL_OUT_CALLS_NOT_CONNECTED": "0",
     "INBOUND_TALK_TIME": "00:00:00", "INBOUND_HOLD_TIME": "00:00:00", "INBOUND_ACW_TIME": "00:00:00",
     "INBOUND_HANDLING_TIME": "00:00:00", "OUTBOUND_TALK_TIME": "00:04:02", "OUTBOUND_HOLD_TIME": "00:00:00",
     "OUTBOUND_ACW_TIME": "00:11:19", "OUTBOUND_HANDLING_TIME": "00:04:21", "MANUAL_OUT_CALL_TIME": "00:00:00",
     "MANUAL_IN_CALL_TIME": "00:00:00", "INTERNAL_OUT_CALL_TIME": "00:00:00", "INTERNAL_IN_CALL_TIME": "00:00:00",
     "LOGGED_IN_TIME": "00:48:10", "AVAILABLE_TIME": "00:15:36", "AUX_TIME": "00:15:20", "BUSY_TIME": "00:16:35"}
]


class MiniSquadAPIClient(APIClient):

    def set_token(self):
        self.credentials(HTTP_AUTHORIZATION=settings.INTELIX_JULO_TOKEN)

    def realtime_agent_level_call_result(self, data):
        url = '/api/minisquad/upload/update-intelix-skiptrace-data-agent-level-calls'
        self.set_token()
        headers = {'Content-Type': 'multipart/form-data'}
        return self.post(url, data, headers=headers)

    def storing_recording_file_call_result(self, data):
        url = '/api/minisquad/store_recording_file_and_detail/'
        self.set_token()
        headers = {'Content-Type': 'multipart/form-data'}
        return self.post(url, data, headers=headers)

    def _mock_call_results_response(self, status=200, json_data=None):
        mock_resp = mock.Mock()
        mock_resp.status_code = status
        mock_resp.ok = status < 400
        if json_data:
            mock_resp.data = json_data
            mock_resp.json.return_value = json_data
        return mock_resp

    def mocked_call_results_response(self, data):
        return self._mock_call_results_response(
            status=200,
            json_data=data
        )

    def ajax_get_bucket_and_agent_data(self):
        url = '/mini_squad/ajax_get_bucket_and_agent_data'
        self.set_token()
        return self.get(url)

    def ajax_assign_agent_to_squad(self, data):
        url = '/mini_squad/ajax_assign_agent_to_squad'
        self.set_token()
        headers = {'Content-Type': 'multipart/form-data'}
        return self.post(url, data, headers=headers)


class JuloAPITestCase(APITestCase):
    client_class = MiniSquadAPIClient


class MockResponse(object):
    def __init__(self, data, status_code):
        self.data = data
        self.status_code = status_code

    def json(self):
        return json.loads(self.data)


def mocked_requests_get_for_call_results(*args, **kwargs):
    return MockResponse(
        json.dumps(INTELIX_CALL_RESULTS_RESPONSE), 200
    )


def mocked_requests_get_for_call_results_last_attempt(*args, **kwargs):
    response = INTELIX_CALL_RESULTS_RESPONSE
    error_data = [
        {
            "SKIPTRACE_HISTORY_ID": "",
            "AGENT_ID": "",
            "AGENT_NAME": "unittest",
            "APPLICATION_ID": 0,
            "APPLICATION_STATUS": "",
            "CALLBACK_TIME": "",
            "CDATE": "",
            "END_TS": "2020-06-16 08:00:29",
            "EXCLUDED_FROM_BUCKET": "",
            "LOAN_ID": 1000,
            "LOAN_STATUS": "",
            "NON_PAYMENT_REASON": "",
            "NOTES": "",
            "OLD_APPLICATION_STATUS": "",
            "PAYMENT_ID": 1001,
            "PAYMENT_STATUS": "",
            "SKIPTRACE_ID": "",
            "SKIPTRACE_RESULT_CHOICE_ID": "",
            "SPOKE_WITH": "",
            "START_TS": "2020-06-16 08:00:15",
            "UDATE": "0000-00-00 00:00:00",
            "PTP_DATE": "",
            "PTP_AMOUNT": "0",
            "CALL_STATUS": "Congestion (circuits busy)"
        },
        {
            "SKIPTRACE_HISTORY_ID": "",
            "AGENT_ID": "",
            "AGENT_NAME": "unittest",
            "APPLICATION_ID": 0,
            "APPLICATION_STATUS": "",
            "CALLBACK_TIME": "",
            "CDATE": "",
            "END_TS": "2020-06-16 08:00:29",
            "EXCLUDED_FROM_BUCKET": "",
            "LOAN_ID": 99,
            "LOAN_STATUS": "",
            "NON_PAYMENT_REASON": "",
            "NOTES": "",
            "OLD_APPLICATION_STATUS": "",
            "PAYMENT_ID": 1001,
            "PAYMENT_STATUS": "",
            "SKIPTRACE_ID": "",
            "SKIPTRACE_RESULT_CHOICE_ID": "",
            "SPOKE_WITH": "",
            "START_TS": "2020-06-16 08:00:15",
            "UDATE": "0000-00-00 00:00:00",
            "PTP_DATE": "",
            "PTP_AMOUNT": "0",
            "CALL_STATUS": "Congestion (circuits busy)"
        },
        {
            "SKIPTRACE_HISTORY_ID": "",
            "AGENT_ID": "",
            "AGENT_NAME": "unittest",
            "APPLICATION_ID": 0,
            "APPLICATION_STATUS": "",
            "CALLBACK_TIME": "",
            "CDATE": "",
            "END_TS": "2020-06-16 08:00:29",
            "EXCLUDED_FROM_BUCKET": "",
            "LOAN_ID": 99,
            "LOAN_STATUS": "",
            "NON_PAYMENT_REASON": "",
            "NOTES": "",
            "OLD_APPLICATION_STATUS": "",
            "PAYMENT_ID": 991,
            "PAYMENT_STATUS": "",
            "SKIPTRACE_ID": "",
            "SKIPTRACE_RESULT_CHOICE_ID": "",
            "SPOKE_WITH": "",
            "START_TS": "2020-06-16 08:00:15",
            "UDATE": "0000-00-00 00:00:00",
            "PTP_DATE": "",
            "PTP_AMOUNT": "0",
            "CALL_STATUS": "wrong skiptrace"
        },
        {
            "SKIPTRACE_HISTORY_ID": "",
            "AGENT_ID": "",
            "AGENT_NAME": "wrong agent",
            "APPLICATION_ID": 0,
            "APPLICATION_STATUS": "",
            "CALLBACK_TIME": "",
            "CDATE": "",
            "END_TS": "2020-06-16 08:00:29",
            "EXCLUDED_FROM_BUCKET": "",
            "LOAN_ID": 99,
            "LOAN_STATUS": "",
            "NON_PAYMENT_REASON": "",
            "NOTES": "",
            "OLD_APPLICATION_STATUS": "",
            "PAYMENT_ID": 991,
            "PAYMENT_STATUS": "",
            "SKIPTRACE_ID": "",
            "SKIPTRACE_RESULT_CHOICE_ID": "",
            "SPOKE_WITH": "",
            "START_TS": "2020-06-16 08:00:15",
            "UDATE": "0000-00-00 00:00:00",
            "PTP_DATE": "",
            "PTP_AMOUNT": "0",
            "CALL_STATUS": "Congestion (circuits busy)"
        },

    ]
    response = response + error_data
    return MockResponse(
        json.dumps(response), 200
    )


def mocked_requests_get_agent_productivity(*args, **kwargs):
    return MockResponse(
        json.dumps(INTELIX_AGENT_PRODUCTIVITY_RESULTS_RESPONSE), 200
    )


def mock_download_sftp(dialer_task_id, vendor_recording_detail_id):
    return dialer_task_id, vendor_recording_detail_id


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestDownloadCallResults(JuloAPITestCase):
    def setUp(self):
        group = Group(name="collection_bucket_2")
        group.save()
        self.user = AuthUserFactory(username="unittest")
        self.user.groups.add(group)
        self.loan = LoanFactory(id=99)
        processed_payment = self.loan.payment_set.all().first()
        processed_payment.id = 991
        processed_payment.save()
        self.payment = processed_payment

        squad = CollectionSquad.objects.create(
            squad_name='B2.S1', group=group
        )
        self.agent = Agent.objects.create(user=self.user, squad=squad)
        SkiptraceResultChoice.objects.create(
            name='RPC - PTP', weight=-20, customer_reliability_score=10
        )
        SkiptraceResultChoice.objects.create(
            name='Busy', weight=-20, customer_reliability_score=10
        )
        self.customer = CustomerFactory()
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA)
        self.account_lookup = AccountLookupFactory(
            partner=self.partner, workflow=self.workflow, name='DANA'
        )
        self.account = AccountFactory(customer=self.customer, account_lookup=self.account_lookup)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990007,
            partner=self.partner,
            email='testing_email1236@gmail.com',
            account=self.account,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=self.customer,
            partner=self.partner,
            application_id=self.application.id,
            dana_customer_identifier="12345679234",
        )

    def test_realtime_skiptrace_history_without_loan_id_and_account_id(self):
        data = {
            'PAYMENT_ID': self.payment.id,
            'CALLBACK_TIME': '12:00:00',
            'START_TS': '2020-06-17 09:50:29',
            'END_TS': '2020-06-17 09:53:29',
            'NON_PAYMENT_REASON': 'Bencana Alam',
            'SPOKE_WITH': 'SIBLING',
            'CALL_STATUS': 'RPC - PTP',
            'AGENT_NAME': self.user.username,
            'NOTES': 'test Notes',
            'PTP_AMOUNT': 2000,
            'PTP_DATE': '2020-06-17',
            'PHONE_NUMBER': '0822672321'
        }
        response = self.client.realtime_agent_level_call_result(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_realtime_skiptrace_history(self):
        data = {
            'PAYMENT_ID': self.payment.id,
            'LOAN_ID': self.loan.id,
            'CALLBACK_TIME': '12:00:00',
            'START_TS': '2020-06-17 09:50:29',
            'END_TS': '2020-06-17 09:53:29',
            'NON_PAYMENT_REASON': 'Bencana Alam',
            'SPOKE_WITH': 'SIBLING',
            'CALL_STATUS': 'RPC - PTP',
            'AGENT_NAME': self.user.username,
            'NOTES': 'test Notes',
            'PTP_AMOUNT': 2000,
            'PTP_DATE': '2020-06-17',
            'PHONE_NUMBER': '0822672321'
        }
        response = self.client.realtime_agent_level_call_result(data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @mock.patch('juloserver.minisquad.tasks2.dialer_system_task.delete_paid_payment_from_dialer')
    def test_realtime_skiptrace_history_dana(self, mock_delete_paid_payment):
        mock_delete_paid_payment.return_value = True
        data = {
            'CALLBACK_TIME': '12:00:00',
            'START_TS': '2020-06-17 09:50:29',
            'END_TS': '2020-06-17 09:53:29',
            'NON_PAYMENT_REASON': 'Bencana Alam',
            'SPOKE_WITH': 'SIBLING',
            'CALL_STATUS': 'RPC - PTP',
            'AGENT_NAME': self.user.username,
            'NOTES': 'test Notes',
            'PTP_AMOUNT': 2000,
            'PTP_DATE': '2020-06-17',
            'PHONE_NUMBER': '0822672321',
            'ACCOUNT_ID': self.account.id
        }
        response = self.client.realtime_agent_level_call_result(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNotNone(response.json()['errors'])

        account_payment = AccountPaymentFactory(
            account=self.account)

        data['ACCOUNT_PAYMENT_ID'] = account_payment.id
        response = self.client.realtime_agent_level_call_result(data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # @mock.patch('juloserver.minisquad.clients.intelix.requests.get', side_effect=mocked_requests_get_for_call_results)
    # def test_trigger_skiptrace_history_system_call_result_every_hours(self, _):
    #     trigger_system_call_result_every_hours.delay()
    #     dialer_task = DialerTask.objects.all().first()
    #     self.assertEqual(dialer_task.status, DialerTaskStatus.DISPATCHED)


    # @mock.patch('juloserver.minisquad.clients.intelix.requests.get', side_effect=mocked_requests_get_for_call_results)
    # def test_trigger_skiptrace_history_system_call_result_last_attempt(self, _):
    #     trigger_system_call_result_every_hours_last_attempt.delay()
    #     dialer_task = DialerTask.objects.all().first()
    #     self.assertEqual(dialer_task.status, DialerTaskStatus.DISPATCHED)

    @mock.patch('juloserver.minisquad.clients.intelix.requests.get',
                side_effect=mocked_requests_get_agent_productivity)
    def test_agent_productivity_every_hours(self, _):
        store_agent_productivity_from_intelix_every_hours.delay()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.AGENT_PRODUCTIVITY_EVERY_HOURS
        ).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @mock.patch('juloserver.minisquad.clients.intelix.requests.get',
                side_effect=mocked_requests_get_agent_productivity)
    def test_agent_productivity_last_attempt(self, _):
        store_agent_productivity_from_intelix_every_hours_last_attempt.delay()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.AGENT_PRODUCTIVITY_EVERY_HOURS
        ).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    def test_intelix_services(self):
        dialer_task = DialerTask.objects.create(
            type=DialerTaskType.SKIPTRACE_HISTORY_AGENT_LEVEL,
            error=''
        )
        create_history_dialer_task_event(param=dict(dialer_task=dialer_task))
        create_history_dialer_task_event(
            param=dict(dialer_task=dialer_task, status=DialerTaskStatus.FAILURE),
            error_message="Test Error message"
        )
        create_failed_call_results(
            {'call_result': INTELIX_CALL_RESULTS_RESPONSE, 'error': 'error test', 'dialer_task': dialer_task}
        )
        update_intelix_callback("error message", DialerTaskStatus.FAILURE, dialer_task)

    def test_get_bucket_and_agent_data(self):
        response = self.client.ajax_get_bucket_and_agent_data()
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_ajax_assign_agent_to_squad(self):
        data = {
            'agent': self.agent.user.username,
            'bucket_name': 'collection_bucket_2',
        }
        response = self.client.ajax_assign_agent_to_squad(data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_realtime_skiptrace_history_wrong_data(self):
        data = {
            'PAYMENT_ID': self.payment.id,
            'LOAN_ID': self.loan.id,
            'CALLBACK_TIME': '12:00:00',
            'START_TS': '2020-06-17 09:50:29',
            'END_TS': '2020-06-17 09:53:29',
            'NON_PAYMENT_REASON': 'Bencana Alam',
            'SPOKE_WITH': 'SIBLING',
            'CALL_STATUS': 'RPC - PTP',
            'AGENT_NAME': self.user.username,
            'NOTES': 'test Notes',
            'PTP_AMOUNT': 'test_serializer',
            'PTP_DATE': '2020-06-17',
        }
        response = self.client.realtime_agent_level_call_result(data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestUploadIntelixTasks(JuloAPITestCase):
    def setUp(self):
        self.today = datetime.now()
        self.loan = LoanFactory()
        self.payment = self.loan.payment_set.first()
        self.account = AccountFactory()
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment = self.account.accountpayment_set.first()
        self.redis_data = {}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]
    # @mock.patch('juloserver.minisquad.tasks2.intelix_task.sort_payments_by_collection_model')
    # @mock.patch('juloserver.minisquad.tasks2.intelix_task.INTELIX_CLIENT.upload_to_queue')
    # def test_upload_julo_b1_data(self, mocked_upload, mocked_sort):
    #     self.loan.loan_status_id = 230
    #     self.loan.save()
    #
    #     oldest_payment = get_oldest_payment_ids_loans()
    #     uploaded_payment = self.loan.payment_set.filter(id=oldest_payment[0]).first()
    #     uploaded_payment.update_safely(
    #         payment_status_id=320,
    #         due_date=self.today - timedelta(days=2)
    #     )
    #
    #     payments = get_payment_details_for_calling(IntelixTeam.JULO_B1)
    #     mocked_sort.return_value = payments
    #
    #     mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
    #
    #     upload_julo_b1_data_to_intelix.delay()
    #     dialer_task = DialerTask.objects.filter(
    #         type=DialerTaskType.UPLOAD_JULO_B1).first()
    #     self.assertEqual(dialer_task.status, DialerTaskStatus.SENT)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_intelix_log_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_populated_data_for_calling')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.INTELIX_CLIENT.upload_to_queue')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_julo_b1_non_contacted_data_to_intelix')
    def test_construct_julo_b1_data(
        self, mock_task, mocked_upload, mock_populated_data_for_calling,
        mock_construct_data, mock_record_intelix_log, mock_cohort, mock_special_cohort_bucket,
        mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp
    ):
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='INDOMARET',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 230
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B1
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        temp_data = CollectionDialerTemporaryDataFactory(team=bucket_name)
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=320,
            due_date=self.today - timedelta(days=2)
        )

        mock_populated_data_for_calling.return_value = CollectionDialerTemporaryData.objects.filter(
            id=temp_data.id).values_list('account_payment_id', flat=True)
        mock_construct_data.return_value = [temp_data.__dict__]
        mock_task.return_value = True
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_record_intelix_log.return_value = True
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_set_temp.return_value = True
        construct_julo_b1_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JULO_B1).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.record_data_for_airudder_experiment')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_julo_b1_non_contacted_data_to_intelix')
    def test_construct_julo_b1_data_with_airudder_experiment(
        self, mock_task, mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp,
        mock_construct_data, mock_special_cohort_bucket, mock_cohort, mock_record_experiment_airudder,
    ):
        bucket_name = IntelixTeam.JULO_B1
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_CODE,
            name=ExperimentConst.PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_NAME,
            is_permanent=True,
            criteria={
                'account_id_tail': {
                    'experiment': [1,3,5,7,9],
                    'control': [0,2,4,6,8],
                }
            }
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        account_payment_ids_intelix = list(AccountPayment.objects.extra(
            where=["right(account_id::text, 1) in %s"],
            params=[tuple(list(map(str, [0,2,4,6,8])))]
        ).values_list('id', flat=True))
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        intelix_data = CollectionDialerTemporaryData.objects.filter(
            account_payment__in=account_payment_ids_intelix
        )
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_set_temp.return_value = True
        mock_construct_data.return_value = [data.__dict__ for data in intelix_data] 
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        mock_task.return_value = True
        construct_julo_b1_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        mock_record_experiment_airudder.delay.assert_called_once()

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_intelix_log_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_populated_data_for_calling')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.INTELIX_CLIENT.upload_to_queue')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_julo_b2_non_contacted_data_to_intelix')
    def test_construct_julo_b2_data(
        self, mock_task, mocked_upload, mock_populated_data_for_calling,
        mock_construct_data, mock_record_intelix_log, mock_cohort, mock_special_cohort_bucket,
        mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp
    ):
        # mock query buat dapetin data populated data
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='ALFAMART',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 232
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B2
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        temp_data = CollectionDialerTemporaryDataFactory(team=bucket_name)
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=322,
            due_date=self.today - timedelta(days=30)
        )
        mock_populated_data_for_calling.return_value = CollectionDialerTemporaryData.objects.filter(
            id=temp_data.id).values_list('account_payment_id', flat=True)
        mock_construct_data.return_value = [temp_data.__dict__]
        mock_task.return_value = True
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_record_intelix_log.return_value = True
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.none(), []
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_set_temp.return_value = True
        construct_julo_b2_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JULO_B2).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)
    
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_intelix_log_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_populated_data_for_calling')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.INTELIX_CLIENT.upload_to_queue')
    def test_construct_julo_b2_nc_data(
            self, mocked_upload, mock_populated_data_for_calling, mock_construct_data,
            mock_record_intelix_log, mock_cohort, mock_special_cohort_bucket,
            mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp
    ):
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='Bank MAYBANK',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 232
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B2_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B2),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        temp_data = CollectionDialerTemporaryDataFactory(team=bucket_name)
        mock_populated_data_for_calling.return_value = CollectionDialerTemporaryData.objects.filter(
            id=temp_data.id)
        mock_construct_data.return_value = [temp_data.__dict__]
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_record_intelix_log.return_value = True
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.none(), []
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=322,
            due_date=self.today - timedelta(days=30)
        )
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        construct_julo_b2_non_contacted_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        mock_set_temp.return_value = True
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JULO_B2_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_intelix_log_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.INTELIX_CLIENT.upload_to_queue')
    def test_construct_julo_b3_data(
        self, mocked_upload,
        mock_construct_data, mock_record_intelix_log, mock_cohort, mock_special_cohort_bucket,
        mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp
    ):
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='PERMATA Bank',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 233
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B3
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        temp_data = CollectionDialerTemporaryDataFactory(team=bucket_name)
        # mock_populated_data_for_calling.return_value = CollectionDialerTemporaryData.objects.filter(
        #     id=temp_data.id)
        mock_construct_data.return_value = [temp_data.__dict__]
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_record_intelix_log.return_value = True
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.none(), []
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=323,
            due_date=self.today - timedelta(days=60)
        )
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_set_temp.return_value = True
        construct_julo_b3_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JULO_B3).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)
        stored_data = CollectionBucketInhouseVendor.objects.all()
        self.assertIsNotNone(stored_data)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_intelix_log_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.INTELIX_CLIENT.upload_to_queue')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_julo_b3_data_to_intelix')
    def test_upload_julo_b3_nc_data(
        self, mock_task, mocked_upload,
        mock_construct_data, mock_record_intelix_log, mock_cohort, mock_special_cohort_bucket,
        mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp
    ):
        dialer_task = DialerTaskSentFactory()
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='Bank BCA',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 233
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B3_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B3),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        temp_data = CollectionDialerTemporaryDataFactory(team=bucket_name)
        mock_construct_data.return_value = [temp_data.__dict__]
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_record_intelix_log.return_value = True
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=323,
            due_date=self.today - timedelta(days=60)
        )
        mock_task.return_value = None
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.none(), []
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_set_temp.return_value = True
        construct_julo_b3_non_contacted_data_to_intelix.delay()
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JULO_B3_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)
        stored_data = CollectionBucketInhouseVendor.objects.all()
        self.assertIsNotNone(stored_data)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.process_not_sent_to_dialer_per_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_account_payment_details_for_calling_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_payment_details_for_calling')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.sort_payment_and_account_payment_by_collection_model')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.INTELIX_CLIENT.upload_to_queue')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_julo_b3_data_to_intelix')
    def test_upload_julo_b3_nc_data_toggle_0_traffic(
            self, mock_task, mocked_upload, mocked_sort,
            mocked_payment, mock_account_payment, mock_process_not_sent_to_dialer_per_bucket):
        dialer_task = DialerTaskSentFactory()
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = 'block_traffic_intelix'
        feature_setting.is_active = True
        feature_setting.parameters = {
            'toggle': '0_traffic'
        }
        feature_setting.save()
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='Bank BCA',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 233
        self.loan.save()

        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=323,
            due_date=self.today - timedelta(days=60)
        )

        mock_process_not_sent_to_dialer_per_bucket.return_value = []
        mocked_sort.return_value = [uploaded_payment]
        mocked_payment.return_value = None, self.loan.payment_set.filter(id=uploaded_payment.id), []
        mock_task.return_value = None
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_account_payment.return_value = AccountPayment.objects.none()
        construct_julo_b3_non_contacted_data_to_intelix.delay()
        dialer_task = DialerTask.objects.filter(
            type=DialerTaskType.UPLOAD_JULO_B3_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.SENT)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_intelix_log_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.INTELIX_CLIENT.upload_to_queue')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_julo_b3_data_to_intelix')
    def test_upload_julo_b3_nc_data_toggle_default(
        self, mock_task, mocked_upload,
        mock_construct_data, mock_record_intelix_log, mock_cohort, mock_special_cohort_bucket,
        mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp
    ):
        dialer_task = DialerTaskSentFactory()
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = 'block_traffic_intelix'
        feature_setting.is_active = False
        feature_setting.parameters = {
            'toggle': 'OFF'
        }
        feature_setting.save()
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='Bank BCA',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 233
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B3_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B3),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        temp_data = CollectionDialerTemporaryDataFactory(team=bucket_name)
        mock_construct_data.return_value = [temp_data.__dict__]
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_record_intelix_log.return_value = True
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=323,
            due_date=self.today - timedelta(days=60)
        )
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.none(), []
        mock_task.return_value = None
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_set_temp.return_value = True
        construct_julo_b3_non_contacted_data_to_intelix.delay()
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JULO_B3_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_intelix_log_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.INTELIX_CLIENT.upload_to_queue')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_julo_b3_data_to_intelix')
    def test_upload_julo_b3_nc_data_toggle_exp1(
        self, mock_task, mocked_upload,
        mock_construct_data, mock_record_intelix_log, mock_cohort, mock_special_cohort_bucket,
        mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp
    ):
        dialer_task = DialerTaskSentFactory()
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = 'block_traffic_intelix'
        feature_setting.is_active = True
        feature_setting.parameters = {
            'toggle': 'exp1'
        }
        feature_setting.save()
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='Bank BCA',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 233
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B3_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B3),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        temp_data = CollectionDialerTemporaryDataFactory(team=bucket_name)
        mock_construct_data.return_value = [temp_data.__dict__]
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_record_intelix_log.return_value = True
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=323,
            due_date=self.today - timedelta(days=60)
        )
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.none(), []
        mock_task.return_value = None
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_set_temp.return_value = True
        construct_julo_b3_non_contacted_data_to_intelix.delay()
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JULO_B3_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @mock.patch('juloserver.collection_vendor.task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_populated_data_for_calling')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.upload_julo_b4_non_contacted_data_to_intelix')
    def test_upload_julo_b4_data(
            self, mock_task, mock_populated_data_for_calling,
            mock_cohort, mock_special_cohort_bucket,
            mock_redis, mock_redis_collection_vendor
    ):
        # mock query buat dapetin data populated data
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='ALFAMART',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 234
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B4
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=324,
            due_date=self.today - timedelta(days=80)
        )
        collection_vendor = CollectionVendorFactory(
            vendor_name='Test',
            is_b4=True,
            is_active=True)
        CollectionVendorRatioFactory(
            vendor_types='B4',
            collection_vendor=collection_vendor,
            account_distribution_ratio=0.5)
        SubBucketFactory(bucket=4)
        temp_data = CollectionDialerTemporaryDataFactory(
            team=bucket_name,
            account_payment=self.account_payment)
        mock_populated_data_for_calling.return_value = list(CollectionDialerTemporaryData.objects.filter(
            id=temp_data.id).values_list('account_payment_id', flat=True))
        mock_cohort.return_value = AccountPayment.objects.none(), []
        mock_special_cohort_bucket.return_value = True
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        mock_redis_collection_vendor.return_value.set_list.side_effect = self.set_redis
        mock_redis_collection_vendor.return_value.get_list.side_effect = self.get_redis
        mock_task.return_value = True
        upload_julo_b4_data_to_intelix.delay()
        # dialer_task = DialerTask.objects.filter(
        #     type=DialerTaskType.UPLOAD_JULO_B4).first()
        # self.assertEqual(dialer_task.status, DialerTaskStatus.SUCCESS)


    @mock.patch('juloserver.collection_vendor.task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_populated_data_for_calling')
    def test_upload_julo_b4_nc_data(
            self, mock_populated_data_for_calling,
            mock_cohort, mock_special_cohort_bucket,
            mock_redis, mock_redis_collection_vendor
    ):
        # mock query buat dapetin data populated data
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='ALFAMART',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 234
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B4_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B4),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=324,
            due_date=self.today - timedelta(days=80)
        )
        collection_vendor = CollectionVendorFactory(
            vendor_name='Test',
            is_b4=True,
            is_active=True)
        CollectionVendorRatioFactory(
            vendor_types='B4',
            collection_vendor=collection_vendor,
            account_distribution_ratio=0.5)
        SubBucketFactory(bucket=4)
        temp_data = CollectionDialerTemporaryDataFactory(
            team=bucket_name,
            account_payment=self.account_payment)
        mock_populated_data_for_calling.return_value = list(CollectionDialerTemporaryData.objects.filter(
            id=temp_data.id).values_list('account_payment_id', flat=True))
        mock_cohort.return_value = AccountPayment.objects.none(), []
        mock_special_cohort_bucket.return_value = True
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        mock_redis_collection_vendor.return_value.set_list.side_effect = self.set_redis
        mock_redis_collection_vendor.return_value.get_list.side_effect = self.get_redis
        upload_julo_b4_non_contacted_data_to_intelix.delay()
        # dialer_task = DialerTask.objects.filter(
        #     type=DialerTaskType.UPLOAD_JULO_B4_NC).first()
        # self.assertEqual(dialer_task.status, DialerTaskStatus.SUCCESS)

    @patch('juloserver.minisquad.services.get_exclude_account_ids_by_intelix_blacklist')
    @patch('juloserver.minisquad.services2.dialer_related.get_eligible_account_payment_for_dialer_and_vendor_qs')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_not_sent_to_intelix_task')
    @mock.patch('juloserver.minisquad.tasks2'
                '.intelix_task.construct_payments_and_account_payment_sorted_by_collection_models')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.send_data_to_intelix_with_retries_mechanism')
    @mock.patch('juloserver.minisquad.services.get_oldest_unpaid_account_payment_ids')
    def test_upload_julo_dpd_minus(
            self, mock_oldest_data, mock_send_data, mock_set_redis, mock_construct, mock_record_not_sent, 
            mock_get_redis_client, mock_eligible_account_payment, mock_intelix_blacklist):
        today_date = timezone.localtime(timezone.now()).date()
        due_date_5 = today_date + timedelta(days=5)
        due_date_3 = today_date + timedelta(days=3)
        due_date_1 = today_date + timedelta(days=1)
        workflow = WorkflowFactory.create_batch(
            2,name=Iterator([WorkflowConst.JULO_ONE, WorkflowConst.JULO_STARTER]))
        account_lookup = AccountLookupFactory.create_batch(2, workflow=Iterator(workflow))
        accounts = AccountFactory.create_batch(
            20, account_lookup=Iterator(account_lookup))
        account_j1_ids = list(Account.objects.filter(
            account_lookup__workflow__name=WorkflowConst.JULO_ONE).values_list('id', flat=True))
        account_jturbo_ids = list(Account.objects.filter(
            account_lookup__workflow__name=WorkflowConst.JULO_STARTER).values_list('id', flat=True))
        account_payments = AccountPaymentFactory.create_batch(
            20,
            due_date=Iterator([due_date_5, due_date_3, due_date_1]),
            account=Iterator(accounts[0:10])
        )
        PdCollectionModelResultFactory.create_batch(
            20,
            prediction_date=today_date,
            range_from_due_date=Iterator([-5, -3, -1]),
            account_payment=Iterator(account_payments),
            account=Iterator(accounts),
            sort_rank=Iterator([0, 1])
        )
        # autodebet for J1 will sent to not_sent_to_dialer
        account_autodebet_j1 = Account.objects.get_or_none(id=account_j1_ids[0])
        ApplicationFactory(account=account_autodebet_j1)
        AutodebetAccountFactory(
            account = account_autodebet_j1,
            vendor = "BCA",
            is_use_autodebet = True,
            is_deleted_autodebet = False
        )
        # autodebet for JTURBO will sent to not_sent_to_dialer
        account_autodebet_jturbo = Account.objects.get_or_none(id=account_jturbo_ids[2])
        ApplicationFactory(account=account_autodebet_jturbo)
        AutodebetAccountFactory(
            account = account_autodebet_jturbo,
            vendor = "BCA",
            is_use_autodebet = True,
            is_deleted_autodebet = False
        )
        FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
            parameters={
                "dpd_minus": True,
            },
            is_active=True
        )
        # treat as risky customer and sent to not_sent_to_dialer
        mock_oldest_data.return_value = AccountPayment.objects.filter(
            account__in=[account_j1_ids[1], account_jturbo_ids[1]])
        mock_intelix_blacklist.return_value = Account.objects.filter(
            id__in=[account_j1_ids[2], account_jturbo_ids[2]]).values_list('id', flat=True)
        mock_eligible_account_payment.return_value = AccountPayment.objects.all().values_list(
            'id', flat=True)
        mock_record_not_sent.return_value = None
        mock_construct.return_valus = True
        mock_set_redis.return_value = True
        upload_j1_jturbo_t_minus_to_intelix.delay()
        mock_send_data.si.assert_called()
        dialer_task_j1 = DialerTask.objects.filter(
            type__in=[DialerTaskType.UPLOAD_JULO_T_5,
                      DialerTaskType.UPLOAD_JULO_T_3, DialerTaskType.UPLOAD_JULO_T_1],
            status=DialerTaskStatus.STORED)
        dialer_task_jturbo = DialerTask.objects.filter(
            type__in=[DialerTaskType.UPLOAD_JTURBO_T_5,
                      DialerTaskType.UPLOAD_JTURBO_T_3, DialerTaskType.UPLOAD_JTURBO_T_1],
            status=DialerTaskStatus.STORED)
        self.assertEqual(len(dialer_task_j1), 3)
        self.assertEqual(len(dialer_task_jturbo), 3)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.record_intelix_log_improved')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_populated_data_for_calling')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.INTELIX_CLIENT.upload_to_queue')
    def test_construct_julo_b1_nc_data(
        self, mocked_upload, mock_populated_data_for_calling,
        mock_construct_data, mock_record_intelix_log, mock_cohort, mock_special_cohort_bucket,
        mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp
    ):
        PaymentMethodFactory(loan=self.loan,
                             payment_method_name='INDOMARET',
                             customer=self.loan.customer)

        self.loan.loan_status_id = 230
        self.loan.save()
        bucket_name = IntelixTeam.JULO_B1_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B1),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        temp_data = CollectionDialerTemporaryDataFactory(team=bucket_name)
        uploaded_payment = self.loan.payment_set.all().last()
        uploaded_payment.update_safely(
            payment_status_id=320,
            due_date=self.today - timedelta(days=2)
        )
        mock_populated_data_for_calling.return_value = CollectionDialerTemporaryData.objects.filter(
            id=temp_data.id).values_list('account_payment_id', flat=True)
        mock_construct_data.return_value = [temp_data.__dict__]
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        mock_record_intelix_log.return_value = True
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_set_temp.return_value = True
        construct_julo_b1_non_contacted_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JULO_B1_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.record_data_for_airudder_experiment')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.exclude_cohort_campaign_from_normal_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_special_cohort_bucket')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.construct_data_for_sent_to_intelix_by_temp_data')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.set_redis_data_temp_table')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.ast')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task2.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    def test_construct_julo_b1_nc_data_with_airudder_experiment(
        self, mock_redis_upload, mock_redis_intelix_task2, ast_mock, mock_set_temp,
        mock_construct_data, mock_special_cohort_bucket, mock_cohort, mock_record_experiment_airudder,
    ):
        bucket_name = IntelixTeam.JULO_B1_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JULO_B1),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_CODE,
            name=ExperimentConst.PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_NAME,
            is_permanent=True,
            criteria={
                'account_id_tail': {
                    'experiment': [1,3,5,7,9],
                    'control': [0,2,4,6,8],
                }
            }
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        account_payment_ids_intelix = list(AccountPayment.objects.extra(
            where=["right(account_id::text, 1) in %s"],
            params=[tuple(list(map(str, [0,2,4,6,8])))]
        ).values_list('id', flat=True))
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        intelix_data = CollectionDialerTemporaryData.objects.filter(
            account_payment__in=account_payment_ids_intelix
        )
        mock_special_cohort_bucket.return_value = True
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_set_temp.return_value = True
        mock_construct_data.return_value = [data.__dict__ for data in intelix_data] 
        ast_mock.return_value.literal_eval.return_value = [{'data': 'unit test'}]
        mock_redis_upload.return_value.set_list.side_effect = self.set_redis
        mock_redis_upload.return_value.get_list.side_effect = self.get_redis
        mock_redis_intelix_task2.return_value.set_list.side_effect = self.set_redis
        mock_redis_intelix_task2.return_value.get_list.side_effect = self.get_redis
        construct_julo_b1_non_contacted_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        mock_record_experiment_airudder.delay.assert_called_once()

    @patch('juloserver.minisquad.services.exclude_cohort_campaign_from_normal_bucket')
    @patch('juloserver.minisquad.services2.intelix.construct_data_for_sent_to_intelix_by_temp_data')
    @patch('juloserver.minisquad.services2.intelix.set_redis_data_temp_table')
    @patch('juloserver.minisquad.tasks2.intelix_task.construct_jturbo_b1_nc_data_to_intelix')
    @patch('juloserver.minisquad.tasks2.intelix_task2.trigger_special_cohort_bucket')
    def test_construct_jturbo_b1_data(
            self, mock_special_cohort_bucket, mock_task, mock_set_temp, mock_construct_data, mock_cohort):
        bucket_name = IntelixTeam.JTURBO_B1
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        construct_data = CollectionDialerTemporaryData.objects.all()
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_construct_data.return_value = [data.__dict__ for data in construct_data]
        mock_set_temp.return_value = True
        mock_special_cohort_bucket.return_value = True
        construct_jturbo_b1_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JTURBO_B1).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)
        mock_task.delay.assert_called_once()

    @patch('juloserver.minisquad.services.exclude_cohort_campaign_from_normal_bucket')
    @patch('juloserver.minisquad.services2.intelix.construct_data_for_sent_to_intelix_by_temp_data')
    @patch('juloserver.minisquad.services2.intelix.set_redis_data_temp_table')
    @patch('juloserver.minisquad.tasks2.intelix_task2.trigger_special_cohort_bucket')
    def test_construct_jturbo_b1_nc_data(
            self, mock_special_cohort_bucket, mock_set_temp, mock_construct_data, mock_cohort):
        bucket_name = IntelixTeam.JTURBO_B1_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JTURBO_B1),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        construct_data = CollectionDialerTemporaryData.objects.all()
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_construct_data.return_value = [data.__dict__ for data in construct_data]
        mock_set_temp.return_value = True
        mock_special_cohort_bucket.return_value = True
        construct_jturbo_b1_nc_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JTURBO_B1_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @patch('juloserver.minisquad.services.exclude_cohort_campaign_from_normal_bucket')
    @patch('juloserver.minisquad.services2.intelix.construct_data_for_sent_to_intelix_by_temp_data')
    @patch('juloserver.minisquad.services2.intelix.set_redis_data_temp_table')
    @patch('juloserver.minisquad.tasks2.intelix_task.construct_jturbo_b2_nc_data_to_intelix')
    @patch('juloserver.minisquad.tasks2.intelix_task2.trigger_special_cohort_bucket')
    def test_construct_jturbo_b2_data(
            self, mock_special_cohort_bucket, mock_task, mock_set_temp, mock_construct_data, mock_cohort):
        bucket_name = IntelixTeam.JTURBO_B2
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        construct_data = CollectionDialerTemporaryData.objects.all()
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_construct_data.return_value = [data.__dict__ for data in construct_data]
        mock_set_temp.return_value = True
        mock_special_cohort_bucket.return_value = True
        construct_jturbo_b2_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JTURBO_B2).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)
        mock_task.delay.assert_called_once()

    @patch('juloserver.minisquad.services.exclude_cohort_campaign_from_normal_bucket')
    @patch('juloserver.minisquad.services2.intelix.construct_data_for_sent_to_intelix_by_temp_data')
    @patch('juloserver.minisquad.services2.intelix.set_redis_data_temp_table')
    @patch('juloserver.minisquad.tasks2.intelix_task2.trigger_special_cohort_bucket')
    def test_construct_jturbo_b2_nc_data(
            self, mock_special_cohort_bucket, mock_set_temp, mock_construct_data, mock_cohort):
        bucket_name = IntelixTeam.JTURBO_B2_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JTURBO_B2),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        construct_data = CollectionDialerTemporaryData.objects.all()
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_construct_data.return_value = [data.__dict__ for data in construct_data]
        mock_set_temp.return_value = True
        mock_special_cohort_bucket.return_value = True
        construct_jturbo_b2_nc_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JTURBO_B2_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @patch('juloserver.minisquad.services.exclude_cohort_campaign_from_normal_bucket')
    @patch('juloserver.minisquad.services2.intelix.construct_data_for_sent_to_intelix_by_temp_data')
    @patch('juloserver.minisquad.services2.intelix.set_redis_data_temp_table')
    @patch('juloserver.minisquad.tasks2.intelix_task.construct_jturbo_b3_nc_data_to_intelix')
    @patch('juloserver.minisquad.tasks2.intelix_task2.trigger_special_cohort_bucket')
    def test_construct_jturbo_b3_data(
            self, mock_special_cohort_bucket, mock_task, mock_set_temp, mock_construct_data, mock_cohort):
        bucket_name = IntelixTeam.JTURBO_B3
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        construct_data = CollectionDialerTemporaryData.objects.all()
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_construct_data.return_value = [data.__dict__ for data in construct_data]
        mock_set_temp.return_value = True
        mock_special_cohort_bucket.return_value = True
        construct_jturbo_b3_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JTURBO_B3).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)
        mock_task.delay.assert_called_once()

    @patch('juloserver.minisquad.services.exclude_cohort_campaign_from_normal_bucket')
    @patch('juloserver.minisquad.services2.intelix.construct_data_for_sent_to_intelix_by_temp_data')
    @patch('juloserver.minisquad.services2.intelix.set_redis_data_temp_table')
    @patch('juloserver.minisquad.tasks2.intelix_task2.trigger_special_cohort_bucket')
    def test_construct_jturbo_b3_nc_data(
            self, mock_special_cohort_bucket, mock_set_temp, mock_construct_data, mock_cohort):
        bucket_name = IntelixTeam.JTURBO_B3_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JTURBO_B3),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        construct_data = CollectionDialerTemporaryData.objects.all()
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_construct_data.return_value = [data.__dict__ for data in construct_data]
        mock_set_temp.return_value = True
        mock_special_cohort_bucket.return_value = True
        construct_jturbo_b3_nc_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JTURBO_B3_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

    @patch('juloserver.minisquad.services.exclude_cohort_campaign_from_normal_bucket')
    @patch('juloserver.minisquad.services2.intelix.construct_data_for_sent_to_intelix_by_temp_data')
    @patch('juloserver.minisquad.services2.intelix.set_redis_data_temp_table')
    @patch('juloserver.minisquad.tasks2.intelix_task.construct_jturbo_b4_nc_data_to_intelix')
    @patch('juloserver.minisquad.tasks2.intelix_task2.trigger_special_cohort_bucket')
    def test_construct_jturbo_b4_data(
            self, mock_special_cohort_bucket, mock_task, mock_set_temp, mock_construct_data, mock_cohort):
        bucket_name = IntelixTeam.JTURBO_B4
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(bucket_name),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        construct_data = CollectionDialerTemporaryData.objects.all()
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_construct_data.return_value = [data.__dict__ for data in construct_data]
        mock_set_temp.return_value = True
        mock_special_cohort_bucket.return_value = True
        construct_jturbo_b4_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JTURBO_B4).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)
        mock_task.delay.assert_called_once()

    @patch('juloserver.minisquad.services.exclude_cohort_campaign_from_normal_bucket')
    @patch('juloserver.minisquad.services2.intelix.construct_data_for_sent_to_intelix_by_temp_data')
    @patch('juloserver.minisquad.services2.intelix.set_redis_data_temp_table')
    @patch('juloserver.minisquad.tasks2.intelix_task2.trigger_special_cohort_bucket')
    def test_construct_jturbo_b4_nc_data(
            self, mock_special_cohort_bucket, mock_set_temp, mock_construct_data, mock_cohort):
        bucket_name = IntelixTeam.JTURBO_B4_NC
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.JTURBO_B4),
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1')
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task, status=DialerTaskStatus.BATCHING_PROCESSED,
            data_count=1
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(bucket_name, '1'),
            data_count=1
        )
        accounts = AccountFactory.create_batch(10)
        account_payments = AccountPaymentFactory.create_batch(
            10,
            account=Iterator(accounts),
        )
        CollectionDialerTemporaryDataFactory.create_batch(
            10,
            account_payment=Iterator(account_payments),
            team=bucket_name,
        )
        construct_data = CollectionDialerTemporaryData.objects.all()
        mock_cohort.return_value = AccountPayment.objects.all(), []
        mock_construct_data.return_value = [data.__dict__ for data in construct_data]
        mock_set_temp.return_value = True
        mock_special_cohort_bucket.return_value = True
        construct_jturbo_b4_nc_data_to_intelix.apply_async(kwargs={'db_name': DEFAULT_DB})
        dialer_task = DialerTask.objects.filter(type=DialerTaskType.CONSTRUCT_JTURBO_B4_NC).first()
        self.assertEqual(dialer_task.status, DialerTaskStatus.STORED)

class TestTestTriggerSlackForEmptyDataBucketDaily(TestCase):
    def setUp(self):
        SentToDialerFactory(bucket='JULO_B5')
        SentToDialerFactory(bucket='JULO_B6_1')
        SentToDialerFactory(bucket='JULO_B6_2')
        SentToDialerFactory(bucket='JULO_T-5')
        SentToDialerFactory(bucket='JULO_T-3')
        self.redis_data = {
            'retry_send_to_intelix_bucket_improvement_JULO_B1': 'JULO_B1',
            'retry_send_to_intelix_bucket_improvement_JULO_B1_NON_CONTACTED': None,
            'retry_send_to_intelix_bucket_improvement_JULO_B2': None,
            'retry_send_to_intelix_bucket_improvement_JULO_B2_NON_CONTACTED': None,
            'retry_send_to_intelix_bucket_improvement_JULO_B3': None,
            'retry_send_to_intelix_bucket_improvement_JULO_B3_NON_CONTACTED': None,
            'retry_send_to_intelix_bucket_improvement_JTURBO_B1': None,
            'retry_send_to_intelix_bucket_improvement_JTURBO_B1_NON_CONTACTED': None,
            'retry_send_to_intelix_bucket_improvement_JTURBO_B2': None,
            'retry_send_to_intelix_bucket_improvement_JTURBO_B2_NON_CONTACTED': None,
            'retry_send_to_intelix_bucket_improvement_JTURBO_B3': None,
            'retry_send_to_intelix_bucket_improvement_JTURBO_B3_NON_CONTACTED': None,
            'retry_send_to_intelix_bucket_improvement_JTURBO_B4': None,
            'retry_send_to_intelix_bucket_improvement_JTURBO_B4_NON_CONTACTED': None,
        }

    def get_redis(self, key):
        return self.redis_data[key]

    @skip('UT is deprecated. No longer needed')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.notify_empty_bucket_sent_to_dialer_daily')
    def test_trigger_slack_for_empty_data_bucket_daily(
            self, mock_send_message_to_slack, mock_redis):
        mock_redis.return_value.get.side_effect = self.get_redis
        trigger_slack_empty_bucket_sent_to_dialer_daily()
        self.assertTrue(mock_send_message_to_slack.called)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestIntelixServices(JuloAPITestCase):
    def setUp(self):
        self.today = datetime.now()
        self.loan = LoanFactory(id=86)
        status_lookup = StatusLookupFactory()
        status_lookup.status_code = 230
        status_lookup.save()
        self.loan.loan_status = status_lookup
        self.loan.application.product_line.product_line_code = ProductLineCodes.MTL1
        self.loan.save()
        self.payment = PaymentFactory(loan=self.loan, due_date=date.today())
        self.loan_refinancing_request = LoanRefinancingRequestFactory(loan=self.loan)

    def test_construct_parameter_for_intelix_upload(self):
        payment = self.payment
        parameters = construct_parameter_for_intelix_upload(payment, IntelixTeam.JULO_B1, False)
        self.assertEquals(type(parameters), dict)

    def test_construct_data_for_intelix(self):
        list_of_params = construct_data_for_intelix(None, [], IntelixTeam.JULO_B1)
        self.assertEquals(list_of_params, [])
        data = self.loan.payment_set.all()
        list_of_params = construct_data_for_intelix(data, [], IntelixTeam.JULO_B1)
        self.assertEquals(type(list_of_params), list)
        self.assertNotEquals(type(list_of_params[0]), Payment)

    def test_construct_data_for_intelix_ptp(self):
        data = self.loan.payment_set.all()
        self.ptp = PTPFactory()
        self.ptp.ptp_date = datetime.now() - timedelta(days=1)
        self.ptp.payment = data[0]
        self.ptp_amount = 99999999
        self.ptp.save()

        list_of_params = construct_data_for_intelix(data, [], IntelixTeam.JULO_B1)
        self.assertEquals(type(list_of_params), list)
        self.assertNotEquals(type(list_of_params[0]), Payment)

    def test_construct_status_and_status_group(self):
        self.assertEquals(
            construct_status_and_status_group('Hard To Pay'),
            ('CONTACTED', 'RPC - HTP')
        )
        self.assertEquals(
            construct_status_and_status_group('Not Connected'),
            ('NO CONTACTED', '')
        )
        self.assertEquals(
            construct_status_and_status_group('Unreachable'),
            ('Unreachable', '')
        )

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_B1(self, mocked_exclude_function, mocked_client):
        date = timezone.localtime(timezone.now()) - timedelta(days=5)
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling(IntelixTeam.JULO_B1)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_B2(self, mocked_exclude_function, mocked_client):
        date = timezone.localtime(timezone.now()) - timedelta(days=20)
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling(IntelixTeam.JULO_B2)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_B3(self, mocked_exclude_function, mocked_client):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        date = timezone.localtime(timezone.now()) - timedelta(days=50)
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling(IntelixTeam.JULO_B3)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_B4(self, mocked_exclude_function, mocked_client):
        date = timezone.localtime(timezone.now()) - timedelta(days=90)
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling(IntelixTeam.JULO_B3)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_TO(self, mocked_exclude_function, mocked_client):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        today = timezone.localtime(timezone.now())
        qs = Payment.objects.not_paid_active().update(due_date=today)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling(IntelixTeam.JULO_T0)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_T_1(self, mocked_exclude_function, mocked_client):
        date = timezone.localtime(timezone.now()) + timedelta(days=1)
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling(IntelixTeam.JULO_T_1)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_T_3(self, mocked_exclude_function, mocked_client):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        date = timezone.localtime(timezone.now()) + timedelta(days=3)
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling(IntelixTeam.JULO_T_3)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_T_5(self, mocked_exclude_function, mocked_client):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        date = timezone.localtime(timezone.now()) + timedelta(days=5)
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling(IntelixTeam.JULO_T_5)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_T_1_4(self, mocked_exclude_function, mocked_client):
        date = timezone.localtime(timezone.now()) - timedelta(days=2)
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling('JULO_T1-T4')
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    @mock.patch('juloserver.minisquad.services.exclude_ptp_payment_loan_ids')
    def test_get_payment_details_for_calling_T_5_10(self, mocked_exclude_function, mocked_client):
        date = timezone.localtime(timezone.now()) - timedelta(days=7)
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], ['14'], []]
        mocked_client.return_value = mocked_redis_client
        qs = Payment.objects.not_paid_active().update(due_date=date)
        mocked_exclude_function.return_value = []
        payments = get_payment_details_for_calling('JULO_T5-T10')
        self.assertIsNotNone(payments)

    def test_exclude_ptp_payment_loan_ids(self):
        data = self.loan.payment_set.all()
        payment = data[0]
        self.ptp = PTPFactory(
            payment=payment,
            loan=payment.loan,
            agent_assigned=None,
            ptp_date=(datetime.now() + timedelta(days=2)).date(),
            ptp_amount=99999999
        )
        excluded_payments = exclude_ptp_payment_loan_ids()
        self.assertIsNotNone(excluded_payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    def test_get_payment_details_T0(self, mocked_client):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], [], []]
        mocked_client.return_value = mocked_redis_client
        payments = get_payment_details_for_calling(IntelixTeam.JULO_T0)
        self.assertIsNotNone(payments)

    @mock.patch('juloserver.minisquad.services.get_redis_client')
    def test_get_payment_details_B1(self, mocked_client):
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.side_effect = [[], [], []]
        mocked_client.return_value = mocked_redis_client
        payments = get_payment_details_for_calling(IntelixTeam.JULO_B1)
        self.assertIsNotNone(payments)

    def test_sort_payment_and_account_payment_by_collection_model(self):
        self.account = AccountFactory()
        AccountPaymentFactory(account=self.account)
        pd_collection_model_results = [
            PdCollectionModelResult(
                id=1,
                cdate=self.today,
                payment=self.loan.payment_set.all()[0],
                model_version='FinalCall B1 v4',
                prediction_before_call=0.4522380966,
                prediction_after_call=0.6106655795,
                due_amount=3000000,
                range_from_due_date=2,
                sort_rank=1),
            PdCollectionModelResult(
                id=2,
                cdate=self.today,
                payment=self.loan.payment_set.all()[1],
                model_version='FinalCall B1 v4',
                prediction_before_call=0.4522380966,
                prediction_after_call=0.6106655795,
                due_amount=3000000,
                range_from_due_date=2,
                sort_rank=3),
            PdCollectionModelResult(
                id=3,
                cdate=self.today,
                account=self.account,
                account_payment=self.account.accountpayment_set.all()[0],
                model_version='FinalCall B1 v4',
                prediction_before_call=0.4522380966,
                prediction_after_call=0.6106655795,
                due_amount=3000000,
                range_from_due_date=3,
                sort_rank=2
            ),
        ]
        PdCollectionModelResult.objects.bulk_create(pd_collection_model_results)
        payments = self.loan.payment_set.all()
        account_payments = self.account.accountpayment_set.all()
        results = sort_payment_and_account_payment_by_collection_model(
            payments, account_payments, list(range(1, 11))
        )
        self.assertEqual(
            results[0].payment_id, self.loan.payment_set.all()[0].id
        )
        self.assertEqual(
            results[1].account_payment_id,
            self.account.accountpayment_set.all()[0].id
        )
        self.assertEqual(
            results[2].payment_id, self.loan.payment_set.all()[1].id
        )


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestStoringRecordingDetail(JuloAPITestCase):
    def setUp(self):
        SkiptraceResultChoice.objects.create(
            name='RPC - PTP', weight=-20, customer_reliability_score=10
        )
        group = Group(name="collection_bucket_2")
        group.save()
        self.user = AuthUserFactory(username="unittest")
        self.user.groups.add(group)

    @mock.patch('juloserver.minisquad.views.download_call_recording_via_sftp', side_effect=mock_download_sftp)
    def test_storing_recording_detail(self, mocked):
        loan = LoanFactory()
        status_lookup = StatusLookupFactory()
        status_lookup.status_code = 230
        status_lookup.save()
        loan.loan_status = status_lookup
        loan.application.product_line.product_line_code = ProductLineCodes.MTL1
        loan.save()
        payment = PaymentFactory(loan=loan, due_date=date.today())
        data = {
            'LOAN_ID': loan.id,
            'PAYMENT_ID': payment.id,
            'START_TS': '2020-06-17 09:50:29',
            'END_TS': '2020-06-17 09:53:29',
            'BUCKET': 'JULO_B5',
            'CALL_TO': '6281111111111',
            'VOICE_PATH': '/files/unitest/recording-unittest.wav',
            'CALL_ID': 'call_id_unit_test',
            'AGENT_NAME': self.user.username,
            'CALL_STATUS': 'RPC - PTP',
        }
        response = self.client.storing_recording_file_call_result(data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestintelixBlacklist(TestCase):
    def setUp(self):
        self.julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(
            mobile_phone_2='087832278933',
            customer=self.account.customer,
            account=self.account
        )
        self.application.workflow = self.julo_one_workflow
        self.application.save()
        self.skiptrace = SkiptraceFactory(
            customer=self.application.customer,
            contact_source='mobile_phone_2',
            phone_number='+6287832278933'
        )
        self.intelix_blacklist = intelixBlacklistFactory(
            account=self.account,
            skiptrace=self.skiptrace,
            reason_for_removal='reason'
        )

    def test_blacklist_phone_number(self):
        phone_numbers = get_phone_numbers_filter_by_intelix_blacklist(self.application)
        self.assertEqual(phone_numbers['mobile_phone_2'], '')

    def test_get_account_blacklist(self):
        self.intelix_blacklist.skiptrace = None
        self.intelix_blacklist.account = self.account
        self.intelix_blacklist.save()

        account_id_blacklist = get_exclude_account_ids_by_intelix_blacklist()
        self.assertIn(self.account.id, account_id_blacklist)


class TestSetTimeRetryMechanismAndSendAlertForUnsentIntelixIssue(TestCase):
    def setUp(self):
        feature_setting = FeatureSettingFactory()
        feature_setting.feature_name = 'retry_mechanism_and_send_alert_for_unsent_intelix_issue'
        feature_setting.is_active = True
        feature_setting.parameters = {
            'time': '06:30'
        }
        feature_setting.save()

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.retry_mechanism_and_send_alert_for_unsent_intelix_issue')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.trigger_slack_empty_bucket_sent_to_dialer_daily')
    def test_success_run(self, mock_slack, mock_retry):
        retry_datetime = timezone.localtime(timezone.now()).\
            replace(hour=6, minute=30, second=0, microsecond=0)
        trigger_slack_datetime = timezone.localtime(timezone.now()).\
            replace(hour=7, minute=30, second=0, microsecond=0)
        set_time_retry_mechanism_and_send_alert_for_unsent_intelix_issue()
        mock_retry.apply_async.assert_called_once_with(eta=retry_datetime)
        mock_slack.apply_async.assert_called_once_with(eta=trigger_slack_datetime)


class TestRetryMechanismAndSendAlertForUnsentIntelixIssue(TestCase):
    def setUp(self):
        now = timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)
        self.dialer_task = DialerTaskFactory(
            type=DialerTaskType.UPLOAD_JULO_B1,
            status=DialerTaskStatus.SENT_PROCESS,
            cdate=now
        )
        DialerTaskEventFactory(
            dialer_task=self.dialer_task, status=DialerTaskStatus.SENT_PROCESS
        )
        self.redis_data = {}

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('juloserver.minisquad.tasks2.intelix_task.get_redis_client')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.send_data_to_intelix_with_retries_mechanism')
    def test_retry_once(self, mock_retry, mock_redis):
        mock_redis.return_value.set_list.side_effect = self.set_redis
        mock_redis.return_value.get_list.side_effect = self.get_redis
        retry_mechanism_and_send_alert_for_unsent_intelix_issue()
        mock_retry.si.assert_called_once_with(
            bucket_name='JULO_B1',
            dialer_task_id=self.dialer_task.id,
            from_retry=True
        )

    def test_no_issue_dialer(self):
        self.dialer_task.status = DialerTaskStatus.SENT
        self.dialer_task.save()
        result = retry_mechanism_and_send_alert_for_unsent_intelix_issue()
        self.assertIsNone(result)


class TestRedisImplementationIntelix(TestCase):
    def setUp(self) -> None:
        pass

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_get_list_data_redis_success(self, mocked_client):
        original_data = [100, 900, 780, 500, 400]
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.return_value = [b'100', b'900', b'780', b'500', b'400']
        mocked_client.return_value = mocked_redis_client
        value = get_redis_data_temp_table('key')
        self.assertListEqual(value, original_data)
        mocked_redis_client.get_list.assert_called_with('key')

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_get_data_redis_success(self, mocked_client):
        original_data = [400, 500, 780, 900, 100]
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get.return_value = '[400, 500, 780, 900, 100]'
        mocked_client.return_value = mocked_redis_client
        value = get_redis_data_temp_table('key', operating_param='get')
        self.assertListEqual(value, original_data)
        mocked_redis_client.get.assert_called_with('key')

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_get_data_list_db_success(self, mocked_client):
        original_data = [400, 500, 780, 900, 100]
        temporary_data = TemporaryStorageDialerFactory()
        temporary_data.key = 'key_get_list'
        temporary_data.temp_values = json.dumps(original_data)
        temporary_data.cdate = timezone.localtime(timezone.now())
        temporary_data.save()
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get_list.return_value = None
        mocked_client.return_value = mocked_redis_client
        value = get_redis_data_temp_table('key_get_list', operating_param='get_list')
        self.assertListEqual(value, original_data)
        mocked_redis_client.get_list.assert_called_with('key_get_list')

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_get_data_db_success(self, mocked_client):
        original_data = [400, 500, 780, 900, 100]
        temporary_data = TemporaryStorageDialerFactory()
        temporary_data.key = 'key_get'
        temporary_data.temp_values = json.dumps(original_data)
        temporary_data.cdate = timezone.localtime(timezone.now())
        temporary_data.save()
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get.return_value = None
        mocked_client.return_value = mocked_redis_client
        value = get_redis_data_temp_table('key_get', operating_param='get')
        self.assertListEqual(value, original_data)
        mocked_redis_client.get.assert_called_with('key_get')

    @patch.object(TemporaryStorageDialer.objects, 'create')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_set_data_list_db_success(self, mocked_client, mocked_obj):
        original_data = [400, 500, 780, 900, 100]
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.set_list.return_value = None
        mocked_client.return_value = mocked_redis_client
        value = set_redis_data_temp_table(
            'key_set_list', original_data, timedelta(days=5), operating_param='set_list')
        self.assertIsNone(value)
        mocked_redis_client.set_list.assert_called_with(
            'key_set_list', original_data, timedelta(days=5))
        mocked_obj.assert_called()

    @patch.object(TemporaryStorageDialer.objects, 'create')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_set_data_db_success(self, mocked_client, mocked_obj):
        original_data = [400, 500, 780, 900, 100]
        mocked_redis_client = mock.MagicMock()
        mocked_redis_client.get.return_value = None
        mocked_client.return_value = mocked_redis_client
        value = set_redis_data_temp_table(
            'key_set', original_data, timedelta(days=5), operating_param='set')
        self.assertIsNone(value)
        mocked_redis_client.set.assert_called_with('key_set', original_data, timedelta(days=5))
        mocked_obj.assert_called()


class TestRecordDataForAirudderExperiment(TestCase):
    def setUp(self):
        self.accounts = AccountFactory.create_batch(10)
        self.account_payments = AccountPaymentFactory.create_batch(
            10,
            id=Iterator([1,3,5,7,9,0,2,4,6,8]),
            account=Iterator(self.accounts),
        )
        self.bucket_name = IntelixTeam.JULO_B1
        self.experiment = ExperimentSettingFactory(
            is_active=True,
            code=ExperimentConst.PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_CODE,
            name=ExperimentConst.PREDICTIVE_DIALER_EXPERIMENT_AIRUDDER_NAME,
            is_permanent=True,
            criteria={
                'account_id_tail': {
                    'experiment': [1,3,5,7,9],
                    'control': [0,2,4,6,8],
                }
            }
        )
        self.dialer_task = DialerTaskFactory()

    def record_data_for_airudder_experiment(self):
        from juloserver.minisquad.tasks2.intelix_task2 import record_data_for_airudder_experiment
        airudder_experiment_criteria = self.experiment.criteria.get('account_id_tail')
        account_id_tail_airudder = airudder_experiment_criteria['experiment']

        account_payment_qs = AccountPayment.objects.all()
        # get account payment ids based on account id tail
        account_payments_for_airudder = account_payment_qs.extra(
            where=["right(account_id::text, 1) in %s"],
            params=[tuple(list(map(str, account_id_tail_airudder)))]
        )
        account_payments_for_intelix = account_payment_qs.exclude(
            pk__in=account_payments_for_airudder.values_list('id', flat=True)
        )

        # record data to vendor_quality_experiment and experiment_group table
        account_payment_ids_for_airudder = account_payments_for_airudder.values('id', 'account_id')
        account_payment_ids_for_intelix = account_payments_for_intelix.values('id', 'account_id')
        record_data_for_airudder_experiment.delay(
            self.bucket_name, self.experiment.id,
            account_payment_ids_for_intelix, account_payment_ids_for_airudder,
            self.dialer_task.id
        )
        check_experiment_intelix = ExperimentGroup.objects.filter(group='control').count()
        check_experiment_airudder = ExperimentGroup.objects.filter(group='experiment').count()
        check_vendor_quality_intelix = VendorQualityExperiment.objects.filter(experiment_group='intelix').count()
        check_vendor_quality_airudder = VendorQualityExperiment.objects.filter(experiment_group='airudder').count()
        self.assertEqual(5, check_experiment_intelix)
        self.assertEqual(5, check_experiment_airudder)
        self.assertEqual(5, check_vendor_quality_intelix)
        self.assertEqual(5, check_vendor_quality_airudder)
