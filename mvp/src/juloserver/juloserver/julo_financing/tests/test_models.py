from django.test.testcases import TestCase
from juloserver.julo_financing.tests.factories import (
    JFinancingProductFactory,
    JFinancingCategoryFactory,
    JFinancingCheckoutFactory,
    JFinancingVerificationFactory,
)
from juloserver.julo_financing.constants import JFinancingStatus
from juloserver.account.constants import AccountConstant
from juloserver.julo.tests.factories import (
    CustomerFactory,
    ApplicationFactory,
    LoanFactory,
    StatusLookupFactory,
    ProductLineFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo_financing.models import (
    JFinancingVerificationHistory,
    JFinancingProductHistory,
    JFinancingProduct,
)


class TestJFinancingModel(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
            ever_entered_B5=True,
        )
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.DRAFT),
        )

    def test_create_j_financing_models(self):
        assert JFinancingCategoryFactory() != None
        product = JFinancingProductFactory()

        assert JFinancingProduct.objects.get_or_none(pk=product.pk) != None

        checkout_info = {
            "address": "test",
            "address_detail": "test",
            "full_name": "test",
            "phone_number": "08321321321",
        }
        checkout = JFinancingCheckoutFactory(customer=self.customer, additional_info=checkout_info)
        assert checkout.additional_info == checkout_info
        # get list checkout of a customer
        assert self.customer.j_financing_checkouts.count() == 1
        # get product
        assert checkout.j_financing_product != None

        verification = JFinancingVerificationFactory(j_financing_checkout=checkout, loan=self.loan)
        assert verification.j_financing_checkout != None
        assert checkout.verification != None
        assert self.loan.j_financing_verification != None
        assert verification.validation_status == JFinancingStatus.ON_REVIEW

        verification_history = JFinancingVerificationHistory.objects.create(
            field_name='validation_status',
            old_value='test',
            new_value='test',
            j_financing_verification=verification,
        )
        assert verification_history != None
        assert verification.histories.count() == 1

        product_history = JFinancingProductHistory.objects.create(
            field_name='pricing', old_value='test', new_value='test', j_financing_product=product
        )
        assert product_history != None
        assert product.histories.count() == 1
