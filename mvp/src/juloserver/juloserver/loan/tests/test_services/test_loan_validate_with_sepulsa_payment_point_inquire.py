from django.test import TestCase
from rest_framework.test import APIClient

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    SepulsaProductFactory,
    FeatureSettingFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.loan.services.loan_validate_with_sepulsa_payment_point_inquire import (
    is_valid_price_with_sepulsa_payment_point,
)
from juloserver.payment_point.constants import (
    SepulsaProductType,
    SepulsaProductCategory,
    TransactionMethodCode,
)
from juloserver.payment_point.tests.factories import SepulsaPaymentPointInquireTrackingFactory


class TestIsValidPriceWithSepulsaPaymentPoint(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.transaction_method_id = TransactionMethodCode.PASCA_BAYAR.code
        self.price = 1223456
        self.inquire_tracking = SepulsaPaymentPointInquireTrackingFactory(
            account=self.account,
            transaction_method_id=self.transaction_method_id,
            price=self.price,
            sepulsa_product=SepulsaProductFactory(),
            other_data={},
        )
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        )

    def test_is_valid_price_with_sepulsa_payment_point(self):
        # Case 1: FeatureSetting is inactive
        # => return True
        self.feature_setting.is_active = False
        self.feature_setting.save()
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account,
            transaction_method_id=self.transaction_method_id,
            price=self.price,
            inquire_tracking_id=None,
            payment_point_product_id=None,
        )
        self.assertTrue(result)

        self.feature_setting.is_active = True
        self.feature_setting.save()

        # Case 2: inquire_tracking_id is provided
        # Case 2.1: matching tracking record exists
        # => return True
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account,
            transaction_method_id=self.transaction_method_id,
            price=self.price,
            inquire_tracking_id=self.inquire_tracking.id,
            payment_point_product_id=None,
        )
        self.assertTrue(result)

        # Case 2.2: no matching tracking record exists
        # => return False
        result = is_valid_price_with_sepulsa_payment_point(
            account=0,
            transaction_method_id=self.transaction_method_id,
            price=self.price,
            inquire_tracking_id=self.inquire_tracking.id,
            payment_point_product_id=None,
        )
        self.assertFalse(result)

        # Case 3: inquire_tracking_id is NOT provided
        # Case 3.1: matching tracking record exists
        # => return True
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account,
            transaction_method_id=self.transaction_method_id,
            price=self.price,
            inquire_tracking_id=None,
            payment_point_product_id=None,
        )
        self.assertTrue(result)

        # Case 3.2: no matching tracking record exists
        # => return False
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account,
            transaction_method_id=self.transaction_method_id,
            price=0,
            inquire_tracking_id=None,
            payment_point_product_id=None,
        )
        self.assertFalse(result)

        # Case 3.3: transaction_method_id is in the list of prepaid methods instead of postpaid
        # => return True
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account,
            transaction_method_id=TransactionMethodCode.SELF.code,
            price=self.price,
            inquire_tracking_id=None,
            payment_point_product_id=None,
        )
        self.assertTrue(result)

        # Case 4: transaction_method_id is LISTRIK_PLN postpaid and matching tracking record exists
        # => return True
        self.inquire_tracking.transaction_method_id = TransactionMethodCode.LISTRIK_PLN.code
        self.inquire_tracking.save()
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account,
            transaction_method_id=TransactionMethodCode.LISTRIK_PLN.code,
            price=self.price,
            inquire_tracking_id=None,
            payment_point_product_id=None,
        )
        self.assertTrue(result)

        # Case 5: transaction_method_id is LISTRIK_PLN prepaid
        # Case 5.1: no matching SepulsaProduct exists
        # => return False
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account,
            transaction_method_id=TransactionMethodCode.LISTRIK_PLN.code,
            price=self.price + 200,
            inquire_tracking_id=None,
            payment_point_product_id=0,
        )
        self.assertFalse(result)

        # Case 5.2: matching SepulsaProduct exists
        # => return True
        electricity_prepaid_product = SepulsaProductFactory(
            type=SepulsaProductType.ELECTRICITY,
            category=SepulsaProductCategory.ELECTRICITY_PREPAID,
            is_active=True,
        )
        result = is_valid_price_with_sepulsa_payment_point(
            account=self.account,
            transaction_method_id=TransactionMethodCode.LISTRIK_PLN.code,
            price=self.price,
            inquire_tracking_id=None,
            payment_point_product_id=electricity_prepaid_product.id,
        )
        self.assertTrue(result)
