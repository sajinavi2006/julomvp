from __future__ import print_function
from builtins import str
from django.test import TestCase, override_settings
from mock import patch, ANY
from factory import Iterator
from datetime import timedelta

from juloserver.julo.tests.factories import AuthUserFactory
from juloserver.julo.tests.factories import LoanFactory
from juloserver.julo.tests.factories import PaymentFactory
from juloserver.julo.tests.factories import PTPFactory
from juloserver.julo.tests.factories import ApplicationFactory
from juloserver.julo.tests.factories import CustomerFactory
from juloserver.julo.tests.factories import SkiptraceResultChoiceFactory
from juloserver.julo.tests.factories import ProductLineFactory
from juloserver.julo.tests.factories import StatusLookupFactory

from juloserver.collection_vendor.tests.factories import (
    AgentAssignmentFactory,
    SubBucketFactory,
    CollectionVendorAssignmentFactory,
    CollectionVendorRatioFactory,
    CollectionVendorFactory,
    CollectionVendorAssigmentTransferTypeFactory,
    UploadVendorReportFactory,
    SkiptraceHistoryFactory
)

from juloserver.collection_vendor.services import *
from juloserver.account_payment.tests.factories import AccountPaymentFactory

from juloserver.collection_vendor.models import VendorReportErrorInformation
from juloserver.julo.models import SkiptraceHistory, ProductLine
from juloserver.collection_vendor.task import store_related_data_calling_vendor_result_task
from juloserver.minisquad.tests.factories import (
    CollectionBucketInhouseVendorFactory,
    CollectionDialerTemporaryDataFactory
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountPropertyFactory
)
from juloserver.julo.constants import BucketConst
from juloserver.minisquad.models import CollectionBucketInhouseVendor


class TestValidateCollectionVendorName(TestCase):
    def setUp(self):
        self.coll_vendor = CollectionVendorFactory()

    def test_vendor_name_invalid(self):
        res = validate_collection_vendor_name('test123')
        self.assertEqual(res, True)

    def test_vendor_name_valid(self):
        self.coll_vendor.vendor_name = 'test123'
        self.coll_vendor.save()
        res = validate_collection_vendor_name('test123')
        self.assertEqual(res, False)


