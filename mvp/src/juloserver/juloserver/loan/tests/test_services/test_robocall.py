import mock
import logging
from datetime import datetime

from django.test import TestCase
from juloserver.julo.tests.factories import FeatureSettingFactory, LoanFactory, StatusLookupFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.loan.constants import (
    TimeZoneName,
    RobocallTimeZoneQueue,
    ROBOCALL_END_TIME,
    PREFIX_LOAN_ROBOCALL_REDIS,
)
from juloserver.julo.clients.sms import JuloSmsAfterRobocall
from juloserver.loan.tasks.send_sms_after_robocall import send_sms_after_robocall
from juloserver.loan.services.robocall import (
    send_promo_code_robocall,
    get_timezone_and_queue_name,
    get_start_time_and_end_time,
    rotate_phone_number_application,
    retry_blast_robocall,
    check_and_send_sms_after_robocall
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    StatusLookupFactory,
    CustomerFactory,
    FeatureSettingFactory,
    ProductLineFactory,
    AuthUserFactory,
    VoiceCallRecordFactory,
    ApplicationFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.redis_helper import MockRedisHelper
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client

sentry = get_julo_sentry_client()
logger = JuloLog()


class TestRotatePhoneNumberRobocall(TestCase):
    def setUp(self):
        params = {
            'list_phone_numbers': [
                '621111111111','622222222222','623333333333','621111111151','622222222272',
                '621111111121','622222222232','623333333334','621111111161','622222222282',
                '621111111131','622222222242','623333333335','621111111171','622222222293',
                '621111111141'
            ],
            'time_config': dict(
                end_time_hour=20,
                retry_delay_minutes=180
            )
        }
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOAN_PHONE_ROTATION_ROBOCALL,
            is_active=True,
            parameters=params
        )
        self.fake_redis = MockRedisHelper()

    @mock.patch('juloserver.loan.services.robocall.get_redis_client')
    @mock.patch('django.utils.timezone.now')
    @mock.patch('juloserver.loan.services.robocall.send_promo_code_robocall_subtask')
    @mock.patch('juloserver.loan.services.robocall.get_list_customers_from_csv')
    def test_send_promo_code_robocall(
        self,
        mock_list_customer,
        mock_send_promo_code_task,
        mock_time_zone,
        mock_redis_client,
    ):
        mock_redis_client.return_value = self.fake_redis
        data = [dict(
            customer_id=1008514217,
            phone_number="08111566123",
            gender="Wanita",
            full_name= "Thanh Hung",
            address_kodepos="9766",
            customer_segment='graduation_script'
        )]
        mock_list_customer.return_value = [ data ]
        self.fake_redis.set(PREFIX_LOAN_ROBOCALL_REDIS + 'graduation_script', 'Test robocall')
        mock_time_zone.return_value = datetime(2023, 6, 10)
        template_code = 'promo_code_june_2023'
        start_hour = 19
        send_promo_code_robocall(
            path='', template_code=template_code, wib_hour=start_hour, customer_data=data)
        mock_send_promo_code_task.apply_async.assert_called()

    @mock.patch('juloserver.loan.services.robocall.get_redis_client')
    @mock.patch('django.utils.timezone.now')
    @mock.patch('juloserver.loan.services.robocall.send_promo_code_robocall_subtask')
    @mock.patch('juloserver.loan.services.robocall.get_list_customers_from_csv')
    def test_send_promo_code_robocall_with_loan_amount_data(
        self,
        mock_list_customer,
        mock_send_promo_code_task,
        mock_time_zone,
        mock_redis_client,
    ):
        mock_redis_client.return_value = self.fake_redis
        data = [
            dict(
                customer_id=1008514217,
                phone_number="08111566123",
                gender="Wanita",
                full_name="Linh Le",
                address_kodepos="9766",
                customer_segment='graduation_script',
                loan_amount="3000000",
                existing_monthly_installment="500000",
                new_monthly_installment="450000",
                saving_amount="50000",
            )
        ]
        mock_list_customer.return_value = [data]
        self.fake_redis.set(PREFIX_LOAN_ROBOCALL_REDIS + 'graduation_script', 'Test robocall')
        mock_time_zone.return_value = datetime(2024, 6, 20)
        template_code = 'promo_code_june_2024'
        start_hour = 19
        send_promo_code_robocall(
            path='', template_code=template_code, wib_hour=start_hour, customer_data=data
        )
        mock_send_promo_code_task.apply_async.assert_called()

    @mock.patch('juloserver.loan.services.robocall.get_redis_client')
    @mock.patch('django.utils.timezone.now')
    @mock.patch('juloserver.loan.services.robocall.send_promo_code_robocall_subtask')
    @mock.patch('juloserver.loan.services.robocall.get_list_customers_from_csv')
    def test_send_promo_code_robocall_with_interest(
        self,
        mock_list_customer,
        mock_send_promo_code_task,
        mock_time_zone,
        mock_redis_client,
    ):
        mock_redis_client.return_value = self.fake_redis
        data = [
            dict(
                customer_id=1008514217,
                phone_number="08111566123",
                gender="Wanita",
                full_name="Thanh Hung",
                address_kodepos="9766",
                customer_segment='graduation_script',
                new_interest="8%",
                existing_interest="12%",
            )
        ]
        mock_list_customer.return_value = [data]
        self.fake_redis.set(PREFIX_LOAN_ROBOCALL_REDIS + 'graduation_script', 'Test robocall')
        mock_time_zone.return_value = datetime(2024, 6, 20)
        template_code = 'promo_code_june_2024'
        start_hour = 19
        send_promo_code_robocall(
            path='', template_code=template_code, wib_hour=start_hour, customer_data=data
        )
        mock_send_promo_code_task.apply_async.assert_called()

    @mock.patch('juloserver.loan.services.robocall.get_redis_client')
    @mock.patch('django.utils.timezone.now')
    @mock.patch('juloserver.loan.services.robocall.send_promo_code_robocall_subtask')
    @mock.patch('juloserver.loan.services.robocall.get_list_customers_from_csv')
    def test_send_promo_code_robocall_failed_not_found_segment(
        self,
        mock_list_customer,
        mock_send_promo_code_task,
        mock_time_zone,
        mock_redis_client,
    ):
        mock_redis_client.return_value = self.fake_redis
        data = [dict(
            customer_id=1008514217,
            phone_number="08111566123",
            gender="Wanita",
            full_name= "Thanh Hung",
            address_kodepos="9766",
            customer_segment='graduation_script_test'
        )]
        mock_list_customer.return_value = [ data ]
        self.fake_redis.set(PREFIX_LOAN_ROBOCALL_REDIS + 'graduation_script', 'Test robocall')
        mock_time_zone.return_value = datetime(2023, 6, 10)
        template_code = 'promo_code_june_2023'
        start_hour = 19
        send_promo_code_robocall(
            path='', template_code=template_code, wib_hour=start_hour, customer_data=data)
        mock_send_promo_code_task.apply_async.assert_not_called()


