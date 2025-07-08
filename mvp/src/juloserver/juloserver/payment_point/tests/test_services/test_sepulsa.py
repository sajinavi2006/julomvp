from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import SepulsaTransaction
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    SepulsaProductFactory,
    SepulsaTransactionFactory,
    StatusLookupFactory,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.models import (
    AYCEWalletTransaction,
    SepulsaPaymentPointInquireTracking,
    XfersEWalletTransaction,
)
from juloserver.payment_point.services.sepulsa import (
    create_sepulsa_payment_point_inquire_tracking_id,
    get_payment_point_transaction_from_loan,
)
from juloserver.payment_point.tests.factories import (
    AYCEWalletTransactionFactory,
    AYCProductFactory,
    TransactionMethodFactory,
    XfersEWalletTransactionFactory,
    XfersProductFactory,
)


class TestCreateSepulsaPaymentPointInquireTrackingId(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.PDAM.code,
        )
        self.price = 123456
        self.sepulsa_product = SepulsaProductFactory()
        self.identity_number = '1234567890'
        self.other_data = {}
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        )

    def test_create_sepulsa_payment_point_inquire_tracking_id_active_feature(self):
        self.feature_setting.is_active = True
        self.feature_setting.save()

        result = create_sepulsa_payment_point_inquire_tracking_id(
            account=self.account,
            transaction_method_id=self.transaction_method.id,
            price=self.price,
            sepulsa_product_id=self.sepulsa_product.id,
            identity_number=self.identity_number,
            other_data=self.other_data,
        )

        inquire_tracking = SepulsaPaymentPointInquireTracking.objects.get(id=result)

        self.assertIsNotNone(result)
        self.assertEqual(inquire_tracking.account, self.account)
        self.assertEqual(inquire_tracking.transaction_method_id, self.transaction_method.id)
        self.assertEqual(inquire_tracking.price, self.price)
        self.assertEqual(inquire_tracking.sepulsa_product_id, self.sepulsa_product.id)

    def test_create_sepulsa_payment_point_inquire_tracking_id_inactive_feature(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()

        result = create_sepulsa_payment_point_inquire_tracking_id(
            account=self.account,
            transaction_method_id=self.transaction_method.id,
            price=self.price,
            sepulsa_product_id=self.sepulsa_product.id,
            identity_number=self.identity_number,
            other_data=self.other_data,
        )

        self.assertIsNone(result)


class TestPaymentPointTransactionFromLoan(TestCase):
    def setUp(self) -> None:
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=420),
        )

        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
        )

    def test_ok_sepulsa_transaction(self):
        # setup 2 transactions
        product = SepulsaProductFactory()
        SepulsaTransactionFactory(customer=self.customer, product=product, loan=self.loan)
        AYCEWalletTransactionFactory(
            customer=self.customer,
            ayc_product=AYCProductFactory(
                sepulsa_product=product,
            ),
            loan=self.loan,
            phone_number='666',
        )

        # should get sepulsa
        transaction = get_payment_point_transaction_from_loan(self.loan)
        self.assertEqual(type(transaction), SepulsaTransaction)

    def test_ok_ayoconnect_ewallet_transaction(self):
        # setup 2 transactions
        product_name = "Uncle Ben!"
        product = SepulsaProductFactory(product_name=product_name)
        ayc_product = AYCProductFactory(
            product_name=product_name,
            sepulsa_product=product,
        )
        AYCEWalletTransactionFactory(
            customer=self.customer, ayc_product=ayc_product, loan=self.loan, phone_number='666'
        )

        # should get ayoconnect transaction
        transaction = get_payment_point_transaction_from_loan(self.loan)
        self.assertEqual(type(transaction), AYCEWalletTransaction)
        self.assertEqual(transaction.product.product_name, product_name)
        self.assertEqual(transaction.phone_number, '666')

    def test_ok_no_transaction(self):
        transaction = get_payment_point_transaction_from_loan(self.loan)
        self.assertIsNone(transaction)

    def test_xfers_ewallet_transaction(self):
        self.xfers_product = XfersProductFactory(sepulsa_product=SepulsaProductFactory())
        XfersEWalletTransactionFactory(
            loan=self.loan, customer=self.loan.customer, xfers_product=self.xfers_product
        )
        transaction = get_payment_point_transaction_from_loan(self.loan)
        assert isinstance(transaction, XfersEWalletTransaction) == True
