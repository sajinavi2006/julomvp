from django.test.testcases import TestCase, override_settings
from datetime import timedelta

from juloserver.julo.tests.factories import PaymentFactory, LoanFactory
from juloserver.minisquad.tests.factories import CollectionHistoryFactory
from juloserver.julo.constants import BucketConst
from django.utils import timezone
from juloserver.julo.models import Payment
from juloserver.minisquad.models import CollectionHistory


@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestCollectionHistoryQuerySet(TestCase):
    def setUp(self):
        self.loan = LoanFactory()
        self.payment = PaymentFactory(loan=self.loan)
        self.collection_history = CollectionHistoryFactory(
            loan=self.payment.loan, payment=self.payment
        )

    def test_get_data_bucket_1(self):
        today = timezone.localtime(timezone.now()).date()
        range_dpd_bucket_1 = today - timedelta(days=BucketConst.BUCKET_1_DPD['from'])
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_1)
        collection_history = CollectionHistory.objects.get_queryset().get_bucket_1()
        self.assertEqual(len(collection_history), 1)

    def test_get_data_bucket_2(self):
        today = timezone.localtime(timezone.now()).date()
        range_dpd_bucket_2 = today - timedelta(days=BucketConst.BUCKET_2_DPD['from'])
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_2)
        collection_history = CollectionHistory.objects.get_queryset().get_bucket_2()
        self.assertEqual(len(collection_history), 1)

    def test_get_data_bucket_3(self):
        today = timezone.localtime(timezone.now()).date()
        range_dpd_bucket_3 = today - timedelta(days=BucketConst.BUCKET_3_DPD['from'])
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_3)
        collection_history = CollectionHistory.objects.get_queryset().get_bucket_3()
        self.assertEqual(len(collection_history), 1)

    def test_get_data_bucket_4(self):
        today = timezone.localtime(timezone.now()).date()
        range_dpd_bucket_4 = today - timedelta(days=BucketConst.BUCKET_4_DPD['from'])
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_4)
        collection_history = CollectionHistory.objects.get_queryset().get_bucket_4()
        self.assertEqual(len(collection_history), 1)

    def test_get_data_bucket_5(self):
        today = timezone.localtime(timezone.now()).date()
        range_dpd_bucket_5 = today - timedelta(days=BucketConst.BUCKET_5_DPD)
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_5)
        collection_history = CollectionHistory.objects.get_queryset().get_bucket_5()
        self.assertEqual(len(collection_history), 1)

    def test_determine_bucket_by_range(self):
        today = timezone.localtime(timezone.now()).date()
        range_dpd_bucket_1 = today - timedelta(days=BucketConst.BUCKET_1_DPD['from'])
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_1)
        collection_history = CollectionHistory.objects.get_queryset().determine_bucket_by_range([
            BucketConst.BUCKET_1_DPD['from'], BucketConst.BUCKET_1_DPD['to']
        ])
        self.assertEqual(len(collection_history), 1)
        range_dpd_bucket_2 = today - timedelta(days=BucketConst.BUCKET_2_DPD['from'])
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_2)
        collection_history = CollectionHistory.objects.get_queryset().determine_bucket_by_range([
            BucketConst.BUCKET_2_DPD['from'], BucketConst.BUCKET_2_DPD['to']
        ])
        self.assertEqual(len(collection_history), 1)
        range_dpd_bucket_3 = today - timedelta(days=BucketConst.BUCKET_3_DPD['from'])
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_3)
        collection_history = CollectionHistory.objects.get_queryset().determine_bucket_by_range([
            BucketConst.BUCKET_3_DPD['from'], BucketConst.BUCKET_3_DPD['to']
        ])
        self.assertEqual(len(collection_history), 1)
        range_dpd_bucket_4 = today - timedelta(days=BucketConst.BUCKET_4_DPD['from'])
        Payment.objects.last().update_safely(due_date=range_dpd_bucket_4)
        collection_history = CollectionHistory.objects.get_queryset().determine_bucket_by_range([
            BucketConst.BUCKET_4_DPD['from'], BucketConst.BUCKET_4_DPD['to']
        ])
        self.assertEqual(len(collection_history), 1)
        collection_history = CollectionHistory.objects.get_queryset().determine_bucket_by_range([
            BucketConst.BUCKET_4_DPD['from'], 150
        ])
        self.assertEqual(len(collection_history), 1)