class TestRobocallTimeZone(TestCase):

    def test_get_timezone_and_queue_name(self):
        wit_postcode = 98787
        timezone, queue_name = get_timezone_and_queue_name(wit_postcode)
        assert timezone == TimeZoneName.WIT
        assert queue_name == RobocallTimeZoneQueue.ROBOCALL_WIT

        wita_postcode = 75641
        timezone, queue_name = get_timezone_and_queue_name(wita_postcode)
        assert timezone == TimeZoneName.WITA
        assert queue_name == RobocallTimeZoneQueue.ROBOCALL_WITA

        wib_postcode = 24104
        timezone, queue_name = get_timezone_and_queue_name(wib_postcode)
        assert timezone == TimeZoneName.WIB
        assert queue_name == RobocallTimeZoneQueue.ROBOCALL_WIB

        # default
        postcode = None
        timezone, queue_name = get_timezone_and_queue_name(postcode)
        assert timezone == TimeZoneName.WIT
        assert queue_name == RobocallTimeZoneQueue.ROBOCALL_WIT

    def test_get_start_time_and_end_time(self):
        # wib
        wib_start_time = datetime(2023, 7, 4, 19, 0, 0)
        wib_hour = 19

        wit_postcode = 98787
        timezone, _ = get_timezone_and_queue_name(wit_postcode)
        start_time, end_time = get_start_time_and_end_time(timezone, wib_hour, wib_start_time, 20)

        assert start_time.hour == wib_start_time.hour - 2
        assert end_time.hour == ROBOCALL_END_TIME - 2

        wita_postcode = 75641
        timezone, _ = get_timezone_and_queue_name(wita_postcode)
        start_time, end_time = get_start_time_and_end_time(timezone, wib_hour, wib_start_time, 20)
        assert start_time.hour == wib_start_time.hour - 1
        assert end_time.hour == ROBOCALL_END_TIME - 1

        wib_postcode = 7564132131
        timezone, _ = get_timezone_and_queue_name(wib_postcode)
        start_time, end_time = get_start_time_and_end_time(timezone, wib_hour, wib_start_time, 20)
        assert start_time.hour == wib_start_time.hour
        assert end_time.hour == ROBOCALL_END_TIME

        wib_postcode = 24104
        timezone, _ = get_timezone_and_queue_name(wib_postcode)
        start_time, end_time = get_start_time_and_end_time(timezone, wib_hour, wib_start_time, 20)
        assert start_time.hour == wib_start_time.hour
        assert end_time.hour == ROBOCALL_END_TIME


