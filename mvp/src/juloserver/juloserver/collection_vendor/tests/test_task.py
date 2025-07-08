from __future__ import print_function
from builtins import range
from unittest import skip
from django.test import TestCase, override_settings
from mock import patch, ANY

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import AuthUserFactory, CustomerFactory, ApplicationFactory, PaymentEventFactory
from juloserver.julo.tests.factories import LoanFactory
from juloserver.julo.tests.factories import PaymentFactory
from juloserver.julo.tests.factories import StatusLookupFactory

from juloserver.collection_vendor.tests.factories import (
    AgentAssignmentFactory,
    SkipTraceFactory,
    SkiptraceResultChoiceFactory,
    SkiptraceHistoryFactory,
    CollectionVendorFactory,
)
from juloserver.collection_vendor.tests.factories import SubBucketFactory
from juloserver.collection_vendor.tests.factories import CollectionVendorAssignmentFactory
from juloserver.collection_vendor.tests.factories import CollectionVendorRatioFactory

from juloserver.collection_vendor.task import *
from juloserver.account_payment.tests.factories import AccountPaymentFactory


@skip(reason='Obsolete')
class TestAssignAgentForBucket5(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.loan = LoanFactory(id=123123)
        PaymentFactory(loan=self.loan)
        self.payment = self.loan.payment_set.first()
        self.sub_bucket = SubBucketFactory()

    def test_oldest_payment_not_found(self):
        self.loan.loan_status = StatusLookupFactory(status_code=210)
        self.loan.save()

        self.payment.loan = self.loan
        self.payment.save()
        res = assign_agent_for_bucket_5(self.user.id,self.loan.id)
        self.assertEqual(res,None)

    @patch('juloserver.collection_vendor.task.get_current_sub_bucket')
    def test_success(self, mock_get_current_sub_bucket):
        self.loan.loan_status = StatusLookupFactory(status_code=230)
        self.loan.save()
        self.payment.payment_number = 0
        self.payment.payment_status = StatusLookupFactory(status_code=320)
        self.payment.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=1)
        self.payment.save()
        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = assign_agent_for_bucket_5(self.user.id, self.loan.id)
        self.assertTrue(AgentAssignment.objects.get(agent=self.user,payment=self.payment))


@skip(reason='Obsolete')
class TestAssignAgentForJ1Bucket5(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.account_payment = AccountPaymentFactory()
        self.sub_bucket = SubBucketFactory()

    def test_account_payment_not_found(self):
        SubBucketFactory(id=5)
        res = assign_agent_for_julo_one_bucket_5(self.user.id, 99999999)
        self.assertEqual(res, None)

    @patch('juloserver.collection_vendor.task.get_current_sub_bucket')
    def test_success(self, mock_get_current_sub_bucket):
        self.account_payment.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=1)
        self.account_payment.save()
        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = assign_agent_for_julo_one_bucket_5(self.user.id, self.account_payment.id)
        self.assertTrue(AgentAssignment.objects.get(
            agent=self.user, account_payment=self.account_payment))


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestProcessUnassignmentWhenPaid(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.loan = LoanFactory(ever_entered_B5=True)
        PaymentFactory(loan=self.loan)
        self.payment = self.loan.payment_set.first()
        self.sub_bucket = SubBucketFactory(bucket=5)
        self.agent_assignment = AgentAssignmentFactory()
        self.coll_vendor_assignment = CollectionVendorAssignmentFactory()

    def test_payment_not_found_or_not_bucket_number_special_case_5(self):
        self.payment.loan = self.loan
        self.payment.save()
        if not SubBucket.objects.filter(id=5).last():
            SubBucketFactory(id=5)
        res = process_unassignment_when_paid(self.payment.id)
        self.assertEqual(res,None)

    def test_not_agent_or_vendor_assignment(self):
        if not SubBucket.objects.filter(id=5).last():
            SubBucketFactory(id=5)
        self.loan.ever_entered_B5 = True
        self.loan.save()

        self.payment.loan = self.loan
        self.payment.save()
        res = process_unassignment_when_paid(self.payment.id)
        self.assertEqual(res,None)

    def test_success(self):
        if not SubBucket.objects.filter(id=5).last():
            SubBucketFactory(id=5)
        self.loan.ever_entered_B5 = True
        self.loan.save()

        self.payment.loan = self.loan
        self.payment.save()

        # agent assignment
        self.agent_assignment.payment = self.payment
        self.agent_assignment.is_active_assignment = True
        self.agent_assignment.is_transferred_to_other = False
        self.agent_assignment.assign_time = timezone.localtime(timezone.now())
        self.agent_assignment.save()
        process_unassignment_when_paid(self.payment.id)
        self.agent_assignment.refresh_from_db()
        self.assertEqual(self.agent_assignment.is_active_assignment, False)

        # collection vendor assignment
        self.coll_vendor_assignment.payment = self.payment
        self.coll_vendor_assignment.is_active_assignment = True
        self.coll_vendor_assignment.is_transferred_to_other = False
        self.coll_vendor_assignment.assign_time = timezone.localtime(timezone.now())
        self.coll_vendor_assignment.save()
        process_unassignment_when_paid(self.payment.id)
        self.coll_vendor_assignment.refresh_from_db()


@skip(reason='Obsolete')
class TestSetSettledStatusForBucket5Sub4And5(TestCase):
    def setUp(self):
        self.sub_bucket1 = SubBucketFactory(id=4)
        self.sub_bucket2 = SubBucketFactory(id=5)

    def test_success(self):
        set_settled_status_for_bucket_6_sub_3_and_4()


@skip(reason='Obsolete')
class TestSetWarehouseStatusForBucket5Sub4And5(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        PaymentFactory(loan=self.loan)
        self.payment = self.loan.payment_set.first()
        self.sub_bucket = SubBucketFactory(id=5)

    @patch('juloserver.collection_vendor.task.calculate_remaining_principal')
    @patch.object(Payment.objects,'not_paid_active')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    @patch('juloserver.collection_vendor.task.get_oldest_payment_ids_loans')
    def test_success(self, mock_get_oldest_payment_ids_loans, mock_get_redis_client,
                     mock_get_subbucket_5, mock_calculate_remaining_principal):
        self.payment.loan = self.loan
        self.payment.account_payment_id = None
        self.payment.save()
        mock_get_oldest_payment_ids_loans.return_value = self.payment.id
        mock_get_subbucket_5.return_value.filter.return_value.get_sub_bucket_5_by_range.return_value.filter.return_value.exclude.return_value = [self.payment]
        mock_calculate_remaining_principal.return_value = 1
        # cached_oldest_payment_ids
        mock_get_redis_client.return_value.get_list.return_value = [self.payment.id]
        set_is_warehouse_status_for_bucket_6_sub_4()
        # not cached_oldest_payment_ids
        mock_get_redis_client.return_value.get_list.return_value = []
        set_is_warehouse_status_for_bucket_6_sub_4()
        mock_get_redis_client.return_value.set_list.assert_called_with('minisquad:oldest_payment_ids', self.payment.id, ANY)
        # loan in warehouse 1
        mock_calculate_remaining_principal.return_value = 2
        set_is_warehouse_status_for_bucket_6_sub_4()
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.is_warehouse_1,True)
        self.assertEqual(self.loan.is_warehouse_2,False)
        # loan in warehouse 2
        mock_calculate_remaining_principal.return_value = -2
        set_is_warehouse_status_for_bucket_6_sub_4()
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.is_warehouse_1,False)
        self.assertEqual(self.loan.is_warehouse_2,True)


