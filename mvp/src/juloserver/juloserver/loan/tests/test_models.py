from django.test import TestCase

from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.tests.factories import (
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    SepulsaProductFactory,
    SepulsaTransactionFactory,
)
from juloserver.julo.utils import display_rupiah
from juloserver.loan.models import LoanAdditionalFee
from juloserver.loan.tests.factories import LoanAdditionalFeeFactory, LoanAdditionalFeeTypeFactory
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.payment_point.tests.factories import AYCEWalletTransactionFactory, AYCProductFactory


class TestLoanModel(TestCase):
    def setUp(self) -> None:
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory()
        self.application = ApplicationJ1Factory(account=self.account, customer=self.customer)
        self.loan = LoanFactory(
            account=self.account,
            application=self.application,
            transaction_method_id=TransactionMethodCode.DOMPET_DIGITAL.code,
        )

        self.digisign_type = LoanAdditionalFeeTypeFactory.digisign()
        self.dukcapil_type = LoanAdditionalFeeTypeFactory.digisign_dukcapil()
        self.fr_type = LoanAdditionalFeeTypeFactory.digisign_fr()
        self.liveness_type = LoanAdditionalFeeTypeFactory.digisign_liveness()

    def test_transaction_detail_sepulsa_transaction(self):
        name = 'one piece'
        category = 'king of the pirate'
        price_regular = 300_000
        product = SepulsaProductFactory(
            product_name=name,
            category=category,
            customer_price_regular=price_regular,
        )
        SepulsaTransactionFactory(
            customer=self.customer,
            product=product,
            loan=self.loan,
            customer_amount=0,
        )

        expected = '{}, {}, {}'.format(name, category, display_rupiah(price_regular))
        result = self.loan.transaction_detail
        self.assertEqual(
            result,
            expected,
        )

    def test_transaction_detail_ayoconnect_transaction(self):
        name = 'one piece'
        category = 'king of the pirate'
        price_regular = 300_000
        product = SepulsaProductFactory(
            product_name=name,
            category=category,
        )
        AYCEWalletTransactionFactory(
            customer=self.customer,
            ayc_product=AYCProductFactory(
                sepulsa_product=product,
                product_name=name,
                category=category,
                customer_price_regular=price_regular,
            ),
            loan=self.loan,
            phone_number='666',
        )
        expected = '{}, {}, {}'.format(name, category, display_rupiah(price_regular))
        result = self.loan.transaction_detail
        self.assertEqual(
            result,
            expected,
        )

    def test_transaction_detail_for_j1_300_ayoconnect(self):
        name = 'one piece'
        category = 'king of the pirate'
        price_regular = 300_000
        product = SepulsaProductFactory(
            product_name=name,
            category=category,
        )
        AYCEWalletTransactionFactory(
            customer=self.customer,
            ayc_product=AYCProductFactory(
                sepulsa_product=product,
                product_name=name,
                category=category,
                customer_price_regular=price_regular,
            ),
            loan=self.loan,
            phone_number='666',
        )
        expected = '{}, {}, {}'.format(name, category, display_rupiah(price_regular))
        result = self.loan.transaction_detail_for_j1_300
        self.assertEqual(
            result,
            expected,
        )

    def test_transaction_detail_for_j1_300_sepulsa(self):
        name = 'one piece'
        category = 'king of the pirate'
        price_regular = 300_000
        product = SepulsaProductFactory(
            product_name=name,
            category=category,
            customer_price_regular=price_regular,
        )
        SepulsaTransactionFactory(
            customer=self.customer,
            product=product,
            loan=self.loan,
            customer_amount=0,
        )
        expected = '{}, {}, {}'.format(name, category, display_rupiah(price_regular))
        result = self.loan.transaction_detail_for_j1_300
        self.assertEqual(
            result,
            expected,
        )

    def test_transaction_detail_for_paid_letter_sepulsa(self):
        name = 'one piece'
        category = 'king of the pirate'
        price_regular = 300_000
        product = SepulsaProductFactory(
            product_name=name,
            category=category,
            customer_price_regular=price_regular,
        )
        SepulsaTransactionFactory(
            customer=self.customer,
            product=product,
            loan=self.loan,
            customer_amount=0,
        )
        expected = 'Transaksi pembelian {} {} sebesar {},-'.format(
            category, name, display_rupiah(price_regular)
        )
        result = self.loan.transaction_detail_for_paid_letter
        self.assertEqual(
            result,
            expected,
        )

    def test_transaction_detail_for_paid_letter_ayoconnect(self):
        name = 'one piece'
        category = 'king of the pirate'
        price_regular = 300_000
        product = SepulsaProductFactory(
            product_name=name,
            category=category,
        )
        AYCEWalletTransactionFactory(
            customer=self.customer,
            ayc_product=AYCProductFactory(
                sepulsa_product=product,
                product_name=name,
                category=category,
                customer_price_regular=price_regular,
            ),
            loan=self.loan,
            phone_number='666',
        )
        expected = 'Transaksi pembelian {} {} sebesar {},-'.format(
            category, name, display_rupiah(price_regular)
        )
        result = self.loan.transaction_detail_for_paid_letter
        self.assertEqual(
            result,
            expected,
        )

    def test_get_digisign_and_registration_fee(self):
        amount1 = 100
        amount2 = 200
        amount3 = 300
        amount4 = 400

        LoanAdditionalFeeFactory(
            loan=self.loan,
            fee_type=self.digisign_type,
            fee_amount=amount1,
        )
        LoanAdditionalFeeFactory(
            loan=self.loan,
            fee_type=self.dukcapil_type,
            fee_amount=amount2,
        )
        LoanAdditionalFeeFactory(
            loan=self.loan,
            fee_type=self.fr_type,
            fee_amount=amount3,
        )
        LoanAdditionalFeeFactory(
            loan=self.loan,
            fee_type=self.liveness_type,
            fee_amount=amount4,
        )

        expected_amount = sum(
            [
                amount1,
                amount2,
                amount3,
                amount4,
            ]
        )
        self.assertEqual(
            self.loan.get_digisign_and_registration_fee(),
            expected_amount,
        )