class TestPromoCodeRobocall(TestCase):
    def setUp(self):
        FeatureSettingFactory(
            feature_name=FeatureNameConst.NEXMO_NUMBER_RANDOMIZER,
            is_active=False
        )
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.j1_product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=self.j1_product_line,
            application_status = StatusLookupFactory(status_code=190)
        )
        self.call_from = "08123321123"
        self.voice_call = VoiceCallRecordFactory(
            application=self.application,
            call_from=self.call_from
        )
        self.list_phone_number = ["01233214242", "08302132138"]

    def test_rotate_phone_number_random(self):
        phone_number = rotate_phone_number_application(self.application, self.list_phone_number)
        assert phone_number != None

    def test_rotate_phone_number_exist(self):
        list_phone_numbers = ["01233214242", "08302132138"]
        self.voice_call.call_from = self.list_phone_number[0]
        self.voice_call.save()
        phone_number = rotate_phone_number_application(self.application, self.list_phone_number)
        assert phone_number == list_phone_numbers[1]

    def test_rotate_phone_number_existing_all(self):
        list_phone_numbers = ["01233214242", "08302132138"]
        VoiceCallRecordFactory(
            application=self.application,
            call_from=list_phone_numbers[0]
        )
        VoiceCallRecordFactory(
            application=self.application,
            call_from=list_phone_numbers[1]
        )

        phone_number = rotate_phone_number_application(self.application,  self.list_phone_number)
        assert phone_number == list_phone_numbers[0]

        VoiceCallRecordFactory(
            application=self.application,
            call_from=phone_number
        )
        phone_number = rotate_phone_number_application(self.application,
                                                       ["01233214242", "08302132138"])
        assert phone_number == list_phone_numbers[1]


