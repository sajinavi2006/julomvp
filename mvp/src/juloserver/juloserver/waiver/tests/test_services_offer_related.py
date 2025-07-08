from builtins import str
from django.test.testcases import TestCase

from juloserver.julo.exceptions import JuloException
from juloserver.julo.tests.factories import ApplicationFactory, ProductLineFactory
from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.loan_refinancing.tests.factories import LoanRefinancingRequestFactory

from juloserver.loan_refinancing.constants import CovidRefinancingConst

from ..services.offer_related import (
    generate_j1_waiver_default_offer,
    get_r4_default_loan_refinancing_offer,
    get_r5_default_loan_refinancing_offer,
    get_r6_default_loan_refinancing_offer,
    get_offer_constructor_function,
    generated_j1_default_offers,
)


class TestLoanRefinancingRelatedWaiverServices(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        product_line = ProductLineFactory(product_line_code=1,product_line_type="J1")
        ApplicationFactory(account=self.account, product_line=product_line)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account, loan=None,
            status=CovidRefinancingConst.STATUSES.offer_generated,
            prerequisite_amount=0,
            expire_in_days=0,
        )

    def test_generate_j1_waiver_default_offer(self):
        offer = generate_j1_waiver_default_offer(
            self.loan_refinancing_request, 1, CovidRefinancingConst.PRODUCTS.r4)
        assert offer['product_type'] == CovidRefinancingConst.PRODUCTS.r4

        r4_offer = get_r4_default_loan_refinancing_offer(self.loan_refinancing_request, 1)
        assert r4_offer['product_type'] == CovidRefinancingConst.PRODUCTS.r4

        r5_offer = get_r5_default_loan_refinancing_offer(self.loan_refinancing_request, 1)
        assert r5_offer['product_type'] == CovidRefinancingConst.PRODUCTS.r5

        r6_offer = get_r6_default_loan_refinancing_offer(self.loan_refinancing_request, 1)
        assert r6_offer['product_type'] == CovidRefinancingConst.PRODUCTS.r6

        r4_construct = get_offer_constructor_function(CovidRefinancingConst.PRODUCTS.r4)
        assert r4_construct == get_r4_default_loan_refinancing_offer

    def test_generated_j1_default_offers(self):
        default_offer = generated_j1_default_offers(self.loan_refinancing_request, None, False)
        assert default_offer == False

        default_offer = generated_j1_default_offers(self.loan_refinancing_request, "R4", False)
        assert default_offer == True

        with self.assertRaises(JuloException) as context:
            self.account.accountpayment_set.all().delete()
            generated_j1_default_offers(self.loan_refinancing_request, "R4", False)
        assert 'tidak dapat diproses. pinjaman belum aktif' == str(context.exception)
