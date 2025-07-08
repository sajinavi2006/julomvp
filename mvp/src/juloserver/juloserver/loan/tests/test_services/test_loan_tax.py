from django.test.testcases import TestCase

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    StatusLookupFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.models import (
    LoanAdditionalFee,
    LoanAdditionalFeeType,
)
from juloserver.loan.services.loan_tax import (
    get_loan_tax_setting,
    calculate_tax_amount,
    insert_loan_tax,
    insert_loan_digisign_fee,
)
from juloserver.loan.constants import LoanTaxConst, LoanDigisignFeeConst
from juloserver.julo.exceptions import JuloException


class TestLoanTax(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(customer=self.customer)
        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.LOAN_TAX_CONFIG,
            description="Enable Credit Matrix Repeat",
            parameters={
                "whitelist": {"is_active": False, "list_application_ids": []},
                "tax_percentage": 0.11,
                "product_line_codes": LoanTaxConst.DEFAULT_PRODUCT_LINE_CODES,
            },
        )

    def test_get_loan_tax_setting(self):
        tax_fs = get_loan_tax_setting()
        self.assertIsNotNone(tax_fs)

        # test whitelist
        application = ApplicationFactory()
        whitelist = self.feature_setting.parameters['whitelist']
        whitelist['is_active'] = True
        whitelist['list_application_ids'] = [application.id]
        self.feature_setting.save()

        tax_fs = get_loan_tax_setting()
        self.assertIsNone(tax_fs)

        tax_fs = get_loan_tax_setting(application.id)
        self.assertIsNotNone(tax_fs)

    def test_get_loan_tax_setting_off(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()
        tax_fs = get_loan_tax_setting()
        self.assertIsNone(tax_fs)

    def test_insert_loan_tax(self):
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.PAID_OFF),
        )
        loan_tax = insert_loan_tax(self.loan, 10_000)
        self.assertIsNone(loan_tax)

        LoanAdditionalFeeType.objects.create(name=LoanTaxConst.ADDITIONAL_FEE_TYPE)
        loan_tax = insert_loan_tax(self.loan, 10_000)
        self.assertIsNotNone(loan_tax)

        # check if updated, not inserted
        loan_tax = insert_loan_tax(self.loan, 20_000)
        loan_additional_fees = LoanAdditionalFee.objects.filter(loan=self.loan)
        self.assertEqual(len(loan_additional_fees), 1)

        # raise exception if loan is empty
        with self.assertRaises(JuloException) as context:
            loan_tax = insert_loan_tax(None, 10_000)

    def test_insert_loan_digisign_fee(self):
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.CURRENT),
        )
        loan_digisign_fee = insert_loan_digisign_fee(self.loan, 5_000)
        self.assertIsNone(loan_digisign_fee)

        LoanAdditionalFeeType.objects.create(name=LoanDigisignFeeConst.DIGISIGN_FEE_TYPE)
        loan_digisign_fee = insert_loan_digisign_fee(self.loan, 4_000)
        self.assertIsNotNone(loan_digisign_fee)

        # check if updated, not inserted
        loan_digisign_fee = insert_loan_digisign_fee(self.loan, 20_000)
        loan_additional_fees = LoanAdditionalFee.objects.filter(loan=self.loan)
        self.assertEqual(len(loan_additional_fees), 1)
        loan_additional_fee = loan_additional_fees[0]
        self.assertEqual(loan_additional_fee.fee_amount, 20_000)

        # raise exception if loan is empty
        with self.assertRaises(JuloException) as context:
            _ = insert_loan_digisign_fee(None, 10_000)

    def test_calculate_tax_amount(self):
        provision_amount = 100_000
        tax_amount = calculate_tax_amount(provision_amount, ProductLineCodes.J1)
        self.assertEqual(11_000, tax_amount)

        tax_amount = calculate_tax_amount(provision_amount, ProductLineCodes.JTURBO)
        self.assertEqual(0, tax_amount)

        # if product_line_codes empty, meaning applied to all product_line_code
        self.feature_setting.parameters['product_line_codes'] = []
        self.feature_setting.save()
        tax_amount = calculate_tax_amount(provision_amount, ProductLineCodes.JTURBO)
        self.assertEqual(11_000, tax_amount)

        self.feature_setting.is_active = False
        self.feature_setting.save()
        tax_amount = calculate_tax_amount(provision_amount, ProductLineCodes.J1)
        self.assertEqual(0, tax_amount)

    def test_calculate_tax_amount_with_insurance_premium(self):
        provision_amount = 1_000_000
        insurance_premium = 8_800
        net_provision_amount = provision_amount + insurance_premium
        tax_amount = calculate_tax_amount(net_provision_amount, ProductLineCodes.J1)
        self.assertEqual(110_968, tax_amount)

        tax_amount = calculate_tax_amount(net_provision_amount, ProductLineCodes.JTURBO)
        self.assertEqual(0, tax_amount)

        # if product_line_codes empty, meaning applied to all product_line_code
        self.feature_setting.parameters['product_line_codes'] = []
        self.feature_setting.save()
        tax_amount = calculate_tax_amount(net_provision_amount, ProductLineCodes.JTURBO)
        self.assertEqual(110_968, tax_amount)

        self.feature_setting.is_active = False
        self.feature_setting.save()
        tax_amount = calculate_tax_amount(net_provision_amount, ProductLineCodes.J1)
        self.assertEqual(0, tax_amount)

    def test_calculate_tax_amount_with_digisign_fee(self):
        provision_amount = 1_000_000
        digisign_fee = 5000
        tax_amount = calculate_tax_amount(
            provision_amount + digisign_fee, ProductLineCodes.J1,
        )
        self.assertEqual(tax_amount, 110_550)

        self.feature_setting.parameters['product_line_codes'] = []
        self.feature_setting.save()
        provision_amount = 1_000_000
        digisign_fee = 4000
        tax_amount = calculate_tax_amount(
            provision_amount + digisign_fee, ProductLineCodes.JTURBO,
        )
        self.assertEqual(tax_amount, 110_440)