class TestPromoCodeRobocallWithRetry(TestCase):
    def setUp(self):
        self.params = {
            'list_phone_numbers': [
                '621111111111','622222222222','623333333333','621111111151','622222222272',
                '621111111121','622222222232','623333333334','621111111161','622222222282',
                '621111111131','622222222242','623333333335','621111111171','622222222293',
                '621111111141'
            ],
            'time_config': dict(
                end_time_hour=20,
                retry_delay_minutes=30
            )
        }
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOAN_PHONE_ROTATION_ROBOCALL,
            is_active=True,
            parameters=self.params
        )
        self.fake_redis = MockRedisHelper()
        self.application = ApplicationFactory(address_kodepos='9766')
        self.customer_segment = 'graduation_script'
        self.voice_call = VoiceCallRecordFactory(
           application=self.application,
           call_from='01233214242',
           template_code='promo_code_2023' + '__' + 'graduation_script'
        )

    @mock.patch('juloserver.loan.services.robocall.timezone.localtime')
    @mock.patch('juloserver.loan.services.robocall.get_redis_client')
    @mock.patch('juloserver.loan.services.robocall.send_promo_code_robocall_subtask')
    def test_send_promo_code_robocall_with_retry(
        self,
        mock_send_promo_code_task,
        mock_redis_client,
        mock_time_zone,
    ):
        mock_redis_client.return_value = self.fake_redis
        mock_time_zone.return_value = datetime(2023, 10, 1, 11)
        self.fake_redis.set(PREFIX_LOAN_ROBOCALL_REDIS + self.customer_segment, 'Test robocall')
        retry_blast_robocall(self.voice_call)

        mock_send_promo_code_task.apply_async.assert_called()

    @mock.patch('juloserver.loan.services.robocall.get_redis_client')
    @mock.patch('juloserver.loan.services.robocall.send_promo_code_robocall_subtask')
    def test_send_promo_code_robocall_with_retry_failed(
        self,
        mock_send_promo_code_task,
        mock_redis_client,
    ):
        mock_redis_client.return_value = self.fake_redis
        self.fake_redis.set('test', 'Test robocall')
        retry_blast_robocall(self.voice_call)

        mock_send_promo_code_task.apply_async.assert_not_called()

    @mock.patch('juloserver.loan.services.robocall.get_redis_client')
    @mock.patch('juloserver.loan.services.robocall.send_promo_code_robocall_subtask')
    def test_send_promo_code_robocall_with_no_retry(
        self,
        mock_send_promo_code_task,
        mock_redis_client,
    ):
        self.feature_setting.parameters['time_config']['retry_delay_minutes'] = ''
        self.feature_setting.save()
        mock_redis_client.return_value = self.fake_redis
        self.fake_redis.set(PREFIX_LOAN_ROBOCALL_REDIS + self.customer_segment, 'Test robocall')
        retry_blast_robocall(self.voice_call)

        mock_send_promo_code_task.apply_async.assert_not_called()

    @mock.patch('django.utils.timezone.now')
    @mock.patch('juloserver.loan.services.robocall.get_redis_client')
    @mock.patch('juloserver.loan.services.robocall.send_promo_code_robocall_subtask')
    def test_send_promo_code_robocall_with_retry_delay_minutes(
        self,
        mock_send_promo_code_task,
        mock_redis_client,
        mock_time_zone,
    ):
        mock_redis_client.return_value = self.fake_redis
        self.fake_redis.set(PREFIX_LOAN_ROBOCALL_REDIS + self.customer_segment, 'Test robocall')
        mock_time_zone.return_value = datetime(2023, 6, 10, 5)
        retry_blast_robocall(self.voice_call)

        mock_send_promo_code_task.apply_async.assert_called()

