from mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta

from juloserver.julo.tests.factories import (
    PaymentFactory,
    LoanFactory,
    StatusLookupFactory
)
from juloserver.collection_vendor.models import (
    CollectionVendorAssignment,
    SubBucket,
)
from juloserver.collection_vendor.task import (
    assign_payments_to_vendor,
    check_assignment_bucket_5,
    check_assignment_bucket_6_1,
    check_assignment_bucket_6_2,
)
from ..factories import (
    CollectionVendorRatioFactory,
    CollectionVendorAssignmentFactory,
    CollectionVendorFactory,
    SubBucketFactory,
    CollectionVendorAssigmentTransferTypeFactory
)
from juloserver.collection_vendor.constant import CollectionVendorCodes

from juloserver.minisquad.constants import IntelixTeam


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestVendorAssignment(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.collection_vendor = CollectionVendorFactory()
        self.today = timezone.localtime(timezone.now())
        today_minus_110 = self.today - timedelta(days=110)
        payment_status = StatusLookupFactory()
        self.payment = PaymentFactory(loan=self.loan, due_date=today_minus_110.date(),
                                      payment_status=payment_status)
        self.collection_vendor_ratio = CollectionVendorRatioFactory()
        self.collection_vendor_transfer_type = CollectionVendorAssigmentTransferTypeFactory()
        SubBucketFactory(
            id=1,
            bucket=5,
            sub_bucket=1,
            start_dpd=91,
            end_dpd=180
        )
        SubBucketFactory(
            id=2,
            bucket=5,
            sub_bucket=2,
            start_dpd=181,
            end_dpd=270
        )
        SubBucketFactory(
            id=3,
            bucket=5,
            sub_bucket=3,
            start_dpd=271,
            end_dpd=360
        )
        SubBucketFactory(
            id=4,
            bucket=5,
            sub_bucket=4,
            start_dpd=361,
            end_dpd=720
        )
        SubBucketFactory(
            id=5,
            bucket=5,
            sub_bucket=5,
            start_dpd=721,
        )
        self.selaras_vendor = CollectionVendorFactory(
            vendor_name='Selaras',
            is_active=True,
            is_special=True,
            is_general=True,
            is_final=True,
        )
        self.selaras_ratio = CollectionVendorRatioFactory(
            collection_vendor=self.selaras_vendor,
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('special'),
            account_distribution_ratio=0.5,
        )
        self.xinghao_vendor = CollectionVendorFactory(
            vendor_name='Xing Hao',
            is_active=True,
            is_special=True,
            is_general=True,
            is_final=True,
        )
        self.xinghao_ratio = CollectionVendorRatioFactory(
            collection_vendor=self.xinghao_vendor,
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('special'),
            account_distribution_ratio=0.2,
        )
        self.payment.refresh_from_db()
        sub_bucket_5_1 = SubBucket.sub_bucket_five(1)
        self.vendor_reassignment = CollectionVendorAssignmentFactory(
            vendor=self.collection_vendor,
            vendor_configuration=self.selaras_ratio,
            payment=self.payment,
            sub_bucket_assign_time=sub_bucket_5_1,
            dpd_assign_time=self.payment.due_late_days,
            assign_time=today_minus_110,
            collection_vendor_assigment_transfer=None
        )
        CollectionVendorAssignmentFactory(
            vendor=self.collection_vendor,
            vendor_configuration=self.selaras_ratio,
            payment=self.payment,
            sub_bucket_assign_time=sub_bucket_5_1,
            dpd_assign_time=self.payment.due_late_days,
            assign_time=self.today,
            collection_vendor_assigment_transfer=None
        )
        CollectionVendorAssignmentFactory(
            vendor=self.collection_vendor_ratio.collection_vendor,
            vendor_configuration=self.collection_vendor_ratio,
            payment=self.payment,
            sub_bucket_assign_time=sub_bucket_5_1,
            dpd_assign_time=self.payment.due_late_days,
            assign_time=self.today,
            collection_vendor_assigment_transfer=None
        )

    @patch('juloserver.collection_vendor.task.allocate_payments_to_collection_vendor_for_bucket_6_1')
    def test_assign_payment_to_vendor(self, mock_allocate_payments_to_collection_vendor_for_bucket_6_1):
        loan = LoanFactory()
        today_minus_110 = self.today - timedelta(days=110)
        payment_status = StatusLookupFactory()
        new_payment = PaymentFactory(
            loan=loan, due_date=today_minus_110.date(),
            payment_status=payment_status)
        assign_payments_to_vendor(
            [{'payment_id': new_payment.id, 'type': 'inhouse_to_vendor', 'reason': 'unit test'}],
            CollectionVendorCodes.VENDOR_TYPES.get('special'),
            IntelixTeam.JULO_B5
        )
        self.assertEqual(4, len(CollectionVendorAssignment.objects.all()))

    def test_check_assignment_bucket_5(self):
        check_assignment_bucket_5()
        self.vendor_reassignment.refresh_from_db()
        self.assertIsNot(self.vendor_reassignment.vendor_configuration, self.selaras_ratio)

    def test_check_assignment_bucket_6_1(self):
        today_minus_190 = self.today - timedelta(days=190)
        self.selaras_ratio.update_safely(
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('general')
        )
        self.selaras_ratio.refresh_from_db()
        sub_bucket = SubBucket.objects.filter(sub_bucket=2).last()
        self.vendor_reassignment.update_safely(
            vendor_configuration=self.selaras_ratio,
            assign_time=today_minus_190,
            sub_bucket_assign_time=sub_bucket
        )
        self.xinghao_ratio.refresh_from_db()
        self.collection_vendor_ratio.refresh_from_db()
        self.vendor_reassignment.refresh_from_db()
        check_assignment_bucket_6_1()
        self.vendor_reassignment.refresh_from_db()
        self.assertEqual(self.vendor_reassignment.is_active_assignment, False)

    @patch('juloserver.collection_vendor.task.assign_payments_to_vendor')
    def test_check_assignment_bucket_6_2(self, mock_assign_payments_to_vendor):
        today_minus_271 = self.today - timedelta(days=271)
        self.selaras_ratio.update_safely(
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('general')
        )
        self.selaras_ratio.refresh_from_db()
        sub_bucket = SubBucket.objects.filter(sub_bucket=3).last()
        self.vendor_reassignment.update_safely(
            vendor_configuration=self.selaras_ratio,
            assign_time=today_minus_271,
            sub_bucket_assign_time=sub_bucket
        )
        self.selaras_ratio.update_safely(
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('final')
        )
        self.xinghao_ratio.update_safely(
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('final')
        )
        self.collection_vendor_ratio.update_safely(
            vendor_types=CollectionVendorCodes.VENDOR_TYPES.get('final')
        )
        self.xinghao_ratio.refresh_from_db()
        self.collection_vendor_ratio.refresh_from_db()
        check_assignment_bucket_6_2()
        self.vendor_reassignment.refresh_from_db()
        self.assertEqual(self.vendor_reassignment.is_active_assignment, False)
