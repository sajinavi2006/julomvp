import mock
import pytest
from datetime import timedelta, datetime
from celery.exceptions import Retry

from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from juloserver.account_payment.tasks.scheduled_tasks import (
    update_account_payment_status,
    update_account_payment_status_subtask,
    run_ptp_update_for_j1,
    register_late_fee_experiment,
)
from juloserver.account_payment.services.doku import (
    doku_snap_payment_process_account,
)
from juloserver.account_payment.tasks.repayment_tasks import (
    doku_snap_inquiry_transaction,
    doku_snap_inquiry_payment_status,
    faspay_snap_inquiry_payment_status,
)
from juloserver.account_payment.models import AccountPayment

from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    ApplicationFactory,
    ProductLineFactory,
    LoanFactory,
    PaymentFactory,
    ProductLookupFactory,
    StatusLookupFactory,
    PaymentMethodFactory,
    PaybackTransactionFactory,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import PaymentStatusCodes, LoanStatusCodes

from juloserver.account.tests.factories import AccountFactory, ExperimentGroupFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.julo.tests.factories import ExperimentSettingFactory
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
from django.conf import settings
import csv
from juloserver.account.models import ExperimentGroup
from juloserver.julo.models import StatusLookup
from juloserver.account_payment.constants import RepaymentRecallPaymentMethod
import os
from juloserver.julo.payment_methods import PaymentMethodCodes, PartnerServiceIds