@skip(reason='Obsolete')
class TestUpdateAgentAssignmentForExpiredAccount(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(id=1000012, application=self.application)
        PaymentFactory(loan=self.loan)
        self.payment = self.loan.payment_set.first()
        self.payment.id = 1122333
        self.payment.loan = self.loan
        self.payment.save()
        self.agent_assignment = AgentAssignmentFactory(
            payment=self.payment)

    def test_success(self):
        self.agent_assignment.is_active_assignment = True
        self.agent_assignment.is_transferred_to_other = False
        self.agent_assignment.assign_time = '1900-12-30'
        self.agent_assignment.payment = self.payment
        self.agent_assignment.save()
        self.agent_assignment.save()
        if not SubBucket.objects.filter(id=1).last():
            SubBucketFactory(id=1)
        update_agent_assigment_for_expired_account()
        self.agent_assignment.refresh_from_db()
        self.assertEqual(self.agent_assignment.is_active_assignment, False)


@skip(reason='Obsolete')
class TestCheckAssignment54(TestCase):
    def setUp(self):
        self.coll_vendor_ratio = CollectionVendorRatioFactory()

    @patch('juloserver.collection_vendor.task.check_vendor_assignment')
    def test_success(self, mock_check_vendor_assignment):
        self.coll_vendor_ratio.vendor_types = 'Final'
        self.coll_vendor_ratio.save()
        check_assignment_bucket_6_3()
        mock_check_vendor_assignment.assert_called_with(self.coll_vendor_ratio)


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCheckAssignment53(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        PaymentFactory(loan=self.loan)
        self.payment = self.loan.payment_set.first()
        self.sub_bucket = SubBucketFactory(id=3)
        self.coll_vendor_assignment = CollectionVendorAssignmentFactory()

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    @patch('juloserver.collection_vendor.task.get_expired_vendor_assignment')
    def test_check_assignment_bucket_6_2_additional_case(
        self,
        mock_get_expired_vendor_assignment,
        mock_assign_payments_to_vendor):
        # coll vendor assignment not found
        mock_get_expired_vendor_assignment.return_value = None
        check_assignment_bucket_6_2()
        # coll vendor assignment found
        self.sub_bucket.bucket = 5
        self.sub_bucket.sub_bucket = None
        self.sub_bucket.save()
        self.sub_bucket.refresh_from_db()
        self.coll_vendor_assignment.is_extension = True
        self.coll_vendor_assignment.sub_bucket_assign_time = self.sub_bucket
        self.coll_vendor_assignment.save()
        mock_get_expired_vendor_assignment.return_value = CollectionVendorAssignment.objects.filter(
            id=self.coll_vendor_assignment.id
        )
        check_assignment_bucket_6_2()
        self.coll_vendor_assignment.refresh_from_db()
        self.assertEqual(self.coll_vendor_assignment.is_active_assignment,True)


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCheckAssignment52(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.sub_bucket = SubBucketFactory(id=2)
        self.coll_vendor_assignment = CollectionVendorAssignmentFactory()

    @patch('juloserver.collection_vendor.task.get_expired_vendor_assignment')
    def test_check_assignment_bucket_6_1_additional_case(self, mock_get_expired_vendor_assignment):
        # coll vendor assignment not found
        mock_get_expired_vendor_assignment.return_value = None
        check_assignment_bucket_6_1()
        # coll vendor assignment found
        self.sub_bucket.bucket = 5
        self.sub_bucket.sub_bucket = None
        self.sub_bucket.save()
        self.sub_bucket.refresh_from_db()
        self.coll_vendor_assignment.is_extension = True
        self.coll_vendor_assignment.sub_bucket_assign_time = self.sub_bucket
        self.coll_vendor_assignment.save()
        mock_get_expired_vendor_assignment.return_value = CollectionVendorAssignment.objects.filter(
            id=self.coll_vendor_assignment.id
        )
        check_assignment_bucket_6_1()
        self.coll_vendor_assignment.refresh_from_db()
        self.assertEqual(self.coll_vendor_assignment.is_active_assignment,True)


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAllocatePaymentToCollVendorBucket51lt91(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.loan.loan_status_id = 220
        self.loan.save()
        self.payment1 = PaymentFactory(payment_number=123)
        self.payment1.loan = self.loan
        self.payment1.save()
        self.payment2 = PaymentFactory(payment_number=124)
        self.payment2.loan = self.loan
        self.payment2.save()
        self.sub_bucket = SubBucketFactory(id=1)

    @patch.object(Payment.objects,'not_paid_active')
    @patch('juloserver.collection_vendor.task.get_oldest_payment_ids_loans')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    def test_allocate_payment_to_collvendor_bucket_51_lt_91_additional_case(
            self, mock_get_redis_client, mock_get_oldest_payment_ids_loans, mock_get_subbucket_5_1):
        # not paid payment status 329
        mock_get_redis_client.return_value.get_list.return_value = None
        mock_get_oldest_payment_ids_loans.return_value = [self.payment2.id]
        self.payment1.payment_status = StatusLookupFactory(status_code=329)
        self.payment1.paid_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment1.save()

        self.payment2.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment2.save()
        mock_get_subbucket_5_1.return_value.get_sub_bucket_5_1_special_case.return_value.filter\
            .return_value.exclude.return_value.exclude.return_value.exclude.return_value = [self.payment2]
        allocate_payments_to_collection_vendor_for_bucket_5_less_then_91([1])
        mock_get_redis_client.return_value.set_list.assert_called_with('minisquad:oldest_payment_ids',[self.payment2.id],ANY)
        # not paid payment status paid on time
        self.payment1.payment_status = StatusLookupFactory(status_code=330)
        self.payment1.save()
        mock_get_subbucket_5_1.return_value.get_sub_bucket_5_1_special_case.return_value.filter \
            .return_value.exclude.return_value.exclude.return_value.exclude.return_value = [self.payment2]
        allocate_payments_to_collection_vendor_for_bucket_5_less_then_91([1])
        mock_get_redis_client.return_value.set_list.assert_called_with(
            'minisquad:oldest_payment_ids', [self.payment2.id], ANY)
        # last_payment_should_be_check_on
        self.payment1.paid_date = timezone.localtime(timezone.now()).date() - timedelta(days=61)
        self.payment1.save()

        self.payment2.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=61)
        self.payment2.save()
        allocate_payments_to_collection_vendor_for_bucket_5_less_then_91([1])
        mock_get_redis_client.return_value.set_list.assert_called_with(
            'minisquad:oldest_payment_ids', [self.payment2.id], ANY)
        # cached_oldest_payment_ids not none
        mock_get_redis_client.return_value.get_list.return_value = [self.payment2.id]
        allocate_payments_to_collection_vendor_for_bucket_5_less_then_91([1])
        mock_get_redis_client.return_value.set_list.assert_called_with(
            'minisquad:oldest_payment_ids', [self.payment2.id], ANY)


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS=True)
class TestAllocatePaymentToCollectionVendorForBucket51(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment1 = PaymentFactory(payment_number=123)
        self.payment2 = PaymentFactory(payment_number=124)
        self.sub_bucket = SubBucketFactory(id=1)

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    @patch.object(Payment.objects,'not_paid_active')
    @patch('juloserver.collection_vendor.task.get_oldest_payment_ids_loans')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    def test_allocate_payment_to_collvendor_bucket_51_additional_case(
            self,
            mock_get_redis_client,
            mock_get_oldest_payment_ids_loans,
            mock_get_subbucket_5_1,
            mock_assign_payments_to_vendor):
        mock_get_redis_client.return_value.get_list.return_value = None
        mock_get_oldest_payment_ids_loans.return_value = [self.payment2.id]
        self.payment1.paid_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment1.save()

        self.payment2.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment2.save()
        mock_get_subbucket_5_1.return_value.get_sub_bucket_5_1_special_case.return_value.filter\
            .return_value.exclude.return_value.exclude.return_value.exclude.return_value = [self.payment2]
        allocate_payments_to_collection_vendor_for_bucket_5()
        mock_get_redis_client.return_value.set_list.assert_called_with('minisquad:oldest_payment_ids',[self.payment2.id],ANY)


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAllocatePaymentToCollectionVendorForBucket52(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.loan = LoanFactory()
        self.payment1 = PaymentFactory(payment_number=123,loan=self.loan)
        self.payment2 = PaymentFactory(payment_number=124,loan=self.loan)
        self.sub_bucket = SubBucketFactory(id=2)
        self.agent_assignment1 = AgentAssignmentFactory(sub_bucket_assign_time=self.sub_bucket)
        self.agent_assignment2 = AgentAssignmentFactory(sub_bucket_assign_time=self.sub_bucket)

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    @patch.object(Payment.objects,'not_paid_active')
    @patch('juloserver.collection_vendor.task.get_oldest_payment_ids_loans')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    def test_allocate_payment_to_collvendor_bucket_52_additional_case(
            self,
            mock_get_redis_client,
            mock_get_oldest_payment_ids_loans,
            mock_get_subbucket_5_2,
            mock_assign_payments_to_vendor):
        mock_get_redis_client.return_value.get_list.return_value = None
        mock_get_oldest_payment_ids_loans.return_value = [self.payment2.id]
        self.payment1.paid_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment1.save()

        self.payment2.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment2.save()
        mock_get_subbucket_5_2.return_value.get_sub_bucket_5_by_range.return_value.exclude.return_value.exclude.return_value = Payment.objects.filter(payment_number=124)
        allocate_payments_to_collection_vendor_for_bucket_6_1()
        mock_get_redis_client.return_value.set_list.assert_called_with('minisquad:oldest_payment_ids',[self.payment2.id],ANY)

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    @patch('juloserver.collection_vendor.task.allocated_to_vendor_for_payment_less_then_fifty_thousand')
    @patch('juloserver.collection_vendor.task.AgentAssignmentConstant')
    @patch.object(Payment.objects, 'not_paid_active')
    @patch('juloserver.collection_vendor.task.get_oldest_payment_ids_loans')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    def test_cached_oldest_payment_ids_not_none(
        self,
        mock_get_redis_client,
        mock_get_oldest_payment_ids_loans,
        mock_get_subbucket_5_2,
        mock_AgentAssignmentConstant,
        mock_allocated_to_vendor_for_payment_lt_5000,
        mock_assign_payments_to_vendor):
        mock_get_oldest_payment_ids_loans.return_value = [self.payment2.id]
        self.payment1.paid_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment1.save()

        self.payment2.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment2.save()

        mock_get_redis_client.return_value.get_list.return_value = [self.payment2.id]
        self.user.payment = self.payment2
        self.user.save()

        self.agent_assignment1.agent = self.user
        self.agent_assignment1.is_active_assignment = True
        self.agent_assignment1.is_transferred_to_other = False
        self.agent_assignment1.payment = self.payment2
        self.agent_assignment1.sub_bucket_assign_time_id = self.sub_bucket.id
        self.agent_assignment1.save()

        self.agent_assignment2.agent = self.user
        self.agent_assignment2.is_active_assignment = True
        self.agent_assignment2.is_transferred_to_other = False
        self.agent_assignment2.payment = self.payment2
        self.agent_assignment2.sub_bucket_assign_time_id = self.sub_bucket.id
        self.agent_assignment2.save()

        mock_get_subbucket_5_2.return_value.get_sub_bucket_5_by_range.return_value.exclude.return_value.exclude.return_value = Payment.objects.filter(
            payment_number=124)
        mock_AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2 = 1
        mock_allocated_to_vendor_for_payment_lt_5000.return_value = [self.payment2.id]
        allocate_payments_to_collection_vendor_for_bucket_6_1()


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAllocatePaymentToCollectionVendorForBucket53(TestCase):

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    def setUp(self, mock_assign_payments_to_vendor):
        self.user = AuthUserFactory()
        self.loan = LoanFactory()
        self.payment1 = PaymentFactory(payment_number=123)
        self.payment2 = PaymentFactory(payment_number=124)
        self.sub_bucket = SubBucketFactory(id=3)
        self.agent_assignment1 = AgentAssignmentFactory(sub_bucket_assign_time=self.sub_bucket)
        self.agent_assignment2 = AgentAssignmentFactory(sub_bucket_assign_time=self.sub_bucket)

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    @patch.object(Payment.objects,'not_paid_active')
    @patch('juloserver.collection_vendor.task.get_oldest_payment_ids_loans')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    def test_allocate_payment_to_collvendor_bucket_51_additional_case(
            self, mock_get_redis_client,
            mock_get_oldest_payment_ids_loans,
            mock_get_subbucket_5_3,
            mock_assign_payments_to_vendor):
        mock_get_redis_client.return_value.get_list.return_value = None
        mock_get_oldest_payment_ids_loans.return_value = [self.payment2.id]
        self.payment1.paid_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment1.save()

        self.payment2.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment2.save()
        mock_get_subbucket_5_3.return_value.get_sub_bucket_5_by_range.return_value.filter\
            .return_value.exclude.return_value.exclude.return_value.exclude.return_value = [self.payment2]
        allocate_payments_to_collection_vendor_for_bucket_6_2()
        mock_get_redis_client.return_value.set_list.assert_called_with('minisquad:oldest_payment_ids',[self.payment2.id],ANY)

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    @patch('juloserver.collection_vendor.task.allocated_oldest_payment_without_active_ptp')
    @patch('juloserver.collection_vendor.task.AgentAssignmentConstant')
    @patch.object(Payment.objects, 'not_paid_active')
    @patch('juloserver.collection_vendor.task.get_oldest_payment_ids_loans')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    def test_cached_oldest_payment_ids_not_none(self, mock_get_redis_client,
                                                mock_get_oldest_payment_ids_loans,
                                                mock_get_subbucket_5_3,
                                                mock_AgentAssignmentConstant,
                                                mock_allocated_oldest_payment_without_active_ptp,
                                                mock_assign_payments_to_vendor):
        mock_get_oldest_payment_ids_loans.return_value = [self.payment2.id]
        self.payment1.paid_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment1.save()

        self.payment2.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment2.save()

        mock_get_redis_client.return_value.get_list.return_value = [self.payment2.id]
        self.user.payment = self.payment2
        self.user.save()

        self.agent_assignment1.agent = self.user
        self.agent_assignment1.is_active_assignment = True
        self.agent_assignment1.is_transferred_to_other = False
        self.agent_assignment1.payment = self.payment2
        self.agent_assignment1.sub_bucket_assign_time_id = self.sub_bucket.id
        self.agent_assignment1.save()

        self.agent_assignment2.agent = self.user
        self.agent_assignment2.is_active_assignment = True
        self.agent_assignment2.is_transferred_to_other = False
        self.agent_assignment2.payment = self.payment2
        self.agent_assignment2.sub_bucket_assign_time_id = self.sub_bucket.id
        self.agent_assignment2.save()

        mock_get_subbucket_5_3.return_value.get_sub_bucket_5_by_range.return_value.exclude.return_value.exclude.return_value = Payment.objects.filter(
            payment_number=124)
        mock_AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_3 = 1
        mock_allocated_oldest_payment_without_active_ptp.return_value = [self.payment2.id]
        res = allocate_payments_to_collection_vendor_for_bucket_6_2()
        print(res)


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAllocatePaymentToCollectionVendorForBucket54(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment1 = PaymentFactory(payment_number=123)
        self.payment2 = PaymentFactory(payment_number=124)
        self.sub_bucket = SubBucketFactory(id=4)

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    @patch.object(Payment.objects,'not_paid_active')
    @patch('juloserver.collection_vendor.task.get_oldest_payment_ids_loans')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    def test_allocate_payment_to_collvendor_bucket_54_additional_case(
            self,
            mock_get_redis_client,
            mock_get_oldest_payment_ids_loans,
            mock_get_subbucket_5_4,
            mock_assign_payments_to_vendor):
        mock_get_redis_client.return_value.get_list.return_value = None
        mock_get_oldest_payment_ids_loans.return_value = [self.payment2.id]
        self.payment1.paid_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment1.save()

        self.payment2.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=31)
        self.payment2.save()
        mock_get_subbucket_5_4.return_value.get_sub_bucket_5_by_range.return_value.filter\
            .return_value.exclude.return_value.exclude.return_value.exclude.return_value = [self.payment2]
        allocate_payments_to_collection_vendor_for_bucket_6_3()
        mock_get_redis_client.return_value.set_list.assert_called_with('minisquad:oldest_payment_ids',[self.payment2.id],ANY)


@skip(reason='Obsolete')
class TestAssignPaymentToVendor(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = PaymentFactory(loan=self.loan)
        self.coll_vendor_ratio = CollectionVendorRatioFactory(vendor_types='final')
        self.coll_vendor_ratio1 = CollectionVendorRatioFactory(vendor_types='final')
        self.sub_bucket = SubBucketFactory(id=5)

    @patch('juloserver.collection_vendor.task.get_current_sub_bucket')
    def test_case_1(self, mock_get_current_sub_bucket):
        self.coll_vendor_ratio.account_distribution_ratio = 2
        self.coll_vendor_ratio.save()
        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = assign_payments_to_vendor([{'payment_id': self.payment.id,
                                          'type': 'agent_to_vendor', 'reason': 'unittests'}], 'final')
        print(res)


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestProcessUnassignmentWhenPaidForJ1(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.account = AccountFactory(
            ever_entered_B5=True
        )
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account
        )
        AccountPaymentFactory(
            account=self.account)
        self.account_payment = self.account.accountpayment_set.order_by('due_date').first()
        self.account_payment.status_id = PaymentStatusCodes.PAID_ON_TIME
        self.account_payment.paid_date = timezone.localtime(timezone.now()).date()
        self.account_payment.save()
        self.loan = LoanFactory(
            account=self.account, application=None,
            ever_entered_B5=True
        )
        PaymentFactory(loan=self.loan, account_payment=self.account_payment)
        self.payment = self.loan.payment_set.first()
        self.sub_bucket = SubBucketFactory(bucket=5)
        self.agent_assignment = AgentAssignmentFactory(
            payment=None, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket,
            account_payment=self.account_payment,
            is_active_assignment=True
        )

    def test_success(self):
        if not SubBucket.objects.filter(id=5).last():
            SubBucketFactory(id=5)
        process_unassignment_when_paid_for_j1(self.account_payment.id)
        self.agent_assignment.refresh_from_db()
        assert self.agent_assignment.is_active_assignment is False


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS=True)
class TestAllocateAccountPaymentToCollectionVendorForBucket5(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.today = timezone.localtime(timezone.now()).date()
        self.sub_bucket = SubBucketFactory(bucket=5, id=1)

    @patch('juloserver.collection_vendor.task.get_eligible_account_payment_for_dialer_and_vendor_qs')
    @patch.object(AccountPayment.objects, 'not_paid_active')
    @patch('juloserver.minisquad.tasks2.intelix_task.upload_julo_b5_data_to_intelix')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    @patch('juloserver.collection_vendor.task.AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_1', 1)
    def test_allocate_account_payment_for_bucket_5(
            self, mocked_redis_client, mocked_sent_to_intelix, mock_account_payment_filter, mock_eligible_account_payment):
        account_1 = AccountFactory(
            ever_entered_B5=True
        )
        account_2 = AccountFactory(
            ever_entered_B5=True
        )
        loan_assigned = LoanFactory(
            account=account_1, ever_entered_B5=True
        )
        loan_assigned.loan_status_code = 234
        loan_assigned.ever_entered_B5 = True
        loan_assigned.save()
        loan_assigned_2 = LoanFactory(
            account=account_2, ever_entered_B5=True
        )
        loan_assigned_2.loan_status_code = 234
        loan_assigned_2.ever_entered_B5 = True
        loan_assigned_2.save()
        AccountPaymentFactory(
            account=account_1)
        AccountPaymentFactory(
            account=account_2)
        dpd_91_date = self.today - timedelta(days=self.sub_bucket.start_dpd)
        account_payment_1 = account_1.accountpayment_set.order_by('due_date').first()
        account_payment_1.due_date = dpd_91_date
        account_payment_1.due_amount = 100000
        account_payment_1.payment_status_code = 324
        account_payment_1.save()

        account_payment_2 = account_2.accountpayment_set.order_by('due_date').first()
        account_payment_2.due_date = dpd_91_date
        account_payment_2.due_amount = 100000
        account_payment_2.payment_status_code = 324
        account_payment_2.save()

        PaymentFactory(loan=loan_assigned)
        PaymentFactory(loan=loan_assigned_2)
        assigned_payment = loan_assigned.payment_set.first()
        assigned_payment.account_payment = account_payment_1
        assigned_payment.due_date = dpd_91_date
        assigned_payment.due_amount = 100000
        assigned_payment.payment_status_code = 324
        assigned_payment.save()

        assigned_payment2 = loan_assigned_2.payment_set.first()
        assigned_payment2.account_payment = account_payment_2
        assigned_payment2.due_date = dpd_91_date
        assigned_payment2.due_amount = 100000
        assigned_payment2.payment_status_code = 324
        assigned_payment2.save()

        yesterday = self.today - timedelta(days=1)
        AgentAssignmentFactory(
            account_payment=account_payment_1, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket, assign_time=yesterday)

        AgentAssignmentFactory(
            account_payment=account_payment_2, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket, assign_time=self.today)

        # test allocate payment if payment event <= 50000
        account_3 = AccountFactory(
            ever_entered_B5=True
        )
        loan_3 = LoanFactory(
            account=account_3, ever_entered_B5=True
        )
        loan_3.loan_status_code = 234
        loan_3.ever_entered_B5 = True
        loan_3.save()
        AccountPaymentFactory(
            account=account_3)
        dpd_91_date = self.today - timedelta(days=self.sub_bucket.start_dpd)
        account_payment_3 = account_3.accountpayment_set.order_by('due_date').first()
        account_payment_3.due_date = dpd_91_date
        account_payment_3.due_amount = 100000
        account_payment_3.payment_status_code = 324
        account_payment_3.save()

        PaymentFactory(loan=loan_3)
        payment_3 = loan_3.payment_set.first()
        payment_3.account_payment = account_payment_3
        payment_3.due_date = dpd_91_date
        payment_3.due_amount = 100000
        payment_3.payment_status_code = 324
        payment_3.save()
        # create payment event just for payment no 1
        PaymentEventFactory(
            payment=payment_3, event_type='payment', event_payment=50000, cdate=self.today)
        # checking last contacted date >= 30
        account_4 = AccountFactory(
            ever_entered_B5=True
        )
        loan_4 = LoanFactory(
            account=account_4, ever_entered_B5=True
        )
        loan_4.loan_status_code = 234
        loan_4.ever_entered_B5 = True
        loan_4.save()
        AccountPaymentFactory(
            account=account_4)
        PaymentFactory(loan=loan_4)
        dpd_120_date = self.today - timedelta(days=120)
        account_payment_4 = account_4.accountpayment_set.order_by('due_date').first()
        account_payment_4.due_date = dpd_120_date
        account_payment_4.due_amount = 100000
        account_payment_4.payment_status_code = 324
        account_payment_4.save()
        PaymentFactory(loan=loan_3)
        payment_4 = loan_3.payment_set.first()
        payment_4.account_payment = account_payment_4
        payment_4.due_date = dpd_120_date
        payment_4.due_amount = 100000
        payment_4.payment_status_code = 324
        payment_4.save()
        # create payment event for pass the first checking
        PaymentEventFactory(
            payment=payment_4, event_type='payment', event_payment=60000, cdate=self.today)

        skiptrace = SkipTraceFactory(
            application=None, customer=account_4.customer)
        skiptrace_results_choices = SkiptraceResultChoiceFactory(name="No Answer")
        for i in range(30, 0, -1):
            cdate = self.today - timedelta(days=i)
            skiptrace_history = SkiptraceHistoryFactory(
                cdate=cdate, skiptrace=skiptrace, call_result=skiptrace_results_choices,
                agent=self.user, loan=None, application=None, payment=None,
                account=account_4, account_payment=account_payment_4
            )
            skiptrace_history.update_safely(cdate=cdate)

        # check last payment >= 60
        account_5 = AccountFactory(
            ever_entered_B5=True
        )
        loan_5 = LoanFactory(
            account=account_4, ever_entered_B5=True
        )
        loan_5.loan_status_code = 234
        loan_5.ever_entered_B5 = True
        loan_5.save()
        AccountPaymentFactory(
            account=account_5)
        PaymentFactory(loan=loan_5)
        dpd_150_date = self.today - timedelta(days=150)
        account_payment_5 = account_5.accountpayment_set.order_by('due_date').first()
        account_payment_5.due_date = dpd_150_date
        account_payment_5.due_amount = 100000
        account_payment_5.payment_status_code = 324
        account_payment_5.save()
        payment_5 = loan_5.payment_set.first()
        payment_5.account_payment = account_payment_5
        payment_5.due_date = dpd_150_date
        payment_5.due_amount = 100000
        payment_5.payment_status_code = 324
        payment_5.save()
        # create payment event for pass the first checking
        last_60_days_payment = self.today - timedelta(days=60)
        payment_event = PaymentEventFactory(cdate=self.today,
                                            payment=payment_5, event_type='payment', event_payment=60000,
                                            event_date=last_60_days_payment)
        payment_event.update_safely(cdate=last_60_days_payment)
        mocked_account_payment_ids = [
            account_payment_1.id,
            account_payment_2.id, account_payment_3.id, account_payment_4.id,
            account_payment_5.id
        ]
        mocked_redis_client.return_value.get_list.return_value = mocked_account_payment_ids
        mocked_sent_to_intelix.return_value = True
        mock_eligible_account_payment.return_value = AccountPayment.objects.none()
        mock_account_payment_filter.return_value.get_bucket_5_by_range.return_value.exclude.return_value =\
            AccountPayment.objects.filter(id__in=mocked_account_payment_ids)
        if not SubBucket.objects.filter(pk=1).last():
            self.sub_bucket = SubBucketFactory(bucket=5, id=1)

        allocate_bucket_5_account_payments_to_collection_vendor()


@skip(reason='Obsolete')
@override_settings(SUSPEND_SIGNALS=True)
class TestAllocateAccountPaymentToCollectionVendorForBucket6(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.today = timezone.localtime(timezone.now()).date()
        self.sub_bucket_6_1 = SubBucketFactory(
            id=2, bucket=6, sub_bucket=1, start_dpd=181, end_dpd=270)
        self.sub_bucket_6_2 = SubBucketFactory(
            id=3, bucket=6, sub_bucket=2, start_dpd=271, end_dpd=360)

    @patch('juloserver.collection_vendor.task.get_eligible_account_payment_for_dialer_and_vendor_qs')
    @patch.object(AccountPayment.objects, 'not_paid_active')
    @patch('juloserver.minisquad.tasks2.intelix_task.upload_julo_b5_data_to_intelix')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    @patch('juloserver.collection_vendor.task.AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2', 1)
    def test_allocate_account_payment_for_bucket_6_1(
            self, mocked_redis_client, mocked_sent_to_intelix, mock_account_payment_filter, mock_eligible_account_payment):
        account_1 = AccountFactory(
            ever_entered_B5=True
        )
        account_2 = AccountFactory(
            ever_entered_B5=True
        )
        loan_assigned = LoanFactory(
            account=account_1, ever_entered_B5=True
        )
        loan_assigned.loan_status_code = 234
        loan_assigned.ever_entered_B5 = True
        loan_assigned.save()
        loan_assigned_2 = LoanFactory(
            account=account_2, ever_entered_B5=True
        )
        loan_assigned_2.loan_status_code = 234
        loan_assigned_2.ever_entered_B5 = True
        loan_assigned_2.save()
        AccountPaymentFactory(
            account=account_1)
        AccountPaymentFactory(
            account=account_2)
        dpd_91_date = self.today - timedelta(days=self.sub_bucket_6_1.start_dpd)
        account_payment_1 = account_1.accountpayment_set.order_by('due_date').first()
        account_payment_1.due_date = dpd_91_date
        account_payment_1.due_amount = 100000
        account_payment_1.payment_status_code = 324
        account_payment_1.save()

        account_payment_2 = account_2.accountpayment_set.order_by('due_date').first()
        account_payment_2.due_date = dpd_91_date
        account_payment_2.due_amount = 100000
        account_payment_2.payment_status_code = 324
        account_payment_2.save()

        PaymentFactory(loan=loan_assigned)
        PaymentFactory(loan=loan_assigned_2)
        assigned_payment = loan_assigned.payment_set.first()
        assigned_payment.account_payment = account_payment_1
        assigned_payment.due_date = dpd_91_date
        assigned_payment.due_amount = 100000
        assigned_payment.payment_status_code = 324
        assigned_payment.save()

        assigned_payment2 = loan_assigned_2.payment_set.first()
        assigned_payment2.account_payment = account_payment_2
        assigned_payment2.due_date = dpd_91_date
        assigned_payment2.due_amount = 100000
        assigned_payment2.payment_status_code = 324
        assigned_payment2.save()

        yesterday = self.today - timedelta(days=1)
        AgentAssignmentFactory(
            account_payment=account_payment_1, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket_6_1, assign_time=yesterday)

        AgentAssignmentFactory(
            account_payment=account_payment_2, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket_6_1, assign_time=self.today)

        # test allocate payment if payment event <= 50000
        account_3 = AccountFactory(
            ever_entered_B5=True
        )
        loan_3 = LoanFactory(
            account=account_3, ever_entered_B5=True
        )
        loan_3.loan_status_code = 234
        loan_3.ever_entered_B5 = True
        loan_3.save()
        AccountPaymentFactory(
            account=account_3)
        dpd_91_date = self.today - timedelta(days=self.sub_bucket_6_1.start_dpd)
        account_payment_3 = account_3.accountpayment_set.order_by('due_date').first()
        account_payment_3.due_date = dpd_91_date
        account_payment_3.due_amount = 100000
        account_payment_3.payment_status_code = 324
        account_payment_3.save()

        PaymentFactory(loan=loan_3)
        payment_3 = loan_3.payment_set.first()
        payment_3.account_payment = account_payment_3
        payment_3.due_date = dpd_91_date
        payment_3.due_amount = 100000
        payment_3.payment_status_code = 324
        payment_3.save()
        # create payment event just for payment no 1
        PaymentEventFactory(
            payment=payment_3, event_type='payment', event_payment=50000, cdate=self.today)
        # checking last contacted date >= 30
        account_4 = AccountFactory(
            ever_entered_B5=True
        )
        loan_4 = LoanFactory(
            account=account_4, ever_entered_B5=True
        )
        loan_4.loan_status_code = 234
        loan_4.ever_entered_B5 = True
        loan_4.save()
        AccountPaymentFactory(
            account=account_4)
        PaymentFactory(loan=loan_4)
        dpd_210_date = self.today - timedelta(days=210)
        account_payment_4 = account_4.accountpayment_set.order_by('due_date').first()
        account_payment_4.due_date = dpd_210_date
        account_payment_4.due_amount = 100000
        account_payment_4.payment_status_code = 324
        account_payment_4.save()
        PaymentFactory(loan=loan_3)
        payment_4 = loan_3.payment_set.first()
        payment_4.account_payment = account_payment_4
        payment_4.due_date = dpd_210_date
        payment_4.due_amount = 100000
        payment_4.payment_status_code = 324
        payment_4.save()
        # create payment event for pass the first checking
        PaymentEventFactory(
            payment=payment_4, event_type='payment', event_payment=60000, cdate=self.today)

        skiptrace = SkipTraceFactory(
            application=None, customer=account_4.customer)
        skiptrace_results_choices = SkiptraceResultChoiceFactory(name="No Answer")
        for i in range(30, 0, -1):
            cdate = self.today - timedelta(days=i)
            skiptrace_history = SkiptraceHistoryFactory(
                cdate=cdate, skiptrace=skiptrace, call_result=skiptrace_results_choices,
                agent=self.user, loan=None, application=None, payment=None,
                account=account_4, account_payment=account_payment_4
            )
            skiptrace_history.update_safely(cdate=cdate)

        # check last payment >= 60
        account_5 = AccountFactory(
            ever_entered_B5=True
        )
        loan_5 = LoanFactory(
            account=account_4, ever_entered_B5=True
        )
        loan_5.loan_status_code = 234
        loan_5.ever_entered_B5 = True
        loan_5.save()
        AccountPaymentFactory(
            account=account_5)
        PaymentFactory(loan=loan_5)
        dpd_240_date = self.today - timedelta(days=240)
        account_payment_5 = account_5.accountpayment_set.order_by('due_date').first()
        account_payment_5.due_date = dpd_240_date
        account_payment_5.due_amount = 100000
        account_payment_5.payment_status_code = 324
        account_payment_5.save()
        payment_5 = loan_5.payment_set.first()
        payment_5.account_payment = account_payment_5
        payment_5.due_date = dpd_240_date
        payment_5.due_amount = 100000
        payment_5.payment_status_code = 324
        payment_5.save()
        # create payment event for pass the first checking
        last_60_days_payment = self.today - timedelta(days=60)
        payment_event = PaymentEventFactory(cdate=self.today,
                                            payment=payment_5, event_type='payment', event_payment=60000,
                                            event_date=last_60_days_payment)
        payment_event.update_safely(cdate=last_60_days_payment)
        mocked_account_payment_ids = [
            account_payment_1.id,
            account_payment_2.id, account_payment_3.id, account_payment_4.id,
            account_payment_5.id
        ]
        mocked_redis_client.return_value.get_list.return_value = mocked_account_payment_ids
        mocked_sent_to_intelix.return_value = True
        mock_eligible_account_payment.return_value = AccountPayment.objects.none()
        mock_account_payment_filter.return_value.get_bucket_6_by_range.return_value.exclude.return_value =\
            AccountPayment.objects.filter(id__in=mocked_account_payment_ids)

        if not SubBucket.objects.filter(pk=2).last():
            SubBucketFactory(
                id=2, bucket=6, sub_bucket=2, start_dpd=271, end_dpd=360)
        allocate_bucket_6_1_account_payments_to_collection_vendor()

    @patch('juloserver.collection_vendor.task.get_eligible_account_payment_for_dialer_and_vendor_qs')
    @patch.object(AccountPayment.objects, 'not_paid_active')
    @patch('juloserver.minisquad.tasks2.intelix_task.upload_julo_b5_data_to_intelix')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    @patch('juloserver.collection_vendor.task.AgentAssignmentConstant.MAXIMUM_THRESHOLD.sub_2', 1)
    def test_allocate_account_payment_for_bucket_6_2(
            self, mocked_redis_client, mocked_sent_to_intelix, mock_account_payment_filter, mock_eligible_account_payment):
        account_1 = AccountFactory(
            ever_entered_B5=True
        )
        account_2 = AccountFactory(
            ever_entered_B5=True
        )
        loan_assigned = LoanFactory(
            account=account_1, ever_entered_B5=True
        )
        loan_assigned.loan_status_code = 234
        loan_assigned.ever_entered_B5 = True
        loan_assigned.save()
        loan_assigned_2 = LoanFactory(
            account=account_2, ever_entered_B5=True
        )
        loan_assigned_2.loan_status_code = 234
        loan_assigned_2.ever_entered_B5 = True
        loan_assigned_2.save()
        AccountPaymentFactory(
            account=account_1)
        AccountPaymentFactory(
            account=account_2)
        dpd_91_date = self.today - timedelta(days=self.sub_bucket_6_2.start_dpd)
        account_payment_1 = account_1.accountpayment_set.order_by('due_date').first()
        account_payment_1.due_date = dpd_91_date
        account_payment_1.due_amount = 100000
        account_payment_1.payment_status_code = 324
        account_payment_1.save()

        account_payment_2 = account_2.accountpayment_set.order_by('due_date').first()
        account_payment_2.due_date = dpd_91_date
        account_payment_2.due_amount = 100000
        account_payment_2.payment_status_code = 324
        account_payment_2.save()

        PaymentFactory(loan=loan_assigned)
        PaymentFactory(loan=loan_assigned_2)
        assigned_payment = loan_assigned.payment_set.first()
        assigned_payment.account_payment = account_payment_1
        assigned_payment.due_date = dpd_91_date
        assigned_payment.due_amount = 100000
        assigned_payment.payment_status_code = 324
        assigned_payment.save()

        assigned_payment2 = loan_assigned_2.payment_set.first()
        assigned_payment2.account_payment = account_payment_2
        assigned_payment2.due_date = dpd_91_date
        assigned_payment2.due_amount = 100000
        assigned_payment2.payment_status_code = 324
        assigned_payment2.save()

        yesterday = self.today - timedelta(days=1)
        AgentAssignmentFactory(
            account_payment=account_payment_1, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket_6_2, assign_time=yesterday)

        AgentAssignmentFactory(
            account_payment=account_payment_2, agent=self.user,
            sub_bucket_assign_time=self.sub_bucket_6_2, assign_time=self.today)

        # test allocate payment if payment event <= 50000
        account_3 = AccountFactory(
            ever_entered_B5=True
        )
        loan_3 = LoanFactory(
            account=account_3, ever_entered_B5=True
        )
        loan_3.loan_status_code = 234
        loan_3.ever_entered_B5 = True
        loan_3.save()
        AccountPaymentFactory(
            account=account_3)
        dpd_91_date = self.today - timedelta(days=self.sub_bucket_6_2.start_dpd)
        account_payment_3 = account_3.accountpayment_set.order_by('due_date').first()
        account_payment_3.due_date = dpd_91_date
        account_payment_3.due_amount = 100000
        account_payment_3.payment_status_code = 324
        account_payment_3.save()

        PaymentFactory(loan=loan_3)
        payment_3 = loan_3.payment_set.first()
        payment_3.account_payment = account_payment_3
        payment_3.due_date = dpd_91_date
        payment_3.due_amount = 100000
        payment_3.payment_status_code = 324
        payment_3.save()
        # create payment event just for payment no 1
        PaymentEventFactory(
            payment=payment_3, event_type='payment', event_payment=50000, cdate=self.today)
        # checking last contacted date >= 30
        account_4 = AccountFactory(
            ever_entered_B5=True
        )
        loan_4 = LoanFactory(
            account=account_4, ever_entered_B5=True
        )
        loan_4.loan_status_code = 234
        loan_4.ever_entered_B5 = True
        loan_4.save()
        AccountPaymentFactory(
            account=account_4)
        PaymentFactory(loan=loan_4)
        dpd_300_date = self.today - timedelta(days=300)
        account_payment_4 = account_4.accountpayment_set.order_by('due_date').first()
        account_payment_4.due_date = dpd_300_date
        account_payment_4.due_amount = 100000
        account_payment_4.payment_status_code = 324
        account_payment_4.save()
        PaymentFactory(loan=loan_3)
        payment_4 = loan_3.payment_set.first()
        payment_4.account_payment = account_payment_4
        payment_4.due_date = dpd_300_date
        payment_4.due_amount = 100000
        payment_4.payment_status_code = 324
        payment_4.save()
        # create payment event for pass the first checking
        PaymentEventFactory(
            payment=payment_4, event_type='payment', event_payment=60000, cdate=self.today)

        skiptrace = SkipTraceFactory(
            application=None, customer=account_4.customer)
        skiptrace_results_choices = SkiptraceResultChoiceFactory(name="No Answer")
        for i in range(30, 0, -1):
            cdate = self.today - timedelta(days=i)
            skiptrace_history = SkiptraceHistoryFactory(
                cdate=cdate, skiptrace=skiptrace, call_result=skiptrace_results_choices,
                agent=self.user, loan=None, application=None, payment=None,
                account=account_4, account_payment=account_payment_4
            )
            skiptrace_history.update_safely(cdate=cdate)

        # check last payment >= 60
        account_5 = AccountFactory(
            ever_entered_B5=True
        )
        loan_5 = LoanFactory(
            account=account_4, ever_entered_B5=True
        )
        loan_5.loan_status_code = 234
        loan_5.ever_entered_B5 = True
        loan_5.save()
        AccountPaymentFactory(
            account=account_5)
        PaymentFactory(loan=loan_5)
        dpd_331_date = self.today - timedelta(days=331)
        account_payment_5 = account_5.accountpayment_set.order_by('due_date').first()
        account_payment_5.due_date = dpd_331_date
        account_payment_5.due_amount = 100000
        account_payment_5.payment_status_code = 324
        account_payment_5.save()
        payment_5 = loan_5.payment_set.first()
        payment_5.account_payment = account_payment_5
        payment_5.due_date = dpd_331_date
        payment_5.due_amount = 100000
        payment_5.payment_status_code = 324
        payment_5.save()
        # create payment event for pass the first checking
        last_60_days_payment = self.today - timedelta(days=60)
        payment_event = PaymentEventFactory(cdate=self.today,
                                            payment=payment_5, event_type='payment', event_payment=60000,
                                            event_date=last_60_days_payment)
        payment_event.update_safely(cdate=last_60_days_payment)
        mocked_account_payment_ids = [
            account_payment_1.id,
            account_payment_2.id, account_payment_3.id, account_payment_4.id,
            account_payment_5.id
        ]
        mocked_redis_client.return_value.get_list.return_value = mocked_account_payment_ids
        mocked_sent_to_intelix.return_value = True
        mock_eligible_account_payment.return_value = AccountPayment.objects.none()
        mock_account_payment_filter.return_value.get_bucket_6_by_range.return_value.exclude.return_value = \
            AccountPayment.objects.filter(id__in=mocked_account_payment_ids)
        if not SubBucket.objects.filter(pk=3).last():
            SubBucketFactory(
                id=3, bucket=6, sub_bucket=2, start_dpd=271, end_dpd=360)
        allocate_bucket_6_2_account_payments_to_collection_vendor()


@skip(reason='Obsolete')
@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestB4VendorDistribution(TestCase):
    def setUp(self):
        self.account_payment_ids = []
        self.vendor_a = CollectionVendorFactory(vendor_name='A', is_b4=True)
        self.vendor_b = CollectionVendorFactory(vendor_name='B', is_b4=True)
        self.vendor_c = CollectionVendorFactory(vendor_name='C', is_b4=True)
        self.vendor_ratio_a = CollectionVendorRatioFactory(
            collection_vendor=self.vendor_a, account_distribution_ratio=0.4,
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('b4')
        )
        self.vendor_ratio_b = CollectionVendorRatioFactory(
            collection_vendor=self.vendor_b, account_distribution_ratio=0.4,
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('b4')
        )
        self.vendor_ratio_c = CollectionVendorRatioFactory(
            collection_vendor=self.vendor_c, account_distribution_ratio=0.2,
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('b4')
        )
        for index in range(0, 10):
            account_payment=AccountPaymentFactory(
                due_amount=int("30000{}".format(index)),
                principal_amount=int("25000{}".format(index)),
                due_date=timezone.localtime(timezone.now()).date() - timedelta(days=71)
            )
            self.account_payment_ids.append(account_payment.id)
        self.sub_bucket = SubBucketFactory(bucket=4, start_dpd=71, end_dpd=90)

    @patch('juloserver.collection_vendor.task.b4_vendor_distribution')
    @patch('juloserver.collection_vendor.task.get_account_payment_details_for_calling')
    @patch('juloserver.collection_vendor.task.get_redis_client')
    def test_success(self, mock_redis, mock_account_payment, mock_b4_vendor_distribution):
        mock_account_payment.return_value = AccountPayment.objects.filter(
            id__in=self.account_payment_ids), []
        mock_redis.return_value.set.return_value = True
        mock_redis.return_value.set_list.return_value = True
        mock_b4_vendor_distribution.return_value.delay.return_value = True
        b4_vendor_distribution(intelix_team=IntelixTeam.JULO_B4)
        vendor_a_count = CollectionVendorAssignment.objects.filter(
            account_payment_id__in=self.account_payment_ids, vendor=self.vendor_a).count()
        vendor_b_count = CollectionVendorAssignment.objects.filter(
            account_payment_id__in=self.account_payment_ids, vendor=self.vendor_b).count()
        vendor_c_count = CollectionVendorAssignment.objects.filter(
            account_payment_id__in=self.account_payment_ids, vendor=self.vendor_c).count()
        assert vendor_a_count == 4
        assert vendor_b_count == 4
        assert vendor_c_count == 2
