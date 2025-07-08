from unittest import skip

import mock
from dateutil.relativedelta import relativedelta
from datetime import timedelta
from django.db.models import (
    F,
    CharField,
    Value,
    ExpressionWrapper,
    IntegerField,
)
from django.test.testcases import TestCase
from django.utils import timezone

from juloserver.account.tests.factories import AccountFactory, AccountLookupFactory
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.dana.constants import (
    RedisKey,
    FeatureNameConst as DanaFeatureNameConst,
)
from juloserver.dana.collection.serializers import DanaDialerTemporarySerializer
from juloserver.dana.collection.tasks import (
    populate_dana_dialer_temp_data,
    process_exclude_dana_data_for_dialer_per_part,
    process_populate_dana_temp_clean_data,
    process_not_sent_to_dialer_per_bucket,
    upload_dana_b1_data_to_intelix,
    upload_dana_b2_data_to_intelix,
    send_batch_dana_data_to_intelix_with_retries_mechanism,
)
from juloserver.dana.tests.factories import DanaCustomerDataFactory
from juloserver.dana.models import DanaDialerTemporaryData
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes
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
)
from juloserver.minisquad.constants import (
    IntelixTeam,
    DialerTaskType,
    DialerTaskStatus,
    FeatureNameConst,
)
from juloserver.minisquad.models import DialerTask, DialerTaskEvent
from juloserver.minisquad.services2.intelix import (
    create_history_dialer_task_event,
    set_redis_data_temp_table,
    get_redis_data_temp_table,
    record_intelix_log_improved,
)
from juloserver.minisquad.tests.factories import DialerTaskFactory, DialerTaskEventFactory
from juloserver.pin.tests.factories import CustomerPinFactory