class TestScheduledTasks(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
            product_line_type='J1'
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=product_line
        )
        loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            product=ProductLookupFactory(product_line=product_line, late_fee_pct=0.05),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            installment_amount=2000000,
            application=None
        )
        five_days_ago_date = timezone.localtime(timezone.now()).date() - timedelta(days=5)
        self.account_payment = AccountPaymentFactory(
            account=self.account,
            due_date=five_days_ago_date
        )
        self.account_payment.status_id = 320
        self.account_payment.save()
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=loan,
        )
        self.user_auth_jturbo = AuthUserFactory()
        self.customer_jturbo = CustomerFactory(user=self.user_auth_jturbo)
        self.account_jturbo = AccountFactory(customer=self.customer_jturbo)
        product_line_jturbo = ProductLineFactory(
            product_line_code=ProductLineCodes.JULO_STARTER,
            product_line_type='J-STARTER'
        )
        self.application_jturbo = ApplicationFactory(
            customer=self.customer_jturbo,
            account=self.account_jturbo,
            product_line=product_line_jturbo,
        )
        loan_jturbo = LoanFactory(
            customer=self.customer_jturbo,
            account=self.account_jturbo,
            product=ProductLookupFactory(product_line=product_line_jturbo, late_fee_pct=0.05),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
            installment_amount=2000000,
            application=None
        )
        five_days_ago_date = timezone.localtime(timezone.now()).date() - timedelta(days=5)
        one_day_ago_date = timezone.localtime(timezone.now()).date() - timedelta(days=1)
        self.account_payment_jturbo = AccountPaymentFactory(
            account=self.account_jturbo,
            due_date=one_day_ago_date
        )
        self.account_payment_jturbo.status_id = 312
        self.account_payment_jturbo.save()
        self.payment_jturbo = PaymentFactory(
            payment_status=self.account_payment_jturbo.status,
            due_date=self.account_payment_jturbo.due_date,
            account_payment=self.account_payment_jturbo,
            loan=loan_jturbo,
        )
        self.experiment = ExperimentSettingFactory(
            is_active=True,
            code=MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            is_permanent=True,
            criteria={"account_id_tail": {"control": [0, 1, 2, 3, 4], "experiment": [5, 6, 7, 8, 9]}},
        )
        ExperimentGroupFactory(
            experiment_setting=self.experiment,
            account_id=self.account_payment_jturbo.account_id,
            group='experiment')

    @mock.patch('juloserver.account.tasks.scheduled_tasks.get_redis_client')
    @mock.patch('juloserver.account_payment.tasks.scheduled_tasks.execute_after_transaction_safely')
    @mock.patch('juloserver.account_payment.models.AccountPayment.objects.status_tobe_update')
    def test_update_account_payment_status(
        self, mock_account_payments, mock_execute_after_transaction_safely, mock_get_redis_client
    ):
        account_payments = AccountPayment.objects.all()
        num_payments = len(account_payments)
        mock_redis_client = mock.MagicMock()
        mock_get_redis_client.return_value = mock_redis_client
        mock_locks = [mock.MagicMock(name=f"mock_lock_{i}") for i in range(num_payments)]
        mock_redis_client.lock.side_effect = mock_locks
        for mock_lock in mock_locks:
            mock_lock.__enter__.return_value = None
            mock_lock.__exit__.return_value = None
        mock_account_payments.return_value = account_payments
        update_account_payment_status()
        self.account_payment.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.account_payment.status_id, PaymentStatusCodes.PAYMENT_5DPD)
        mock_execute_after_transaction_safely.assert_called()
        self.assertEqual(self.payment.late_fee_applied, 1)

    @mock.patch('juloserver.account.tasks.scheduled_tasks.get_redis_client')
    @mock.patch('juloserver.account_payment.tasks.scheduled_tasks.execute_after_transaction_safely')
    def test_update_account_payment_status_subtask(
        self, mock_execute_after_transaction_safely, mock_get_redis_client
    ):
        mock_redis_client = mock.MagicMock()
        mock_lock = mock.MagicMock()
        mock_get_redis_client.return_value = mock_redis_client
        mock_redis_client.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = None
        mock_lock.__exit__.return_value = None
        update_account_payment_status_subtask(self.account_payment.id)
        self.account_payment.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.account_payment.status_id, PaymentStatusCodes.PAYMENT_5DPD)
        mock_execute_after_transaction_safely.assert_called()
        self.assertEqual(self.payment.late_fee_applied, 1)

    @mock.patch('juloserver.account.tasks.scheduled_tasks.get_redis_client')
    @mock.patch('juloserver.account_payment.tasks.scheduled_tasks.execute_after_transaction_safely')
    def test_update_account_payment_status_subtask_dpd_6(
        self, mock_execute_after_transaction_safely, mock_get_redis_client
    ):
        mock_redis_client = mock.MagicMock()
        mock_lock = mock.MagicMock()
        mock_get_redis_client.return_value = mock_redis_client
        mock_redis_client.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = None
        mock_lock.__exit__.return_value = None
        six_days_ago_date = timezone.localtime(timezone.now()).date() - timedelta(days=6)
        self.account_payment.update_safely(due_date=six_days_ago_date)
        self.payment.update_safely(due_date=six_days_ago_date)
        update_account_payment_status_subtask(self.account_payment.id)
        self.account_payment.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.account_payment.status_id, PaymentStatusCodes.PAYMENT_5DPD)
        mock_execute_after_transaction_safely.assert_called()
        self.assertEqual(self.payment.late_fee_applied, 1)

    @override_settings(CELERY_ALWAYS_EAGER=True)
    @override_settings(BROKER_BACKEND='memory')
    @override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
    @mock.patch('juloserver.account_payment.tasks.scheduled_tasks.execute_after_transaction_safely')
    def test_update_account_payment_status_subtask_error(self,
                                                         mock_execute_after_transaction_safely):
        self.application.update_safely(account=None)
        with pytest.raises(Retry) as retry_exc:
            update_account_payment_status_subtask.delay(self.account_payment.id)
        self.assertEqual(retry_exc.value.when, 5)
        self.account_payment.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.account_payment.status_id, PaymentStatusCodes.PAYMENT_1DPD)
        mock_execute_after_transaction_safely.assert_not_called()
        self.assertEqual(self.payment.late_fee_applied, 0)
    
    @mock.patch('juloserver.account_payment.models.AccountPayment.objects.filter')
    @mock.patch('juloserver.account_payment.tasks.scheduled_tasks.ptp_update_for_j1')
    def test_run_ptp_update_for_j1(self, mock_ptp_update_for_j1, mock_account_payments):
        mock_ptp_update_for_j1.return_value = True
        mock_account_payments.return_value = AccountPayment.objects.all()
        run_ptp_update_for_j1()

    @mock.patch('juloserver.account.tasks.scheduled_tasks.get_redis_client')
    @mock.patch('juloserver.account_payment.tasks.scheduled_tasks.execute_after_transaction_safely')
    @mock.patch('juloserver.account_payment.models.AccountPayment.objects.status_tobe_update')
    def test_update_account_payment_status_late_fee_earlier(
        self, mock_account_payments, mock_execute_after_transaction_safely, mock_get_redis_client
    ):
        account_payments = AccountPayment.objects.all()
        num_payments = len(account_payments)
        mock_redis_client = mock.MagicMock()
        mock_get_redis_client.return_value = mock_redis_client
        mock_locks = [mock.MagicMock(name=f"mock_lock_{i}") for i in range(num_payments)]
        mock_redis_client.lock.side_effect = mock_locks
        for mock_lock in mock_locks:
            mock_lock.__enter__.return_value = None
            mock_lock.__exit__.return_value = None
        mock_account_payments.return_value = account_payments
        update_account_payment_status()
        self.account_payment_jturbo.refresh_from_db()
        self.payment_jturbo.refresh_from_db()
        self.assertEqual(self.account_payment_jturbo.status_id, PaymentStatusCodes.PAYMENT_1DPD)
        mock_execute_after_transaction_safely.assert_called()
        self.assertEqual(self.payment_jturbo.late_fee_applied, 1)

    @mock.patch('juloserver.account.tasks.scheduled_tasks.get_redis_client')
    @mock.patch('juloserver.account_payment.tasks.scheduled_tasks.execute_after_transaction_safely')
    def test_update_account_payment_status_subtask_late_fee_earlier(
        self, mock_execute_after_transaction_safely, mock_get_redis_client
    ):
        mock_redis_client = mock.MagicMock()
        mock_lock = mock.MagicMock()
        mock_get_redis_client.return_value = mock_redis_client
        mock_redis_client.lock.return_value = mock_lock
        mock_lock.__enter__.return_value = None
        mock_lock.__exit__.return_value = None
        update_account_payment_status_subtask(self.account_payment_jturbo.id)
        self.account_payment_jturbo.refresh_from_db()
        self.payment_jturbo.refresh_from_db()
        self.assertEqual(self.account_payment_jturbo.status_id, PaymentStatusCodes.PAYMENT_1DPD)
        mock_execute_after_transaction_safely.assert_called()
        self.assertEqual(self.payment_jturbo.late_fee_applied, 1)