class TestSendSMSAfterRobocall(TestCase):
    def setUp(self):
        params = {
            "sms_config": {
                "call_status": ['answered', 'unanswered'],
                "loan_delay": {'delay': 5, 'unit': 'days'},
                "content_by_segment":{
                    "graduation_reachable": 'Promo code ABC123',
                    "uninstall": 'Promo code ABC456',
                    "retroload": 'Promo code ABC789'
                },
            }  
        }
        self.sms_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOAN_SMS_AFTER_ROBOCALL,
            is_active=True,
            parameters=params,
            category='loan_robocall',
            description='Config send SMS after robocall',
        )

    def test_empty_sms_config(self):
        sms_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.LOAN_SMS_AFTER_ROBOCALL,
            is_active=False,
            parameters={},
            category='loan_robocall',
            description='Config send SMS after robocall',
        )
        assert len(sms_setting.parameters) == 0

    def test_invalid_call_status(self):
        voice_call_record = VoiceCallRecordFactory(
            template_code='promo_code_sep_2023__graduation_reachable',
            status='failed',
        )
        result = check_and_send_sms_after_robocall(voice_call_record)
        self.assertIsNone(result)

    @mock.patch.object(sentry, 'captureMessage')
    def test_invalid_customer_segment(self, mock_capture_message):
        new_parameters = {
            "sms_config": {
                "call_status": ['answered', 'unanswered'],
                "loan_delay": {'delay': 5, 'unit': 'days'},
                "content_by_segment":{
                    "graduation_reachable": 'Promo code ABC123',
                    "uninstall": 'Promo code ABC456',
                    "retroload": 'Promo code ABC789'
                },
            }  
        }
        self.sms_setting.update_safely(parameters=new_parameters)
        voice_call_record = VoiceCallRecordFactory(
            template_code='promo_code_sep_2023__graduation_unreachable',
            status='answered',
            application=ApplicationFactory(account=AccountFactory()),
        )
        result = check_and_send_sms_after_robocall(voice_call_record)
        self.assertTrue(mock_capture_message.called)
        self.assertIsNone(result)

    @mock.patch.object(sentry, 'captureMessage')
    def test_empty_sms_content(self, mock_capture_message):
        new_parameters = {
            "sms_config": {
                "call_status": ['answered', 'unanswered'],
                "loan_delay": {'delay': 5, 'unit': 'days'},
                "content_by_segment":{
                    "graduation_reachable": '',
                    "uninstall": 'Promo code ABC456',
                    "retroload": 'Promo code ABC789'
                },
            }  
        }
        self.sms_setting.update_safely(parameters=new_parameters)
        voice_call_record = VoiceCallRecordFactory(
            template_code='promo_code_sep_2023__graduation_reachable',
            status='answered',
            application=ApplicationFactory(account=AccountFactory()),
        )
        result = check_and_send_sms_after_robocall(voice_call_record)
        self.assertTrue(mock_capture_message.called)
        self.assertIsNone(result)

    
    @mock.patch('juloserver.loan.tasks.send_sms_after_robocall.get_julo_sms_after_robocall')
    @mock.patch('django.utils.timezone.now')
    def test_send_sms_after_robocall(
        self,
        mock_time_zone,
        mock_get_julo_sms_after_robocall,
    ):
        mock_time_zone.return_value = datetime(2023, 9, 28)
        account = AccountFactory()
        application = ApplicationFactory(account=account)
        voice_call_record = VoiceCallRecordFactory(
            cdate=datetime(2023, 9, 28, 13, 21, 0),
            call_to="0843318433",
            application=application,
            template_code='promo_code_sep_2023__graduation_reachable',
        )
        status = StatusLookupFactory()
        status.status_code = 220
        status.save()
        loan = LoanFactory(
            account=voice_call_record.application.account,
            cdate=(2023, 9, 29, 13, 21, 0),
            loan_status=status,
        )
        # Get message
        content_by_segment = self.sms_setting.parameters["sms_config"]["content_by_segment"]
        customer_segment = voice_call_record.template_code.split('__')[1]
        message = content_by_segment.get(customer_segment)
        # Mock xid
        mock_get_julo_sms_after_robocall.return_value.send_sms.return_value = "7167a12e-af35-4265-8420-f57ae0cd3f0f"
        send_sms_after_robocall(
            voice_call_record.pk,
            message,
        )

        mock_get_julo_sms_after_robocall.return_value.check_status.assert_called()


    @mock.patch('juloserver.julo.clients.sms.requests')
    def test_request_send_sms(self, mock_response):
        body = {
            "data": {"xid": "c9f2589f-1445-45bd-b598-895dc612e492"},
            "error": None,
            "success": True,
        }
        response = mock.MagicMock()
        response.json.return_value = body
        response.status_code = 200
        mock_response.post.return_value = response
        mock_response.return_value = response

        voice_call_record = VoiceCallRecordFactory(
            cdate=datetime(2023, 9, 28, 13, 21, 0),
            call_to="0843318433",
            template_code="promo_code__uninstall"
        )

        # Get message
        content_by_segment = self.sms_setting.parameters["sms_config"]["content_by_segment"]
        customer_segment = voice_call_record.template_code.split('__')[1]
        message = content_by_segment.get(customer_segment)

        sms_client = JuloSmsAfterRobocall(
            api_key="123231",
            api_secret="ABCD",
            base_url="https://example.co.id/"
        )
        xid = sms_client.send_sms(
            voice_call_record.call_to,
            message,
            voice_call_record.template_code,
        )

        self.assertIsNotNone(xid)

    @mock.patch('juloserver.julo.clients.sms.requests')
    def test_request_check_status(self, mock_response):
        xid = "7167a12e-af35-4265-8420-f57ae0cd3f0f"
        body = {
            "data": [
                {
                    "xid": xid,
                    "status": "delivered"
                }
            ],
            "error": None,
            "success": True
        }
        response = mock.MagicMock()
        response.json.return_value = body
        response.status_code = 200
        mock_response.post.return_value = response
        mock_response.return_value = response

        voice_call_record = VoiceCallRecordFactory(
            cdate=datetime(2023, 9, 28, 13, 21, 0),
            call_to="0843318433",
            template_code="promo_code__uninstall"
        )

        # Get message
        content_by_segment = self.sms_setting.parameters["sms_config"]["content_by_segment"]
        customer_segment = voice_call_record.template_code.split('__')[1]
        message = content_by_segment.get(customer_segment)

        sms_client = JuloSmsAfterRobocall(
            api_key="123231",
            api_secret="ABCD",
            base_url="https://example.co.id/"
        )
        status = sms_client.check_status(xid)

        assert status == 'delivered'