@skip('UT is deprecated. Should be deleted when Intelix is inactive')
class TestPopulateDataDanaIntelix(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user, nik='1601260506021270', phone='082231457591'
        )
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.DANA)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA, handler='DanaWorkflowHandler')
        self.status_lookup = StatusLookupFactory(status_code=420)
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name='DANA', payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email123@gmail.com',
            account=self.account,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679230',
            customer=self.customer,
            nik=self.customer.nik,
            mobile_number=self.customer.phone,
            partner=partner,
            full_name=self.customer.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account,
            application_id=self.application.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user,
            latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90),
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)

        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application=self.application,
            loan_amount=10000000,
            loan_xid=1000003056,
        )
        LoanFactory.create_batch(2, loan_amount=10000000, loan_duration=12)
        self.bucket_name = IntelixTeam.DANA_BUCKET
        self.redis_data = {}
        self.current_date = timezone.localtime(timezone.now()).date()

        self.account.accountpayment_set.all().delete()
        self.account_payment_b2 = AccountPaymentFactory(
            account=self.account,
            due_date=self.current_date - timedelta(days=20),
            is_collection_called=False,
        )
        self.account_payment_b2.account = self.account
        self.account_payment_b2.save(update_fields=['account'])
        self.account_b3 = AccountFactory(status=self.status_lookup)
        self.user1 = AuthUserFactory()
        self.customer1 = CustomerFactory(
            user=self.user1, nik='1601260506021271', phone='082231457592'
        )
        self.application3 = ApplicationFactory(
            customer=self.customer1,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email123@gmail.com',
            account=self.account_b3,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679770',
            customer=self.customer1,
            nik=self.customer1.nik,
            mobile_number=self.customer1.phone,
            partner=partner,
            full_name=self.customer1.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b3,
            application_id=self.application3.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b3.accountpayment_set.all().delete()
        self.account_payment_b3 = AccountPaymentFactory(
            account=self.account_b3,
            due_date=self.current_date - timedelta(days=25),
            is_collection_called=False,
        )
        self.account_payment_b3.account = self.account_b3
        self.account_payment_b3.save()

        self.account_b4 = AccountFactory(status=self.status_lookup)
        self.user2 = AuthUserFactory()
        self.customer2 = CustomerFactory(
            user=self.user2, nik='1601260506021272', phone='082231457593'
        )
        self.application4 = ApplicationFactory(
            customer=self.customer2,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email123@gmail.com',
            account=self.account_b4,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679880',
            customer=self.customer2,
            nik=self.customer2.nik,
            mobile_number=self.customer2.phone,
            partner=partner,
            full_name=self.customer2.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b4,
            application_id=self.application4.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b4.accountpayment_set.all().delete()
        self.account_payment_b4 = AccountPaymentFactory(
            account=self.account_b4,
            due_date=self.current_date - timedelta(days=30),
            is_collection_called=False,
        )

        self.account_b5 = AccountFactory(status=self.status_lookup)
        self.user5 = AuthUserFactory()
        self.customer5 = CustomerFactory(
            user=self.user5, nik='1601260506021273', phone='082231457593'
        )
        self.application5 = ApplicationFactory(
            customer=self.customer5,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email123@gmail.com',
            account=self.account_b5,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679399',
            customer=self.customer5,
            nik=self.customer5.nik,
            mobile_number=self.customer5.phone,
            partner=partner,
            full_name=self.customer5.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b5,
            application_id=self.application5.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b5.accountpayment_set.all().delete()
        self.account_payment_b5 = AccountPaymentFactory(
            account=self.account_b5,
            due_date=self.current_date - timedelta(days=32),
            is_collection_called=False,
        )

        self.account_b6 = AccountFactory(status=self.status_lookup)
        self.user6 = AuthUserFactory()
        self.customer6 = CustomerFactory(
            user=self.user6, nik='1601260506021278', phone='082231457598'
        )
        self.application6 = ApplicationFactory(
            customer=self.customer6,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email123@gmail.com',
            account=self.account_b6,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679300',
            customer=self.customer6,
            nik=self.customer6.nik,
            mobile_number=self.customer6.phone,
            partner=partner,
            full_name=self.customer6.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b6,
            application_id=self.application6.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b6.accountpayment_set.all().delete()
        self.account_payment_b6 = AccountPaymentFactory(
            account=self.account_b6,
            due_date=self.current_date - timedelta(days=60),
            is_collection_called=False,
        )
        self.account_b7 = AccountFactory(status=self.status_lookup)
        self.user7 = AuthUserFactory()
        self.customer7 = CustomerFactory(
            user=self.user7, nik='1601260506021218', phone='082231457538'
        )
        self.application7 = ApplicationFactory(
            customer=self.customer7,
            workflow=self.workflow,
            application_xid=9999990087,
            partner=partner,
            product_line=self.product_line,
            email='testing_email123@gmail.com',
            account=self.account_b7,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679800',
            customer=self.customer7,
            nik=self.customer7.nik,
            mobile_number=self.customer7.phone,
            partner=partner,
            full_name=self.customer7.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b7,
            application_id=self.application7.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b7.accountpayment_set.all().delete()
        self.account_payment_b7 = AccountPaymentFactory(
            account=self.account_b7,
            due_date=self.current_date - timedelta(days=5),
            is_collection_called=False,
        )

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('juloserver.dana.collection.tasks.get_eligible_dana_account_payment_for_dialer')
    @mock.patch('juloserver.dana.collection.tasks.delete_redis_key_list_with_prefix')
    def test_failed_no_eligible_dana_account_payment_data(
        self, mock_delete_redis_key, mock_eligible_dana_account_payment
    ):
        mock_delete_redis_key.return_value = True
        mock_delete_redis_key.return_value = True
        mock_eligible_dana_account_payment.return_value = AccountPayment.objects.filter(
            id__in=[self.account_payment_b2.id, self.account_payment_b3.id]
        )

        populate_dana_dialer_temp_data()
        dialer_task_b2 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        ).last()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task_b2).last()
        self.assertEqual(dialer_task_event.status, DialerTaskStatus.FAILURE)

        mock_eligible_dana_account_payment.return_value = AccountPayment.objects.filter(
            id__in=[self.account_payment_b7.id]
        )
        populate_dana_dialer_temp_data()
        dialer_task_b1 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B1)
        ).last()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task_b1).last()
        self.assertEqual(dialer_task_event.status, DialerTaskStatus.FAILURE)

    @mock.patch(
        'juloserver.dana.collection.tasks.process_exclude_dana_data_for_dialer_per_part.delay'
    )
    @mock.patch('juloserver.dana.collection.tasks.set_redis_data_temp_table')
    @mock.patch('juloserver.dana.collection.tasks.get_eligible_dana_account_payment_for_dialer')
    @mock.patch('juloserver.dana.collection.tasks.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_dana_payment_data(
        self,
        mock_delete_redis_key,
        mock_eligible_dana_account_payment,
        mock_redis_data_temp_table,
        mock_async_process_sent_dialer_per_part,
    ):
        mock_delete_redis_key.return_value = True
        mock_eligible_dana_account_payment.return_value = AccountPayment.objects.filter(
            id__in=[self.account_payment_b2.id, self.account_payment_b3.id]
        )
        populate_dana_dialer_temp_data()
        dialer_task_b2 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        ).last()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task_b2).last()

        self.assertEqual(dialer_task_event.status, DialerTaskStatus.BATCHING_PROCESSED)
        self.assertEqual(dialer_task_event.data_count, 1)
        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 1)

    @mock.patch(
        'juloserver.dana.collection.tasks.process_exclude_dana_data_for_dialer_per_part.delay'
    )
    @mock.patch('juloserver.dana.collection.tasks.set_redis_data_temp_table')
    @mock.patch('juloserver.dana.collection.tasks.get_eligible_dana_account_payment_for_dialer')
    @mock.patch('juloserver.dana.collection.tasks.delete_redis_key_list_with_prefix')
    def test_success_splitting_eligible_dana_account_payment_data_with_config(
        self,
        mock_delete_redis_key,
        mock_eligible_dana_account_payment,
        mock_redis_data_temp_table,
        mock_async_process_sent_dialer_per_part,
    ):
        parameters = {"DANA_B2": 2}
        self.intelix_data_batching_feature_setting = FeatureSetting.objects.create(
            feature_name=FeatureNameConst.INTELIX_BATCHING_POPULATE_DATA_CONFIG,
            parameters=parameters,
            is_active=True,
        )
        mock_delete_redis_key.return_value = True
        mock_eligible_dana_account_payment.return_value = AccountPayment.objects.all()

        populate_dana_dialer_temp_data()
        dialer_task_b2 = DialerTask.objects.filter(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        ).last()
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task_b2).last()

        self.assertEqual(dialer_task_event.status, DialerTaskStatus.BATCHING_PROCESSED)
        self.assertEqual(dialer_task_event.data_count, 2)
        self.assertEqual(mock_async_process_sent_dialer_per_part.call_count, 4)

    @mock.patch('juloserver.dana.collection.tasks.logger.warn')
    @mock.patch('juloserver.dana.collection.tasks.get_eligible_dana_account_payment_for_dialer')
    @mock.patch('juloserver.dana.collection.tasks.delete_redis_key_list_with_prefix')
    def test_failed_with_empty_populated_eligible_dana_data(
        self, mock_delete_redis_key, mock_eligible_dana_account_payment, mocked_logger
    ):
        mock_delete_redis_key.return_value = True
        mock_eligible_dana_account_payment.return_value = AccountPayment.objects.filter(
            id__in=[self.account_payment_b6.id]
        )
        populate_dana_dialer_temp_data()
        mocked_logger.assert_called()

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_failed_with_empty_cache_populated_eligible_dana_data(self, mock_get_redis_client):
        page_num = 1
        dialer_task_b2 = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        data = process_exclude_dana_data_for_dialer_per_part('test', page_num, dialer_task_b2.id)
        self.assertIsNone(data)
        data = process_exclude_dana_data_for_dialer_per_part(
            IntelixTeam.DANA_B2, page_num, dialer_task_b2.id
        )
        self.assertIsNone(data)
        data = process_exclude_dana_data_for_dialer_per_part(IntelixTeam.DANA_B2, page_num, 34234)
        self.assertIsNone(data)

    @mock.patch('juloserver.dana.collection.tasks.process_populate_dana_temp_clean_data.delay')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_success_with_cache_populated_eligible_dana_data(
        self, mock_get_redis_client, mock_process_populate_dana_temp_clean_data
    ):
        account_payment_ids = [1000, 2000]
        page_num = 1
        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS.format(
                IntelixTeam.DANA_B2, page_num
            ),
            account_payment_ids,
        )
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        with self.assertRaises(Exception):
            with self.assertRaises(Exception) as e:
                process_exclude_dana_data_for_dialer_per_part(
                    IntelixTeam.DANA_B2, page_num, dialer_task.id
                )
            self.assertTrue(str(e), "Data for {} {} is null".format(IntelixTeam.DANA_B2, page_num))
        account_payment_ids = AccountPayment.objects.filter(
            id__in=[self.account_payment_b2.id]
        ).values_list('id', flat=True)

        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS.format(
                IntelixTeam.DANA_B2, page_num
            ),
            account_payment_ids,
        )
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        self.status_lookup = StatusLookupFactory(status_code=440)
        self.account = self.status_lookup
        self.account.save()

        with self.assertRaises(Exception):
            with self.assertRaises(Exception) as e:
                process_exclude_dana_data_for_dialer_per_part(
                    IntelixTeam.DANA_B2, page_num, dialer_task.id
                )
            self.assertTrue(
                str(e),
                "{} - part {} dont have eligible data for send to dialer".format(
                    IntelixTeam.DANA_B2, page_num
                ),
            )

        account_payment_ids = AccountPayment.objects.all().values_list('id', flat=True)
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS.format(
                IntelixTeam.DANA_B2, page_num
            ),
            account_payment_ids,
        )
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis

        with self.assertRaises(Exception):
            with self.assertRaises(Exception) as e:
                process_exclude_dana_data_for_dialer_per_part(
                    IntelixTeam.DANA_B2, page_num, dialer_task.id
                )
            self.assertEqual(mock_process_populate_dana_temp_clean_data.called, True)

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_failed_process_populate_dana_temp_clean_data_with_empty_cache(
        self, mock_get_redis_client
    ):
        page_num = 1
        dialer_task_b2 = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        data = process_populate_dana_temp_clean_data(
            IntelixTeam.DANA_B2, page_num, dialer_task_b2.id
        )
        self.assertIsNone(data)

        data = process_populate_dana_temp_clean_data(IntelixTeam.DANA_B2, page_num, 500)
        self.assertIsNone(data)

    @mock.patch('juloserver.dana.collection.tasks.process_not_sent_to_dialer_per_bucket.delay')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_success_process_populate_dana_temp_clean_data(
        self, mock_get_redis_client, mock_async_process_not_sent_to_dialer_per_bucket
    ):
        page_num = 1
        dialer_task_b2 = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        )
        account_payment_ids = [1000, 2000]
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.CLEAN_DANA_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                IntelixTeam.DANA_B2, page_num
            ),
            account_payment_ids,
        )
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis

        with self.assertRaises(Exception):
            with self.assertRaises(Exception) as e:
                process_populate_dana_temp_clean_data(
                    IntelixTeam.DANA_B2, page_num, dialer_task_b2.id
                )
            self.assertTrue(str(e), "data is null")

        account_payment_ids = AccountPayment.objects.all().values_list('id', flat=True)
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.CLEAN_DANA_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED.format(
                IntelixTeam.DANA_B2, page_num
            ),
            account_payment_ids,
        )

        grouped_account_payments = (
            AccountPayment.objects.not_paid_active()
            .filter(id__in=account_payment_ids)
            .distinct('account')
            .annotate(
                team=Value(IntelixTeam.DANA_B2, output_field=CharField()),
                dpd_field=ExpressionWrapper(
                    self.current_date - F('due_date'), output_field=IntegerField()
                ),
            )
            .values(
                'account__customer_id',  # customer_id
                'account__dana_customer_data__application__id',  # application_id
                'account__dana_customer_data__mobile_number',  # mobile_phone_1
                'account__dana_customer_data__full_name',  # full_name
                'due_date',  # tanggal_jatuh_tempo
                'team',  # bucket_name
                'id',  # account payment id,
                'dpd_field',
            )
        )
        serialize_data = DanaDialerTemporarySerializer(
            data=list(grouped_account_payments), many=True
        )
        serialize_data.is_valid(raise_exception=True)
        serialized_data = serialize_data.validated_data
        serialized_data_objects = [DanaDialerTemporaryData(**vals) for vals in serialized_data]
        DanaDialerTemporaryData.objects.bulk_create(serialized_data_objects)
        process_populate_dana_temp_clean_data(IntelixTeam.DANA_B2, page_num, dialer_task_b2.id)
        dialer_task_event = DialerTaskEvent.objects.filter(dialer_task=dialer_task_b2).last()
        self.assertEqual(
            dialer_task_event.status,
            DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                IntelixTeam.DANA_B2, page_num
            ),
        )
        self.assertGreater(mock_async_process_not_sent_to_dialer_per_bucket.call_count, 0)

    def test_create_history_dialer_task_event_success(self):
        dialer_task = DialerTaskFactory()
        error = "ERROR"
        test_dict = dict(
            dialer_task=dialer_task,
            status=DialerTaskStatus.FAILURE_BATCH.format('1'),
        )
        error_message = str(error)
        create_history_dialer_task_event(test_dict, error_message)
        dialer_task_event_1 = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertIsNotNone(dialer_task_event_1)
        self.assertEqual(dialer_task_event_1.status, 'failure_part_1')

        create_history_dialer_task_event(
            dict(
                dialer_task=dialer_task,
                status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                    IntelixTeam.DANA_B2, '1'
                ),
            )
        )
        dialer_task_event_2 = DialerTaskEvent.objects.filter(dialer_task=dialer_task).last()
        self.assertIsNotNone(dialer_task_event_2)
        self.assertEqual(
            dialer_task_event_2.status, 'processed_populated_account_payments_DANA_B2_part_1'
        )

    @mock.patch('juloserver.dana.collection.tasks.record_not_sent_to_intelix')
    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    def test_process_not_sent_to_dialer_per_bucket(
        self, mock_get_redis_client, mock_record_not_sent_to_intelix
    ):
        page_num = 1
        account_payment_ids = AccountPayment.objects.all().values_list('id', flat=True)
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS.format(
                IntelixTeam.DANA_B2, page_num
            ),
            account_payment_ids,
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.EXCLUDED_KEY_LIST_DANA_ACCOUNT_IDS_PER_BUCKET.format(
                IntelixTeam.DANA_B2, page_num
            ),
            [],
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.EXCLUDED_DANA_BY_ACCOUNT_STATUS.format(IntelixTeam.DANA_B2, page_num), []
        )

        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        data = process_not_sent_to_dialer_per_bucket(IntelixTeam.DANA_B2, page_num, 500)
        self.assertIsNone(data)

        dialer_task = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        )
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis(
            RedisKey.POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS.format(
                IntelixTeam.DANA_B2, page_num
            ),
            account_payment_ids,
        )

        data = process_not_sent_to_dialer_per_bucket(IntelixTeam.DANA_B2, page_num, dialer_task.id)
        self.assertIsNone(data)