class TestScheduledPullLateFeeExperiment(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.experiment = ExperimentSettingFactory(
            is_active=True,
            code=MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            is_permanent=True,
            criteria={
                "folder_id": "dummy",
                "account_id_tail": {"control": [0, 1, 2, 3, 4], "experiment": [5, 6, 7, 8, 9]}
            },
        )

    @mock.patch('juloserver.account_payment.tasks.scheduled_tasks.get_data_google_drive_api_client')
    @mock.patch('juloserver.moengage.tasks.trigger_send_user_attribute_late_fee_earlier_experiment')
    def test_pull_late_fee_experiment(self, mock_moengage, mock_download):
        path_mock_file = settings.BASE_DIR + \
            '/juloserver/account_payment/tests/test_tasks/mock_late_fee.csv'
        mock_download.return_value.find_file_on_folder_by_id.return_value = path_mock_file
        mock_moengage.return_value = True
        data = [
            ['account_id', 'experiment_group'],
            [self.account.id, 'experiment']
        ]
        with open(path_mock_file, mode='w', newline='') as file:
            csv_writer = csv.writer(file, delimiter=',')
            csv_writer.writerows(data)

        register_late_fee_experiment.delay()
        registered = ExperimentGroup.objects.filter(account=self.account).exists()
        self.assertEqual(True, registered)
        self.assertEqual(False, os.path.exists(path_mock_file))


class TestFaspaySnapTasks(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.due_amount = 5000000
        self.account_payment.save()
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000,
        )
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000,
        )
        self.payment_method = PaymentMethodFactory(
            payment_method_code="888999088",
            customer=self.customer,
            virtual_account="88899908800252920",
            payment_method_name="fasoat",
        )
        self.payback_trx = PaybackTransactionFactory(
            transaction_id="123",
            customer=self.customer,
            transaction_date=datetime.today(),
            payment_method=self.payment_method,
            payment=self.payment,
            account=self.account,
            payback_service=RepaymentRecallPaymentMethod.FASPAY,
        )
        self.response_faspay_inquiry_success = {
            'responseCode': '2002600',
            'responseMessage': 'Success',
            'virtualAccountData': {
                'paymentFlagReason': {'english': 'Success'},
                'partnerServiceId': '88308220',
                'customerNo': '00526471',
                'virtualAccountNo': '123',
                'inquiryRequestId': 'f3750e67-5c99-1251g-9921-12561',
                'paidAmount': {'value': '100000.00', 'currency': 'IDR'},
                'referenceNo': '17625162512671',
                'paymentFlagStatus': '00',
                'additionalInfo': {'channelCode': '802'},
            },
        }
        self.response_faspay_inquiry_error = {
            'responseCode': '5002600',
            'responseMessage': 'General Error',
        }

    # @mock.patch(
    #     'juloserver.account_payment.tasks.repayment_tasks.detokenize_sync_primary_object_model'
    # )
    @mock.patch('juloserver.account_payment.tasks.repayment_tasks.get_faspay_snap_client')
    @mock.patch(
        'juloserver.account_payment.tasks.repayment_tasks.faspay_snap_payment_process_account'
    )
    def test_faspay_snap_inquiry_payment_status_success(
        self,
        mock_process_account,
        mock_get_client,
        # mock_detokenize_sync_primary_object_model
    ):
        mock_client = mock.Mock()
        mock_get_client.return_value = mock_client

        mock_client.inquiry_status.return_value = (self.response_faspay_inquiry_success, None)
        # mock_detokenize_sync_primary_object_model.return_value = self.payment_method

        faspay_snap_inquiry_payment_status(self.payback_trx.id)

        mock_client.inquiry_status.assert_called_once()
        mock_process_account.assert_called_once()

    # @mock.patch(
    #     'juloserver.account_payment.tasks.repayment_tasks.detokenize_sync_primary_object_model'
    # )
    @mock.patch('juloserver.account_payment.tasks.repayment_tasks.get_faspay_snap_client')
    @mock.patch(
        'juloserver.account_payment.tasks.repayment_tasks.faspay_snap_payment_process_account'
    )
    def test_faspay_snap_inquiry_payment_status_error(
        self,
        mock_process_account,
        mock_get_client,
        # mock_detokenize_sync_primary_object_model
    ):
        mock_client = mock.Mock()
        mock_get_client.return_value = mock_client

        mock_client.inquiry_status.return_value = (None, 'General Error')
        # mock_detokenize_sync_primary_object_model.return_value = self.payment_method

        faspay_snap_inquiry_payment_status(self.payback_trx.id)

        mock_client.inquiry_status.assert_called_once()
        mock_process_account.assert_not_called()

        mock_client.inquiry_status.return_value = (
            self.response_faspay_inquiry_error,
            'General Error',
        )
        # mock_detokenize_sync_primary_object_model.return_value = self.payment_method

        faspay_snap_inquiry_payment_status(self.payback_trx.id)

        mock_process_account.assert_not_called()