class TestGenerateCollectionVendorRatio(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.coll_vendor = CollectionVendorFactory()
        self.coll_vendor_ratio = CollectionVendorRatioFactory()

    def test_collection_vendor_ratio_already_exist(self):
        self.coll_vendor_ratio.collection_vendor = self.coll_vendor
        self.coll_vendor_ratio.vendor_types = 'Final'
        self.coll_vendor_ratio.save()
        generate_collection_vendor_ratio(self.coll_vendor, self.user)


class TestGetGroupedCollectionVendorRatio(TestCase):
    def setUp(self):
        self.coll_vendor = CollectionVendorFactory()
        self.coll_vendor_ratio = CollectionVendorRatioFactory()

    def test_success(self):
        self.coll_vendor_ratio.collection_vendor = self.coll_vendor
        self.coll_vendor_ratio.vendor_types = 'Final'
        self.coll_vendor_ratio.save()
        qs = CollectionVendorRatio.objects.filter(collection_vendor=self.coll_vendor)
        res = get_grouped_collection_vendor_ratio(qs)
        self.assertEqual(res[0]['account_distribution_ratios'],
                         str(self.coll_vendor_ratio.account_distribution_ratio))
        self.assertEqual(res[0]['vendor_types'], 'Final')
        self.assertEqual(res[0]['vendor_ratio_ids'], str(self.coll_vendor_ratio.id))
        self.assertEqual(res[0]['vendor_names'], self.coll_vendor.vendor_name)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestGetCurrentSubBucket5(TestCase):
    def setUp(self):
        self.loan = LoanFactory(id=551)
        PaymentFactory(loan=self.loan)
        self.payment = self.loan.payment_set.first()
        self.sub_bucket = SubBucketFactory(id=5, bucket=5)

    def test_subbucket_start_dpd_lt_dpd(self):
        self.payment.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=3)
        self.payment.save()

        self.sub_bucket.start_dpd = 0
        self.sub_bucket.save()
        res = get_current_sub_bucket(self.payment)
        self.assertEqual(res, self.sub_bucket)

    def test_loan_ever_entered_b5_(self):
        self.loan.ever_entered_B5 = True
        self.loan.save()

        self.payment.due_date = timezone.localtime(timezone.now()).date() + timedelta(days=1)
        self.payment.loan = self.loan
        self.payment.save()

        self.sub_bucket.start_dpd = 0
        self.sub_bucket.save()

        res = get_current_sub_bucket(self.payment)
        self.assertEqual(res, self.sub_bucket)
        # false return
        self.loan.ever_entered_B5 = False
        self.loan.save()
        res = get_current_sub_bucket(self.payment)
        self.assertEqual(res, False)

    def test_get_current_bucket_for_j1(self):
        account_payment = AccountPaymentFactory(
            due_date=timezone.localtime(timezone.now()).date() - timedelta(days=3)
        )
        self.sub_bucket.start_dpd = 0
        self.sub_bucket.save()
        res = get_current_sub_bucket(account_payment, is_julo_one=True)
        self.assertEqual(res, self.sub_bucket)

        account_payment.account.ever_entered_B5 = True
        account_payment.account.save()
        account_payment.due_date = timezone.localtime(timezone.now()).date() + timedelta(days=1)
        account_payment.save()
        loan = LoanFactory(
            account=account_payment.account,
            ever_entered_B5=True
        )
        PaymentFactory(account_payment=account_payment, loan=loan)
        payment = loan.payment_set.first()
        payment.account_payment = account_payment
        payment.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=91)
        res = get_current_sub_bucket(account_payment, is_julo_one=True)
        self.assertEqual(res, self.sub_bucket)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestIsPaymentHaveActivePTP(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.ptp = PTPFactory()

    def test_success(self):
        self.payment.paid_amount = 99
        self.payment.save()

        self.ptp.payment = self.payment
        self.ptp.ptp_amount = 100
        self.ptp.ptp_date = timezone.localtime(timezone.now()).date()
        self.ptp.save()

        res = is_payment_have_active_ptp(self.payment)
        self.assertEqual(res, True)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestDetermineFirstVendorShouldAssign(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.coll_vendor_ratio1 = CollectionVendorRatioFactory()
        self.coll_vendor_ratio2 = CollectionVendorRatioFactory()
        self.coll_vendor_ratio3 = CollectionVendorRatioFactory()
        self.coll_vendor_assignment1 = CollectionVendorAssignmentFactory()
        self.coll_vendor_assignment2 = CollectionVendorAssignmentFactory()

    def test_success(self):
        self.coll_vendor_assignment1.vendor_configuration = self.coll_vendor_ratio1
        self.coll_vendor_assignment1.save()
        self.coll_vendor_assignment2.vendor_configuration = self.coll_vendor_ratio3
        self.coll_vendor_assignment2.save()
        res = determine_first_vendor_should_assign(self.coll_vendor_ratio3)
        self.assertEqual(res,[{'vendor_configuration': ANY}, {'total': ANY, 'vendor_configuration': ANY}])
        # not vendor ratios
        self.coll_vendor_assignment1.vendor_configuration = self.coll_vendor_ratio3
        self.coll_vendor_assignment1.save()
        self.coll_vendor_assignment2.vendor_configuration = self.coll_vendor_ratio3
        self.coll_vendor_assignment2.save()
        res = determine_first_vendor_should_assign(self.coll_vendor_ratio3)
        self.assertEqual(res,[{'vendor_configuration': ANY}, {'vendor_configuration': ANY}])


class TestFormatAssignmentTransferFrom(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.agent_assignment = AgentAssignmentFactory(payment=self.payment)
        self.sub_bucket = SubBucketFactory(id=5)

    @patch('juloserver.collection_vendor.services.get_current_sub_bucket')
    def test_success(self, mock_get_current_sub_bucket):
        self.payment.due_date = timezone.localtime(timezone.now()).date()
        self.payment.save()
        self.agent_assignment.assign_time = timezone.localtime(timezone.now())
        self.agent_assignment.save()

        mock_get_current_sub_bucket.return_value = self.sub_bucket
        res = format_assigment_transfer_from(self.agent_assignment)
        self.assertEqual(res['payment_id'], self.payment.id)
        self.assertEqual(res['loan_id'], self.loan.id)
        self.assertEqual(res['application_id'], self.application.id)


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCheckVendorAssignment(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = PaymentFactory()
        self.coll_vendor = CollectionVendorFactory()
        self.coll_vendor_assignment = CollectionVendorAssignmentFactory()
        self.coll_vendor_ratio = CollectionVendorRatioFactory()
        self.sub_bucket = SubBucketFactory()
        self.coll_vendor_assignment_trf_type = CollectionVendorAssigmentTransferTypeFactory()

    @patch('juloserver.collection_vendor.services.determine_first_vendor_should_assign')
    def test_assignment_extension_is_true(self, mock_determine_first_vendor_should_assign):
        self.coll_vendor_assignment.vendor_configuration = self.coll_vendor_ratio
        self.coll_vendor_assignment.assign_time = timezone.localtime(
            timezone.now()).date() - timedelta(days=61)
        self.coll_vendor_assignment.is_active_assignment = True
        self.coll_vendor_assignment.is_extension = True
        self.sub_bucket.bucket = 5
        self.sub_bucket.save()
        self.sub_bucket.refresh_from_db()
        self.coll_vendor_assignment.sub_bucket_assign_time = self.sub_bucket
        self.coll_vendor_assignment.save()
        self.coll_vendor_assignment.refresh_from_db()
        mock_determine_first_vendor_should_assign.return_value = \
            {'coll_vendor': {'vendor_configuration': self.coll_vendor_ratio.id}}, 'coll_vendor'
        check_vendor_assignment(self.coll_vendor_ratio)
        self.coll_vendor_assignment.refresh_from_db()
        self.assertEqual(self.coll_vendor_assignment.is_active_assignment, False)
        self.assertEqual(timezone.localtime(self.coll_vendor_assignment.unassign_time).date(),
                         timezone.localtime(timezone.now()).date())

    @patch('juloserver.collection_vendor.services.determine_first_vendor_should_assign')
    def test_special_due_late_days_gt_max_dpd(self, mock_determine_first_vendor_should_assign):
        # collection_vendor_assignment.is_extension is false
        self.payment.payment_status_id = 327
        self.payment.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=181)
        self.payment.save()

        self.coll_vendor_assignment.vendor_configuration = self.coll_vendor_ratio
        self.coll_vendor_assignment.assign_time = timezone.localtime(
            timezone.now()).date() - timedelta(days=61)
        self.coll_vendor_assignment.is_active_assignment = True
        self.coll_vendor_assignment.is_extension = False
        self.coll_vendor_assignment.payment = self.payment
        self.coll_vendor_assignment.save()

        mock_determine_first_vendor_should_assign.return_value = \
            {'coll_vendor': {'vendor_configuration': self.coll_vendor_ratio.id}}, 'coll_vendor'
        check_vendor_assignment(self.coll_vendor_ratio)
        self.coll_vendor_assignment.refresh_from_db()
        self.assertEqual(self.coll_vendor_assignment.is_active_assignment, False)
        self.assertEqual(timezone.localtime(self.coll_vendor_assignment.unassign_time).date(),
                         timezone.localtime(timezone.now()).date())

    @patch('juloserver.collection_vendor.services.determine_first_vendor_should_assign')
    def test_not_special_due_late_days_lt_max_dpd(self, mock_determine_first_vendor_should_assign):
        self.payment.payment_status_id = 327
        self.payment.due_date = timezone.localtime(timezone.now()).date() - timedelta(days=181)
        self.payment.save()

        self.coll_vendor_ratio.vendor_types = 'general'
        self.coll_vendor_ratio.save()

        self.coll_vendor_assignment.vendor_configuration = self.coll_vendor_ratio
        self.coll_vendor_assignment.assign_time = timezone.localtime(
            timezone.now()).date() - timedelta(days=91)
        self.coll_vendor_assignment.is_active_assignment = True
        self.coll_vendor_assignment.is_extension = False
        self.coll_vendor_assignment.payment = self.payment
        self.coll_vendor_assignment.save()

        mock_determine_first_vendor_should_assign.return_value = \
            {'coll_vendor': {'vendor_configuration': self.coll_vendor_ratio.id}}, 'coll_vendor'
        res = check_vendor_assignment(self.coll_vendor_ratio)
        print(res)

    @patch('juloserver.collection_vendor.services.get_current_sub_bucket')
    @patch('juloserver.collection_vendor.services.determine_first_vendor_should_assign')
    def test_success(self, mock_determine_first_vendor_should_assign, mock_get_sub_bucket_5):
        self.payment.payment_status_id = 327
        self.payment.due_date = timezone.localtime(timezone.now()).date()
        self.payment.save()

        self.coll_vendor_ratio.vendor_types = 'special'
        self.coll_vendor_ratio.save()
        self.coll_vendor_assignment.vendor_configuration = self.coll_vendor_ratio
        self.coll_vendor_assignment.assign_time = timezone.localtime(
            timezone.now()).date() - timedelta(days=61)
        self.coll_vendor_assignment.is_active_assignment = True
        self.coll_vendor_assignment.is_extension = False
        self.coll_vendor_assignment.payment = self.payment
        self.coll_vendor_assignment.save()

        mock_determine_first_vendor_should_assign.return_value = \
            {0: {'vendor_configuration': self.coll_vendor_ratio.id}}
        mock_get_sub_bucket_5.return_value = self.sub_bucket
        check_vendor_assignment(self.coll_vendor_ratio)
        coll_vendor_assignment_trf = CollectionVendorAssignmentTransfer.objects.get(
            payment=self.payment,
            transfer_type=CollectionVendorAssigmentTransferType.vendor_to_vendor(),
        )
        self.coll_vendor_assignment.refresh_from_db()
        self.assertEqual(self.coll_vendor_assignment.is_active_assignment, False)
        self.assertEqual(timezone.localtime(self.coll_vendor_assignment.unassign_time).date(),
                         timezone.localtime(timezone.now()).date())
        self.assertEqual(self.coll_vendor_assignment.is_transferred_to_other, True)
        self.assertEqual(self.coll_vendor_assignment.collection_vendor_assigment_transfer,
                         coll_vendor_assignment_trf)


class TestCheckActivePTPAgentAssignment(TestCase):
    def setUp(self):
        self.application = ApplicationFactory()
        self.loan = LoanFactory(application=self.application)
        self.payment = PaymentFactory(loan=self.loan)
        self.ptp = PTPFactory(payment=self.payment)

    def test_success(self):
        # ptp today or tomorrow
        self.ptp.ptp_amount = self.payment.paid_amount + 1
        self.ptp.ptp_date = timezone.localtime(timezone.now()).date()
        self.ptp.save()
        res = check_active_ptp_agent_assignment(self.payment)
        self.assertEqual(res, self.ptp.agent_assigned.username)
        # yesterday
        self.ptp.ptp_amount = self.payment.paid_amount + 1
        self.ptp.ptp_date = timezone.localtime(timezone.now() - timedelta(days=1)).date()
        self.ptp.save()
        res = check_active_ptp_agent_assignment(self.payment)
        assert res == ''


def mtl_product_line():
    if not ProductLine.objects.filter(product_line_code=10).exists():
        return ProductLineFactory(product_line_code=10)


class TestReportVendorService(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.product_line = mtl_product_line()
        self.status = StatusLookupFactory(status_code=230)
        self.application = ApplicationFactory(product_line=self.product_line,
                                              customer=self.customer,
                                              application_xid=111222)
        self.loan = LoanFactory(customer=self.customer,
                                loan_status=self.status,
                                application=self.application)
        self.skiptrace_result_choice = SkiptraceResultChoiceFactory(id=1)
        self.payment = PaymentFactory(loan=self.loan)
        self.upload_vendor_report = UploadVendorReportFactory()

    def test_validate_data_calling_result(self):
        data = [{
            'application xid': str(self.application.application_xid),
            'action id': str(self.skiptrace_result_choice.id),
            'collector id': str(self.user.id),
            'phone number': '6281210189909',
            'waktu visit/penelponan': '10-12-2020, 14.15'
        }]
        is_valid = validate_data_calling_result(data)
        self.assertTrue(is_valid)
        data[0]['waktu visit/penelponan'] = '10-14-2020, 14.15'
        is_valid, _ = validate_data_calling_result(data)
        self.assertFalse(is_valid)

    def test_store_error_information_calling_vendor_result(self):
        error = [{
            'identifier': 'application xid',
            'identifier_id': str(self.application.application_xid),
            'error_detail': {
                'fields': 'action code',
                'error_reason': 'data tidak diisi',
                'value': None,
            }
        }]
        store_error_information_calling_vendor_result(error, self.upload_vendor_report)
        self.assertEqual(len(VendorReportErrorInformation.objects.all()), 1)

    def test_store_related_data_calling_vendor_result(self):
        data = [{
            'application xid': str(self.application.application_xid),
            'action code': str(self.skiptrace_result_choice.id),
            'collector id': str(self.user.id),
            'phone number': '6281210189909',
            'waktu visit/penelponan': '10-12-2020, 14.15'
        }]
        self.payment.update_safely(payment_status_id=320)
        self.payment.refresh_from_db()
        store_related_data_calling_vendor_result_task(data)
        self.assertEqual(len(SkiptraceHistory.objects.all()), 1)


class TestProcessDistributionB3ToVendor(TestCase):
    def setUp(self):
        self.today_date = timezone.localtime(timezone.now()).date()
        self.account = AccountFactory.create_batch(50)
        self.account_payment = AccountPaymentFactory.create_batch(
            50,
            account=Iterator(self.account),
            due_date=Iterator([
                self.today_date - timedelta(BucketConst.BUCKET_3_DPD['to']),
                self.today_date - timedelta(BucketConst.BUCKET_3_DPD['from'])
            ]),
            due_amount=Iterator([
                5000, 4000, 3500, 1500 
            ]),
            status_id=Iterator([
                PaymentStatusCodes.PAYMENT_60DPD,
                PaymentStatusCodes.PAYMENT_60DPD
            ])
        )
        self.populate_data_b3 = CollectionDialerTemporaryDataFactory.create_batch(
            50, 
            team=Iterator([
                IntelixTeam.JULO_B3, IntelixTeam.JULO_B3_NC
            ]),
            account_payment=Iterator(self.account_payment),
            cdate=timezone.localtime(timezone.now())
        )
        self.acccount_property = AccountPropertyFactory.create_batch(
            50,
            pgood=Iterator([0.8, 0.9, 0.7, 0,7, 0.5, 0.4, 0.5]),
            account=Iterator(self.account)
        )
        # set from 50 data, 13 account payment ever RPC
        self.skiptrace_results_choices = SkiptraceResultChoiceFactory(name="RPC")
        self.skiptrace_history = SkiptraceHistoryFactory.create_batch(
            13,
            call_result=Iterator([self.skiptrace_results_choices]),
            account_payment=Iterator(self.account_payment[:13])
        )

    def test_process_distribution_b3_to_vendor_unbalanced_will_store_to_inhouse(self):
        # in this case
        # 30 data already on vendor
        # 10 data already in inhouse
        existing_data_on_vendor = \
            CollectionBucketInhouseVendorFactory.create_batch(
                30,
                account_payment=Iterator(self.account_payment[:30]),
                bucket=Iterator(['JULO_B3', 'JULO_B3_NON_CONTACTED']),
                vendor=Iterator([True])
            )
        existing_data_on_inhouse = \
            CollectionBucketInhouseVendorFactory.create_batch(
                10,
                account_payment=Iterator(self.account_payment[30:40]),
                bucket=Iterator(['JULO_B3', 'JULO_B3_NON_CONTACTED']),
                vendor=Iterator([False])
            )
        process_distribution_b3_to_vendor(0.05, 10)
        # 10 fresh data should be send to inhouse
        # vendor 30:20 inhouse
        result_vendor = list(
            CollectionBucketInhouseVendor.objects.filter(vendor=True).values_list('id', flat=True))
        self.assertEqual(30, len(result_vendor))

    def test_process_distribution_b3_to_vendor_unbalanced_will_store_to_vendor(self):
        # in this case
        # 30 data already on inhouse
        # 10 data already in vendor
        existing_data_on_inhouse = \
            CollectionBucketInhouseVendorFactory.create_batch(
                30,
                account_payment=Iterator(self.account_payment[:30]),
                bucket=Iterator(['JULO_B3', 'JULO_B3_NON_CONTACTED']),
                vendor=Iterator([False])
            )
        existing_data_on_vendor = \
            CollectionBucketInhouseVendorFactory.create_batch(
                10,
                account_payment=Iterator(self.account_payment[30:40]),
                bucket=Iterator(['JULO_B3', 'JULO_B3_NON_CONTACTED']),
                vendor=Iterator([True])
            )
        process_distribution_b3_to_vendor(0.05, 10)
        # 10 fresh data should be send to vendor
        # vendor 20:30 inhouse
        result_vendor = list(
            CollectionBucketInhouseVendor.objects.filter(vendor=True).values_list('id', flat=True))
        self.assertEqual(20, len(result_vendor))

    def test_process_distribution_b3_to_vendor(self):
        # in this case
        # 4 data already on inhouse
        # 7 data already in vendor
        existing_data_on_vendor = \
            CollectionBucketInhouseVendorFactory.create_batch(
                7,
                account_payment=Iterator(self.account_payment[43:]),
                bucket=Iterator(['JULO_B3', 'JULO_B3_NON_CONTACTED']),
                vendor=Iterator([True])
            )
        existing_data_on_inhouse = \
            CollectionBucketInhouseVendorFactory.create_batch(
                4,
                account_payment=Iterator(self.account_payment[:4]),
                bucket=Iterator(['JULO_B3', 'JULO_B3_NON_CONTACTED']),
                vendor=Iterator([False])
            )
        process_distribution_b3_to_vendor(0.05, 10)
        # 13 fresh data should be send to vendor
        # it's mean data vendor should be 25 account payment
        # 7 existing data, the rest 13 data from fresh account payment
        # vendor 25:25 inhouse
        result_vendor = list(
            CollectionBucketInhouseVendor.objects.filter(vendor=True).values_list('id', flat=True))
        self.assertEqual(25, len(result_vendor))