class TestSendPopulatedDanaDataIntelix(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(
            user=self.user, nik='1601260506021271', phone='082231457592'
        )
        partner = PartnerFactory(user=self.user, is_active=True)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.DANA)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA, handler='DanaWorkflowHandler')
        self.status_lookup = StatusLookupFactory(status_code=420)
        self.account_lookup = AccountLookupFactory(
            workflow=self.workflow, name='DANA', payment_frequency='daily'
        )
        self.account = AccountFactory(
            customer=self.customer,
            status=self.status_lookup,
            account_lookup=self.account_lookup,
            cycle_day=1,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            application_xid=9999990088,
            partner=partner,
            product_line=self.product_line,
            email='testing_email1213@gmail.com',
            account=self.account,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679231',
            customer=self.customer,
            nik=self.customer.nik,
            mobile_number=self.customer.phone,
            partner=partner,
            full_name=self.customer.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account,
            application_id=self.application.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        now = timezone.localtime(timezone.now())
        CustomerPinFactory(
            user=self.application.customer.user,
            latest_failure_count=1,
            last_failure_time=now - relativedelta(minutes=90),
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )

        self.product_lookup = ProductLookupFactory()
        self.credit_matrix = CreditMatrixFactory(product=self.product_lookup)

        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            application=self.application,
            loan_amount=10000000,
            loan_xid=1000003076,
        )
        LoanFactory.create_batch(2, loan_amount=10000000, loan_duration=12)
        self.bucket_name = IntelixTeam.DANA_BUCKET
        self.redis_data = {}
        self.current_date = timezone.localtime(timezone.now()).date()

        self.account.accountpayment_set.all().delete()
        self.account_payment_b2 = AccountPaymentFactory(
            account=self.account,
            due_date=self.current_date - timedelta(days=20),
            is_collection_called=False,
        )
        self.account_payment_b2.account = self.account
        self.account_payment_b2.save(update_fields=['account'])
        self.account_b3 = AccountFactory(status=self.status_lookup)
        self.user1 = AuthUserFactory()
        self.customer1 = CustomerFactory(
            user=self.user1, nik='1601260506021281', phone='082231457582'
        )
        self.application3 = ApplicationFactory(
            customer=self.customer1,
            workflow=self.workflow,
            application_xid=9999990077,
            partner=partner,
            product_line=self.product_line,
            email='testing_email1232@gmail.com',
            account=self.account_b3,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679776',
            customer=self.customer1,
            nik=self.customer1.nik,
            mobile_number=self.customer1.phone,
            partner=partner,
            full_name=self.customer1.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b3,
            application_id=self.application3.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b3.accountpayment_set.all().delete()
        self.account_payment_b3 = AccountPaymentFactory(
            account=self.account_b3,
            due_date=self.current_date - timedelta(days=25),
            is_collection_called=False,
        )
        self.account_payment_b3.account = self.account_b3
        self.account_payment_b3.save()

        self.account_b4 = AccountFactory(status=self.status_lookup)
        self.user2 = AuthUserFactory()
        self.customer2 = CustomerFactory(
            user=self.user2, nik='1601260506021252', phone='082231457596'
        )
        self.application4 = ApplicationFactory(
            customer=self.customer2,
            workflow=self.workflow,
            application_xid=9999990097,
            partner=partner,
            product_line=self.product_line,
            email='testing_6email123@gmail.com',
            account=self.account_b4,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679884',
            customer=self.customer2,
            nik=self.customer2.nik,
            mobile_number=self.customer2.phone,
            partner=partner,
            full_name=self.customer2.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b4,
            application_id=self.application4.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b4.accountpayment_set.all().delete()
        self.account_payment_b4 = AccountPaymentFactory(
            account=self.account_b4,
            due_date=self.current_date - timedelta(days=30),
            is_collection_called=False,
        )

        self.account_b5 = AccountFactory(status=self.status_lookup)
        self.user5 = AuthUserFactory()
        self.customer5 = CustomerFactory(
            user=self.user5, nik='1601260506021273', phone='082231457563'
        )
        self.application5 = ApplicationFactory(
            customer=self.customer5,
            workflow=self.workflow,
            application_xid=9999990037,
            partner=partner,
            product_line=self.product_line,
            email='testingu_email123@gmail.com',
            account=self.account_b5,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679369',
            customer=self.customer5,
            nik=self.customer5.nik,
            mobile_number=self.customer5.phone,
            partner=partner,
            full_name=self.customer5.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b5,
            application_id=self.application5.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b5.accountpayment_set.all().delete()
        self.account_payment_b5 = AccountPaymentFactory(
            account=self.account_b5,
            due_date=self.current_date - timedelta(days=32),
            is_collection_called=False,
        )

        self.account_b6 = AccountFactory(status=self.status_lookup)
        self.user6 = AuthUserFactory()
        self.customer6 = CustomerFactory(
            user=self.user6, nik='1601260506021208', phone='082231457590'
        )
        self.application6 = ApplicationFactory(
            customer=self.customer6,
            workflow=self.workflow,
            application_xid=9999990007,
            partner=partner,
            product_line=self.product_line,
            email='testingy_email123@gmail.com',
            account=self.account_b6,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679305',
            customer=self.customer6,
            nik=self.customer6.nik,
            mobile_number=self.customer6.phone,
            partner=partner,
            full_name=self.customer6.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b6,
            application_id=self.application6.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b6.accountpayment_set.all().delete()
        self.account_payment_b6 = AccountPaymentFactory(
            account=self.account_b6,
            due_date=self.current_date - timedelta(days=60),
            is_collection_called=False,
        )
        self.account_b7 = AccountFactory(status=self.status_lookup)
        self.user7 = AuthUserFactory()
        self.customer7 = CustomerFactory(
            user=self.user7, nik='1601260506021298', phone='082231457508'
        )
        self.application7 = ApplicationFactory(
            customer=self.customer7,
            workflow=self.workflow,
            application_xid=9999990067,
            partner=partner,
            product_line=self.product_line,
            email='testingk_email123@gmail.com',
            account=self.account_b7,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            dana_customer_identifier='12345679805',
            customer=self.customer7,
            nik=self.customer7.nik,
            mobile_number=self.customer7.phone,
            partner=partner,
            full_name=self.customer7.fullname,
            proposed_credit_limit=1_000_000,
            account=self.account_b7,
            application_id=self.application7.id,
            registration_time=timezone.localtime(timezone.now()),
        )
        self.account_b7.accountpayment_set.all().delete()
        self.account_payment_b7 = AccountPaymentFactory(
            account=self.account_b7,
            due_date=self.current_date - timedelta(days=5),
            is_collection_called=False,
        )
        self.current_time = timezone.localtime(timezone.now())

    def set_redis(self, key, val, time=None):
        self.redis_data[key] = val

    def get_redis(self, key):
        return self.redis_data[key]

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch(
        'juloserver.dana.collection.tasks.send_batch_dana_data_to_intelix_with_retries_mechanism'
    )
    @mock.patch('juloserver.dana.collection.tasks.set_redis_data_temp_table')
    @mock.patch('juloserver.dana.collection.tasks.logger.info')
    @mock.patch('juloserver.dana.collection.tasks.is_block_dana_intelix')
    def test_upload_dana_b1_data_to_intelix(
        self,
        mock_is_block_dana_intelix,
        mocked_logger,
        mock_redis_data_temp_table,
        mock_send_batch_dana_data_to_intelix_with_retries_mechanism_async,
        mock_get_redis_client,
    ):
        self.feature_setting = FeatureSettingFactory(
            feature_name=DanaFeatureNameConst.DANA_BLOCK_INTELIX_TRAFFIC, is_active=True
        )
        mock_is_block_dana_intelix.return_value = True
        upload_dana_b1_data_to_intelix()
        mocked_logger.assert_called()
        retries_time = 0
        self.feature_setting = FeatureSettingFactory(
            feature_name=DanaFeatureNameConst.DANA_BLOCK_INTELIX_TRAFFIC, is_active=False
        )
        mock_is_block_dana_intelix.return_value = False
        dialer_task = DialerTaskFactory(type=DialerTaskType.UPLOAD_DANA_B1)
        with self.assertRaises(Exception) as e:
            upload_dana_b1_data_to_intelix()
        self.assertIn(
            "data still not populated yet after retries {} times on".format(retries_time),
            str(e.exception),
        )
        dialer_task_b1 = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B1)
        )
        with self.assertRaises(Exception) as e:
            upload_dana_b1_data_to_intelix()
        self.assertIn(
            "dont have batching log yet after retries {} times on".format(retries_time),
            str(e.exception),
        )
        dialer_task_event = DialerTaskEventFactory(
            dialer_task=dialer_task_b1, status=DialerTaskStatus.BATCHING_PROCESSED, data_count=2
        )
        with self.assertRaises(Exception) as e:
            upload_dana_b1_data_to_intelix()
        self.assertIn(
            "dont have processed log yet after retries {} times on".format(retries_time),
            str(e.exception),
        )

        DialerTaskEventFactory(
            dialer_task=dialer_task_b1,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                IntelixTeam.DANA_B1, '1'
            ),
            data_count=1,
        )

        with self.assertRaises(Exception) as e:
            upload_dana_b1_data_to_intelix()
        self.assertIn("process not complete", str(e.exception))
        dialer_task_event.data_count = 1
        dialer_task_event.save(update_fields=['data_count'])
        with self.assertRaises(Exception) as e:
            upload_dana_b1_data_to_intelix()
        self.assertEqual(str(e.exception), "dont have any data to send")
        account_payment_ids = AccountPayment.objects.all().values_list('id', flat=True)
        grouped_account_payments = (
            AccountPayment.objects.not_paid_active()
            .filter(id__in=account_payment_ids)
            .distinct('account')
            .annotate(
                team=Value(IntelixTeam.DANA_B1, output_field=CharField()),
                dpd_field=ExpressionWrapper(
                    self.current_date - F('due_date'), output_field=IntegerField()
                ),
            )
            .values(
                'account__customer_id',  # customer_id
                'account__dana_customer_data__application__id',  # application_id
                'account__dana_customer_data__mobile_number',  # mobile_phone_1
                'account__dana_customer_data__full_name',  # full_name
                'due_date',  # tanggal_jatuh_tempo
                'team',  # bucket_name
                'id',  # account payment id,
                'dpd_field',
            )
        )
        serialize_data = DanaDialerTemporarySerializer(
            data=list(grouped_account_payments), many=True
        )
        serialize_data.is_valid(raise_exception=True)
        serialized_data = serialize_data.validated_data
        serialized_data_objects = [DanaDialerTemporaryData(**vals) for vals in serialized_data]
        DanaDialerTemporaryData.objects.bulk_create(serialized_data_objects)
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        upload_dana_b1_data_to_intelix()
        populated_dialer_call_data = DanaDialerTemporaryData.objects.get_daily_temp_data_per_bucket(
            IntelixTeam.DANA_B1
        )
        self.assertGreater(populated_dialer_call_data.count(), 0)
        assert mock_send_batch_dana_data_to_intelix_with_retries_mechanism_async.apply_async.called_with(
            kwargs={
                'dialer_task_id': dialer_task.id,
                'page_number': '1',
                'bucket_name': IntelixTeam.DANA_B1,
            }
        )

    @mock.patch('juloserver.minisquad.services2.intelix.get_redis_client')
    @mock.patch(
        'juloserver.dana.collection.tasks.send_batch_dana_data_to_intelix_with_retries_mechanism'
    )
    @mock.patch('juloserver.dana.collection.tasks.set_redis_data_temp_table')
    @mock.patch('juloserver.dana.collection.tasks.logger.info')
    @mock.patch('juloserver.dana.collection.tasks.is_block_dana_intelix')
    def test_upload_dana_b2_data_to_intelix(
        self,
        mock_is_block_dana_intelix,
        mocked_logger,
        mock_redis_data_temp_table,
        mock_send_batch_dana_data_to_intelix_with_retries_mechanism_async,
        mock_get_redis_client,
    ):
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        self.feature_setting = FeatureSettingFactory(
            feature_name=DanaFeatureNameConst.DANA_BLOCK_INTELIX_TRAFFIC, is_active=True
        )
        mock_is_block_dana_intelix.return_value = True
        upload_dana_b2_data_to_intelix()
        mocked_logger.assert_called()
        retries_time = 0
        self.feature_setting = FeatureSettingFactory(
            feature_name=DanaFeatureNameConst.DANA_BLOCK_INTELIX_TRAFFIC, is_active=False
        )
        mock_is_block_dana_intelix.return_value = False
        dialer_task = DialerTaskFactory(type=DialerTaskType.UPLOAD_DANA_B2)

        with self.assertRaises(Exception) as e:
            upload_dana_b2_data_to_intelix()
        self.assertIn(
            "data still not populated yet after retries {} times on".format(retries_time),
            str(e.exception),
        )
        dialer_task_b1 = DialerTaskFactory(
            type=DialerTaskType.POPULATING_COLLECTION_DIALER_TEMP_DATA.format(IntelixTeam.DANA_B2)
        )

        with self.assertRaises(Exception) as e:
            upload_dana_b2_data_to_intelix()
        self.assertIn(
            "dont have batching log yet after retries {} times on".format(retries_time),
            str(e.exception),
        )
        dialer_task_event = DialerTaskEventFactory(
            dialer_task=dialer_task_b1, status=DialerTaskStatus.BATCHING_PROCESSED, data_count=2
        )
        with self.assertRaises(Exception) as e:
            upload_dana_b2_data_to_intelix()
        self.assertIn(
            "dont have processed log yet after retries {} times on".format(retries_time),
            str(e.exception),
        )
        DialerTaskEventFactory(
            dialer_task=dialer_task_b1,
            status=DialerTaskStatus.PROCESSED_POPULATED_ACCOUNT_PAYMENTS.format(
                IntelixTeam.DANA_B2, '1'
            ),
            data_count=1,
        )

        with self.assertRaises(Exception) as e:
            upload_dana_b2_data_to_intelix()
        self.assertIn("process not complete", str(e.exception))
        dialer_task_event.data_count = 1
        dialer_task_event.save(update_fields=['data_count'])
        with self.assertRaises(Exception) as e:
            upload_dana_b2_data_to_intelix()
        self.assertEqual(str(e.exception), "dont have any data to send")
        account_payment_ids = AccountPayment.objects.all().values_list('id', flat=True)
        grouped_account_payments = (
            AccountPayment.objects.not_paid_active()
            .filter(id__in=account_payment_ids)
            .distinct('account')
            .annotate(
                team=Value(IntelixTeam.DANA_B2, output_field=CharField()),
                dpd_field=ExpressionWrapper(
                    self.current_date - F('due_date'), output_field=IntegerField()
                ),
            )
            .values(
                'account__customer_id',  # customer_id
                'account__dana_customer_data__application__id',  # application_id
                'account__dana_customer_data__mobile_number',  # mobile_phone_1
                'account__dana_customer_data__full_name',  # full_name
                'due_date',  # tanggal_jatuh_tempo
                'team',  # bucket_name
                'id',  # account payment id,
                'dpd_field',
            )
        )
        serialize_data = DanaDialerTemporarySerializer(
            data=list(grouped_account_payments), many=True
        )
        serialize_data.is_valid(raise_exception=True)
        serialized_data = serialize_data.validated_data
        serialized_data_objects = [DanaDialerTemporaryData(**vals) for vals in serialized_data]
        DanaDialerTemporaryData.objects.bulk_create(serialized_data_objects)
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        upload_dana_b2_data_to_intelix()
        populated_dialer_call_data = DanaDialerTemporaryData.objects.get_daily_temp_data_per_bucket(
            IntelixTeam.DANA_B2
        )
        self.assertGreater(populated_dialer_call_data.count(), 0)
        assert mock_send_batch_dana_data_to_intelix_with_retries_mechanism_async.apply_async.called_with(
            kwargs={
                'dialer_task_id': dialer_task.id,
                'page_number': '1',
                'bucket_name': IntelixTeam.DANA_B2,
            }
        )

    @mock.patch('juloserver.dana.collection.tasks.INTELIX_CLIENT.upload_to_queue')
    @mock.patch('juloserver.dana.collection.tasks.get_redis_data_temp_table')
    @mock.patch('juloserver.dana.collection.tasks.get_redis_client')
    def test_send_batch_dana_data_to_intelix_with_retries_mechanism(
        self, mock_get_redis_client, mock_get_redis_data_temp_table, mocked_upload
    ):
        mock_get_redis_client.return_value.set_list.side_effect = self.set_redis
        mock_get_redis_client.return_value.get_list.side_effect = self.get_redis
        data = send_batch_dana_data_to_intelix_with_retries_mechanism(
            bucket_name=DialerTaskType.UPLOAD_DANA_B2, dialer_task_id=5000, page_number=1
        )
        self.assertIsNone(data)
        dialer_task_b2 = DialerTaskFactory(type=DialerTaskType.UPLOAD_DANA_B2)
        mock_get_redis_data_temp_table.return_value = []
        with self.assertRaises(Exception) as e:
            send_batch_dana_data_to_intelix_with_retries_mechanism(
                bucket_name=IntelixTeam.DANA_B2, dialer_task_id=dialer_task_b2.id, page_number=1
            )
        self.assertEqual(
            str(e.exception),
            "data not stored on redis for send data {} page {}".format(IntelixTeam.DANA_B2, 1),
        )
        mock_get_redis_data_temp_table.return_value = [100, 200, 300]
        mocked_upload.return_value = {'result': 'failure', 'rec_num': 1}
        with self.assertRaises(Exception) as e:
            send_batch_dana_data_to_intelix_with_retries_mechanism(
                bucket_name=IntelixTeam.DANA_B2, dialer_task_id=dialer_task_b2.id, page_number=1
            )
        self.assertEqual(
            str(e.exception),
            "Failed Send data to Intelix {} {}".format(
                IntelixTeam.DANA_B2, mocked_upload.return_value['result']
            ),
        )
        mocked_upload.return_value = {'result': 'success', 'rec_num': 1}
        send_batch_dana_data_to_intelix_with_retries_mechanism(
            bucket_name=IntelixTeam.DANA_B2, dialer_task_id=dialer_task_b2.id, page_number=1
        )