class TestDokuSnapTasks(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment.status_id = 320
        self.account_payment.due_amount = 5000000
        self.account_payment.save()
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT),
            initial_cashback=2000,
        )
        self.payment = PaymentFactory(
            payment_status=self.account_payment.status,
            due_date=self.account_payment.due_date,
            account_payment=self.account_payment,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=10000,
        )
        self.payment_method = PaymentMethodFactory(
            payment_method_code=PaymentMethodCodes.MANDIRI_DOKU,
            customer=self.customer,
            virtual_account=f"{PaymentMethodCodes.MANDIRI_DOKU}00252920",
            payment_method_name="doku",
        )
        self.payback_trx = PaybackTransactionFactory(
            transaction_id="123",
            customer=self.customer,
            transaction_date=datetime.today(),
            payment_method=self.payment_method,
            payment=self.payment,
            account=self.account,
            payback_service=RepaymentRecallPaymentMethod.DOKU,
        )
        self.response_doku_inquiry = {
            'responseCode': '2002600',
            'responseMessage': 'Success',
            'virtualAccountData': {
                'paymentFlagReason': {'english': 'Success', 'indonesia': 'Sukses'},
                'partnerServiceId': '   88899',
                'customerNo': '908800252920',
                'virtualAccountNo': '88899908800252920',
                'inquiryRequestId': 'abcdef-123456-abcdef',
                'paymentRequestId': 'abcdef-123456-abcdef',
                'paidAmount': {'value': '12345678.00', 'currency': 'IDR'},
                'billAmount': {'value': '12345678.00', 'currency': 'IDR'},
                'additionalInfo': {'acquirer': 'MANDIRI', 'trxId': ' test123'},
            },
        }

    @mock.patch(
        'juloserver.account_payment.tasks.repayment_tasks.doku_snap_inquiry_payment_status.delay'
    )
    @mock.patch(
        'juloserver.account_payment.tasks.repayment_tasks.PaybackTransaction.objects.filter'
    )
    def test_doku_snap_inquiry_transaction(self, mock_filter, mock_delay):
        # Mock queryset return values
        mock_queryset1 = mock.Mock()
        mock_queryset2 = mock.Mock()
        mock_queryset1.values_list.return_value = [1, 2, 3]
        mock_queryset2.values_list.return_value = [4, 5]

        # Ensure the mock returns a mock queryset
        mock_filter.side_effect = [mock_queryset1, mock_queryset2]

        # Call the task function
        doku_snap_inquiry_transaction()

        # Assertions
        mock_filter.assert_called()
        mock_delay.assert_has_calls(
            [
                mock.call(1),
                mock.call(2),
                mock.call(3),
                mock.call(4),
                mock.call(5),
            ]
        )
        self.assertEqual(mock_delay.call_count, 5)

    @pytest.mark.skip(reason="Flaky")
    @mock.patch('juloserver.account_payment.tasks.repayment_tasks.get_doku_snap_client')
    @mock.patch(
        'juloserver.account_payment.tasks.repayment_tasks.doku_snap_payment_process_account'
    )
    def test_doku_snap_inquiry_payment_status(self, mock_process_account, mock_get_client):
        mock_client = mock.Mock()
        mock_get_client.return_value = mock_client

        mock_client.inquiry_status.return_value = (self.response_doku_inquiry, None)

        doku_snap_inquiry_payment_status(self.payback_trx.id)

        mock_process_account.assert_called_once_with(
            self.payback_trx,
            self.response_doku_inquiry['virtualAccountData'],
            f'payment with va {PaymentMethodCodes.MANDIRI_DOKU}00252920 doku',
        )
        mock_client.inquiry_status.assert_called_once_with(
            partner_service_id=PartnerServiceIds.MANDIRI_DOKU,
            customer_no=self.payment_method.virtual_account[len(PartnerServiceIds.MANDIRI_DOKU) :],
            virtual_account_no=f'{PaymentMethodCodes.MANDIRI_DOKU}00252920',
            transaction_id=self.payback_trx.transaction_id,
        )

    @mock.patch('juloserver.account_payment.services.doku.get_oldest_payment_due')
    @mock.patch('juloserver.account_payment.services.doku.get_active_loan')
    @mock.patch('juloserver.account_payment.services.doku.j1_refinancing_activation')
    @mock.patch('juloserver.account_payment.services.doku.process_j1_waiver_before_payment')
    @mock.patch('juloserver.account_payment.services.doku.process_rentee_deposit_trx')
    @mock.patch('juloserver.account_payment.services.doku.process_repayment_trx')
    @mock.patch(
        'juloserver.account_payment.services.doku.update_moengage_for_payment_received_task.delay'
    )
    def test_doku_snap_payment_process_account(
        self,
        mock_update_moengage_for_payment_received_task,
        mock_process_repayment_trx,
        mock_process_rentee_deposit_trx,
        mock_process_j1_waiver_before_payment,
        mock_j1_refinancing_activation,
        mock_get_active_loan,
        mock_get_oldest_payment_due,
    ):
        mock_get_active_loan.return_value = self.loan
        mock_get_oldest_payment_due.return_value = self.payment

        doku_snap_payment_process_account(
            self.payback_trx,
            self.response_doku_inquiry['virtualAccountData'],
            'payment with va 88899908800252920 doku',
        )

        mock_get_active_loan.assert_called_once()
        mock_get_oldest_payment_due.assert_called_once()
        mock_j1_refinancing_activation.assert_called_once()
        mock_process_j1_waiver_before_payment.assert_called_once()
        mock_process_rentee_deposit_trx.assert_called_once()
        mock_process_repayment_trx.assert_not_called()
        mock_update_moengage_for_payment_received_task.assert_called_once()
