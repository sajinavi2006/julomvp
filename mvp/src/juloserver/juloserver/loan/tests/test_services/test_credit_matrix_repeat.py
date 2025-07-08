from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase

from juloserver.ana_api.tests.factories import PdCustomerSegmentModelResultFactory
from juloserver.julo.tests.factories import (
    CreditMatrixRepeatFactory,
    FeatureSettingFactory,
)
from juloserver.loan.services.credit_matrix_repeat import (
    get_customer_segment,
    get_credit_matrix_repeat,
)
from juloserver.julo.constants import FeatureNameConst


class TestGetCustomerSegment(TestCase):
    def setUp(self):
        self.customer_id = 1
        self.segment = 'activeus_a'
        PdCustomerSegmentModelResultFactory(
            customer_id=self.customer_id,
            customer_segment=self.segment,
            partition_date=date.today() - timedelta(days=1),
        )

    def test_get_customer_segment_with_data(self):
        # test older data is not returned
        older_segment = 'abc'
        PdCustomerSegmentModelResultFactory(
            customer_id=self.customer_id,
            customer_segment=older_segment,
            partition_date=date.today() - timedelta(days=8),
        )

        # older_segment because id >  after self.segment.id
        self.assertEqual(get_customer_segment(customer_id=self.customer_id), older_segment)

        newer_segment = 'neveruse_uninstalled_a'
        PdCustomerSegmentModelResultFactory(
            customer_id=self.customer_id,
            customer_segment=newer_segment,
            partition_date=date.today(),
        )

        # tomorrow segment
        tomorrow_segment = 'neveruse_uninstalled_a2'
        PdCustomerSegmentModelResultFactory(
            customer_id=self.customer_id,
            customer_segment=tomorrow_segment,
            partition_date=date.today() + timedelta(days=1),
        )

        # get lastest segment by ID
        self.assertEqual(get_customer_segment(customer_id=self.customer_id), tomorrow_segment)

        # test get latest data, not depend on partition_date is more than 7 days ago
        self.assertEqual(
            get_customer_segment(
                customer_id=self.customer_id, day_filter_range=date.today() + timedelta(days=100)
            ),
            tomorrow_segment,
        )

        # test filter day in past
        self.assertEqual(
            get_customer_segment(
                customer_id=self.customer_id, day_filter_range=date.today() - timedelta(days=2)
            ),
            older_segment,
        )

    def test_get_customer_segment_without_data(self):
        self.assertIsNone(get_customer_segment(customer_id=122153))


class TestGetCreditMatrixRepeat(TestCase):
    def setUp(self):
        self.credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment='activeus_a', product_line_id=1, transaction_method_id=1, version=1
        )
        self.credit_matrix_repeat_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CREDIT_MATRIX_REPEAT_SETTING,
            description="Enable Credit Matrix Repeat",
        )

    @patch('juloserver.loan.services.credit_matrix_repeat.get_customer_segment')
    def test_get_credit_matrix_repeat_with_data(self, mock_get_customer_segment):
        mock_get_customer_segment.return_value = self.credit_matrix_repeat.customer_segment

        self.credit_matrix_repeat.is_active = True
        self.credit_matrix_repeat.save()
        self.assertEqual(
            get_credit_matrix_repeat(
                customer_id=1,
                product_line_id=self.credit_matrix_repeat.product_line_id,
                transaction_method_id=self.credit_matrix_repeat.transaction_method_id,
            ),
            self.credit_matrix_repeat,
        )

        newer_credit_matrix_repeat = CreditMatrixRepeatFactory(
            customer_segment=self.credit_matrix_repeat.customer_segment,
            product_line_id=self.credit_matrix_repeat.product_line_id,
            transaction_method_id=self.credit_matrix_repeat.transaction_method_id,
            version=2,
        )
        self.assertEqual(
            get_credit_matrix_repeat(
                customer_id=1,
                product_line_id=self.credit_matrix_repeat.product_line_id,
                transaction_method_id=self.credit_matrix_repeat.transaction_method_id,
            ),
            newer_credit_matrix_repeat,
        )

    @patch('juloserver.loan.services.credit_matrix_repeat.get_customer_segment')
    def test_get_credit_matrix_repeat_without_data(self, mock_get_customer_segment):
        # test disabled credit matrix repeat
        mock_get_customer_segment.return_value = self.credit_matrix_repeat.customer_segment
        self.credit_matrix_repeat.is_active = False
        self.credit_matrix_repeat.save()
        self.assertEqual(
            get_credit_matrix_repeat(
                customer_id=1,
                product_line_id=self.credit_matrix_repeat.product_line_id,
                transaction_method_id=self.credit_matrix_repeat.transaction_method_id,
            ),
            None,
        )

        # test customer_segment is None
        mock_get_customer_segment.return_value = None
        self.assertEqual(
            get_credit_matrix_repeat(
                customer_id=1,
                product_line_id=self.credit_matrix_repeat.product_line_id,
                transaction_method_id=self.credit_matrix_repeat.transaction_method_id,
            ),
            None,
        )

        # test do not have suitable credit matrix repeat
        mock_get_customer_segment.return_value = self.credit_matrix_repeat.customer_segment
        self.assertEqual(
            get_credit_matrix_repeat(
                customer_id=1, product_line_id=99999, transaction_method_id=99999
            ),
            None,
        )

    @patch('juloserver.loan.services.credit_matrix_repeat.get_customer_segment')
    def test_get_credit_matrix_setting_disabled(self, mock_get_customer_segment):
        self.credit_matrix_repeat_setting.is_active = False
        self.credit_matrix_repeat_setting.save()
        mock_get_customer_segment.return_value = self.credit_matrix_repeat.customer_segment
        self.credit_matrix_repeat.is_active = True
        self.credit_matrix_repeat.save()
        self.assertEqual(
            get_credit_matrix_repeat(
                customer_id=1,
                product_line_id=self.credit_matrix_repeat.product_line_id,
                transaction_method_id=self.credit_matrix_repeat.transaction_method_id,
            ),
            None,
        )
