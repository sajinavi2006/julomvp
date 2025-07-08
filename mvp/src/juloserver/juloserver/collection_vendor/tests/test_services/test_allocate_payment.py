from builtins import range
from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.test.utils import override_settings

from juloserver.collection_vendor.models import SubBucket
from juloserver.collection_vendor.task import (allocate_payments_to_collection_vendor_for_bucket_5,
                                               allocate_payments_to_collection_vendor_for_bucket_6_3)
from juloserver.collection_vendor.tests.factories import (SkipTraceFactory, SkiptraceResultChoiceFactory,
                                                          SkiptraceHistoryFactory, AgentAssignmentFactory)
from juloserver.julo.tests.factories import (AuthUserFactory,
                                             LoanFactory,
                                             PaymentFactory, PaymentEventFactory)
from django.utils import timezone
from datetime import timedelta
import mock


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestAllocatePayment(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(username="unittest")
        self.today = timezone.localtime(timezone.now())

        # create subbucket
        self.sub_bucket_1 = SubBucket.objects.create(
            bucket=5, sub_bucket=1, start_dpd=91, end_dpd=180, id=1)
        self.sub_bucket_2 = SubBucket.objects.create(
            bucket=5, sub_bucket=2, start_dpd=91, end_dpd=180, id=2)
        self.sub_bucket_3 = SubBucket.objects.create(
            bucket=5, sub_bucket=3, start_dpd=91, end_dpd=180, id=3)
        self.sub_bucket_4 = SubBucket.objects.create(
            bucket=5, sub_bucket=4, start_dpd=361, end_dpd=720, id=4)

    @mock.patch('juloserver.collection_vendor.task.allocate_bucket_5_account_payments_to_collection_vendor')
    @mock.patch('juloserver.minisquad.tasks2.intelix_task.upload_julo_b5_data_to_intelix')
    @mock.patch('juloserver.collection_vendor.task.get_redis_client')
    @mock.patch('juloserver.collection_vendor.task.AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1', 1)
    def test_allocate_payment_for_bucket_5(self, mocked_redis_client, mocked_sent_to_intelix, mock_allocate_account_payment):
        loan_assigned = LoanFactory(id=77)
        loan_assigned.loan_status_code = 234
        loan_assigned.ever_entered_B5 = True
        loan_assigned.save()
        loan_assigned_2 = LoanFactory(id=78)
        loan_assigned_2.loan_status_code = 234
        loan_assigned_2.ever_entered_B5 = True
        loan_assigned_2.save()
        PaymentFactory(loan=loan_assigned)
        PaymentFactory(loan=loan_assigned_2)
        assigned_payment = loan_assigned.payment_set.first()
        dpd_91_date = self.today.date() - timedelta(days=self.sub_bucket_1.start_dpd)
        assigned_payment.due_date = dpd_91_date
        assigned_payment.due_amount = 100000
        assigned_payment.payment_status_code = 324
        assigned_payment.save()
        assigned_payment2 = loan_assigned_2.payment_set.first()
        assigned_payment2.due_date = dpd_91_date
        assigned_payment2.due_amount = 100000
        assigned_payment2.payment_status_code = 324
        assigned_payment2.save()
        yesterday = self.today - timedelta(days=1)
        AgentAssignmentFactory(
            payment=assigned_payment, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket_1, assign_time=yesterday)
        AgentAssignmentFactory(
            payment=assigned_payment2, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket_1, assign_time=self.today)
        # test allocate payment if payment event <= 50000
        loan = LoanFactory(id=88)
        loan.loan_status_code = 234
        loan.ever_entered_B5 = True
        loan.save()

        loan2 = LoanFactory(id=89)
        loan2.loan_status_code = 234
        loan2.ever_entered_B5 = True
        loan2.save()

        PaymentFactory(loan=loan)
        payment = loan.payment_set.first()
        payment.due_date = dpd_91_date
        payment.due_amount = 100000
        payment.payment_status_code = 324
        payment.save()
        PaymentFactory(loan=loan2)
        payment2 = loan2.payment_set.first()
        dpd_92_date = self.today.date() - timedelta(days=92)
        payment2.due_date = dpd_92_date
        payment2.due_amount = 100000
        payment2.payment_status_code = 324
        payment2.save()
        # create payment event just for payment no 1
        PaymentEventFactory(payment=payment, event_type='payment', event_payment=50000, cdate=self.today)
        # checking last contacted date >= 30
        loan3 = LoanFactory(id=90)
        loan3.loan_status_code = 234
        loan3.ever_entered_B5 = True
        loan3.save()
        PaymentFactory(loan=loan3)
        payment3 = loan3.payment_set.first()
        dpd_120_date = self.today.date() - timedelta(days=120)
        payment3.due_date = dpd_120_date
        payment3.due_amount = 100000
        payment3.payment_status_code = 324
        payment3.save()
        # create payment event for pass the first checking
        PaymentEventFactory(payment=payment3, event_type='payment', event_payment=60000, cdate=self.today)

        skiptrace = SkipTraceFactory(application=loan3.application, customer=loan3.application.customer)
        skiptrace_results_choices = SkiptraceResultChoiceFactory(name="No Answer")
        for i in range(30, 0, -1):
            cdate = self.today - timedelta(days=i)
            skiptrace_history = SkiptraceHistoryFactory(
                cdate=cdate, skiptrace=skiptrace, call_result=skiptrace_results_choices,
                agent=self.user, loan=loan3, application=loan3.application, payment=payment3
            )
            skiptrace_history.update_safely(cdate=cdate)

        # check last payment >= 60
        loan4 = LoanFactory(id=555)
        loan4.loan_status_code = 236
        loan4.ever_entered_B5 = True
        loan4.is_restructured = False
        loan4.save()
        PaymentFactory(loan=loan4)
        payment4 = loan4.payment_set.first()
        dpd_150_date = self.today.date() - timedelta(days=150)

        payment4.due_date = dpd_150_date
        payment4.due_amount = 100000
        payment4.payment_status_code = 326
        payment4.is_restructured = False
        payment4.save()
        # create payment event for pass the first checking
        last_60_days_payment = self.today.date() - timedelta(days=60)
        payment_event = PaymentEventFactory(cdate=self.today,
                                            payment=payment4, event_type='payment', event_payment=60000,
                                            event_date=last_60_days_payment)
        payment_event.update_safely(cdate=last_60_days_payment)
        mocked_redis_client.return_value.get_list.return_value = [
            payment.id, payment2.id, payment3.id, payment4.id, assigned_payment.id, assigned_payment2.id]
        mocked_sent_to_intelix.return_value = True
        mock_allocate_account_payment.return_value = True
        allocate_payments_to_collection_vendor_for_bucket_5.delay()

    @mock.patch('juloserver.collection_vendor.task.get_redis_client')
    @mock.patch('juloserver.collection_vendor.task.AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1', 1)
    def test_allocate_payment_for_bucket_5_sub_4(self, mocked_redis_client):
        loan = LoanFactory(id=444)
        loan.loan_status_code = 237
        loan.ever_entered_B5 = True
        loan.save()
        PaymentFactory(loan=loan)
        payment = loan.payment_set.first()
        mocked_redis_client.return_value.get_list.return_value = [payment.id]
        due_date = self.today.date() - timedelta(days=self.sub_bucket_4.start_dpd)
        payment.due_date = due_date
        payment.due_amount = 100000
        payment.payment_status_code = 327
        payment.save()
        allocate_payments_to_collection_vendor_for_bucket_6_3.delay()
